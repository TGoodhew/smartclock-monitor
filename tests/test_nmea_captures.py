"""Every captured talker, replayed through the real driver.

`tests/fixtures/nmea/` holds ten sittings carried from WinZ3805A (#56) and two taken on this
bench. They are the NMEA family's oracle in the way `tests/fixtures/captured/` is the SmartClock
family's, and for the same reason: until they arrived, everything the driver had ever been tested
against came from `tools/nmea_simulator.py`, which can only produce what we already believed a
talker sends.

**Three of the assertions here are expected failures**, and that is the point of the file rather
than a defect in it. Each names the issue it belongs to:

- `xfail_gns` — a talker that sends `GNS` instead of `GGA` yields **no cycles at all** (#58)
- `xfail_identity` — two constellations collide on one satellite number (#57)
- `xfail_error_statistics` — `GST` and `GBS` are not read (#58)

`CLAUDE.md`: *"Write the fixture assertion before the parsing code."* These are those assertions.
When one of them starts passing, take the marker off; ``strict`` makes an unexpected pass a
failure, so none can be left behind by accident.
"""

from __future__ import annotations

import collections
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.drivers.base import WHOLE_CYCLE
from smartclock_device.drivers.capability import ReceiverReading
from smartclock_device.drivers.nmea import sentences
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.models.fix_quality import FixQuality
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_device.models.satellite import Constellation, TrackedSatellite
from smartclock_device.transport.broadcast import BroadcastListener
from smartclock_device.transport.transaction import Transaction, TransactionOutcome

CAPTURES: Final = Path(__file__).parent / "fixtures" / "nmea"

#: The sittings carried from WinZ3805A. Named rather than globbed, so a capture that goes missing
#: fails here instead of quietly reducing the corpus — the same reason `test_fixtures.py` walks all
#: ten status screens rather than the one at the top of the directory.
CARRIED: Final = (
    "vk162-steady-state",
    "vk162-cold-start",
    "vk162-glonass-only",
    "vk162-gns-no-gga",
    "vk162-microwave",
    "form8n-gps-beidou-first-light",
    "form8n-gns-without-gga",
    "form8n-gps-beidou-outdoors",
    "form8n-gst-gbs",
    "form8n-fix-lost",
)


