"""One connection to one receiver (§7.2).

**Per-device, never a singleton.** v1 connects to one receiver, and §12 requires that this not be
baked in: there is no module-level state here for the connection or the identity, so a second
session is a second object rather than a rewrite.

**One transaction at a time.** The receiver serves one command and finishes what it started, so
every send goes through a single lock. That is the duty §7.2 puts here rather than on the line
protocol, which deliberately does not serialise its callers.

Qt-free on purpose. Everything here is testable with no display, against the fake transport.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from smartclock_device.clock import Clock
from smartclock_device.commands import catalog
from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import WHOLE_CYCLE, LinkStyle, ReceiverDriver
from smartclock_device.drivers.capability import Capability
from smartclock_device.drivers.registry import Registry
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.model_profile import ModelProfile, for_identity
from smartclock_device.transport import timeouts
from smartclock_device.transport.base import Transport
from smartclock_device.transport.broadcast import BroadcastListener
from smartclock_device.transport.faults import TransportError, TransportFault, describe
from smartclock_device.transport.line_protocol import LineProtocol
from smartclock_device.transport.transaction import Transaction, TransactionOutcome

#: §7.2: three consecutive timeouts before the link is treated as lost.
CONSECUTIVE_FAILURES_BEFORE_DISCONNECT = 3


class ConnectionState(Enum):
    """Where the session is, in the terms §9.11's state matrix uses."""

    DISCONNECTED = 0
    CONNECTING = 1
    CONNECTED = 2
    #: The link failed and is being retried, or is waiting to be.
    LOST = 3


@dataclass(frozen=True, slots=True)
class Refusal:
    """A command the session declined to send, and why.

    Returned rather than raised because it is not exceptional: §10.11's picker is built from the
    allowlist, so the only way to reach this is a caller with a bug, and a bug in a poll loop
    should surface as a diagnostic rather than take the loop down.
    """

    mnemonic: str
    reason: str


@dataclass(frozen=True, slots=True)
class CommandOutcome:
    """What came back from one catalogued send.

    Carries the error queue's answer separately from the transaction, because §7.2's rule is that a
    receiver which rejected a setter still answers the setter itself with a prompt. "It went" and
    "it worked" are different facts and a caller must be able to tell them apart.
    """

    #: ``None`` where the connected family had no command for what was asked — see ``capability``.
    command: ScpiCommand | None

    #: What the caller asked for, where it asked by capability rather than by command. Lets a page
    #: match an answer back to its question without knowing the family's mnemonic for it.
    capability: Capability | None = None

    #: Exactly what was put on the wire, for the Advanced Console's echo.
    sent: str | None = None

    transaction: Transaction | None = None

    #: The error queue's answer, where §7.2 required it to be read. ``None`` means not read;
    #: an empty string means read and clear.
    error: str | None = None

    #: Set instead of the rest where nothing was sent at all.
    refusal: Refusal | None = None

    @property
    def succeeded(self) -> bool:
        """Sent, completed, and the receiver reported no error."""
        if self.refusal is not None or self.transaction is None:
            return False
        return self.transaction.succeeded and not self.error


def _error_text(queue: Transaction) -> str | None:
    """The error queue's answer, or ``None`` where it reported none.

    ``+0,"No error"`` is the receiver saying it is happy, and reporting that as a fault would make
    every successful setter look like a failure.
    """
    if not queue.succeeded:
        return None

    text = (queue.first_line or "").strip()
    if not text or text.startswith("+0,") or text.startswith("0,"):
        return None
    return text


