"""The session and the §7.3 poll loop, driven with no hardware.

Phase 4's done-condition is that a fake clock can drive a full poll schedule deterministically.
What makes that possible is that nothing here reaches for a real clock or a real port: the session
takes a :class:`Transport`, the driver takes a :class:`Clock`, and both are injected.

The §7.3.1 tests are the ones worth reading. That rule exists because an unlocked receiver asked
once a second for a reading it cannot give filled its error queue until it began answering *queue
overflow*, and the Diagnostics page could not empty it because the sweep refilled it faster than
the page drained it. Real errors were being discarded to make room for poll noise.
"""

from __future__ import annotations

import asyncio
import dataclasses
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.drivers.capability import STATUS_FIELDS
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.models.device_identity import ReceiverModel
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_device.transport.fake import FakeTransport, error_prompt
from smartclock_device.transport.transaction import Transaction, TransactionOutcome
from smartclock_monitor.services.polling import PollingService, Reading
from smartclock_monitor.services.replay import DEMO_SEQUENCE, ReplayTransport
from smartclock_monitor.services.session import ConnectionState, DeviceSession, Refusal

from smartclock_device.drivers.smartclock import SmartClockDriver  # isort: skip

#: Every ReceiverStatus field any reading maps to, so the gate below can ask what moved.
STATUS_FIELDS_ALL = tuple(name for names in STATUS_FIELDS.values() for name in names)

FIXTURES = Path(__file__).resolve().parent / "fixtures"
IDENTITY = "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("latin-1")


#: The connect probe, shortened for the tests.
#:
#: A silent fake costs the full §7.2 probe on every ``open()``, and at eighteen connections that
#: was thirty seconds of the suite spent waiting for a banner nobody sent. A suite nobody runs
#: because it is slow is a suite that catches nothing.
PROBE = timedelta(milliseconds=20)


def build(responses: dict[str, str], **kwargs: object) -> tuple[DeviceSession, FakeTransport]:
    clock = FixedClock(NOW)
    transport = FakeTransport(responses, **kwargs)  # type: ignore[arg-type]
    session = DeviceSession(transport, SmartClockDriver(clock=clock), clock)
    return session, transport


def poller(session: DeviceSession) -> PollingService:
    clock = FixedClock(NOW)
    return PollingService(session=session, driver=SmartClockDriver(clock=clock), clock=clock)


SWEEP: dict[str, str] = {
    ":SYNC:STAT?": " LOCK",
    ":SYNC:TFOM?": " +3",
    ":SYNC:FFOM?": " +0",
    ":SYNC:TINT?": " -5.4E-009",
    ":DIAG:ROSC:EFC:REL?": " +2.4E+001",
    ":GPS:SAT:TRAC:COUN?": " +6",
    # The full tier's one extra (#112). Scripted here rather than left unanswered because an
    # unscripted command queues nothing at all from the fake — the honest simulation of a silent
    # receiver — and the poll would then pay a transaction timeout before retiring it, which is
    # correct behaviour and three seconds of suite time per test that never meant to test it.
    ":STAT:OPER:HARD:COND?": " +0",
}


# ---- The session -------------------------------------------------------------------------------


async def test_an_identity_missed_at_connect_is_asked_for_again() -> None:
    """#29's gate, and it fails without the re-probe.

    A transient at open was permanent for this one field and temporary for every other: the status
    screen is re-read every poll, so a garbled answer costs one cycle, while the identity was read
    once in `open` and never again. Seen on real hardware — the receiver locked and tracked six
    satellites while the window called it "an unidentified receiver" for the whole session.

    The mechanism is `spend_startup_glitch`: the first command after the port opens draws `E-362>`
    on this hardware, and two commands are spent absorbing it. When two is not enough, `*IDN?` is
    next in line.
    """
    session, transport = build(
        {"*CLS": "", ":SYST:STAT?": read_fixture("captured/locked-to-gps.txt")}
    )
    await session.open(probe=PROBE)

    # Read into a local rather than asserted on the attribute: mypy keeps the narrowing and calls
    # everything after the later "is not None" unreachable.
    at_connect = session.identity
    assert at_connect is None, "the fake never answered *IDN?, so the connect cannot have"
    conservative = session.profile.model
    assert conservative is ReceiverModel.UNKNOWN, "§8.6 falls back to the conservative one"

    # The receiver starts answering, as it would once past its own startup glitch.
    transport.script("*IDN?", IDENTITY)
    filled = await session.refresh_identity()

    assert filled is True, "the re-probe reported nothing changed"
    identity = session.identity
    assert identity is not None
    assert identity.receiver is ReceiverModel.Z3805A
    adopted = session.profile.model
    assert adopted is ReceiverModel.Z3805A, "§8.6's profile follows the identity"

    assert await session.refresh_identity() is False, (
        "a session that already knows its identity must not re-announce it on every poll"
    )
    await session.close()


