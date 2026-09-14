"""The whole application, driven by replayed bytes, one run per family (#99, part 1).

**Every other UI test in this suite constructs a page and hands it a status.** Nothing else builds
the registry, opens a session over a transport, runs the poll loop and lets the readings arrive the
way the application's own callbacks deliver them. So nothing else can catch a defect that lives
*between* those parts — and §12's #304, the defect that produced the capability seam in the first
place, was exactly that: a page that threw on navigation the first time a family it had never seen
was connected.

What this drives, in the order `__main__._run` and `_announce` do it:

    Registry([SmartClock, NMEA, UCCM]) → DeviceSession(transport) → open() →
    MainWindow → open_details() → set_command_runner / set_driver / set_identity →
    PollingService → poll_full + poll_fast → window.show_reading(reading)

Three transports stand in for three receivers. The SmartClock's is `ReplayTransport`, which is the
application's own `--demo` path and therefore the least invented thing here; the other two are
`FakeTransport` fed from the captured corpora. **None of them shortcuts the line protocol** — the
prompt, the CRLF endings and the chunked delivery are all real, and only the source of the bytes is
not.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from smartclock_device.clock import FixedClock
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.drivers.registry import Registry
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.drivers.uccm.driver import UccmDriver
from smartclock_device.transport.base import Transport
from smartclock_device.transport.fake import FakeTransport
from smartclock_monitor.services.commands import SessionCommands
from smartclock_monitor.services.polling import PollingService, Reading
from smartclock_monitor.services.replay import ReplayTransport
from smartclock_monitor.services.session import DeviceSession
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.views.main_window import MainWindow

FIXTURES: Final = Path(__file__).resolve().parent / "fixtures"
NOW: Final = datetime(2026, 9, 14, tzinfo=UTC)

#: The connect probe, shortened. A fake that never speaks costs the full §7.2 probe on every open.
PROBE: Final = timedelta(milliseconds=20)

#: The UCCM prompt, which is not the SmartClock's — `response_buffer.py` keys on the difference.
UCCM_PROMPT: Final = "UCCM-P >"


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


# ---- The three receivers -------------------------------------------------------------------------


def smartclock_transport(clock: FixedClock) -> Transport:
    """The application's own `--demo` source: ten captured screens in a story order."""
    return ReplayTransport(clock)


def talker_transport() -> FakeTransport:
    """A talker, from the first cycles of a capture taken on this bench.

    Broadcast, so nothing is ever written to it: everything it says arrives through `feed`, which
    is what `FakeTransport` documents it for — *"a broadcast talker that speaks without being
    spoken to."*
    """
    lines = (FIXTURES / "nmea" / "vk162-steady-state.nmea").read_bytes().decode("ascii", "replace")
    transport = FakeTransport(banner="".join(lines.splitlines(keepends=True)[:120]))
    transport.feed("".join(lines.splitlines(keepends=True)[120:400]))
    return transport


def uccm_screen() -> str:
    """One `SYST:STAT?` screen, lifted from the Mt Warrigal sitting with its bytes intact.

    The NUL prefix on every line is part of it — the module emits `0D 0A 00` and the parser strips
    it. A screen tidied on the way in here would test a parser against something no receiver sends.
    """
    text = (FIXTURES / "uccm" / "transitions-13sep2026.replies.txt").read_bytes().decode("latin-1")
    start = text.index("---- SYST:STAT?")
    body = text[text.index("\n", start) + 1 : text.index("\n---- ", start + 10)]
    return body.strip("\r\n")


def uccm_transport() -> FakeTransport:
    """A UCCM, answering the four commands its own plan asks for.

    The identity is the corpus's one module — `TRIMBLE,57964-80,…` — because the registry claims
    this family on the **vendor token**, and it asks the SmartClock first precisely because
    `SYMMETRICOM` is a token both answer with.
    """
    return FakeTransport(
        {
            "*IDN?": "TRIMBLE,57964-80,40896646,V2.0.1.6-01",
            "SYST:STAT?": uccm_screen(),
            "SYNC:TINT?": "+4.5E-009",
            "DIAG:ROSC:EFC:REL?": "+5.91E-08",
        },
        prompt=UCCM_PROMPT,
        # Everything else answers with the prompt alone, which is what a receiver does for a setter
        # — and what `spend_startup_glitch`'s two throwaway commands need. Without it each of them
        # costs a transaction timeout, which was ten seconds of this file before anyone noticed.
        default_response="",
    )


# ---- The harness ---------------------------------------------------------------------------------


@dataclass
class Run:
    """One application, wired as `__main__` wires it, after a few poll cycles."""

    window: MainWindow
    details: DetailsWindow
    session: DeviceSession
    cycles: int
    last: Reading | None

    def texts(self) -> set[str]:
        """Every string on every page, which is what a user would be reading."""
        from test_guide_against_the_interface import strings_on

        found: set[str] = set()
        for page in self.details.pages:
            found |= strings_on(page)
        return found