class DeviceSession:
    """Owns the transport, the protocol and the driver for one receiver."""

    def __init__(
        self,
        transport: Transport,
        driver: ReceiverDriver,
        clock: Clock,
        *,
        registry: Registry | None = None,
    ) -> None:
        self._transport = transport
        self._driver = driver
        #: §12: the receiver on the port can have been swapped while the link was down, so the
        #: driver is re-selected on **every** connect rather than once at startup. ``None`` means
        #: a single-family build that was handed its driver directly, which keeps it.
        self._registry = registry
        self._clock = clock
        self._protocol = LineProtocol(transport, clock)

        # The single command channel. The receiver serves one transaction at a time (§7.2).
        self._lock = asyncio.Lock()

        self._state = ConnectionState.DISCONNECTED
        self._identity: DeviceIdentity | None = None
        self._identity_text: str | None = None
        self._profile: ModelProfile = for_identity(None)
        self._banner: str = ""
        self._consecutive_failures = 0
        self._last_fault: str | None = None
        self._unrecognised = False

        # Set only where a broadcast family claimed the receiver. Its presence *is* the link style
        # as far as execute() is concerned — one thing to check rather than a driver property and
        # a listener that could disagree with each other.
        self._listener: BroadcastListener | None = None
        self._listen_task: asyncio.Task[None] | None = None

    # -- What the application asks it ---------------------------------------------------------

    @property
    def driver(self) -> ReceiverDriver:
        return self._driver

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def identity_text(self) -> str | None:
        """Exactly what ``*IDN?`` answered, or ``None`` if it did not."""
        return self._identity_text

    @property
    def identity(self) -> DeviceIdentity | None:
        """The parsed ``*IDN?``, or ``None`` if it has not been read or would not parse."""
        return self._identity

    @property
    def profile(self) -> ModelProfile:
        """What this model has (§8.6). The conservative profile until the identity is known."""
        return self._profile

    @property
    def description(self) -> str:
        return self._transport.description

    @property
    def last_fault(self) -> str | None:
        """The most recent link failure, in words a user can act on."""
        return self._last_fault

    # -- Lifecycle -----------------------------------------------------------------------------

    async def open(self, probe: timedelta = timeouts.AUTO_DETECT_PROBE) -> None:
        """Open the link, absorb the power-up banner, and read the identity.

        The order matters and is not arbitrary. The banner is absorbed **before** the first command
        because a Z3805A announces itself when DTR is asserted, and a session that sends first
        reads that announcement as its own answer and stays one reply behind for as long as it is
        up.

        :param probe: How long to wait for the banner. A receiver that says nothing costs exactly
            this much and nothing afterwards, so it is short — and it is a parameter because the
            auto-detect walk spends it eight times over, and because a test driving a silent fake
            should not wait two real seconds per connection.
        """
        self._state = ConnectionState.CONNECTING
        self._last_fault = None

        try:
            await self._transport.open()
        except TransportError as error:
            self._state = ConnectionState.DISCONNECTED
            self._last_fault = describe(error.fault, self._transport.description)
            raise

        connect = await self._protocol.synchronise(probe)
        self._banner = connect.text

        # The banner names the model and the firmware revision before a single command is sent, so
        # it is tried first — and *IDN? is asked anyway, because a sibling model may say nothing.
        self._adopt_identity(DeviceIdentity.parse(self._banner))

        # §12: a family may claim the receiver from what it *said*, before anything is asked. A
        # talker has no command parser, so probing it would cost a timeout and would be a write to
        # a link whose driver says it is never written to.
        if self._adopt_overheard(connect.lines):
            self._state = ConnectionState.CONNECTED
            self._consecutive_failures = 0
            return

        # Only now: the glitch is the SmartClock's own power-up behaviour, and spending it is two
        # writes — which is two more than a talker may ever receive.
        await self._protocol.spend_startup_glitch()

        identity = await self._probe_identity()
        if identity is not None and identity.succeeded:
            # Kept whole: §10.4 shows the raw answer where it is not four comma-separated fields,
            # because four dashes would say "nothing is connected" — a different statement from
            # "a model this build has not seen". §11.1 keeps the evidence.
            self._identity_text = (identity.first_line or "").strip() or None
            self._adopt_identity(DeviceIdentity.parse(identity.first_line))

        # §12: **the probe phase belongs to no driver.** The banner is absorbed and ``*IDN?`` is
        # asked neutrally, and only now is a family chosen — choosing first would mean asking one
        # family's questions of a receiver that may be another's.
        self._select_driver()

        self._state = ConnectionState.CONNECTED
        self._consecutive_failures = 0

    async def refresh_identity(self) -> bool:
        """Ask ``*IDN?`` again when the identity is still unknown.

        Returns whether **this call** filled it in — not whether it is known, which would be true
        on every poll of a session that identified normally and would re-announce a receiver whose
        name had not changed once a second.

        **A transient at open was permanent for this one field and temporary for every other**
        (#29). The status screen is re-read on every poll, so a garbled first answer costs one
        cycle; the identity was read once in :meth:`open` and never again, so the same garble cost
        the whole session — an empty §10.4 *Receiver* card, "an unidentified receiver" in the
        status bar, and :data:`CONSERVATIVE` standing in for §8.6's profile. On a 59551A that last
        one silently withdraws every optional capability the model has.

        The mechanism is documented two files away: :meth:`spend_startup_glitch` exists because
        the first command after the port opens draws ``E-362>`` on this hardware, and it spends
        two commands to absorb that. When two is not enough, ``*IDN?`` is the next in line and
        there was nothing to ask again.

        **Cheap, because it only runs while the answer is missing.** A session that identified at
        open never sends this, so the ordinary case costs one attribute test per poll.
        """
        if self._identity is not None:
            return False
        if self._state is not ConnectionState.CONNECTED or self._listener is not None:
            # A talker is claimed by what it says and is never written to (§12), and a link that
            # is not up has nothing to ask.
            return False

        identity = await self._probe_identity()
        if identity is None or not identity.succeeded:
            return False

        # Read from the parse rather than back off `self._identity`: the early return above
        # narrows that attribute to None for the rest of the method, and mypy then calls
        # everything after a second test of it unreachable.
        parsed = DeviceIdentity.parse(identity.first_line)
        self._identity_text = (identity.first_line or "").strip() or None
        self._adopt_identity(parsed)
        if parsed is None:
            return False

        # The driver was chosen without an identity to go on, so choose again now there is one.
        self._select_driver()
        return True

    async def close(self) -> None:
        await self._stop_listening()
        await self._transport.close()
        self._state = ConnectionState.DISCONNECTED

    # -- Sending -------------------------------------------------------------------------------

    async def execute(
        self,
        mnemonic: str,
        # ASYNC109 would have the caller wrap this in asyncio.timeout(). Same answer as the line
        # protocol's: §7.2 assigns a timeout class per command, and the point is that a caller does
        # not have to know which. Passing None — which every caller does — takes that class.
        timeout: timedelta | None = None,  # noqa: ASYNC109
    ) -> Transaction | Refusal:
        """Send one catalogued command, one at a time.

        **The point-of-send allowlist check is here** (§8.1), asked of the driver rather than of a
        module, so the answer is the one for whichever family the session holds. A command that is
        not catalogued is refused; the question asked is whether it *is* catalogued, never whether
        it is excluded — an allowlist answers the first, and answering the second instead is the
        architecture §8.1 rejects.
        """
        # §12's other link style, and the branch is here rather than in the poller on purpose: the
        # plan is one type for both, so a page or a poll asks for a plan entry the same way and the
        # session knows which kind of link it is holding. A broadcast entry is a *key*, answered
        # from what the talker already said — nothing is written, and the allowlist below is not
        # consulted because a talker has none to be on.
        if self._listener is not None:
            return self._answer_from_broadcast(mnemonic)

        if not self._driver.is_allowed(mnemonic):
            return Refusal(mnemonic, "That command is not in the catalog, so it was not sent.")

        async with self._lock:
            result = await self._protocol.execute(mnemonic, timeout)

        self._note(result)
        return result

    async def execute_command(
        self, command: ScpiCommand, argument: object = None
    ) -> CommandOutcome:
        """Send one catalogued command, with its argument validated and its aftermath read.

        **The allowlist check is still an exact match on the header.** The argument is composed and
        bounded by the command's own declaration, so nothing here concatenates user text onto a
        mnemonic and then asks whether the result is allowed — that would make the point-of-send
        check a prefix match.

        **§7.2 requires the error queue after every tier C command**, and it is read here rather
        than by each caller: a receiver that rejected a setter answers the setter with a prompt and
        says why only when asked, so a page that forgot to ask would report success for a command
        the receiver refused.
        """
        if not self._driver.is_allowed(command.mnemonic):
            return CommandOutcome(
                command=command,
                refusal=Refusal(
                    command.mnemonic, "That command is not in the catalog, so it was not sent."
                ),
            )

        rendered = command.rendered(argument)
        if rendered is None:
            return CommandOutcome(
                command=command,
                refusal=Refusal(
                    command.mnemonic,
                    f"{argument!r} is not a value this command accepts, so it was not sent.",
                ),
            )

        async with self._lock:
            result = await self._protocol.execute(rendered, None)
        self._note(result)

        error: str | None = None
        if command.needs_confirmation and result.succeeded:
            async with self._lock:
                queue = await self._protocol.execute(catalog.ERROR_QUEUE.mnemonic, None)
            self._note(queue)
            error = _error_text(queue)

        return CommandOutcome(command=command, sent=rendered, transaction=result, error=error)

    def _note(self, result: Transaction) -> None:
        """Track §7.2's three-consecutive-failures rule."""
        if result.outcome is TransactionOutcome.COMPLETED:
            self._consecutive_failures = 0
            return

        self._consecutive_failures += 1

        if result.outcome is TransactionOutcome.FAULTED:
            self._last_fault = describe(result.fault, self._transport.description)
            # A fault is not a timeout: the link is gone now, not three tries from now.
            self._state = ConnectionState.LOST
            return

        if self._consecutive_failures >= CONSECUTIVE_FAILURES_BEFORE_DISCONNECT:
            self._state = ConnectionState.LOST
            self._last_fault = describe(TransportFault.IO, self._transport.description)

    async def _probe_identity(self) -> Transaction | None:
        """Ask ``*IDN?`` **neutrally**, outside any driver's allowlist.

        §12: *"the probe phase belongs to no driver."* Routing this through
        :meth:`execute` gates it on whichever driver happens to be first in the registry — so a
        family registered ahead of the one that actually serves the receiver refuses the identity
        query, nothing is ever recognised, and the fallback becomes the only outcome. Found by
        registering a reads-only talker first and watching a Z3805A go unclaimed.

        **This is the one command not checked against a driver, and it is a constant.** It is not
        a path: nothing supplies the mnemonic, no argument is appended, and §8.1's allowlist still
        governs everything a page or the console can send. The alternative — an allowlist that
        every driver must contain ``*IDN?`` in — would put a requirement on the contract to make
        the probe work, which is the coupling the neutrality rule exists to avoid.
        """
        async with self._lock:
            result = await self._protocol.execute(catalog.IDENTITY.mnemonic, None)
        self._note(result)
        return result

    def _answer_from_broadcast(self, key: str) -> Transaction:
        """One plan key, from the last complete cycle.

        **Silence becomes a timeout** rather than a state of its own. §7.2's reconnect policy
        already knows what to do about a link that has stopped answering, and giving broadcast its
        own failure vocabulary would mean teaching the supervisor — and the three-consecutive-
        failures rule, and the status bar — a second one for no gain.

        A cycle that has not closed yet is *not* a failure: it is the first second of a connection,
        and reporting it as one would spend a third of §7.2's failure budget on a link that is
        working perfectly.
        """
        assert self._listener is not None

        if self._listener.is_quiet():
            result = Transaction(command=key, outcome=TransactionOutcome.TIMED_OUT)
            self._note(result)
            return result

        lines = self._listener.whole_cycle() if key == WHOLE_CYCLE else self._listener.answer(key)
        result = Transaction(command=key, outcome=TransactionOutcome.COMPLETED, lines=lines)
        self._note(result)
        return result

    def _on_broadcast_line(self, line: str) -> None:
        if self._listener is not None:
            self._listener.feed(self._driver.classify(line), line)

    def _start_listening(self, overheard: Sequence[str]) -> None:
        """Begin reading a talker's stream, and keep the task so close() can stop it.

        Unreferenced, the task would be garbage-collected mid-read — asyncio only holds a weak
        reference — and the link would go quiet for a reason nothing reported.
        """
        self._listener = BroadcastListener(
            clock=self._clock,
            # §12: the plan's first fast-tier entry delimits a cycle. The driver names it; nothing
            # here knows which sentence that is, which is the whole point of the seam.
            boundary=self._driver.plan.fast[0].mnemonic,
        )

        # **Seeded with what was overheard**, and both halves matter. Those sentences are real data
        # — throwing them away would discard the first cycle of every connection — and they are
        # also the proof the talker is speaking. Without them the listener has heard nothing, and a
        # listener that has heard nothing is quiet *at once* by design, so the connection that had
        # just claimed a talker by listening to it would report the link as timed out.
        for line in overheard:
            self._on_broadcast_line(line)

        self._listen_task = asyncio.create_task(self._protocol.listen(self._on_broadcast_line))

    async def _stop_listening(self) -> None:
        task, self._listen_task = self._listen_task, None
        self._listener = None
        if task is None:
            return
        task.cancel()
        # A listener being torn down has nothing left to report: the port is closing, and a fault
        # raised on the way out would replace the reason the session is closing at all.
        #
        # CancelledError is named explicitly because it is a *BaseException* and Exception alone
        # does not catch it — which would let the cancel we just asked for propagate out of
        # close(), from the one line in the teardown that exists to make it not.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    def _adopt_overheard(self, lines: Sequence[str]) -> bool:
        """Whether a family claimed the receiver from the banner, before ``*IDN?`` was asked.

        Returning ``True`` ends the connect: there is nothing further to probe, and no identity to
        adopt — a talker has none, and inventing one from the sentences it happened to send would
        put a made-up model number on §10.4's Receiver card.
        """
        if self._registry is None:
            return False

        selection = self._registry.overhear(lines)
        if selection is None:
            return False

        self._driver = selection.driver
        self._unrecognised = False
        if self._driver.link is LinkStyle.BROADCAST:
            self._start_listening(lines)
        return True

    def _select_driver(self) -> None:
        """Choose the family that claims this receiver, or keep the first registered."""
        if self._registry is None:
            return

        selection = self._registry.select(self._identity)
        self._driver = selection.driver

        if not selection.recognised and self._registry.is_ambiguous:
            # Warned only where more than one family is registered: with one, the fallback is the
            # driver that would have served it regardless, and a warning would be noise on every
            # connection an unidentified receiver ever makes.
            self._unrecognised = True
        else:
            self._unrecognised = False

    @property
    def driver_was_recognised(self) -> bool:
        """Whether a driver actually claimed this receiver, as opposed to being the fallback."""
        return not self._unrecognised

    def _adopt_identity(self, identity: DeviceIdentity | None) -> None:
        if identity is None:
            return
        self._identity = identity
        self._profile = for_identity(identity)