async def test_the_poll_loop_is_what_asks_again() -> None:
    """The re-probe has to be reached by something that runs repeatedly, or it is just a method.

    Wired to the *slow* tier: the identity does not change while a receiver is plugged in, so
    asking on every fast sweep would spend a command a second on a question already answered.
    """
    screen = read_fixture("captured/locked-to-gps.txt")
    session, transport = build({"*CLS": "", ":SYST:STAT?": screen, **SWEEP})
    await session.open(probe=PROBE)
    at_connect = session.identity
    assert at_connect is None

    told: list[None] = []
    service = poller(session)
    service.on_identity = lambda: told.append(None)

    transport.script("*IDN?", IDENTITY)
    await service.poll_full()

    identity = session.identity
    assert identity is not None, "a full poll did not retry the identity"
    assert len(told) == 1, "the surfaces that name the receiver were never told"

    await service.poll_full()
    assert len(told) == 1, "it announced the same identity twice"
    await session.close()


async def test_connecting_absorbs_the_banner_and_learns_the_model() -> None:
    """The banner names the model and firmware before a command is sent, and §8.6 needs the model
    to decide which commands exist."""
    session, _ = build({"*CLS": "", "*IDN?": IDENTITY}, banner=f"{IDENTITY}\r\n")

    await session.open(PROBE)

    assert session.state is ConnectionState.CONNECTED
    assert session.identity is not None
    assert session.identity.receiver is ReceiverModel.Z3805A


def test_a_fresh_session_has_the_conservative_profile() -> None:
    """§8.5: absent unless shown to be present. Before the identity is read, nothing optional is
    claimed."""
    session, _ = build({})

    assert session.profile.has_second_serial_port is False
    assert session.state is ConnectionState.DISCONNECTED


async def test_a_silent_receiver_still_connects() -> None:
    """A sibling model may not announce itself, and that is not a failure to connect."""
    session, _ = build({"*CLS": "", "*IDN?": IDENTITY})

    await session.open(PROBE)

    assert session.state is ConnectionState.CONNECTED


async def test_an_uncatalogued_command_is_refused_rather_than_sent() -> None:
    """The point-of-send allowlist check (§8.1). The question asked is whether the command *is*
    catalogued, never whether it is excluded."""
    session, transport = build({"*CLS": "", "*IDN?": IDENTITY})
    await session.open(PROBE)
    before = len(transport.written)

    result = await session.execute(":NOSUCH:COMMAND?")

    assert isinstance(result, Refusal)
    assert len(transport.written) == before, "A refused command must not reach the wire."


async def test_a_refusal_is_returned_rather_than_raised() -> None:
    """A bug in a poll loop should surface as a diagnostic, not take the loop down."""
    session, _ = build({"*CLS": "", "*IDN?": IDENTITY})
    await session.open(PROBE)

    result = await session.execute(":NOSUCH?")

    assert isinstance(result, Refusal)
    assert result.mnemonic == ":NOSUCH?"


async def test_three_consecutive_timeouts_lose_the_link() -> None:
    """§7.2's rule. Two is not enough — a lab on the end of a serial cable drops the occasional
    reply, and reconnecting on the first one would thrash."""
    session, _ = build({"*CLS": "", "*IDN?": IDENTITY})
    await session.open(PROBE)

    brief = timedelta(milliseconds=30)
    for _ in range(2):
        await session.execute(":SYNC:TINT?", brief)
    after_two = session.state

    await session.execute(":SYNC:TINT?", brief)
    after_three = session.state

    assert after_two is ConnectionState.CONNECTED, "Two timeouts must not lose the link."
    assert after_three is ConnectionState.LOST