def _replay(name: str) -> list[ReceiverStatus]:
    """Drive one capture through the driver and the listener, exactly as a session would.

    Bytes off the file, decoded the way the transport decodes them — ``replace`` rather than
    ``strict``, because §11.1 forbids raising and a capture holding a byte no codec likes is a
    capture doing its job.
    """
    clock = FixedClock(datetime(2026, 9, 13, tzinfo=UTC))
    driver = NmeaDriver(clock)
    listener = BroadcastListener(clock=clock, boundaries=driver.plan.cycle_boundaries)

    statuses: list[ReceiverStatus] = []
    previous: ReceiverStatus | None = None
    for raw in (CAPTURES / f"{name}.nmea").read_bytes().decode("ascii", "replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        before = listener.cycles
        listener.feed(driver.classify(line), line)
        if listener.cycles > before:
            transaction = Transaction(
                command=WHOLE_CYCLE,
                outcome=TransactionOutcome.COMPLETED,
                lines=listener.whole_cycle(),
            )
            previous = driver.parse_full(transaction, previous)
            statuses.append(previous)
    return statuses


def _headers(name: str) -> collections.Counter[str]:
    counted: collections.Counter[str] = collections.Counter()
    for raw in (CAPTURES / f"{name}.nmea").read_bytes().decode("ascii", "replace").splitlines():
        parsed = sentences.parse(raw.strip())
        if parsed is not None:
            counted[f"{parsed.talker}{parsed.kind}"] += 1
    return counted


# ---- The corpus is here at all -----------------------------------------------------------------


def test_every_carried_capture_is_present_and_has_its_note() -> None:
    """A capture cannot be regenerated on demand, so a missing one is a loss, not a skip."""
    for name in CARRIED:
        assert (CAPTURES / f"{name}.nmea").is_file(), f"{name}.nmea is missing"
        assert (CAPTURES / f"{name}.md").is_file(), f"{name}.md is missing"


def test_the_captures_kept_their_bytes() -> None:
    """`.gitattributes` marks `tests/fixtures/**` as `-text`; this notices if that stops working.

    A talker's output is CRLF-terminated and a checkout that converted it would change every byte
    offset the sidecars quote — `form8n-fix-lost.md` names the cold start at byte 87164.
    """
    raw = (CAPTURES / "vk162-steady-state.nmea").read_bytes()
    assert b"\r\n" in raw, "the line endings have been converted; see .gitattributes"


# ---- What the driver makes of them today -------------------------------------------------------


@pytest.mark.parametrize("name", CARRIED)
def test_no_capture_makes_the_parser_raise(name: str) -> None:
    """§11.1, against the only input that has ever been near a receiver."""
    _replay(name)


def test_the_boring_case_at_length_is_boring() -> None:
    """1,800 cycles of a differential 3D fix. The control for every other capture."""
    statuses = _replay("vk162-steady-state")

    assert len(statuses) == 1799, "a cycle went missing in the capture that has no gaps"
    assert all(s.position is not None for s in statuses), "the steady state lost a fix"


def test_a_cold_start_has_exactly_one_cycle_without_a_fix() -> None:
    """The corpus's only no-fix cycle on this receiver, and the one the acquisition path needs."""
    statuses = _replay("vk162-cold-start")

    assert sum(1 for s in statuses if s.position is None) == 1


def test_a_talker_that_is_not_gp_is_heard() -> None:
    """`bfe46b7` upstream. The VK-162 configured for GLONASS speaks `GL`, and nothing else.

    Then 152 consecutive cycles with no fix — the corpus's longest outage — followed by
    acquisition. A driver that keyed on the `GP` talker would read none of it.
    """
    headers = _headers("vk162-glonass-only")
    assert not any(h.startswith("GP") for h in headers), "this capture should be GLONASS only"

    statuses = _replay("vk162-glonass-only")
    assert len(statuses) > 800
    assert sum(1 for s in statuses if s.position is None) == 152


def test_a_fix_is_taken_away_and_given_back() -> None:
    """The only capture in which a receiver loses a fix and recovers it (#420)."""
    statuses = _replay("form8n-fix-lost")

    without = [i for i, s in enumerate(statuses) if s.position is None]
    assert len(without) == 65, "the outage is not the length the sitting recorded"
    assert without[0] > 0, "it should start with a fix"
    assert without[-1] < len(statuses) - 1, "and end with one"


# ---- The three that are expected to fail -------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "cycles"), [("vk162-gns-no-gga", 719), ("form8n-gns-without-gga", 129)]
)
def test_a_talker_that_sends_gns_instead_of_gga_is_read(name: str, cycles: int) -> None:
    """**Not a missing readout — an unreadable receiver**, until #58.

    Both captures carry a valid fix in every cycle and not one `GGA`. `sentences.py` used to call
    `GGA` "the sentence every talker emits exactly once per cycle"; these are two receivers that
    do not. The boundary never came round, no cycle ever closed, and the application showed
    nothing at all while connected to a working talker.

    Written as an expected failure before the parsing existed, per `CLAUDE.md`. The marker came
    off when `strict` turned the unexpected pass into a failure, which is the mechanism working.
    """
    headers = _headers(name)
    assert not any(h.endswith("GGA") for h in headers), "this capture should have no GGA"
    assert any(h.endswith("GNS") for h in headers), "this capture should have GNS"

    statuses = _replay(name)

    assert len(statuses) == cycles, "the GNS boundary did not close every cycle"
    assert all(s.position is not None for s in statuses), "GNS carries the fix that GGA would"
    assert all(s.mode is SmartClockMode.LOCKED for s in statuses), (
        "a talker with a fix is LOCKED, whichever sentence reported it"
    )


def test_two_constellations_do_not_collide_on_one_number() -> None:
    """The forM8N outdoors, where BeiDou actually tracks.

    Every cycle in this capture has at least one satellite number reported by two talkers. Keyed on
    the number alone, `_visible` collapsed each pair and the count came up short — which reads as
    poor reception rather than as a parsing choice, and sends someone onto the roof.
    """
    name = "form8n-gps-beidou-outdoors"
    talkers_by_number: dict[int, set[str]] = collections.defaultdict(set)
    for raw in (CAPTURES / f"{name}.nmea").read_bytes().decode("ascii", "replace").splitlines():
        parsed = sentences.parse(raw.strip())
        if parsed is None or parsed.kind != sentences.GSV:
            continue
        for index in range(3, len(parsed.fields), 4):
            number = sentences.parse_int(parsed.fields[index])
            if number is not None:
                talkers_by_number[number].add(parsed.talker)

    shared = {n for n, talkers in talkers_by_number.items() if len(talkers) > 1}
    assert shared, "this capture should carry colliding satellite numbers"

    statuses = _replay(name)
    richest = max(statuses, key=lambda s: len(s.tracked))

    assert len({s.identity for s in richest.tracked}) == len(richest.tracked)
    assert len({(s.identity.constellation) for s in richest.tracked}) > 1, (
        "the richest cycle should draw on both constellations"
    )


