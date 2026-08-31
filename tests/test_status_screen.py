"""What a captured status screen says (§11, P0-4).

The assertions against ``locked-stabilizing.txt`` are the important ones: it is real output from
the unit named in ``tests/fixtures/README.md``, and every value below was cross-checked against
the scalar queries taken in the same session. They are ported from ``StatusScreenParserTests.cs``,
which is the pass/fail oracle this port is measured against — the Python parser is finished when
it agrees with the C# one on all ten fixtures, field for field, including the nulls.

The remaining tests build small screens in code to exercise a rule the captures cannot reach — an
``SS`` column, a single column group, a screen that is not a screen at all. They are deliberately
*not* written into ``tests/fixtures/``: that folder is captured device output and nothing else,
and a synthesised file sitting among real ones would be believed later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from smartclock_device.clock import FixedClock
from smartclock_device.models.position import (
    HeightDatum,
    PositionMode,
    PositionQualifier,
    SurveySuspendedReason,
)
from smartclock_device.models.receiver_status import (
    ClockAdvisory,
    LeapSecondPending,
    OutputValidity,
    ReceiverStatus,
    SignalStrengthKind,
    SmartClockMode,
    TimeScale,
)
from smartclock_device.parsing.status_screen import StatusScreenParser

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: The fixtures are committed ``-text`` and carry the device's own CRLF endings. Spelled out so
#: nothing here depends on the platform's idea of a line.
CRLF = "\r\n"

#: The instant ``locked-stabilizing.txt`` was taken, to the second, from its own clock row
#: corrected by the §7.4 rollover. Pinning the clock is what makes the rollover assertions mean
#: anything.
CAPTURE_INSTANT = datetime(2026, 8, 12, 14, 45, 2, tzinfo=UTC)

#: When the 27–28 August 2026 backyard sitting took its screens. Distinct from
#: :data:`CAPTURE_INSTANT` because the §7.4 correction is a function of "now", and asserting a
#: corrected date against the wrong instant would assert the constant rather than the arithmetic.
SITTING_INSTANT = datetime(2026, 8, 28, 5, 15, 0, tzinfo=UTC)

#: When the holdover screen was taken, from its own clock row corrected by the rollover.
HOLDOVER_INSTANT = datetime(2026, 8, 28, 15, 52, 54, tzinfo=UTC)

#: When the reconnect screens were taken, from their own clock rows.
RECOVERY_INSTANT = datetime(2026, 8, 28, 16, 9, 57, tzinfo=UTC)


def parser_at(now: datetime) -> StatusScreenParser:
    return StatusScreenParser(FixedClock(now))


def read_fixture(name: str) -> str:
    """A fixture as the device wrote it.

    Latin-1 because it never substitutes — ``ascii`` with ``errors="replace"`` would turn a stray
    high byte into U+FFFD and quietly change the bytes under test. The trailing newline is
    stripped and the join is an explicit CRLF because the file is committed ``-text`` and must not
    depend on the platform's idea of a line. This mirrors ``ReadFixtureLines`` in the C# tests.
    """
    text = (FIXTURES / name).read_bytes().decode("latin-1")
    return CRLF.join(text.rstrip(CRLF).split(CRLF))


def parse_fixture(name: str, now: datetime = CAPTURE_INSTANT) -> ReceiverStatus:
    return parser_at(now).parse(read_fixture(name))


def parse_clock_row(clock_row: str) -> ReceiverStatus:
    """Parse a synthetic screen built around one clock row.

    The date shapes under test come from the 58503A and Z3801A manuals rather than from anything
    this unit emits, so there is no fixture to read them from — a captured screen is evidence of
    what a receiver printed, and inventing one would make it evidence of nothing. The clock row is
    the only line these assertions touch.
    """
    banner = "------------------------------- Receiver Status -------------------------------"
    return parser_at(SITTING_INSTANT).parse(banner + CRLF + clock_row)


# ---------------------------------------------------------------------------------------------
# The captured screen
# ---------------------------------------------------------------------------------------------


def test_the_captured_screen_reports_its_synchronization_state() -> None:
    status = parse_fixture("locked-stabilizing.txt")

    assert status.outputs is OutputValidity.VALID_REDUCED
    assert status.mode is SmartClockMode.LOCKED
    assert status.mode_detail == "stabilizing frequency"
    assert status.tfom == 3
    assert status.ffom == 1


def test_the_mode_detail_stops_at_the_edge_of_its_panel() -> None:
    """The mode row shares its line with the reference-outputs panel, so a detail of
    "stabilizing frequency TFOM 3 FFOM 1" is the failure this guards against."""
    status = parse_fixture("locked-stabilizing.txt")

    assert status.mode_detail is not None
    assert "TFOM" not in status.mode_detail
    assert "FFOM" not in status.mode_detail


def test_the_captured_screen_reports_its_timing_figures() -> None:
    status = parse_fixture("locked-stabilizing.txt")

    # -5.4 ns, cross-checked against :SYNC:TINT? answering -5.4E-009 in the same session.
    assert status.one_pps_ti_nanoseconds == pytest.approx(-5.4, abs=1e-6)

    # "HOLD THR 1.000 us" and "Predict  2.5 us/initial 24 hrs" — both read in the unit printed.
    assert status.hold_threshold_seconds == pytest.approx(1e-6, abs=1e-15)
    assert status.holdover_predicted_seconds == pytest.approx(2.5e-6, abs=1e-15)

    # The screen shows no present-uncertainty row and no holdover elapsed time.
    assert status.holdover_present_seconds is None
    assert status.holdover_duration is None

    # 77 ns, against :GPS:REF:ADEL? answering +7.70000E-008.
    assert status.antenna_delay_nanoseconds == pytest.approx(77, abs=1e-6)


def test_the_captured_screen_reports_one_tracked_satellite_with_its_signal_strength() -> None:
    status = parse_fixture("locked-stabilizing.txt")

    assert status.gps_one_pps_valid is True
    assert status.signal_strength_kind is SignalStrengthKind.CARRIER_TO_NOISE
    assert status.elevation_mask_degrees == 10

    assert len(status.tracked) == 1
    satellite = status.tracked[0]
    assert satellite.prn == 18
    assert satellite.elevation_degrees == 79
    assert satellite.azimuth_degrees == 2
    assert satellite.signal_strength == 32


def test_the_captured_screen_reports_nine_not_tracked_satellites_including_wide_azimuths() -> None:
    """The nine not-tracked satellites, in screen order. Four of them have a three-digit azimuth
    under a two-character ``Az`` header, which is the case that breaks any parser slicing the
    header token's own extent — 219 would read as 19."""
    status = parse_fixture("locked-stabilizing.txt")

    expected = [
        (5, 25, 50),
        (10, 21, 219),
        (15, 42, 108),
        (16, 31, 290),
        (20, 31, 68),
        (23, 53, 215),
        (26, 26, 256),
        (27, 15, 311),
        (29, 41, 143),
    ]

    assert [(s.prn, s.elevation_degrees, s.azimuth_degrees) for s in status.not_tracked] == expected


