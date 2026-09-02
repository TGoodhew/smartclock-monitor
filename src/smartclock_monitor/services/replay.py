"""A receiver made of captured status screens, so the application can be run with no hardware.

The states the fixtures record — power-up, acquisition, locked, stabilising, surveying, recovery
and three depths of holdover — happen only while a receiver is being moved or restarted. Replaying
them in sequence puts the whole §9.11 state matrix in front of a reviewer in a couple of minutes,
which no amount of sitting in front of a locked receiver would.

**It answers through the same transport interface a real port does**, so what is exercised is the
line protocol, the session and the poll loop rather than a shortcut around them. The prompt, the
CRLF endings and the chunked delivery are all real; only the source of the bytes is not.

**The scalars are derived from the screen being replayed**, not invented alongside it. A demo whose
figures of merit disagreed with its own status screen would teach a reviewer the wrong thing about
the application, and this is a review surface.

It also reproduces §7.3.1: while the replayed screen is not locked, ``:SYNC:TINT?`` is answered
with an error prompt and no body, exactly as the receiver does — so the suppression rule is
visible in the demo rather than only in a test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Final

from smartclock_device.clock import Clock
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_device.parsing.status_screen import StatusScreenParser
from smartclock_device.transport.faults import TransportError, TransportFault

#: Where the captured screens live in a **repository checkout**.
#:
#: Not the only place they can be. An installed copy has no `tests/` directory at all, so this path
#: resolves to nothing and `--demo` starts an application that never shows a reading — silently,
#: because a demo with no screens looks exactly like a receiver that has not answered yet. That was
#: true of every non-editable install, wheel and bundle alike, while the README offered `--demo` as
#: the first thing to try. See :func:`fixture_root`.
CHECKOUT_FIXTURES: Final = Path(__file__).resolve().parents[3] / "tests" / "fixtures"

#: Where they live in an installed copy, put there by `pyproject.toml` and the PyInstaller spec.
PACKAGED_FIXTURES: Final = "smartclock_monitor.resources.fixtures"

#: The order the demo walks them in: a receiver being switched on, finding the sky, locking,
#: losing the antenna, and recovering. It reads as a story rather than as a list.
DEMO_SEQUENCE: Final[tuple[str, ...]] = (
    "captured/power-up-gps-acquisition.txt",
    "captured/power-up-fine-freq-adj.txt",
    "captured/locked-to-gps-stabilizing-frequency.txt",
    "captured/locked-to-gps.txt",
    "captured/surveying-locked-to-gps-stabilizing-frequency.txt",
    "captured/holdover-gps-1pps-invalid.txt",
    "captured/holdover-gps-1pps-invalid-3.txt",
    "captured/holdover-gps-1pps-invalid-deep.txt",
    "captured/recovery-fine-freq-adj.txt",
    "locked-stabilizing.txt",
)

_ORDINARY_PROMPT: Final = "scpi > "

#: What the receiver answers when asked for a reading it cannot give (§7.3.1). Data corrupt or
#: stale — the correct answer to the question, and the question is the mistake.
_REFUSAL_PROMPT: Final = "E-230> "

_IDENTITY: Final = "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"


def fixture_root() -> Traversable:
    """Where the captured screens are on *this* installation.

    The packaged copy first, then the checkout. Both are the same bytes — the fixtures are device
    output and `.gitattributes` marks them `-text` so nothing rewrites their line endings on the
    way into a wheel either.

    Raises with both paths named when neither exists. **Loudly, and this is the one place that is
    right**: §11.1's rule is that a *parser* never raises, because an unreadable field is ordinary.
    A demo with no screens is not ordinary — it is an installation that cannot do the thing the
    README tells a new user to try first, and starting anyway means a window that waits for ever
    for a receiver that was never going to answer.
    """
    try:
        packaged = resources.files(PACKAGED_FIXTURES)
        if (packaged / "locked-stabilizing.txt").is_file():
            # Returned as it comes. ``Path(str(packaged))`` looks harmless and is not: on an
            # installed copy this is a MultiplexedPath, whose ``str`` is its *repr*, so that built
            # a relative path named "MultiplexedPath('…')" and every read failed. Both this and a
            # real Path support ``/`` and ``read_bytes``, which is all a caller needs.
            return packaged
    except (ModuleNotFoundError, OSError):
        pass

    if (CHECKOUT_FIXTURES / "locked-stabilizing.txt").is_file():
        return CHECKOUT_FIXTURES

    raise FileNotFoundError(
        "The captured status screens --demo replays are not installed. Looked for "
        f"{PACKAGED_FIXTURES!r} in the package and {CHECKOUT_FIXTURES} on disk. "
        "A checkout has them at tests/fixtures/; an installed copy should carry them and this one "
        "does not."
    )


def _read(name: str) -> str:
    """A fixture exactly as the device wrote it, CRLF endings included.

    Joined a segment at a time: the demo names screens as ``captured/power-up…`` and a
    ``Traversable`` is not required to accept a separator inside one component.
    """
    found = fixture_root()
    for part in name.split("/"):
        found = found / part
    return found.read_bytes().decode("latin-1")


@dataclass(frozen=True, slots=True)
class _Screen:
    """One captured screen, and the scalars derived from it."""

    name: str
    text: str
    status: ReceiverStatus

    @property
    def is_locked(self) -> bool:
        return self.status.mode is SmartClockMode.LOCKED

    @property
    def sync_state(self) -> str:
        """What ``:SYNC:STAT?`` would answer for this screen."""
        return {
            SmartClockMode.LOCKED: "LOCK",
            SmartClockMode.HOLDOVER: "HOLD",
            SmartClockMode.RECOVERY: "RECO",
            SmartClockMode.POWER_UP: "PWRU",
        }.get(self.status.mode, "UNKN")


class ReplayTransport:
    """A scripted Z3805A built from the captured screens.

    :param clock: Used only to parse the fixtures, so the derived scalars agree with the screen.
    :param screens: Fixture names, in the order to walk them.
    :param advance_every: How many full-screen reads to answer before moving to the next state.
    :param chunk_size: Deliver in pieces of this size, as a real port does. ``None`` for whole.
    """

    def __init__(
        self,
        clock: Clock,
        screens: Sequence[str] = DEMO_SEQUENCE,
        *,
        advance_every: int = 2,
        chunk_size: int | None = 512,
    ) -> None:
        parser = StatusScreenParser(clock)
        self._screens = tuple(
            _Screen(name=name, text=_read(name), status=parser.parse(_read(name)))
            for name in screens
        )
        if not self._screens:
            raise ValueError("A replay needs at least one screen.")

        self._advance_every = max(1, advance_every)
        self._chunk_size = chunk_size
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._is_open = False
        self._index = 0
        self._full_reads = 0

        #: Every command written, in order. Useful when the demo is driven from a test.
        self.written: list[str] = []

    # -- Transport ---------------------------------------------------------------------------

    @property
    def description(self) -> str:
        return f"replay of {len(self._screens)} captured screens"

    @property
    def is_open(self) -> bool:
        return self._is_open

    @property
    def current(self) -> str:
        """Which capture is being replayed, for the window's own status line."""
        return self._screens[self._index].name

    async def open(self) -> None:
        self._is_open = True
        # A Z3805A announces itself when DTR is asserted. Absorbing that is what synchronise() is
        # for, so the demo has to do it or that step would be untested here.
        self._enqueue(f"{_IDENTITY}\r\n{_ORDINARY_PROMPT}")

    async def read(self) -> bytes:
        if not self._is_open:
            raise TransportError(TransportFault.NOT_OPEN, "The replay is not open.")
        return await self._inbound.get()

    async def write(self, data: bytes) -> None:
        if not self._is_open:
            raise TransportError(TransportFault.NOT_OPEN, "The replay is not open.")
        command = data.decode("latin-1").strip()
        self.written.append(command)
        self._answer(command)

    def discard_input(self) -> None:
        while True:
            try:
                self._inbound.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def close(self) -> None:
        self._is_open = False
        self._inbound.put_nowait(b"")

    # -- The script ---------------------------------------------------------------------------

    def _answer(self, command: str) -> None:
        screen = self._screens[self._index]
        upper = command.upper()

        if upper == "*IDN?":
            self._respond(_IDENTITY)
        elif upper == "*CLS":
            self._respond(None)
        elif upper == ":SYST:STAT?":
            self._respond(screen.text.rstrip("\r\n"))
            self._advance()
        elif upper == ":SYNC:STAT?":
            self._respond(f" {screen.sync_state}")
        elif upper == ":SYNC:TFOM?":
            self._respond(_signed(screen.status.tfom))
        elif upper == ":SYNC:FFOM?":
            self._respond(_signed(screen.status.ffom))
        elif upper == ":SYNC:TINT?":
            self._answer_time_interval(screen)
        elif upper == ":DIAG:ROSC:EFC:REL?":
            self._respond(" +2.4E+001")
        elif upper == ":GPS:SAT:TRAC:COUN?":
            self._respond(_signed(len(screen.status.tracked)))
        else:
            # Anything else is answered with the prompt alone, as a receiver answers a setter.
            self._respond(None)

    def _answer_time_interval(self, screen: _Screen) -> None:
        """§7.3.1, reproduced.

        While the receiver is unlocked there is no GPS 1 PPS to measure against, so it answers no
        data at all and puts *data corrupt or stale* in the prompt. The application is expected to
        stop asking until the sync state changes; the demo is where that is watchable.
        """
        if not screen.is_locked:
            self._enqueue(_REFUSAL_PROMPT)
            return

        nanoseconds = screen.status.one_pps_ti_nanoseconds
        if nanoseconds is None:
            self._enqueue(_REFUSAL_PROMPT)
            return

        self._respond(f" {nanoseconds / 1e9:+.5E}")

    def _advance(self) -> None:
        self._full_reads += 1
        if self._full_reads % self._advance_every == 0:
            self._index = (self._index + 1) % len(self._screens)

    def _respond(self, body: str | None) -> None:
        text = f"{body}\r\n{_ORDINARY_PROMPT}" if body is not None else _ORDINARY_PROMPT
        self._enqueue(text)

    def _enqueue(self, text: str) -> None:
        data = text.encode("latin-1")
        size = self._chunk_size
        if size is None or len(data) <= size:
            self._inbound.put_nowait(data)
            return
        for at in range(0, len(data), size):
            self._inbound.put_nowait(data[at : at + size])


def _signed(value: int | None) -> str:
    """A scalar as the receiver spells it: a leading space, then an explicit sign."""
    return " —" if value is None else f" {value:+d}"