def test_a_smartclock_satellite_is_still_a_bare_number() -> None:
    """#57 widened the identity for the family that needs it and left the other alone.

    A SmartClock reports bare PRNs and its exclusion commands take bare PRNs, so its satellites are
    `UNKNOWN` and every surface renders them exactly as §9.10.2 says — *"PRN 19, elevation 65
    degrees…"*. If this ever fails, the change leaked into the family it was supposed not to touch.
    """
    satellite = TrackedSatellite(prn=19, elevation_degrees=65, azimuth_degrees=52)

    assert satellite.constellation is Constellation.UNKNOWN
    assert satellite.identity.designation == "19"
    assert satellite.identity.spoken == "PRN 19"


def test_the_fix_reports_its_own_error() -> None:
    """The only capture carrying `GST` or `GBS` — 300 of each, enabled deliberately (#516).

    §10.6 has a row for the position's error in metres, and this is the sitting that can fill it.
    Written as an expected failure before the parsing existed; the marker came off when `strict`
    turned its unexpected pass into a failure.
    """
    headers = _headers("form8n-gst-gbs")
    assert headers["GNGST"] == 300, "this capture should carry 300 GST"
    assert headers["GNGBS"] == 300, "and 300 GBS"

    statuses = _replay("form8n-gst-gbs")

    assert all(s.uncertainty is not None for s in statuses), "every cycle carries a GST"
    horizontals = [s.uncertainty.horizontal_metres for s in statuses if s.uncertainty is not None]
    assert all(h is not None and 2.4 <= h <= 2.9 for h in horizontals), (
        "the horizontal error should sit near 2.7 m throughout this sitting"
    )


def test_the_range_rms_is_never_read_because_it_cannot_be_believed() -> None:
    """`GST` field 1 from this module runs from 17 to 3,179,277 on one unbroken fix.

    Measured here rather than taken on trust from the capture's note — which says *"34 of the 300
    are in the millions"* where 34 is the count above ten thousand and 23 are above a million.
    Either way the field is unusable, and nothing in the application displays it.
    """
    values = []
    for raw in (CAPTURES / "form8n-gst-gbs.nmea").read_bytes().decode("ascii").splitlines():
        parsed = sentences.parse(raw.strip())
        if parsed is not None and parsed.kind == sentences.GST:
            rms = sentences.parse_float(parsed.field(1))
            if rms is not None:
                values.append(rms)

    assert min(values) < 20 and max(values) > 1e6, "the field is as wild as the sitting recorded"

    statuses = _replay("form8n-gst-gbs")
    for status in statuses:
        assert status.uncertainty is not None
        # Nothing on the model can carry it, which is the point: there is no field to put it in.
        assert not hasattr(status.uncertainty, "range_rms_metres")


def test_an_integrity_check_that_found_nothing_is_not_the_same_as_no_check() -> None:
    """A clean `GBS` and an absent one look identical on the wire, and must not read the same.

    Every cycle in the corpus is clean — no satellite was ever flagged — so the faulted branch has
    **never met a receiver**. It is covered below by a sentence written here, and that test says so.
    """
    with_gbs = _replay("form8n-gst-gbs")
    without_gbs = _replay("vk162-steady-state")

    assert all(s.integrity is not None and s.integrity.is_clean for s in with_gbs), (
        "asked, and nothing wrong"
    )
    assert all(s.integrity is None for s in without_gbs), "never asked"


def test_a_faulted_satellite_is_read_from_a_synthetic_sentence() -> None:
    """**Synthetic, and deliberately so.** No receiver in the corpus has ever flagged a satellite.

    RAIM needs redundancy and an excluded satellite to exclude; five minutes of a good indoor fix
    produced neither. This pins the parse of a branch the hardware has not exercised, and is
    labelled so nobody reads it as evidence that one did.
    """
    from smartclock_device.drivers.nmea.driver import _integrity

    # The checksum is computed rather than typed. Hand-written NMEA has now failed twice in this
    # suite for a wrong checksum, which `parse` correctly refuses — and a test that fails because
    # its fixture is malformed says nothing about the code it was written for.
    body = "GNGBS,015509.00,-0.3,-0.2,3.0,03,0.0,-21.4,3.8,1,0"
    parsed = sentences.parse(f"${body}*{sentences.checksum_of(body):02X}")
    assert parsed is not None, "the synthetic sentence must be checksum-valid to prove anything"

    integrity = _integrity(parsed)

    assert integrity is not None
    assert integrity.is_clean is False
    assert integrity.faulted is not None
    assert integrity.faulted.prn == 3
    assert integrity.faulted.constellation is Constellation.GPS, "system id 1 is GPS"
    assert integrity.bias_metres == pytest.approx(-21.4)