async def test_one_success_resets_the_failure_count() -> None:
    """Consecutive, not cumulative."""
    session, _ = build({"*CLS": "", "*IDN?": IDENTITY, ":SYNC:STAT?": " LOCK"})
    await session.open(PROBE)
    brief = timedelta(milliseconds=30)

    await session.execute(":SYNC:TINT?", brief)
    await session.execute(":SYNC:TINT?", brief)
    await session.execute(":SYNC:STAT?")
    await session.execute(":SYNC:TINT?", brief)

    assert session.state is ConnectionState.CONNECTED


async def test_a_fault_loses_the_link_immediately() -> None:
    """A fault is not a timeout: the link is gone now, not three tries from now."""
    session, transport = build({"*CLS": "", "*IDN?": IDENTITY})
    await session.open(PROBE)
    await transport.close()

    await session.execute(":SYNC:STAT?", timedelta(milliseconds=30))

    assert session.state is ConnectionState.LOST
    assert session.last_fault is not None


def test_two_sessions_share_no_state() -> None:
    """§12: per-device, never a singleton. v1 connects to one receiver and this must not be baked
    in, so there is no module-level state for the connection or the identity."""
    first, _ = build({})
    second, _ = build({})

    assert first is not second
    assert first.identity is None and second.identity is None


# ---- The poll loop -----------------------------------------------------------------------------


async def test_a_full_read_produces_a_status() -> None:
    screen = read_fixture("captured/locked-to-gps.txt")
    session, _ = build({"*CLS": "", "*IDN?": IDENTITY, ":SYST:STAT?": screen})
    await session.open(PROBE)
    service = poller(session)

    await service.poll_full()

    assert service.latest is not None
    assert service.latest.status.mode is SmartClockMode.LOCKED


async def test_the_fast_sweep_folds_into_the_last_full_status() -> None:
    screen = read_fixture("captured/locked-to-gps.txt")
    session, _ = build({"*CLS": "", "*IDN?": IDENTITY, ":SYST:STAT?": screen, **SWEEP})
    await session.open(PROBE)
    service = poller(session)

    await service.poll_full()
    await service.poll_fast()

    reading = service.latest
    assert reading is not None
    assert reading.status.tfom == 3
    assert reading.tracked_count == 6
    assert reading.sync_state == "LOCK"


async def test_the_fast_sweep_asks_in_section_7_3_s_order() -> None:
    session, transport = build({"*CLS": "", "*IDN?": IDENTITY, **SWEEP})
    await session.open(PROBE)
    transport.written.clear()

    await poller(session).poll_fast()

    assert transport.written == [command.mnemonic for command in catalog.FAST_TIER]


async def test_a_reading_arrives_through_the_callback() -> None:
    screen = read_fixture("captured/locked-to-gps.txt")
    session, _ = build({"*CLS": "", "*IDN?": IDENTITY, ":SYST:STAT?": screen})
    await session.open(PROBE)

    seen: list[Reading] = []
    service = poller(session)
    service.on_reading = seen.append

    await service.poll_full()

    assert len(seen) == 1


# ---- §7.3.1 -------------------------------------------------------------------------------------


def refusing_sweep() -> dict[str, str]:
    """The sweep as an **unlocked** receiver answers it: everything but the time interval.

    The sync state is ``HOLD`` rather than ``LOCK``, because that is the situation in which the
    receiver refuses: there is no GPS 1 PPS to measure against. A refusal reported while the state
    said ``LOCK`` would make the self-clearing test below pass for the wrong reason.
    """
    answers = {key: value for key, value in SWEEP.items() if key != ":SYNC:TINT?"}
    answers[":SYNC:STAT?"] = " HOLD"
    return answers


async def test_a_refused_reading_is_not_asked_for_again_in_the_same_state() -> None:
    """The rule. Asked once a second, this filled the bench receiver's error queue until real
    errors were being discarded to make room for poll noise."""
    responses = {"*CLS": "", "*IDN?": IDENTITY, **refusing_sweep(), ":SYNC:TINT?": ""}
    session, transport = build(responses, prompt=error_prompt(230))
    await session.open(PROBE)
    service = poller(session)

    await service.poll_fast()
    assert ":SYNC:TINT?" in transport.written

    transport.written.clear()
    await service.poll_fast()

    assert ":SYNC:TINT?" not in transport.written, "The refused reading was asked for again."