def test_the_captured_screen_reports_its_time_and_advisory() -> None:
    status = parse_fixture("locked-stabilizing.txt")

    assert status.time_scale is TimeScale.UTC
    assert status.device_date_time == datetime(2006, 12, 27, 14, 45, 2, tzinfo=UTC)
    assert status.one_pps_clock_advisory is ClockAdvisory.SYNCHRONIZED_TO_UTC
    assert status.leap_pending is LeapSecondPending.NONE


def test_the_captured_screen_is_one_gps_epoch_behind_and_is_corrected() -> None:
    """This unit reports 27 December 2006 — one 1024-week epoch behind — which is the exact case
    P0-10 names. With the clock pinned to the capture instant the delta is a whole epoch to the
    second, so the correction lands on the capture date itself."""
    status = parse_fixture("locked-stabilizing.txt")

    assert status.week_rollover_epochs == 1
    assert status.corrected_date_time == CAPTURE_INSTANT

    # §7.4 forbids substituting the correction for what the hardware said.
    assert status.device_date_time == datetime(2006, 12, 27, 14, 45, 2, tzinfo=UTC)


def test_the_captured_screen_reports_a_held_position() -> None:
    status = parse_fixture("locked-stabilizing.txt")

    assert status.position_mode is PositionMode.HOLD
    assert status.survey_percent_complete is None
    assert status.survey_suspended_reason is SurveySuspendedReason.NONE

    assert status.position is not None
    # N 47:31:18.822 and W 122:12:22.152 — west of Greenwich, so the longitude is negative.
    assert status.position.latitude_degrees == pytest.approx(47.521895, abs=1e-6)
    assert status.position.longitude_degrees == pytest.approx(-122.206153, abs=1e-6)
    assert status.position.height_metres == pytest.approx(38.0, abs=1e-6)
    assert status.height_datum is HeightDatum.MSL


def test_the_captured_screen_reports_every_health_item_passing() -> None:
    status = parse_fixture("locked-stabilizing.txt")

    assert status.health_ok is True
    assert len(status.health_items) == 6
    assert all(status.health_items.values())

    for label in ("Self Test", "Int Pwr", "Oven Pwr", "OCXO", "EFC", "GPS Rcv"):
        assert status.health_item(label) is True, f"Expected a health item named '{label}'."


def test_the_captured_screen_parses_with_no_warnings() -> None:
    """Nothing on a screen this ordinary should be reported as odd. A warning here means a field
    silently stopped parsing, which is the regression this whole file exists to catch."""
    status = parse_fixture("locked-stabilizing.txt")

    assert status.parse_warnings == ()


def test_the_capture_instant_comes_from_the_injected_clock() -> None:
    status = parse_fixture("locked-stabilizing.txt")

    assert status.captured_at == CAPTURE_INSTANT


# ---------------------------------------------------------------------------------------------
# Rules the captures cannot reach
# ---------------------------------------------------------------------------------------------


def test_an_ss_column_is_recorded_as_a_different_scale_from_carrier_to_noise() -> None:
    """A 59551A-class unit labels the column ``SS`` on a 0–255 scale rather than ``C/N`` on 26–55.
    §11.1 is explicit that the two are not interchangeable, so which one was seen has to survive
    into the model."""
    status = parser_at(CAPTURE_INSTANT).parse(
        CRLF.join(
            [
                "ACQUISITION ................................................ [ GPS 1PPS Valid ]",
                "Tracking: 1 ____   Not Tracking: 0 ________",
                "PRN  El  Az  SS ",
                " 18  79 219 212",
            ]
        )
    )

    assert status.signal_strength_kind is SignalStrengthKind.SIGNAL_STRENGTH
    assert len(status.tracked) == 1
    assert status.tracked[0].signal_strength == 212
    assert status.tracked[0].azimuth_degrees == 219


