"""§12's second family: a receiver that talks instead of answering.

**This is what exercises the seam.** A contract satisfied by one implementation is a contract
nobody has tested — every assumption the SmartClock happens to satisfy looks like a requirement
until something else has to meet it.

The sentences here come from ``tools/nmea_simulator.py``, which is kept apart from the driver so a
driver author takes one folder and never sees it. Nothing under ``src/`` imports it.
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import nmea_simulator

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.drivers.base import (
    WHOLE_CYCLE,
    LinkStyle,
    ReceiverDriver,
)
from smartclock_device.drivers.nmea import (
    NmeaDriver,
    sentences,
)
from smartclock_device.drivers.registry import Registry
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_device.transport.broadcast import BroadcastListener
from smartclock_device.transport.fake import FakeTransport
from smartclock_device.transport.transaction import Transaction, TransactionOutcome
from smartclock_monitor.services.session import DeviceSession


def clock() -> FixedClock:
    return FixedClock(NOW)


def driver() -> NmeaDriver:
    return NmeaDriver(clock=clock())


def a_cycle(fix: bool = True) -> list[str]:
    return list(nmea_simulator.cycle(time.gmtime(0), fix=fix))


def as_transaction(lines: list[str]) -> Transaction:
    return Transaction(
        command=WHOLE_CYCLE, outcome=TransactionOutcome.COMPLETED, lines=tuple(lines)
    )


# ---- The contract ---------------------------------------------------------------------------


def test_it_is_a_driver() -> None:
    """If this fails the seam is a suggestion. Everything else here depends on it."""
    assert isinstance(driver(), ReceiverDriver)


def test_it_is_a_talker_and_is_never_written_to() -> None:
    """A talker has no command parser. §12's capability gate turns an empty allowlist into greyed
    controls with a sentence, rather than buttons that fail on click."""
    family = driver()

    assert family.link is LinkStyle.BROADCAST
    for mnemonic in ("*IDN?", ":SYST:STAT?", ":SYNC:HOLD:INIT", "anything at all"):
        assert family.is_allowed(mnemonic) is False, mnemonic


def test_nothing_is_excluded_because_nothing_can_be_sent() -> None:
    """§8.4 has nothing to bite on for a family with no command parser — which is a different
    statement from "this family's exclusions are empty" and is why the verdict is asked rather
    than a list being consulted."""
    assert driver().is_blocked(":SYST:STAT?") is False


def test_it_is_never_recognised_by_identity() -> None:
    """A talker would not answer ``*IDN?``, so claiming an identity would be claiming a receiver
    it had never heard from."""
    family = driver()

    assert family.recognises(DeviceIdentity.parse("SYMMETRICOM,Z3805A,1,1")) is False
    assert family.recognises(None) is False


# ---- Recognition by listening ----------------------------------------------------------------


def test_it_claims_a_stream_it_has_overheard() -> None:
    """§12: recognised by what the synchronise step heard, before anything was asked — and
    ``*IDN?`` is never sent to a receiver claimed that way."""
    assert driver().overhear(a_cycle()) is True


def test_one_sentence_is_not_a_talker() -> None:
    """A single valid sentence can arrive from another device sharing the bus, and claiming on it
    would take over a link that belongs to something else."""
    assert driver().overhear([a_cycle()[0]]) is False


def test_a_stream_with_no_fix_sentence_is_not_claimed() -> None:
    """GGA is the boundary as well as the discriminator: a cycle whose boundary never arrives
    never closes and is never answered, so a stream without one is not one this can read."""
    without_gga = [line for line in a_cycle() if "GGA" not in line]

    assert driver().overhear(without_gga) is False


def test_the_smartclock_s_own_banner_is_not_claimed() -> None:
    """The two families share a port type, and the walk offers every driver the same lines."""
    assert driver().overhear(["SYMMETRICOM,Z3805A,3625A02931,1.01.03-A", "scpi > "]) is False


def test_a_talker_wins_the_registry_over_a_family_that_needs_an_identity() -> None:
    """Registered first, and nothing else claims a stream it has not identified."""
    registry = Registry([driver(), SmartClockDriver(clock=clock())])

    # The talker is chosen by overhearing, not by select() — which is keyed on identity — so this
    # asserts the other half: nothing claims a talker's stream by mistake.
    assert registry.select(None).recognised is False


# ---- Classifying and cycling -------------------------------------------------------------------


def test_every_sentence_is_classified() -> None:
    family = driver()

    kinds = {family.classify(line) for line in a_cycle()}

    assert kinds == {"GGA", "GSA", "GSV", "RMC"}


def test_a_line_that_is_not_ours_is_not_claimed() -> None:
    family = driver()

    assert family.classify("scpi > ") is None
    assert family.classify("$GPVTG,0.0,T,,M,0.0,N,0.0,K,A*23") is None, "valid, but not in the plan"


def test_the_listener_answers_from_the_last_complete_cycle() -> None:
    """A sentence that arrives in three parts is wrong twice before it is right, and a reader who
    saw the half-arrived state would watch the satellite count drop and recover every second."""
    family = driver()
    listener = BroadcastListener(clock=clock(), boundary=sentences.GGA)

    for line in a_cycle():
        listener.feed(family.classify(line), line)

    assert listener.has_answered is False, "the cycle has not closed yet"
    assert listener.answer(sentences.GGA) == ()

    # The boundary comes round again.
    listener.feed(family.classify(a_cycle()[0]), a_cycle()[0])

    assert listener.cycles == 1
    assert len(listener.answer(sentences.GSV)) == 2
    assert len(listener.whole_cycle()) == len(a_cycle())


def test_a_line_from_another_device_still_counts_as_traffic() -> None:
    """A talker sharing a bus with something else is alive, and treating another device's sentence
    as silence would report a link that is plainly working as gone."""
    listener = BroadcastListener(clock=clock(), boundary=sentences.GGA)
    listener.feed(None, "something else entirely")

    assert listener.is_quiet() is False


def test_silence_is_reported_as_a_timeout() -> None:
    """§12: *"reporting a talker that has gone quiet as a timeout so the reconnect logic applies
    unchanged."* Giving broadcast its own failure vocabulary would mean teaching the supervisor a
    second one."""
    moving = FixedClock(NOW)
    listener = BroadcastListener(clock=moving, boundary=sentences.GGA)
    listener.feed(sentences.GGA, a_cycle()[0])
    assert listener.is_quiet() is False

    moving.advance(timedelta(seconds=6))
    assert listener.is_quiet() is True


def test_a_listener_that_has_heard_nothing_is_quiet_at_once() -> None:
    """A port opened onto a device that never speaks is exactly the case auto-detect walks past,
    and waiting five seconds to say so would cost five seconds per combination."""
    assert BroadcastListener(clock=clock(), boundary=sentences.GGA).is_quiet() is True


# ---- Reading a cycle ---------------------------------------------------------------------------


def test_a_cycle_becomes_a_status() -> None:
    status = driver().parse_full(as_transaction(a_cycle()), None)

    assert status.mode is SmartClockMode.LOCKED
    assert status.position is not None
    assert status.position.latitude_degrees == pytest.approx(47.5218, abs=0.001)
    assert status.position.longitude_degrees == pytest.approx(-122.2062, abs=0.001)


def test_tracked_and_visible_are_told_apart() -> None:
    """GSV lists what is visible and GSA lists what is used. §10.5's table draws exactly that
    distinction, and a driver that reported everything visible as tracked would make the sky plot
    claim six satellites it was not using."""
    status = driver().parse_full(as_transaction(a_cycle()), None)

    assert len(status.tracked) == 6
    assert len(status.not_tracked) == 2
    assert {sat.prn for sat in status.not_tracked} == {3, 30}


def test_a_satellite_with_no_strength_keeps_none() -> None:
    """An empty GSV strength field is a satellite the talker sees and is not tracking. Zero would
    be a measurement — and one saying the signal is absent rather than unreported."""
    status = driver().parse_full(as_transaction(a_cycle()), None)

    assert all(sat.signal_strength is not None for sat in status.tracked)


def test_no_fix_is_not_holdover() -> None:
    """§12's #304 item 3: the mode is the driver's. A talker with no fix is *searching* — it is
    not in holdover, because it has no oscillator to hold over on."""
    status = driver().parse_full(as_transaction(a_cycle(fix=False)), None)

    assert status.mode is SmartClockMode.RECOVERY
    assert status.mode not in {SmartClockMode.HOLDOVER, SmartClockMode.LOCKED}


def test_it_invents_none_of_the_oscillator_fields() -> None:
    """The heart of it. NMEA carries no 1 PPS interval, no EFC, no TFOM, no holdover — and §11.1's
    discipline is what makes leaving them empty safe rather than broken: every consumer already
    renders None as a dash. A driver that filled them with plausible numbers would be worse,
    because nothing downstream could tell."""
    status = driver().parse_full(as_transaction(a_cycle()), None)

    assert status.one_pps_ti_nanoseconds is None
    assert status.tfom is None
    assert status.ffom is None
    assert status.holdover_duration is None
    assert status.antenna_delay_nanoseconds is None


def test_the_time_scale_is_stated_as_utc() -> None:
    """§10.14 renders the scale because UTC and GPS differ by the accumulated leap seconds, and a
    talker reports UTC."""
    from smartclock_device.models.receiver_status import TimeScale

    assert driver().parse_full(as_transaction(a_cycle()), None).time_scale is TimeScale.UTC


def test_no_date_is_inferred_from_the_host_clock() -> None:
    """A talker that has not decoded the almanac sends a time and no date. Pairing it with today's
    date would produce a timestamp that looked authoritative and came half from this machine —
    the §7.4 mistake in a different costume."""
    without_rmc = [line for line in a_cycle() if "RMC" not in line]

    status = driver().parse_full(as_transaction(without_rmc), None)

    assert status.device_date_time is None


def test_the_parser_never_raises() -> None:
    """§11.1, and a talker on a shared bus is the case it was written for: sentences from other
    devices, at other revisions, sometimes truncated by a reconnect."""
    rubbish = [
        "",
        "$",
        "$GPGGA",
        "$GPGGA,*FF",
        "$GPGGA," + "," * 40,
        "$GPGSV,2,1,8," + "x" * 200,
        "not a sentence at all",
        "$GPRMC,999999,A,9999.9999,Q,,,,,999999,,,*00",
    ]

    status = driver().parse_full(as_transaction(rubbish), None)

    assert status.mode is SmartClockMode.UNKNOWN
    assert status.position is None


def test_a_bad_checksum_is_dropped_rather_than_half_read() -> None:
    """There is no framing here beyond ``$…*hh``: a line that arrived with a byte flipped looks
    exactly like a valid line with different numbers in it."""
    good = a_cycle()[0]
    flipped = good[:-2] + "00"

    assert sentences.parse(good) is not None
    assert sentences.parse(flipped) is None


def test_the_packed_coordinate_format_is_not_read_as_a_decimal() -> None:
    """``ddmm.mmmm`` with no separator is the single most common thing to get wrong about NMEA:
    reading it as a decimal gives a position that is plausible, wrong, and wrong by a different
    amount at every latitude."""
    assert sentences.parse_degrees("4807.038", "N") == pytest.approx(48.1173, abs=0.0001)
    assert sentences.parse_degrees("4807.038", "S") == pytest.approx(-48.1173, abs=0.0001)
    assert sentences.parse_degrees("4807.038", "N") != pytest.approx(4807.038)


def test_minutes_of_sixty_or_more_are_refused() -> None:
    """A malformed field that happens to be numeric is exactly the case §11.1 exists for."""
    assert sentences.parse_degrees("4890.000", "N") is None


def test_a_timestamp_round_trips_from_the_simulator() -> None:
    """End to end through the sentence the simulator wrote.

    A date in this century, because RMC carries a **two-digit year** and there is no more of it to
    read — the century is a convention rather than data, and this driver takes 2000. Written
    against the epoch first, which RMC simply cannot express: it came back as 2070.
    """
    when = time.gmtime(1_780_000_000)  # 2026-06-08, in the century the convention assumes
    lines = list(nmea_simulator.cycle(when))

    status = driver().parse_full(as_transaction(lines), None)

    assert status.device_date_time is not None
    assert status.device_date_time.tzinfo is UTC
    assert status.device_date_time == datetime(
        when.tm_year, when.tm_mon, when.tm_mday, when.tm_hour, when.tm_min, when.tm_sec, tzinfo=UTC
    )


def test_a_line_with_no_checksum_is_refused() -> None:
    """The checksum is the only thing distinguishing a valid sentence from a byte-flipped one, so
    a line carrying none has nothing saying it is not that. Accepting one let a GGA of forty empty
    commas through and report *no fix* rather than *not a sentence*."""
    assert sentences.parse("$GPGGA,123519,4807.038,N,01131.000,E,1,08,0.9,545.4,M,46.9,M,,") is None
    assert sentences.parse("$GPGGA," + "," * 40) is None


# ---- The session holds a talker ----------------------------------------------------------------
#
# The wiring, not the driver: that a broadcast family reaches the poller through the same
# ``session.execute(mnemonic)`` every page and every poll already uses. §12 keeps the plan one type
# for both link styles, so the branch lives in the session and nothing above it knows.


def a_talker_session(clock_: FixedClock | None = None) -> tuple[DeviceSession, FakeTransport]:
    tick = clock_ if clock_ is not None else clock()
    smartclock = SmartClockDriver(clock=tick)
    transport = FakeTransport(banner="\r\n".join(a_cycle()) + "\r\n")
    session = DeviceSession(
        transport=transport,
        driver=smartclock,
        clock=tick,
        registry=Registry([smartclock, NmeaDriver(clock=tick)]),
    )
    return session, transport


@pytest.mark.asyncio
async def test_a_talker_is_claimed_and_never_probed() -> None:
    """The whole reason recognition-by-listening runs first. ``*IDN?`` would cost a full timeout
    on a device that cannot answer it, and it would be a *write* to a link this driver says is
    never written to."""
    session, transport = a_talker_session()

    await session.open(probe=timedelta(milliseconds=50))

    assert session.driver.name == "NMEA 0183 talker"
    assert session.driver_was_recognised is True
    assert transport.written == [], "nothing may be sent to a talker, the probe included"

    await session.close()


@pytest.mark.asyncio
async def test_a_smartclock_is_still_probed_and_claimed() -> None:
    """The other half, and the one that would break quietly: registering a second family must not
    change what happens to the first."""
    tick = clock()
    smartclock = SmartClockDriver(clock=tick)
    transport = FakeTransport(
        {"*IDN?": "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"},
        banner="SYMMETRICOM,Z3805A,3625A02931,1.01.03-A\r\nscpi > ",
    )
    session = DeviceSession(
        transport=transport,
        driver=smartclock,
        clock=tick,
        registry=Registry([smartclock, NmeaDriver(clock=tick)]),
    )

    await session.open(probe=timedelta(milliseconds=50))

    assert session.driver is smartclock
    assert session.driver_was_recognised is True
    assert "*IDN?" in transport.written

    await session.close()


@pytest.mark.asyncio
async def test_a_plan_key_is_answered_from_the_stream() -> None:
    session, transport = a_talker_session()
    await session.open(probe=timedelta(milliseconds=50))

    # Two more cycles, so one has closed and can be answered from.
    for _ in range(2):
        transport.feed("\r\n".join(a_cycle()) + "\r\n")
    await asyncio.sleep(0.05)

    answer = await session.execute(sentences.GSV)

    assert isinstance(answer, Transaction)
    assert answer.succeeded
    assert len(answer.lines) == 2
    assert transport.written == [], "answering a key must never write"

    await session.close()


@pytest.mark.asyncio
async def test_the_whole_cycle_key_answers_the_whole_cycle() -> None:
    session, transport = a_talker_session()
    await session.open(probe=timedelta(milliseconds=50))
    for _ in range(2):
        transport.feed("\r\n".join(a_cycle()) + "\r\n")
    await asyncio.sleep(0.05)

    answer = await session.execute(WHOLE_CYCLE)

    assert isinstance(answer, Transaction)
    assert len(answer.lines) == len(a_cycle())

    await session.close()


@pytest.mark.asyncio
async def test_a_cycle_still_in_progress_is_not_a_failure() -> None:
    """The first second of every connection. Reporting it as a failure would spend a third of
    §7.2's three-consecutive-failures budget on a link that is working perfectly."""
    session, _ = a_talker_session()
    await session.open(probe=timedelta(milliseconds=50))

    answer = await session.execute(sentences.GSV)

    assert isinstance(answer, Transaction)
    assert answer.succeeded, "nothing to report yet is not the same as a failure"
    assert answer.lines == ()

    await session.close()


@pytest.mark.asyncio
async def test_a_talker_that_goes_quiet_reports_a_timeout() -> None:
    """§12: silence reuses the vocabulary §7.2 already has. Teaching the supervisor, the failure
    count and the status bar a second failure mode would buy nothing."""
    tick = clock()
    session, transport = a_talker_session(tick)
    await session.open(probe=timedelta(milliseconds=50))
    transport.feed("\r\n".join(a_cycle()) + "\r\n")
    await asyncio.sleep(0.05)

    tick.advance(timedelta(seconds=30))
    answer = await session.execute(sentences.GGA)

    assert isinstance(answer, Transaction)
    assert answer.outcome is TransactionOutcome.TIMED_OUT

    await session.close()


@pytest.mark.asyncio
async def test_closing_stops_the_listener() -> None:
    """A reader left running against a closed port is a task that faults with nobody waiting on it,
    and asyncio only holds a weak reference to it — so it is kept and cancelled deliberately."""
    session, _ = a_talker_session()
    await session.open(probe=timedelta(milliseconds=50))

    await session.close()

    assert session._listen_task is None