async def test_the_rest_of_the_sweep_still_runs_while_one_reading_is_suppressed() -> None:
    """Suppressing one reading must not cost the other five."""
    responses = {"*CLS": "", "*IDN?": IDENTITY, **refusing_sweep(), ":SYNC:TINT?": ""}
    session, transport = build(responses, prompt=error_prompt(230))
    await session.open(PROBE)
    service = poller(session)

    await service.poll_fast()
    transport.written.clear()
    await service.poll_fast()

    assert len(transport.written) == len(catalog.FAST_TIER) - 1


async def test_the_suppression_self_clears_when_the_state_changes() -> None:
    """A receiver that regains lock is asked again on the next sweep, because its state changed."""
    responses = {"*CLS": "", "*IDN?": IDENTITY, **refusing_sweep(), ":SYNC:TINT?": ""}
    session, transport = build(responses, prompt=error_prompt(230))
    await session.open(PROBE)
    service = poller(session)

    await service.poll_fast()  # refused while HOLD

    # The receiver regains lock.
    transport.script(":SYNC:STAT?", " LOCK")
    transport.written.clear()
    await service.poll_fast()

    assert ":SYNC:TINT?" in transport.written, "A state change must lift the suppression."


async def test_a_timeout_does_not_suppress_anything(monkeypatch: pytest.MonkeyPatch) -> None:
    """**Only a refusal counts.** A timeout or a dropped link says nothing about whether the
    receiver would have answered, and suppressing a reading because a cable was unplugged would
    keep it suppressed after the cable was plugged back in.

    The scalar deadline is shortened for this one test. Two sweeps against an unanswering receiver
    is six seconds of real waiting at §7.2's three-second tier, and a suite nobody runs because it
    is slow is a suite that catches nothing.
    """
    from smartclock_device.transport import timeouts as _timeouts

    monkeypatch.setattr(_timeouts, "DEFAULT", timedelta(milliseconds=30))

    responses = {"*CLS": "", "*IDN?": IDENTITY, **refusing_sweep()}  # TINT? simply never answers
    session, transport = build(responses)
    await session.open(PROBE)
    service = poller(session)

    await service.poll_fast()
    transport.written.clear()
    await service.poll_fast()

    assert ":SYNC:TINT?" in transport.written, "A timeout must not suppress a reading."


async def test_the_state_query_is_asked_before_the_refusable_one() -> None:
    """The rule depends on knowing the state before the rest of the tier is asked."""
    session, transport = build({"*CLS": "", "*IDN?": IDENTITY, **SWEEP})
    await session.open(PROBE)
    transport.written.clear()

    await poller(session).poll_fast()

    assert transport.written.index(":SYNC:STAT?") < transport.written.index(":SYNC:TINT?")


# ---- The replay --------------------------------------------------------------------------------


async def test_the_replay_drives_the_whole_stack() -> None:
    """The demo answers through the same transport interface a real port does, so what runs is the
    line protocol, the session and the poll loop rather than a shortcut around them."""
    clock = FixedClock(NOW)
    transport = ReplayTransport(clock, chunk_size=64)
    session = DeviceSession(transport, SmartClockDriver(clock=clock), clock)

    await session.open(PROBE)
    service = poller(session)
    await service.poll_full()
    await service.poll_fast()

    reading = service.latest
    assert reading is not None
    assert reading.status.mode is not SmartClockMode.UNKNOWN
    assert session.identity is not None


async def test_the_replay_walks_through_its_states() -> None:
    """A reviewer sees the whole §9.11 matrix in a couple of minutes rather than one locked
    receiver."""
    clock = FixedClock(NOW)
    transport = ReplayTransport(clock, advance_every=1, chunk_size=None)
    session = DeviceSession(transport, SmartClockDriver(clock=clock), clock)
    await session.open(PROBE)
    service = poller(session)

    modes = set()
    for _ in range(len(DEMO_SEQUENCE)):
        await service.poll_full()
        assert service.latest is not None
        modes.add(service.latest.status.mode)

    assert len(modes) >= 3, "The replay should show several distinct states."