def test_a_single_column_group_parses_with_no_predicted_satellites() -> None:
    """A screen with only a tracking group still parses; the not-tracked list is simply empty."""
    status = parser_at(CAPTURE_INSTANT).parse(
        CRLF.join(
            [
                "ACQUISITION ................................................ [ GPS 1PPS Valid ]",
                "Tracking: 2 ____   Not Tracking: 0 ________",
                "PRN  El  Az  C/N",
                " 18  79   2   32",
                "  5  25  50   41",
            ]
        )
    )

    assert len(status.tracked) == 2
    assert status.not_tracked == ()
    assert status.signal_strength_kind is SignalStrengthKind.CARRIER_TO_NOISE


def test_a_row_count_that_contradicts_the_header_is_warned_about() -> None:
    """The counts the receiver prints above the table are its own view of the world, so a
    disagreement with the rows means the column model has slipped on this firmware — worth a
    warning in Diagnostics rather than a quietly wrong sky plot."""
    status = parser_at(CAPTURE_INSTANT).parse(
        CRLF.join(
            [
                "ACQUISITION ................................................ [ GPS 1PPS Valid ]",
                "Tracking: 4 ____   Not Tracking: 0 ________",
                "PRN  El  Az  C/N",
                " 18  79   2   32",
            ]
        )
    )

    assert len(status.tracked) == 1
    assert any("4 tracked" in w for w in status.parse_warnings)


def test_unreadable_columns_become_nulls() -> None:
    """A row whose columns hold dashes rather than numbers degrades to nulls, not an exception."""
    status = parser_at(CAPTURE_INSTANT).parse(
        CRLF.join(
            [
                "Tracking: 1 ____   Not Tracking: 0 ________",
                "PRN  El  Az  C/N",
                " 18  --  --   --",
            ]
        )
    )

    assert len(status.tracked) == 1
    satellite = status.tracked[0]
    assert satellite.prn == 18
    assert satellite.elevation_degrees is None
    assert satellite.azimuth_degrees is None
    assert satellite.signal_strength is None


@pytest.mark.parametrize(
    ("advisory", "expected"),
    [
        ("Synchronized to UTC", ClockAdvisory.SYNCHRONIZED_TO_UTC),
        ("Synchronized to GPS Time", ClockAdvisory.SYNCHRONIZED_TO_GPS_TIME),
        ("Assessing stability", ClockAdvisory.ASSESSING_STABILITY),
        ("Assessing stability...", ClockAdvisory.ASSESSING_STABILITY),
        ("Questionable accuracy", ClockAdvisory.QUESTIONABLE_ACCURACY),
        ("Inaccurate: not tracking", ClockAdvisory.INACCURATE_NOT_TRACKING),
        ("Inaccurate: inacc position", ClockAdvisory.INACCURATE_INACCURATE_POSITION),
        ("Absent or freq error", ClockAdvisory.ABSENT_OR_FREQUENCY_ERROR),
        ("Invalid: GPS rcvr err", ClockAdvisory.INVALID_GPS_RECEIVER_ERROR),
    ],
)
def test_every_advisory_in_the_specification_decodes_to_its_own_value(
    advisory: str, expected: ClockAdvisory
) -> None:
    status = parser_at(CAPTURE_INSTANT).parse(f"GPS 1PPS {advisory}")

    assert status.one_pps_clock_advisory is expected

    # A recognised advisory is not an anomaly. The other warnings this one-line screen raises — no
    # health banner, no table, no clock row — are all correct and beside the point.
    assert not any("advisory" in w.lower() for w in status.parse_warnings)


def test_an_unrecognised_advisory_is_quoted_in_the_warnings() -> None:
    """§11.3 keeps no string form of the advisory on the model, so an unfamiliar one would vanish
    entirely if the parser did not quote it. That warning is what makes a field report about an
    odd firmware revision answerable."""
    status = parser_at(CAPTURE_INSTANT).parse("GPS 1PPS Assessing drift")

    assert status.one_pps_clock_advisory is ClockAdvisory.OTHER
    assert any("Assessing drift" in w for w in status.parse_warnings)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Suspended: track <4 sats", SurveySuspendedReason.TOO_FEW_SATELLITES),
        ("Suspended: poor geometry", SurveySuspendedReason.POOR_GEOMETRY),
        ("Suspended: no track data", SurveySuspendedReason.NO_TRACK_DATA),
    ],
)
def test_a_suspended_survey_reports_why(line: str, expected: SurveySuspendedReason) -> None:
    status = parser_at(CAPTURE_INSTANT).parse(CRLF.join(["MODE     Survey: 45% complete", line]))

    assert status.position_mode is PositionMode.SURVEY
    assert status.survey_percent_complete == 45.0
    assert status.survey_suspended_reason is expected


# ---------------------------------------------------------------------------------------------
# The week rollover
# ---------------------------------------------------------------------------------------------


def test_a_date_that_is_wrong_but_not_by_a_whole_epoch_is_not_corrected() -> None:
    """A gap that is not close to a whole number of epochs is a receiver with its date set wrongly,
    not a rollover, and §7.4's ±7 day tolerance is what tells them apart."""
    status = parser_at(CAPTURE_INSTANT).parse("UTC      14:45:02     27 Dec 2010")

    assert status.week_rollover_epochs == 0
    assert status.corrected_date_time == status.device_date_time


def test_a_current_date_is_left_alone() -> None:
    status = parser_at(CAPTURE_INSTANT).parse("UTC      14:45:02     12 Aug 2026")

    assert status.week_rollover_epochs == 0
    assert status.corrected_date_time == CAPTURE_INSTANT