def test_a_smartclock_declines_both_of_them() -> None:
    """The seam running the other way, for the first time.

    Every other reading is one a SmartClock supplies and a talker may not. These are two a talker
    supplies and a SmartClock cannot: it prints a position and stops, and no firmware revision is
    going to add an error estimate to an 80-column screen.
    """
    from smartclock_device.drivers.smartclock import SmartClockDriver

    smartclock = SmartClockDriver(clock=FixedClock(NOW))

    assert smartclock.reports(ReceiverReading.POSITION_UNCERTAINTY) is False
    assert smartclock.reports(ReceiverReading.CONSTELLATION_INTEGRITY) is False
    assert NmeaDriver(clock=FixedClock(NOW)).reports(ReceiverReading.POSITION_UNCERTAINTY) is True


# ---- The two taken on this bench ---------------------------------------------------------------

#: Captured here with `tools/capture_talker.py`, from the same two module families, five days
#: after the carried sittings. They are a cross-check rather than new states — see their notes.
BENCH: Final = ("vk162-wsl-bench", "form8n-wsl-bench")


@pytest.mark.parametrize("name", BENCH)
def test_the_bench_captures_are_present_and_written_up(name: str) -> None:
    assert (CAPTURES / f"{name}.nmea").is_file()
    assert (CAPTURES / f"{name}.md").is_file()


@pytest.mark.parametrize("name", BENCH)
def test_the_harness_here_produces_what_the_upstream_one_did(name: str) -> None:
    """`tools/capture_talker.py` writes raw bytes, CRLF intact, and the driver reads them.

    The point of the assertion is the harness, not the receiver: a capture tool that silently
    re-terminated or decoded would produce a corpus that agrees with the parser because both had
    made the same assumption, which is the one way a fixture can be worse than none.
    """
    raw = (CAPTURES / f"{name}.nmea").read_bytes()

    assert b"\r\n" in raw, "the harness did not preserve CRLF"
    assert raw.count(b"\r") == raw.count(b"\r\n"), "a bare CR survived, so something re-terminated"

    statuses = _replay(name)
    assert len(statuses) > 600, "ten minutes of a 1 Hz talker should close about 600 cycles"
    assert all(s.position is not None for s in statuses), "an indoor fix was held throughout"


def test_a_navigational_status_field_is_not_mistaken_for_the_fix() -> None:
    """The forM8N sends `V` as RMC's last field in every cycle; the VK-162 sends `A`.

    That field is NMEA 4.1's navigational-status indicator, which this firmware carries and does
    not implement. It sits exactly where a reader skimming for "the mode indicator" would land,
    and reading it as one would report no valid fix for a receiver whose GGA quality is 1 and
    whose position is good.

    Gated because it is a *latent* mistake rather than a present one: nothing reads that field
    today, and this is what notices if something starts.
    """
    trailing = collections.Counter[str]()
    for raw in (CAPTURES / "form8n-wsl-bench.nmea").read_bytes().decode("ascii").splitlines():
        parsed = sentences.parse(raw.strip())
        if parsed is not None and parsed.kind == sentences.RMC and parsed.fields:
            trailing[parsed.fields[-1]] += 1

    assert set(trailing) == {"V"}, "this capture should carry V in RMC's last field throughout"

    statuses = _replay("form8n-wsl-bench")
    assert all(s.position is not None for s in statuses), (
        "RMC's navigational-status field is being read as the fix"
    )


def test_the_banner_is_present_and_says_what_the_unit_is_programmed_for() -> None:
    """#62's once-only reading, captured by construction rather than by luck.

    `usbipd attach` re-enumerates the device, so every capture taken through it starts at the
    talker's power-on. The forM8N prints both what its firmware supports and what this unit is
    one-time-programmed for, and only the second is true of the receiver in front of you — there
    is not one GLONASS sentence in the capture despite GLO appearing in the supported line.
    """
    text = (CAPTURES / "form8n-wsl-bench.nmea").read_bytes().decode("ascii")

    assert "GPS;GLO;BDS" in text, "the supported-constellation line"
    assert "GNSS OTP=GPS;BDS" in text, "and the one that describes this unit"
    assert "GLGSV" not in text, "GLO is supported and not programmed, so nothing GLONASS arrives"