async def test_the_replay_reproduces_the_refusal_while_unlocked() -> None:
    """§7.3.1 is visible in the demo rather than only in a test: while the replayed screen is not
    locked, the time interval is answered with an error prompt and no body."""
    clock = FixedClock(NOW)
    # Starts on power-up acquisition, which is not locked.
    transport = ReplayTransport(clock, screens=("captured/power-up-gps-acquisition.txt",))
    session = DeviceSession(transport, SmartClockDriver(clock=clock), clock)
    await session.open(PROBE)

    result = await session.execute(":SYNC:TINT?")

    assert isinstance(result, Transaction)
    assert result.was_rejected is True


async def test_the_replay_scalars_agree_with_the_screen_they_came_from() -> None:
    """A demo whose figures of merit disagreed with its own status screen would teach a reviewer
    the wrong thing about the application."""
    clock = FixedClock(NOW)
    transport = ReplayTransport(clock, screens=("captured/locked-to-gps.txt",), chunk_size=None)
    session = DeviceSession(transport, SmartClockDriver(clock=clock), clock)
    await session.open(PROBE)
    service = poller(session)

    await service.poll_full()
    screen_tfom = service.latest.status.tfom if service.latest else None
    await service.poll_fast()

    assert service.latest is not None
    assert service.latest.status.tfom == screen_tfom


@pytest.mark.parametrize("name", DEMO_SEQUENCE)
def test_every_demo_screen_exists(name: str) -> None:
    """The sequence names fixtures by hand, and a typo would show as a missing state rather than
    as an error."""
    assert (FIXTURES / name).is_file()


# ---- The demo's screens have to be where an installed copy can find them ------------------------


def test_the_demo_finds_its_screens_here() -> None:
    """A checkout resolves them from ``tests/fixtures``; an installed copy has no such directory.

    Both paths are covered because the second one broke silently for the whole life of the project:
    `--demo` is the first thing the README tells a new user to run, and outside a checkout it
    started an application that never showed a reading — which looks exactly like a receiver that
    has not answered yet.
    """
    from smartclock_monitor.services.replay import DEMO_SEQUENCE, fixture_root

    root = fixture_root()
    for name in DEMO_SEQUENCE:
        found = root
        for part in name.split("/"):
            found = found / part
        assert found.is_file(), f"{name} is not where the demo will look for it"


def test_a_missing_screen_set_says_so_rather_than_starting_empty() -> None:
    """**Loudly, and this is the one place that is right.** §11.1's rule is that a parser never
    raises, because an unreadable field is ordinary. An installation that cannot do the thing its
    own README opens with is not ordinary, and starting anyway means a window waiting for ever."""
    from smartclock_monitor.services import replay

    absent = Path("/nonexistent/fixtures")

    with (
        pytest.MonkeyPatch.context() as patch,
        pytest.raises(FileNotFoundError) as raised,
    ):
        patch.setattr(replay, "PACKAGED_FIXTURES", "smartclock_monitor.resources.not_a_package")
        patch.setattr(replay, "CHECKOUT_FIXTURES", absent)
        replay.fixture_root()

    message = str(raised.value)
    assert "not_a_package" in message, "the message does not name where it looked"
    # Compared against the path's **own** rendering, not a literal. Written as the literal
    # "/nonexistent/fixtures" this passed here and failed on Windows, where a Path renders with
    # backslashes — the message was right and the assertion was not.
    assert str(absent) in message, "the message does not name the other place"


# ---- #61: the tier rule, both halves, each against a deliberate violation -----------------------


def test_a_plan_only_claims_readings_its_family_supplies() -> None:
    """A fast tier cannot be answerable for a reading the family says it can never produce.

    The two declarations are written in different files by different people at different times,
    and nothing but this notices when they disagree.
    """
    clock = FixedClock(NOW)
    for driver in (SmartClockDriver(clock=clock), NmeaDriver(clock=clock)):
        for reading in driver.plan.fast_readings:
            assert driver.reports(reading), (
                f"{driver.name}'s fast tier claims {reading.value}, which it says it never supplies"
            )