# ---------------------------------------------------------------------------------------------
# §11.1: the parser never raises
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "screen",
    [
        None,
        "",
        "   ",
        "\r\n\r\n",
        "not a status screen at all",
        "PRN",
        "PRN  El  Az  C/N",
        "\0\xff[2J",
    ],
)
def test_nothing_unparseable_raises(screen: str | None) -> None:
    """A parser that raised would take down the polling loop that called it."""
    status = parser_at(CAPTURE_INSTANT).parse(screen)

    assert status.captured_at == CAPTURE_INSTANT
    assert status.tracked == ()
    assert status.not_tracked == ()


def test_a_truncated_screen_keeps_what_arrived() -> None:
    """A screen truncated mid-table — which a timeout on a slow link produces — keeps the rows
    that did arrive rather than discarding the lot."""
    truncated = CRLF.join(read_fixture("locked-stabilizing.txt").split(CRLF)[:15])
    status = parser_at(CAPTURE_INSTANT).parse(truncated)

    assert status.mode is SmartClockMode.LOCKED
    assert len(status.tracked) == 1
    assert len(status.not_tracked) == 3

    # What is missing is reported rather than passed off as fine.
    assert status.parse_warnings


@pytest.mark.parametrize("name", sorted(p.name for p in (FIXTURES / "captured").glob("*.txt")))
def test_every_prefix_of_every_capture_parses_without_raising(name: str) -> None:
    """The fuzz half of §11.1's guarantee, at byte granularity.

    A status screen arrives in dozens of chunks at 9600 baud, so every one of these prefixes is a
    state the parser can genuinely be handed if a read is cut short. Truncating between the header
    row and the table, mid-coordinate, or inside the clock row are the interesting ones, and this
    reaches all of them without anyone having to think of them.
    """
    whole = read_fixture(f"captured/{name}")
    parser = parser_at(CAPTURE_INSTANT)

    for end in range(len(whole) + 1):
        parser.parse(whole[:end])


# ---------------------------------------------------------------------------------------------
# Satellites the receiver is attempting to track (#4)
# ---------------------------------------------------------------------------------------------


def test_satellites_the_receiver_is_attempting_to_track_are_not_dropped() -> None:
    """A starred PRN is a satellite, not a parse failure.

    While acquiring, the receiver marks satellites it is trying to lock onto with a leading
    asterisk, and explains it in the screen's own legend: ``*attempting to track``. Read as a plain
    integer that row yields ``None`` and the whole satellite is dropped.

    **The screen contradicted itself and nothing noticed.** The captured power-up screen says
    ``Not Tracking: 10`` and the parser produced five — because five of the ten were starred.
    """
    status = parse_fixture("captured/power-up-gps-acquisition.txt", SITTING_INSTANT)

    assert len(status.not_tracked) == 10
    attempting = [s for s in status.not_tracked if s.attempting_to_track]
    assert len(attempting) == 5

    # The starred five, by PRN, so a regression that keeps the count but loses the marker fails.
    assert sorted(s.prn for s in attempting) == [15, 19, 20, 22, 24]

    # And a starred row keeps its other columns rather than being half-parsed.
    fifteen = next(s for s in status.not_tracked if s.prn == 15)
    assert fifteen.elevation_degrees == 29
    assert fifteen.azimuth_degrees == 271


# ---------------------------------------------------------------------------------------------
# The four states captured on the 27 Aug 2026 backyard sitting (#4, #185)
# ---------------------------------------------------------------------------------------------


def test_the_surveying_screen_parses() -> None:
    """A survey in progress — taken at 1.9 % of the two-hour survey that ran overnight on 27 Aug.
    It is the only screen in the corpus that is not a held position, which makes it the only one
    exercising the survey half of §11.2 at all."""
    status = parse_fixture(
        "captured/surveying-locked-to-gps-stabilizing-frequency.txt", SITTING_INSTANT
    )

    assert status.mode is SmartClockMode.LOCKED
    assert status.mode_detail == "stabilizing frequency"
    assert status.outputs is OutputValidity.VALID_REDUCED
    assert status.tfom == 4
    assert status.ffom == 1

    assert status.one_pps_ti_nanoseconds == pytest.approx(-22.9, abs=1e-10)
    assert status.hold_threshold_seconds == pytest.approx(1e-6, abs=1e-12)
    assert status.holdover_predicted_seconds == pytest.approx(432e-6, abs=1e-12)

    assert status.gps_one_pps_valid is True
    assert len(status.tracked) == 8
    assert len(status.not_tracked) == 2
    assert status.elevation_mask_degrees == 10
    assert status.signal_strength_kind is SignalStrengthKind.CARRIER_TO_NOISE
    assert status.antenna_delay_nanoseconds == pytest.approx(77.0)

    # The survey, which is the point of this fixture.
    assert status.position_mode is PositionMode.SURVEY
    assert status.survey_percent_complete == 1.9
    assert status.survey_suspended_reason is SurveySuspendedReason.NONE

    # AVG LAT / AVG LON / AVG HGT: a running average, not a held position.
    assert status.position_qualifier is PositionQualifier.AVERAGE
    assert status.height_datum is HeightDatum.MSL
    assert status.position is not None
    assert status.position.height_metres == 30.47

    assert status.health_ok is True
    assert len(status.health_items) == 6
    assert all(status.health_items.values())
    assert status.parse_warnings == ()


