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
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum

from smartclock_device.clock import Clock
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.model_profile import ModelProfile, for_identity
from smartclock_device.transport import timeouts
from smartclock_device.transport.base import Transport
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


class DeviceSession:
    """Owns the transport, the protocol and the driver for one receiver."""

    def __init__(self, transport: Transport, driver: ReceiverDriver, clock: Clock) -> None:
        self._transport = transport
        self._driver = driver
        self._clock = clock
        self._protocol = LineProtocol(transport, clock)

        # The single command channel. The receiver serves one transaction at a time (§7.2).
        self._lock = asyncio.Lock()

        self._state = ConnectionState.DISCONNECTED
        self._identity: DeviceIdentity | None = None
        self._profile: ModelProfile = for_identity(None)
        self._banner: str = ""
        self._consecutive_failures = 0
        self._last_fault: str | None = None

    # -- What the application asks it ---------------------------------------------------------

    @property
    def driver(self) -> ReceiverDriver:
        return self._driver

    @property
    def state(self) -> ConnectionState:
        return self._state

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

        identity = await self.execute("*IDN?")
        if isinstance(identity, Transaction) and identity.succeeded:
            self._adopt_identity(DeviceIdentity.parse(identity.first_line))

        self._state = ConnectionState.CONNECTED
        self._consecutive_failures = 0

    async def close(self) -> None:
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
        if not self._driver.is_allowed(mnemonic):
            return Refusal(mnemonic, "That command is not in the catalog, so it was not sent.")

        async with self._lock:
            result = await self._protocol.execute(mnemonic, timeout)

        self._note(result)
        return result

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

    def _adopt_identity(self, identity: DeviceIdentity | None) -> None:
        if identity is None:
            return
        self._identity = identity
        self._profile = for_identity(identity)