def test_the_fast_sweep_folds_only_what_its_plan_claims() -> None:
    """§7.3's tiers share one status object, so the fast half must not write the slow half's work.

    Builds a status with every field filled, hands `apply_fast` a sweep that answers *everything*
    the fast tier could ask, and asserts the only fields that moved are the ones the plan declared.
    A driver that folded a reading it had not claimed would be quietly overwriting a value the full
    read owns — which, on a tier that runs once a second against a screen read once a minute, is
    a field that flickers for reasons nobody can reproduce.
    """
    clock = FixedClock(NOW)
    driver = SmartClockDriver(clock=clock)
    before = ReceiverStatus(
        captured_at=NOW,
        tfom=1,
        ffom=2,
        one_pps_ti_nanoseconds=3,
        elevation_mask_degrees=10,
        antenna_delay_nanoseconds=77,
    )

    after = driver.apply_fast(
        before,
        {
            catalog.TIME_FIGURE_OF_MERIT.mnemonic: _answered("+9"),
            catalog.FREQUENCY_FIGURE_OF_MERIT.mnemonic: _answered("+8"),
            catalog.TIME_INTERVAL.mnemonic: _answered("-5.4E-009"),
            catalog.OSCILLATOR_EFC.mnemonic: _answered("-1.68528E+001"),
            catalog.ELEVATION_MASK.mnemonic: _answered("+42"),
        },
    )

    allowed: set[str] = set()
    for reading in driver.plan.fast_readings:
        allowed.update(STATUS_FIELDS.get(reading, ()))

    moved = {
        name
        for name in STATUS_FIELDS_ALL
        if getattr(before, name, None) != getattr(after, name, None)
    }

    assert moved <= allowed, (
        f"the fast sweep wrote fields its plan does not claim: {moved - allowed}"
    )
    assert "tfom" in moved, "and it must still fold the ones it does claim"


def test_the_gate_notices_a_sweep_that_folds_an_unclaimed_reading() -> None:
    """`CLAUDE.md`: a rule that matches nothing enforces nothing.

    Stands in for a driver that folds the elevation mask — a full-tier reading — on the fast sweep.
    """
    before = ReceiverStatus(captured_at=NOW, elevation_mask_degrees=10)
    after = dataclasses.replace(before, elevation_mask_degrees=42)

    allowed = {
        name
        for reading in SmartClockDriver(clock=FixedClock(NOW)).plan.fast_readings
        for name in STATUS_FIELDS.get(reading, ())
    }
    moved = {
        name
        for name in STATUS_FIELDS_ALL
        if getattr(before, name, None) != getattr(after, name, None)
    }

    assert moved, "the violation changed nothing, so this proves nothing"
    assert not moved <= allowed, "the gate would not have caught an unclaimed fold"


def _answered(line: str) -> Transaction:
    return Transaction(
        command="", outcome=TransactionOutcome.COMPLETED, lines=(line,), prompt_status="scpi >"
    )


# ---- #61: a page is as fresh as its slowest tier ------------------------------------------------


def test_a_page_is_as_fresh_as_the_older_tier_that_fills_it() -> None:
    """§7.3's tiers run at different rates, so the newest of the two is not the page's age."""
    full = NOW
    fast = NOW + timedelta(seconds=45)
    reading = Reading(
        status=ReceiverStatus(captured_at=full),
        captured_at=fast,
        full_at=full,
        fast_at=fast,
    )

    assert reading.oldest_tier_at == full, (
        "the fast sweep's timestamp reported a minute-old screen as current"
    )


def test_a_reading_with_only_one_tier_reports_that_one() -> None:
    """A broadcast family has no separate fast tier, and the first full read has no fast one yet."""
    only_full = Reading(status=ReceiverStatus(captured_at=NOW), captured_at=NOW, full_at=NOW)

    assert only_full.oldest_tier_at == NOW


def test_a_reading_built_by_hand_falls_back_to_its_own_timestamp() -> None:
    """Most tests build a Reading with neither stamp, and they must not all become stale."""
    bare = Reading(status=ReceiverStatus(captured_at=NOW), captured_at=NOW)

    assert bare.oldest_tier_at == NOW
    assert bare.stale is False