def test_the_surveying_screens_rolled_over_date_is_corrected() -> None:
    """The week rollover, checked against a screen whose real capture time is known.

    The receiver printed ``12 Jan 2007``; the screen was taken at about 22:12 on 27 Aug 2026
    Pacific, which is 05:12 UTC on the 28th. One 1024-week epoch is the whole correction, and the
    minutes and seconds have to survive it — the strongest rollover evidence in the corpus,
    because the truth is independently known from the application log.
    """
    status = parse_fixture(
        "captured/surveying-locked-to-gps-stabilizing-frequency.txt", SITTING_INSTANT
    )

    assert status.time_scale is TimeScale.UTC
    assert status.device_date_time == datetime(2007, 1, 12, 5, 12, 20, tzinfo=UTC)
    assert status.week_rollover_epochs == 1
    assert status.corrected_date_time == datetime(2026, 8, 28, 5, 12, 20, tzinfo=UTC)
    assert status.one_pps_clock_advisory is ClockAdvisory.SYNCHRONIZED_TO_UTC


def test_the_power_up_screen_separates_absent_from_provisional_readings() -> None:
    """Power-up, whose readings are absent, provisional, or real — and must be told apart.

    **The fixture that exercises §11.1 hardest.** A receiver seconds from cold prints a screen
    with three different kinds of nothing on it, and the requirement is that each is reported as
    what it is rather than as a plausible value.
    """
    status = parse_fixture("captured/power-up-fine-freq-adj.txt", SITTING_INSTANT)

    assert status.mode is SmartClockMode.POWER_UP
    assert status.mode_detail == "fine freq adj"
    assert status.outputs is OutputValidity.INVALID
    assert status.tfom == 9
    assert status.ffom == 3

    # Absent, and None rather than zero — a 1 PPS offset of 0 ns would read as a perfect lock.
    assert status.one_pps_ti_nanoseconds is None

    # Present and provisional (#245). The value is read, and the caveat travels with it rather
    # than being left in a warning nobody looking at a clock will see.
    assert status.device_date_time == datetime(2007, 1, 12, 5, 10, 26, tzinfo=UTC)
    assert status.time_scale is TimeScale.UTC
    assert status.device_time_is_provisional is True

    # §7.4 still applies on top: this unit is 19 years and change behind, and the corrected
    # instant lands within a minute of the sitting. That the arithmetic works on a provisional
    # time is the point — the two caveats are independent, and the UI has to show both.
    assert status.week_rollover_epochs == 1
    assert status.corrected_date_time is not None
    assert abs(status.corrected_date_time - SITTING_INSTANT) < timedelta(minutes=5)

    # The row parses now, so the clock produces no warning at all.
    assert not any("clock row" in w.lower() for w in status.parse_warnings)

    # The survey the power cycle started, three tenths of a per cent in (#229).
    assert status.position_mode is PositionMode.SURVEY
    assert status.survey_percent_complete == 0.3
    assert status.position_qualifier is PositionQualifier.AVERAGE

    assert len(status.tracked) == 8
    assert len(status.not_tracked) == 2
    assert status.health_ok is True


def test_the_fully_locked_screen_parses() -> None:
    """Full lock with nine satellites, the best state the sitting reached."""
    status = parse_fixture("captured/locked-to-gps.txt", SITTING_INSTANT)

    assert status.mode is SmartClockMode.LOCKED
    assert not status.mode_detail
    assert status.outputs is OutputValidity.VALID
    assert status.tfom == 3
    assert status.ffom == 0
    assert status.one_pps_ti_nanoseconds == pytest.approx(49.8, abs=1e-10)

    assert len(status.tracked) == 9
    assert len(status.not_tracked) == 2

    # Still the rack position: taken before the survey ran, so the receiver was holding a position
    # surveyed indoors while its antenna was already outside.
    assert status.position_mode is PositionMode.HOLD
    assert status.survey_percent_complete is None
    assert status.position_qualifier is PositionQualifier.UNKNOWN
    assert status.position is not None
    assert status.position.height_metres == 38.0


def test_the_stabilizing_screen_parses() -> None:
    """Locked but still stabilizing, the state the sitting spent longest in."""
    status = parse_fixture("captured/locked-to-gps-stabilizing-frequency.txt", SITTING_INSTANT)

    assert status.mode is SmartClockMode.LOCKED
    assert status.mode_detail == "stabilizing frequency"

    # The distinction the medallion turns on: locked, but not yet at full accuracy.
    assert status.outputs is OutputValidity.VALID_REDUCED
    assert status.tfom == 3
    assert status.ffom == 1
    assert status.one_pps_ti_nanoseconds == pytest.approx(-20.9, abs=1e-10)

    assert len(status.tracked) == 8
    assert status.position_mode is PositionMode.HOLD
    assert status.position_qualifier is PositionQualifier.UNKNOWN


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("captured/surveying-locked-to-gps-stabilizing-frequency.txt", PositionQualifier.AVERAGE),
        ("captured/power-up-fine-freq-adj.txt", PositionQualifier.AVERAGE),
        ("captured/locked-to-gps.txt", PositionQualifier.UNKNOWN),
        ("captured/locked-to-gps-stabilizing-frequency.txt", PositionQualifier.UNKNOWN),
        ("locked-stabilizing.txt", PositionQualifier.UNKNOWN),
    ],
)
def test_an_averaged_position_is_distinguished_from_a_held_one(
    name: str, expected: PositionQualifier
) -> None:
    """The regression this pins is specific. The qualifier was matched by a parenthesised word —
    ``(Average)`` — which the documented form uses and this receiver never prints; it prefixes the
    label instead, as ``AVG LAT``. Both surveying fixtures therefore read as having no qualifier,
    losing the one distinction the field exists to draw, on the only two screens that draw it."""
    assert parse_fixture(name, SITTING_INSTANT).position_qualifier is expected