async def drive(transport: Transport, *, cycles: int = 2, window: MainWindow | None = None) -> Run:
    """Open, wire, poll, and hand back what a user would be looking at."""
    clock = FixedClock(NOW)
    # Registration order is priority order, and it is the composition root's, not a convenient one:
    # the SmartClock leads and the UCCM goes last, because `SYMMETRICOM` is a token both answer.
    registry = Registry(
        [SmartClockDriver(clock=clock), NmeaDriver(clock=clock), UccmDriver(clock=clock)]
    )
    session = DeviceSession(transport, registry.drivers[0], clock, registry=registry)
    await session.open(probe=PROBE)

    window = window if window is not None else MainWindow()
    window.open_details()
    details = window.details
    assert details is not None

    # `_announce`'s order, which matters: the blank reading first, so nothing of the last receiver
    # is on screen while this one's first read is still in flight.
    window.show_reading(_nothing_known(clock))
    window.set_command_runner(SessionCommands(session))
    window.set_driver(session.driver)
    window.set_identity(session.identity, session.identity_text)

    service = PollingService(session=session, driver=session.driver, clock=clock)
    for _ in range(cycles):
        await service.poll_full()
        await service.poll_fast()
        if service.latest is not None:
            window.show_reading(service.latest)

    await session.close()
    return Run(window=window, details=details, session=session, cycles=cycles, last=service.latest)


def _nothing_known(clock: FixedClock) -> Reading:
    """What `_announce` shows before the first read of a new receiver: nothing, said plainly."""
    return Reading.nothing_known(clock.utc_now())


# ---- One run per family --------------------------------------------------------------------------


async def test_the_smartclock_run_reaches_the_window() -> None:
    """The `--demo` path, end to end. If this breaks, so does the first thing the README offers."""
    run = await drive(smartclock_transport(FixedClock(NOW)))

    assert run.session.driver.name.startswith("SmartClock")
    assert run.session.driver_was_recognised is True
    assert "Z3805A" in (run.session.identity_text or "")
    assert run.window.mode_pill.text != "Disconnected"


async def test_the_talker_run_reaches_the_window() -> None:
    """A family recognised by **what it said before anything was asked**, driven through the same
    poll loop as the one that answers questions."""
    run = await drive(talker_transport())

    assert run.session.driver.name.startswith("NMEA")
    assert run.session.driver_was_recognised is True


async def test_the_uccm_run_reaches_the_window() -> None:
    """D7's family, which has never been connected to a receiver — so this replay is the only end
    to end it will ever get."""
    run = await drive(uccm_transport())

    assert "UCCM" in run.session.driver.name
    assert run.session.driver_was_recognised is True


@pytest.mark.parametrize("build", [smartclock_transport, talker_transport, uccm_transport])
async def test_every_page_survives_navigation_for_every_family(build: object) -> None:
    """**§12's #304, which is the defect that produced the capability seam.**

    Every Details page asked for its tier C commands in a form that throws, which was *"correct
    while one family shipped, and a crash on navigation the day a reads-only talker arrived"*. The
    pages are fed whether they are visible or not, so this walks the navigation as well: a page
    that only breaks when it is *shown* would otherwise pass.
    """
    transport = build(FixedClock(NOW)) if build is smartclock_transport else build()  # type: ignore[operator]
    run = await drive(transport)
    reading = run.last
    assert reading is not None

    for row in range(run.details.navigation.count()):
        run.details.navigation.setCurrentRow(row)
        page = run.details.current_page()

        assert page is run.details.pages[row], "navigation and the stack disagree about the page"
        # **Shown, then fed again.** The pages are fed whether they are visible or not, so a page
        # that only breaks once it is on screen — a paint that reads a field the reading does not
        # have — would otherwise never be exercised.
        page.show_reading(reading)
        run.details.refresh_current()


@pytest.mark.parametrize("build", [smartclock_transport, talker_transport, uccm_transport])
async def test_both_windows_lay_out_at_their_own_minimum(build: object) -> None:
    """§9.6.2's floors are measured, not written down — so the measurement has to hold with real
    data in the widgets rather than with empty ones."""
    transport = build(FixedClock(NOW)) if build is smartclock_transport else build()  # type: ignore[operator]
    run = await drive(transport)

    run.window.resize(run.window.minimumWidth(), run.window.minimumHeight())
    run.details.resize(run.details.minimumWidth(), run.details.minimumHeight())

    assert run.window.width() >= run.window.minimumSizeHint().width()
    assert run.details.width() >= run.details.minimumSizeHint().width()


# ---- The one only an end-to-end run can ask ------------------------------------------------------


async def test_a_second_receiver_leaves_nothing_of_the_first_on_screen() -> None:
    """**The defect this part of #99 was written for**: a page rendering a previous receiver's data.

    One window, two receivers in turn, as a user gets when a port is unplugged and another is
    plugged in. The SmartClock's serial number is the thing to look for — it is unmistakable, it is
    on §10.4's Receiver card, and nothing about a talker could ever produce it.
    """
    window = MainWindow()
    first = await drive(smartclock_transport(FixedClock(NOW)), window=window)
    assert any("3625A02931" in text for text in first.texts())

    second = await drive(talker_transport(), window=window)

    assert not any("3625A02931" in text for text in second.texts()), (
        "the talker's pages still carry the SmartClock's serial number"
    )
    assert not any("Z3805A" in text for text in second.texts())
