"""§10.12's auto-detect walk.

What is worth asserting is the **ordering** and the **give-up behaviour**, and neither needs a
serial port — which is why the transport factory is injected. §7.1's own note records what getting
the order wrong cost: an even-parity spelling with no source behind it sat where odd belonged, so a
Z3801A was found on the last attempt of eight rather than the second.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.transport.base import Transport
from smartclock_device.transport.fake import FakeTransport
from smartclock_device.transport.faults import TransportError, TransportFault
from smartclock_device.transport.settings import (
    AUTO_DETECT_SEQUENCE,
    Parity,
    SerialSettings,
    StopBits,
)
from smartclock_monitor.services.autodetect import (
    DetectionCancelledError,
    detect,
    open_with,
)

PROBE = timedelta(milliseconds=5)
IDENTITY = "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"


def clock() -> FixedClock:
    return FixedClock(NOW)


def answering(settings: SerialSettings) -> Transport:
    """A receiver that talks on this combination."""
    return FakeTransport({"*CLS": "", "*IDN?": IDENTITY}, default_response="")


def silent(settings: SerialSettings) -> Transport:
    """A port that opens and answers nothing recognisable — every wrong combination.

    ``default_response=""`` rather than an empty map: an unmapped command makes the fake wait out
    its full timeout, and eight of those per test had this module taking 84 seconds. What is under
    test is the ordering and the give-up behaviour, not the timeout — which
    ``tests/test_line_protocol.py`` covers where it belongs.
    """
    return FakeTransport({"*CLS": ""}, default_response="")


def factory_answering_only_on(wanted: SerialSettings, tried: list[SerialSettings]) -> object:
    def build(port: str, settings: SerialSettings) -> Transport:
        tried.append(settings)
        return answering(settings) if settings == wanted else silent(settings)

    return build


def test_the_first_combination_is_tried_first() -> None:
    """9600-8-N-1 is the Z3805A's factory configuration and the first candidate. A receiver at the
    default should cost one probe."""
    tried: list[SerialSettings] = []
    found = asyncio.run(
        detect(
            "/dev/fake",
            SmartClockDriver(clock=clock()),
            clock(),
            factory_answering_only_on(AUTO_DETECT_SEQUENCE[0], tried),  # type: ignore[arg-type]
            probe=PROBE,
        )
    )

    assert found is not None
    assert found.attempts == 1
    assert tried == [AUTO_DETECT_SEQUENCE[0]]


def test_the_z3801a_is_found_second_rather_than_eighth() -> None:
    """§7.1's correction, asserted. The Z3801A guide says odd twice — "19200 / Parity: Odd / 7
    data bits" — and an even-parity spelling with no source behind it had it eighth, about
    fourteen extra seconds at the probe timeout."""
    z3801a = SerialSettings(19200, 7, Parity.ODD, StopBits.ONE)
    assert AUTO_DETECT_SEQUENCE[1] == z3801a

    tried: list[SerialSettings] = []
    found = asyncio.run(
        detect(
            "/dev/fake",
            SmartClockDriver(clock=clock()),
            clock(),
            factory_answering_only_on(z3801a, tried),  # type: ignore[arg-type]
            probe=PROBE,
        )
    )

    assert found is not None
    assert found.attempts == 2


def test_silence_everywhere_is_none_rather_than_an_error() -> None:
    """A different outcome from a port that would not open, and the caller says something
    different about each."""
    found = asyncio.run(
        detect(
            "/dev/fake",
            SmartClockDriver(clock=clock()),
            clock(),
            lambda port, settings: silent(settings),
            probe=PROBE,
        )
    )

    assert found is None


def test_every_combination_is_tried_before_giving_up() -> None:
    tried: list[SerialSettings] = []

    def build(port: str, settings: SerialSettings) -> Transport:
        tried.append(settings)
        return silent(settings)

    asyncio.run(detect("/dev/fake", SmartClockDriver(clock=clock()), clock(), build, probe=PROBE))

    assert tried == list(AUTO_DETECT_SEQUENCE)


def test_a_port_that_will_not_open_stops_the_walk() -> None:
    """Every remaining combination would fail the same way, so stopping is honest — and seven
    probe timeouts faster than proving it."""
    tried: list[SerialSettings] = []

    class Refusing(FakeTransport):
        async def open(self) -> None:
            raise TransportError(TransportFault.ACCESS_DENIED, "in use")

    def build(port: str, settings: SerialSettings) -> Transport:
        tried.append(settings)
        return Refusing({}, default_response="")

    with pytest.raises(TransportError):
        asyncio.run(
            detect("/dev/fake", SmartClockDriver(clock=clock()), clock(), build, probe=PROBE)
        )

    assert len(tried) == 1, "it must not try all eight against a port it cannot have"


def test_a_combination_that_fails_oddly_does_not_abandon_the_walk() -> None:
    """A wrong baud rate produces framing noise that can fail in a variety of ways, and none of
    them is a reason to give up with six candidates untried."""
    tried: list[SerialSettings] = []
    wanted = AUTO_DETECT_SEQUENCE[3]

    class Exploding(FakeTransport):
        async def open(self) -> None:
            raise RuntimeError("framing noise decoded as something absurd")

    def build(port: str, settings: SerialSettings) -> Transport:
        tried.append(settings)
        if settings == wanted:
            return answering(settings)
        return Exploding({})

    found = asyncio.run(
        detect("/dev/fake", SmartClockDriver(clock=clock()), clock(), build, probe=PROBE)
    )

    assert found is not None
    assert found.settings == wanted
    assert found.attempts == 4


def test_progress_is_reported_before_each_attempt() -> None:
    """§10.12 asks for progress. Reported *before* the attempt, because the probe is the part that
    takes time and a progress line that appeared after it would always be a step behind."""
    seen: list[tuple[str, int, int]] = []
    asyncio.run(
        detect(
            "/dev/fake",
            SmartClockDriver(clock=clock()),
            clock(),
            lambda port, settings: silent(settings),
            probe=PROBE,
            on_progress=lambda settings, index, total: seen.append((str(settings), index, total)),
        )
    )

    assert len(seen) == len(AUTO_DETECT_SEQUENCE)
    assert seen[0] == ("9600-8-N-1", 1, len(AUTO_DETECT_SEQUENCE))
    assert [index for _, index, _ in seen] == list(range(1, len(AUTO_DETECT_SEQUENCE) + 1))


def test_cancelling_stops_the_walk() -> None:
    tried: list[SerialSettings] = []

    def build(port: str, settings: SerialSettings) -> Transport:
        tried.append(settings)
        return silent(settings)

    with pytest.raises(DetectionCancelledError):
        asyncio.run(
            detect(
                "/dev/fake",
                SmartClockDriver(clock=clock()),
                clock(),
                build,
                probe=PROBE,
                should_cancel=lambda: len(tried) >= 2,
            )
        )

    assert len(tried) == 2


def test_cancelling_is_not_the_same_as_finding_nothing() -> None:
    """An exception rather than ``None`` so it cannot be mistaken for "nothing answered", which is
    a different thing to tell the user."""
    assert issubclass(DetectionCancelledError, Exception)


def test_the_manual_path_does_not_fall_back_to_the_walk() -> None:
    """A user who has picked a setting is asserting something about their hardware. Quietly trying
    seven others would make the picker a suggestion."""
    tried: list[SerialSettings] = []

    def build(port: str, settings: SerialSettings) -> Transport:
        tried.append(settings)
        return silent(settings)

    session = asyncio.run(
        open_with(
            "/dev/fake",
            SerialSettings(1200, 8, Parity.NONE, StopBits.ONE),
            SmartClockDriver(clock=clock()),
            clock(),
            build,
            probe=PROBE,
        )
    )

    assert tried == [SerialSettings(1200, 8, Parity.NONE, StopBits.ONE)]
    assert session.identity is None


def test_the_sequence_is_the_eight_section_7_1_gives() -> None:
    """Pinned because the order *is* the design: every combination costs about the same, so where
    a receiver sits in the list is the whole of how long it takes to find."""
    assert len(AUTO_DETECT_SEQUENCE) == 8
    assert [str(settings) for settings in AUTO_DETECT_SEQUENCE] == [
        "9600-8-N-1",
        "19200-7-O-1",
        "19200-7-E-1",
        "9600-7-E-1",
        "19200-8-N-1",
        "2400-8-N-1",
        "1200-8-N-1",
        "9600-7-O-1",
    ]