@pytest.mark.parametrize(
    ("name", "hour", "minute", "second", "expected_scale"),
    [
        ("captured/power-up-gps-acquisition.txt", 5, 10, 4, TimeScale.GPS),
        ("captured/power-up-fine-freq-adj.txt", 5, 10, 26, TimeScale.UTC),
    ],
)
def test_a_provisional_power_up_time_is_read_and_flagged(
    name: str, hour: int, minute: int, second: int, expected_scale: TimeScale
) -> None:
    """**The flag is the point, not the time.** The guide calls this "the default power-up setting
    … corrected when the first satellite is tracked". These two captures happen to be accurate to
    the minute because the oscillator held time across the power cycle; the guide's own example,
    ``12:00:00[?] 01 JAN 1996``, is a placeholder that is arbitrarily wrong. The marker is the
    only thing separating those cases."""
    status = parse_fixture(name, SITTING_INSTANT)

    assert status.device_date_time == datetime(2007, 1, 12, hour, minute, second, tzinfo=UTC)
    assert status.time_scale is expected_scale
    assert status.device_time_is_provisional is True


@pytest.mark.parametrize("name", ["locked-stabilizing.txt", "captured/power-up-fine-freq-adj.txt"])
def test_only_a_marked_row_is_provisional(name: str) -> None:
    """The half that keeps the flag meaningful. A marker detector that fired on every row would be
    indistinguishable from one that never fired, since the UI would caveat everything."""
    marked = "(?)" in read_fixture(name)

    assert parse_fixture(name, SITTING_INSTANT).device_time_is_provisional is marked


@pytest.mark.parametrize(
    "clock_row",
    [
        "UTC      12:00:00(?) 01 Jan 1996",
        "UTC      12:00:00[?] 01 Jan 1996",
        "UTC      12:00:00 (?) 01 Jan 1996",
        "UTC      12:00:00 [ ? ] 01 Jan 1996",
    ],
)
def test_either_bracket_style_marks_a_provisional_time(clock_row: str) -> None:
    """This unit prints ``(?)``; the Z3801A and 58503A guides print ``[?]`` for the same field.
    Neither is more correct, and a parser that knew only the one in front of it would fail on the
    sibling model §11.1 exists to survive."""
    status = parse_clock_row(clock_row)

    assert status.device_time_is_provisional is True
    assert status.device_date_time == datetime(1996, 1, 1, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("clock_row", "year", "month", "day"),
    [
        ("GPS      03:56:44 1994 DEC 01", 1994, 12, 1),
        ("GPS      03:56:44 01 DEC 1994", 1994, 12, 1),
    ],
)
def test_either_date_order_is_read(clock_row: str, year: int, month: int, day: int) -> None:
    """``58503A-1.txt`` and ``z3801.txt`` both print ``GPS  03:56:44 1994 DEC 01`` — year first,
    day last — against the ``d MMM yyyy`` every screen captured from this unit uses.

    The day and year are both digits, so the two orders are told apart by width alone. That is why
    the alternation anchors on four digits for the year rather than trying to be clever: a
    two-digit year would make ``94 DEC 01`` genuinely ambiguous, and no manual prints one.
    """
    status = parse_clock_row(clock_row)

    assert status.device_date_time == datetime(year, month, day, 3, 56, 44, tzinfo=UTC)
    assert status.device_time_is_provisional is False


def test_a_screen_with_no_clock_row_still_says_so() -> None:
    """The other half, and the one that keeps the change honest: loosening the detection until
    nothing is ever called missing would be its own defect. ``GPS 1PPS Synchronized to UTC``
    begins with a scale name and must not be mistaken for a clock row, which is why the shape test
    requires a time of day after it."""
    status = parser_at(SITTING_INSTANT).parse(
        CRLF.join(
            [
                "------------------------------- Receiver Status -----------------------------",
                "SYNCHRONIZATION ........................................... [ Outputs Invalid ]",
                ">> Power-up: GPS acquisition                  TFOM     9             FFOM     3",
                "ACQUISITION .............................................. [ GPS 1PPS Invalid ]",
                "Tracking: 0 ____   Not Tracking: 0 ________",
                "                                              GPS 1PPS Synchronized to UTC",
                "HEALTH MONITOR ......................................................... [ OK ]",
            ]
        )
    )

    assert status.device_date_time is None
    assert any("No clock row was found" in w for w in status.parse_warnings)


# ---------------------------------------------------------------------------------------------
# Holdover, captured 28 Aug 2026 by disconnecting the antenna (#4, #185)
# ---------------------------------------------------------------------------------------------


def test_the_holdover_screen_parses() -> None:
    """The receiver reports the reason in the mode line itself — ``Holdover: GPS 1PPS invalid`` —
    which is the same shape as ``Locked to GPS: stabilizing frequency``, so the detail is the text
    after the colon and must not swallow the reference-outputs panel beside it."""
    status = parse_fixture("captured/holdover-gps-1pps-invalid.txt", HOLDOVER_INSTANT)

    assert status.mode is SmartClockMode.HOLDOVER
    assert status.mode_detail == "GPS 1PPS invalid"

    # Outputs are still valid-but-reduced: holdover degrades them, it does not invalidate them
    # until the phase error passes HOLD THR.
    assert status.outputs is OutputValidity.VALID_REDUCED
    assert status.tfom == 3
    assert status.ffom == 2

    assert status.gps_one_pps_valid is False
    assert status.tracked == ()
    assert len(status.not_tracked) == 9

    # Nothing is being attempted, because there is no antenna to attempt it with. Distinct from
    # the power-up screens, where five of ten carry the asterisk.
    assert not any(s.attempting_to_track for s in status.not_tracked)

    # No tracked satellites means no signal-strength column and so no scale to name.
    assert status.signal_strength_kind is SignalStrengthKind.UNKNOWN

    assert status.health_ok is True
    assert status.parse_warnings == ()