def test_number_only_keying_loses_satellites_and_identity_keying_does_not() -> None:
    """How much #57 was actually costing, measured rather than asserted.

    Counts every satellite sighting in every GSV page two ways — by number alone, which is what
    `_visible` used to key on, and by identity. The difference is what the sky plot and the
    satellite count were dropping, and it is not small: **2,526 of 15,176** on this bench's own
    forM8N capture.

    The second half is the one that guards against over-correcting: on a single-constellation
    talker the two keyings must agree **exactly**, because widening the identity must not change
    what a receiver with one constellation reports.
    """
    multi, single = 0, 0
    for name in (*CARRIED, *BENCH):
        by_number: set[int] = set()
        by_identity: set[tuple[Constellation, int]] = set()
        for raw in (CAPTURES / f"{name}.nmea").read_bytes().decode("ascii", "replace").splitlines():
            parsed = sentences.parse(raw.strip())
            if parsed is None or parsed.kind != sentences.GSV:
                continue
            for index in range(3, len(parsed.fields), 4):
                number = sentences.parse_int(parsed.fields[index])
                if number is None:
                    continue
                by_number.add(number)
                by_identity.add((sentences.constellation_for(parsed.talker, number), number))

        lost = len(by_identity) - len(by_number)
        if name.startswith("vk162"):
            assert lost == 0, f"{name} has one constellation and must be unaffected"
            single += 1
        else:
            assert lost > 0, f"{name} has two constellations and should have been losing some"
            multi += 1

    assert single >= 6, "the single-constellation half of the corpus went missing"
    assert multi >= 5, "the multi-constellation half of the corpus went missing"


def test_waas_is_sbas_in_both_sentences_or_it_is_dropped() -> None:
    """The bug this change introduced on the way, and the reason it is gated.

    NMEA numbers satellite-based augmentation **33–64 inside the GPS talker**, so one `$GPGSA` can
    hold GPS and SBAS slots together. Deciding the constellation once per sentence made every WAAS
    satellite GPS in GSA and SBAS in GSV; the two then never matched and the tracked list quietly
    lost them — `vk162-steady-state` went from 12 tracked to 10.

    A decrease is the one direction this change must never produce, so it is pinned.
    """
    statuses = _replay("vk162-steady-state")
    richest = max(statuses, key=lambda s: len(s.tracked))

    assert len(richest.tracked) == 12, "the SBAS satellites fell out of the tracked list"
    assert any(s.constellation is Constellation.SBAS for s in richest.tracked), (
        "this capture carries WAAS satellites 46 and 48; they should be recognised as SBAS"
    )


# ---- #62: what kind of fix, and the banner ------------------------------------------------------


def test_a_cold_start_walks_the_fix_ladder() -> None:
    """`vk162-cold-start` carries all three qualities, in order, as the receiver acquires.

    This port read `GGA` field 5 as a single bit — `quality > 0` — and threw the rest away, so
    a standalone fix and a differential one were the same picture.
    """
    qualities = [s.fix_quality for s in _replay("vk162-cold-start")]

    assert qualities[0] is FixQuality.NONE
    assert set(qualities) == {FixQuality.NONE, FixQuality.AUTONOMOUS, FixQuality.DIFFERENTIAL}
    assert qualities.index(FixQuality.AUTONOMOUS) < qualities.index(FixQuality.DIFFERENTIAL)


def test_the_same_module_five_days_apart_reports_two_different_qualities() -> None:
    """Which is what says the field is being read rather than assumed.

    `vk162-steady-state` is differential in all 1,799 cycles; `vk162-wsl-bench` is the same
    silicon on the same desk, standalone in all 632. A parser that hard-coded either would pass
    against one capture and fail against the other.
    """
    assert {s.fix_quality for s in _replay("vk162-steady-state")} == {FixQuality.DIFFERENTIAL}
    assert {s.fix_quality for s in _replay("vk162-wsl-bench")} == {FixQuality.AUTONOMOUS}


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("vk162-gns-no-gga", FixQuality.DIFFERENTIAL),
        ("form8n-gns-without-gga", FixQuality.AUTONOMOUS),
    ],
)
def test_a_gns_talker_reports_quality_from_its_mode_string(name: str, expected: FixQuality) -> None:
    """`GNS` has no integer code — the quality is one character per constellation.

    `DN` from the VK-162 is differential on GPS and nothing on the second system; `ANNN` from the
    forM8N is autonomous on GPS and nothing on three others. The fix as a whole is the **best** any
    constellation managed, because a receiver with a differential solution on one has produced a
    differential fix.
    """
    assert {s.fix_quality for s in _replay(name)} == {expected}