def test_a_full_read_that_stops_goes_stale_while_the_fast_sweep_keeps_answering() -> None:
    """The defect, end to end: the tier that fills most of the interface dies and nothing said so.

    Drives a real `PollingService` against a transport that answers the scalars and refuses the
    status screen, then winds the injected clock past two full intervals.
    """

    async def run() -> None:
        clock = FixedClock(NOW)
        driver = SmartClockDriver(clock=clock)
        transport = FakeTransport(
            {
                "*CLS": "",
                "*IDN?": "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A",
                catalog.STATUS_SCREEN.mnemonic: DEMO_SEQUENCE[0],
                catalog.SYNC_STATE.mnemonic: " LOCK",
                catalog.TIME_FIGURE_OF_MERIT.mnemonic: " +3",
                catalog.FREQUENCY_FIGURE_OF_MERIT.mnemonic: " +2",
                catalog.TIME_INTERVAL.mnemonic: " -5.4E-009",
                catalog.OSCILLATOR_EFC.mnemonic: " -1.68528E+001",
                catalog.TRACKED_COUNT.mnemonic: " +8",
            }
        )
        session = DeviceSession(transport, driver, clock)
        await session.open(probe=timedelta(seconds=1))

        published: list[Reading] = []
        service = PollingService(
            session=session, driver=driver, clock=clock, on_reading=published.append
        )

        await service.poll_full()
        fresh = published[-1]
        assert fresh.stale is False, "a fresh full read is not stale"

        # The screen stops answering; the scalars do not.
        transport.script(catalog.STATUS_SCREEN.mnemonic, None)
        clock.advance(driver.cadence.full * 3)
        await service.poll_fast()

        # Bound to a local rather than re-indexing: `published[-1].stale` is a narrowable
        # expression to mypy, so asserting it False above made every later reading of it
        # unreachable — while the list had in fact grown a different element underneath.
        after = published[-1]
        assert after.stale, (
            "the status screen has not been read for three intervals and nothing said so"
        )
        assert after.oldest_tier_at == NOW, (
            "the page's age must still be the full read's, not the sweep's"
        )

    asyncio.run(run())


# ---- §7.3's full tier, and the one extra it carries here (#112) ----------------------------------


async def test_the_full_read_asks_for_the_hardware_register_too() -> None:
    """§7.3's table gives the full tier one command; its rationale gives that tier the **health**
    section, and §10.4's health card is built from a block that cannot name two of the twelve
    hardware faults. The divergence is `docs/divergences.md`'s, and this is where it happens."""
    screen = read_fixture("locked-stabilizing.txt")
    session, transport = build({"*CLS": "", ":SYST:STAT?": screen, **SWEEP})
    await session.open(probe=PROBE)
    service = poller(session)

    await service.poll_full()

    assert ":STAT:OPER:HARD:COND?" in transport.written
    reading = service.latest
    assert reading is not None
    assert reading.status.unreported_faults == ()


async def test_a_register_the_receiver_will_not_answer_is_asked_once() -> None:
    """**Once, and then not again this session.**

    An extra that answers nothing costs a full transaction timeout, and paying that every ten
    seconds for the life of a connection buys nothing — §7.3.1 makes the same trade on the fast
    tier, keyed on the sync state. There is no state to key on here, so it is once.
    """
    screen = read_fixture("locked-stabilizing.txt")
    answers = {key: value for key, value in SWEEP.items() if key != ":STAT:OPER:HARD:COND?"}
    session, transport = build({"*CLS": "", ":SYST:STAT?": screen, **answers})
    await session.open(probe=PROBE)
    service = poller(session)

    await service.poll_full()
    await service.poll_full()

    assert transport.written.count(":STAT:OPER:HARD:COND?") == 1


async def test_a_fault_the_health_block_cannot_name_reaches_the_reading() -> None:
    """The whole point of #112: bit 11 is a failed EEPROM write, the screen has no label for it,
    and §10.4 would otherwise draw six green ticks over it."""
    screen = read_fixture("locked-stabilizing.txt")
    answers = {**SWEEP, ":STAT:OPER:HARD:COND?": f" +{1 << 11}"}
    session, _ = build({"*CLS": "", ":SYST:STAT?": screen, **answers})
    await session.open(probe=PROBE)
    service = poller(session)

    await service.poll_full()

    reading = service.latest
    assert reading is not None
    assert reading.status.health_ok is True
    assert len(reading.status.unreported_faults) == 1
    assert "EEPROM" in reading.status.unreported_faults[0]