def test_the_holdover_screen_reports_both_uncertainties() -> None:
    """``holdover_present_seconds`` existed on the model and in the view models and had never once
    been populated from a real screen, because no captured screen showed a receiver in holdover.
    The row is ``Holdover Duration:  0m 03s   Present  1.0 us`` — both values on one line."""
    status = parse_fixture("captured/holdover-gps-1pps-invalid.txt", HOLDOVER_INSTANT)

    assert status.hold_threshold_seconds == pytest.approx(1e-6, abs=1e-12)
    assert status.holdover_predicted_seconds == pytest.approx(6.8e-6, abs=1e-12)
    assert status.holdover_present_seconds == pytest.approx(1e-6, abs=1e-12)

    # "1PPS TI --" with no antenna: absent, and None rather than zero.
    assert status.one_pps_ti_nanoseconds is None


@pytest.mark.parametrize(
    ("name", "minutes", "seconds"),
    [
        ("captured/holdover-gps-1pps-invalid.txt", 0, 3),
        ("captured/holdover-gps-1pps-invalid-deep.txt", 11, 34),
    ],
)
def test_the_holdover_screen_reports_how_long_it_has_been_degraded(
    name: str, minutes: int, seconds: int
) -> None:
    """**Two screens, and the second is why there are two.** The field is right-aligned in a fixed
    width, so a short holdover prints `` 0m 03s`` and a longer one ``11m 34s`` — minutes unpadded
    and able to be two digits, seconds always padded to two. A parser written against the first
    alone could have sliced fixed columns and passed."""
    status = parse_fixture(name, HOLDOVER_INSTANT)

    assert status.holdover_duration == timedelta(minutes=minutes, seconds=seconds)


@pytest.mark.parametrize(
    "name",
    [
        "captured/holdover-gps-1pps-invalid.txt",
        "captured/holdover-gps-1pps-invalid-deep.txt",
    ],
)
def test_the_present_uncertainty_is_the_same_on_both_holdover_screens(name: str) -> None:
    """Both screens report ``Present  1.0 us`` — at three seconds and at eleven and a half
    minutes — sitting exactly on the 1.000 µs hold threshold. So at the resolution the receiver
    prints, this figure does not distinguish a fresh holdover from a long one. Recorded as an
    observation about the instrument, not as a parser requirement."""
    status = parse_fixture(name, HOLDOVER_INSTANT)

    assert status.holdover_present_seconds == pytest.approx(1e-6, abs=1e-12)


def test_the_mode_row_is_not_mistaken_for_the_advisory() -> None:
    """**Only holdover can trigger this**, which is why five earlier fixtures and §11.3's own
    tests all passed. In holdover the mode row reads ``>> Holdover: GPS 1PPS invalid``, which the
    advisory pattern matches and then runs to the end of the line — taking the reference-outputs
    panel beside it. Before the fix this fixture produced the advisory ``'invalid HOLD THR 1.000
    us'``, warned that it was unrecognised, and never reached the real advisory two panels below.
    """
    status = parse_fixture("captured/holdover-gps-1pps-invalid.txt", HOLDOVER_INSTANT)

    # From "GPS 1PPS Invalid: not tracking", the real advisory line.
    assert status.one_pps_clock_advisory is ClockAdvisory.INACCURATE_NOT_TRACKING
    assert not any("advisory" in w.lower() for w in status.parse_warnings)


def test_the_holdover_screen_holds_the_surveyed_position() -> None:
    """Worth asserting because it is the evidence that the survey took: these coordinates are the
    backyard position the receiver adopted at 00:10, not the rack position every fixture taken
    before the survey carries."""
    status = parse_fixture("captured/holdover-gps-1pps-invalid.txt", HOLDOVER_INSTANT)

    assert status.position_mode is PositionMode.HOLD
    assert status.position_qualifier is PositionQualifier.UNKNOWN
    assert status.height_datum is HeightDatum.MSL
    assert status.position is not None
    assert status.position.height_metres == pytest.approx(25.20, abs=1e-6)

    # N 47:31:18.582 — the surveyed position, against 47:31:18.822 on every pre-survey screen.
    assert status.position.latitude_degrees == pytest.approx(47.521828, abs=1e-6)
    assert status.position.longitude_degrees == pytest.approx(-122.206137, abs=1e-6)


# ---------------------------------------------------------------------------------------------
# Recovery, and the state between it and holdover (#4, #185)
# ---------------------------------------------------------------------------------------------


def test_the_recovery_screen_parses() -> None:
    """Captured by reconnecting the antenna after twelve minutes of holdover. The receiver passes
    through recovery on its way back to lock, so it exists only in this window and cannot be
    reached by waiting."""
    status = parse_fixture("captured/recovery-fine-freq-adj.txt", RECOVERY_INSTANT)

    assert status.mode is SmartClockMode.RECOVERY
    assert status.mode_detail == "fine freq adj"
    assert status.outputs is OutputValidity.VALID_REDUCED
    assert status.tfom == 3
    assert status.ffom == 2

    assert status.gps_one_pps_valid is True
    assert len(status.tracked) == 7
    assert len(status.not_tracked) == 2
    assert status.one_pps_clock_advisory is ClockAdvisory.SYNCHRONIZED_TO_UTC
    assert status.one_pps_ti_nanoseconds == pytest.approx(-17.9, abs=1e-10)

    assert status.health_ok is True
    assert status.parse_warnings == ()