def test_the_banner_survives_the_cycles_that_do_not_repeat_it() -> None:
    """A talker prints it in its first second and never again (#62).

    Carried forward from the previous status rather than re-read, which is why the last cycle of a
    thirty-minute sitting still has it. It lives on the status rather than the driver because a
    driver is a singleton that would hand one receiver's banner to the next.
    """
    statuses = _replay("form8n-wsl-bench")

    assert len(statuses[-1].banner) == 12, "the forM8N prints twelve TXT lines"
    assert "GNSS OTP=GPS;BDS" in statuses[-1].banner, (
        "and the line that says what this unit is programmed for, not merely what it supports"
    )
    assert statuses[0].banner == statuses[-1].banner, "unchanged across 632 cycles"


def test_a_session_that_joined_late_simply_has_no_banner() -> None:
    """Not an error, and not worth a dash: whether it is there depends on whether we were listening.

    Replaying a capture from the middle is the same situation as attaching to a receiver that has
    been running for an hour.
    """
    clock = FixedClock(datetime(2026, 9, 13, tzinfo=UTC))
    driver = NmeaDriver(clock)
    listener = BroadcastListener(clock=clock, boundaries=driver.plan.cycle_boundaries)

    raw = (CAPTURES / "form8n-wsl-bench.nmea").read_bytes().decode("ascii", "replace")
    previous: ReceiverStatus | None = None
    # Start a third of the way in, long after the banner has gone by.
    for line in raw.splitlines()[3000:4000]:
        line = line.strip()
        if not line:
            continue
        before = listener.cycles
        listener.feed(driver.classify(line), line)
        if listener.cycles > before:
            previous = driver.parse_full(
                Transaction(
                    command=WHOLE_CYCLE,
                    outcome=TransactionOutcome.COMPLETED,
                    lines=listener.whole_cycle(),
                ),
                previous,
            )

    assert previous is not None, "the slice should still close cycles"
    assert previous.banner == (), "no banner, and nothing pretending there is one"


# ---- #62 / D8: GPS − UTC, the reading the send path was traded for ------------------------------


def test_the_poll_reply_carries_gps_minus_utc() -> None:
    """`form8n-time-poll.nmea` is six polls and six replies, taken on this bench.

    **The first capture here containing something this application sent.** Everything else is a
    receiver talking unprompted; D8 traded away the guarantee that made that true, and 18 seconds
    is what it was traded for.
    """
    statuses = _replay("form8n-time-poll")

    offsets = {s.gps_utc_offset_seconds for s in statuses if s.gps_utc_offset_seconds is not None}

    assert offsets == {18}, "both bench modules answered 18, a firmware generation apart"
    assert not any(s.gps_utc_is_default for s in statuses), "decoded from satellites, not a default"


def test_the_offset_survives_the_cycles_between_polls() -> None:
    """Asked on the slow tier, so most cycles carry no reply and the last answer still holds.

    Without the carry-forward §10.14 would flicker between a figure and a dash once a second, which
    is the same defect `apply_fast` was written to avoid on the other family.
    """
    statuses = _replay("form8n-time-poll")
    after_first = statuses[len(statuses) // 2 :]

    assert all(s.gps_utc_offset_seconds == 18 for s in after_first), (
        "the offset disappeared on a cycle that carried no reply"
    )


def test_a_firmware_default_is_marked_as_one() -> None:
    """**Synthetic.** Neither bench module produced a `D` suffix — both had been tracking for hours.

    It matters because a default is a *guess the receiver is making* about a value a timing
    application displays as fact, and the two must not render the same.
    """
    from smartclock_device.drivers.nmea.driver import _gps_utc

    body = "PUBX,04,213835.00,130926,77915.00,2436,18D,-296402,-68.588,21"
    parsed = sentences.parse(f"${body}*{sentences.checksum_of(body):02X}")
    assert parsed is not None

    offset, is_default = _gps_utc(parsed)

    assert offset == 18
    assert is_default is True