@pytest.mark.parametrize(
    "name",
    ["captured/recovery-fine-freq-adj.txt", "captured/power-up-fine-freq-adj.txt"],
)
def test_a_mode_detail_stops_before_its_bracketed_figure(name: str) -> None:
    """Both screens that report ``fine freq adj`` carry a bracketed figure, in different modes and
    with different signs::

        >> Recovery: fine freq adj   [TI  -17.0 ns]   1PPS TI -17.9 ns relative to GPS
        >> Power-up: fine freq adj   [TI +108.5 ns]   Holdover Uncertainty ____________

    On the recovery screen the two figures differ — the bracket is the receiver's own adjustment
    reading, the panel is the 1 PPS time interval — so they are not interchangeable, and only the
    panel one is parsed into ``one_pps_ti_nanoseconds``.
    """
    status = parse_fixture(name, RECOVERY_INSTANT)

    assert status.mode_detail == "fine freq adj"


def test_holdover_with_the_signal_back_is_still_holdover() -> None:
    """Captured fourteen seconds before the recovery screen. The antenna is reconnected, six
    satellites are tracked and the acquisition banner reads ``GPS 1PPS Valid`` — but the receiver
    is still in holdover, because regaining the signal and leaving holdover are separate events.
    Anything deriving "is the 1 PPS usable" from the SmartClock mode alone gets this state wrong.
    """
    status = parse_fixture("captured/holdover-gps-1pps-invalid-3.txt", RECOVERY_INSTANT)

    assert status.mode is SmartClockMode.HOLDOVER
    assert status.gps_one_pps_valid is True
    assert len(status.tracked) == 6
    assert status.one_pps_clock_advisory is ClockAdvisory.SYNCHRONIZED_TO_UTC

    # Still no 1 PPS time interval: the receiver is not yet steering to GPS.
    assert status.one_pps_ti_nanoseconds is None
    assert status.parse_warnings == ()


def test_the_duration_keeps_counting_from_holdover_into_recovery() -> None:
    """The Z3801A guide states twice that this is "the cumulative duration of holdover and
    recovery operations". The counter does not reset when the antenna is reconnected and does not
    stop when the mode changes. So a caller must not label it "time since signal loss" — by the
    recovery screen the signal had been back for over a minute."""
    in_holdover = parse_fixture(
        "captured/holdover-gps-1pps-invalid-3.txt", RECOVERY_INSTANT
    ).holdover_duration
    in_recovery = parse_fixture(
        "captured/recovery-fine-freq-adj.txt", RECOVERY_INSTANT
    ).holdover_duration

    assert in_holdover == timedelta(minutes=16, seconds=52)
    assert in_recovery == timedelta(minutes=17, seconds=6)
    assert in_recovery is not None and in_holdover is not None
    assert in_recovery > in_holdover, "the counter must not reset on leaving holdover"


# ---------------------------------------------------------------------------------------------
# Corrupted fields degrade; corrupted fields do not cost the screen
# ---------------------------------------------------------------------------------------------


def replace_holdover_duration(name: str, duration: str) -> ReceiverStatus:
    """A captured screen with its holdover duration overwritten, and nothing else touched."""
    lines = read_fixture(name).split(CRLF)
    rewritten = [
        f"Holdover Duration: {duration}" if "Holdover Duration:" in line else line for line in lines
    ]
    return parser_at(HOLDOVER_INSTANT).parse(CRLF.join(rewritten))


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        ("9" * 5000 + " m 0 s", None),
        ("2000000000 d 0 m 0 s", None),
        ("999999999 d 24 h 0 m 0 s", None),
        ("1 d 2 h 3 m 4 s", timedelta(days=1, hours=2, minutes=3, seconds=4)),
    ],
)
def test_an_unreadable_duration_costs_the_field_and_not_the_screen(
    duration: str, expected: timedelta | None
) -> None:
    """§11.1's rule is that an unparseable **field** becomes ``None`` — not that the screen is
    discarded. Both of these used to cost the whole screen: ``int()`` raises above 4300 digits and
    ``timedelta`` raises ``OverflowError`` past 999999999 days, and the catch-all in
    :meth:`StatusScreenParser.parse` caught each one and threw away a perfectly good mode,
    satellite table and position along with it.

    Regression test, and the assertion that matters is the second one.
    """
    status = replace_holdover_duration("captured/holdover-gps-1pps-invalid.txt", duration)

    assert status.holdover_duration == expected
    assert status.mode is not SmartClockMode.UNKNOWN
    assert not any("failed unexpectedly" in warning for warning in status.parse_warnings)


def test_the_rewrite_helper_reproduces_the_fixture_when_it_changes_nothing() -> None:
    """Guarding the guard: if the substitution above missed its line, every assertion in the test
    beside it would pass against an unmodified screen and prove nothing."""
    original = parse_fixture("captured/holdover-gps-1pps-invalid.txt", HOLDOVER_INSTANT)
    assert original.holdover_duration is not None

    rewritten = replace_holdover_duration(
        "captured/holdover-gps-1pps-invalid.txt", "9" * 5000 + " m 0 s"
    )
    assert rewritten.holdover_duration != original.holdover_duration
