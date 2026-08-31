"""Turns the receiver's ``:SYST:STAT?`` screen into a :class:`ReceiverStatus` (§11).

This is the highest-risk component in the project, which is why §15 schedules it before any UI
exists. The satellite elevation, azimuth and signal-strength table has no individual query — it
exists only inside this screen — so everything the Satellites page, the sky plot and the position
readout show comes through here.

**It never raises** (§11.1). Every field is attempted independently, a field that will not parse
becomes ``None``, and the reason is added to :attr:`ReceiverStatus.parse_warnings` for the
Diagnostics page. The whole body sits inside one last-resort ``except`` as well, so even a defect
in this file degrades to an empty status with a warning rather than tearing down the polling loop.

**Column positions come from the header row, never from constants** (§11.1). The family differs in
column labels and widths — ``C/N`` on 58503B-class units against ``SS`` on 59551A-class units —
and values overflow their header token to the left when they need the room (a three-digit azimuth
under a two-character ``Az``), so each field runs from just past the previous column's header to
the end of its own. That single rule is what makes the table survive a firmware revision that
shifts a column by a character.

Everything outside the satellite table is found by its label rather than by position, because the
labels are unique across the screen and a label scan cannot be broken by a width change at all.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Final, NamedTuple

from smartclock_device.clock import Clock
from smartclock_device.models import gps_week_rollover
from smartclock_device.models.position import (
    GeoPosition,
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
from smartclock_device.models.satellite import PredictedSatellite, TrackedSatellite
from smartclock_device.parsing.scalars import parse_decimal, parse_integer

# ---------------------------------------------------------------------------------------------
# Patterns
#
# Compiled once at import rather than per call: these run on every poll for the life of the
# session. Each carries the IGNORECASE the C# original applies through RegexOptions.
# ---------------------------------------------------------------------------------------------

_TFOM: Final = re.compile(r"\bTFOM\s+(?P<value>[-+]?\d+)", re.IGNORECASE)
_FFOM: Final = re.compile(r"\bFFOM\s+(?P<value>[-+]?\d+)", re.IGNORECASE)
_ELEVATION_MASK: Final = re.compile(r"\bELEV\s+MASK\s+(?P<value>[-+]?\d+)", re.IGNORECASE)
_TRACKING_COUNT: Final = re.compile(r"(?<!Not\s)\bTracking:\s*(?P<value>\d+)", re.IGNORECASE)
_NOT_TRACKING_COUNT: Final = re.compile(r"\bNot\s+Tracking:\s*(?P<value>\d+)", re.IGNORECASE)

#: The unit alternation the receiver may print beside a time value. Shared by the four scaled
#: fields so a unit added to one is added to all.
_UNITS: Final = r"(?P<unit>ps|ns|us|µs|μs|ms|s)"

_ONE_PPS_TI: Final = re.compile(
    rf"\b1PPS\s+TI\s+(?P<value>[-+]?[\d.]+)\s*{_UNITS}\b", re.IGNORECASE
)
_HOLD_THRESHOLD: Final = re.compile(
    rf"\bHOLD\s+THR\s+(?P<value>[-+]?[\d.]+)\s*{_UNITS}\b", re.IGNORECASE
)
_HOLDOVER_PREDICT: Final = re.compile(
    rf"\bPredict\w*\s+(?P<value>[-+]?[\d.]+)\s*{_UNITS}\b", re.IGNORECASE
)
_HOLDOVER_PRESENT: Final = re.compile(
    rf"\bPresent\s+(?P<value>[-+]?[\d.]+)\s*{_UNITS}\b", re.IGNORECASE
)
_ANTENNA_DELAY: Final = re.compile(
    rf"\bANT\s+DLY\s+(?P<value>[-+]?[\d.]+)\s*{_UNITS}\b", re.IGNORECASE
)

#: The elapsed-holdover row, as ``Holdover Duration:  0m 03s``.
#:
#: Minutes and seconds are required because both the captured screen and the Z3801A guide's
#: Figure 3-4 print them, and neither pads the minutes. Hours and days are accepted ahead of them
#: but **not** confirmed: no capture has run long enough to show what this prints past an hour, so
#: the leading groups are a tolerance rather than a claim. If a long holdover ever turns out to
#: print something else, this yields ``None`` and the field reads as a dash, which is the §11.1
#: behaviour and not a regression.
#:
#: The row shares its line with ``Present  1.0 us``, whose unit ends in ``s``. Matching left to
#: right from the label consumes the duration and stops before reaching it.
_HOLDOVER_DURATION: Final = re.compile(
    r"\bHoldover\s+Duration:\s*(?:(?P<days>\d+)\s*d\s+)?(?:(?P<hours>\d+)\s*h\s+)?"
    r"(?P<minutes>\d+)\s*m\s+(?P<seconds>\d+)\s*s\b",
    re.IGNORECASE,
)

#: A clock row: a time scale, a time of day, an optional power-up marker, and a date.
#:
#: **The provisional marker.** Between the time and the date the receiver may print ``(?)`` —
#: printed ``[?]`` in the Z3801A user guide's Figure 3-1, which is the same field on a sibling
#: model. It means the time is the **default power-up value, not yet corrected from GPS**, and the
#: guide says it is corrected once the first satellite is tracked. It is captured rather than
#: merely tolerated — see :attr:`ReceiverStatus.device_time_is_provisional` for why reading the
#: value while discarding the marker would be worse than not reading it at all.
#:
#: **Two date orders.** Every screen captured from this unit prints ``12 Jan 2007``, but the
#: 58503A and Z3801A manuals both print ``1994 DEC 01`` — year first, day last. §11.1's
#: header-relative parsing exists to survive exactly this kind of cross-model difference, and the
#: alternation costs nothing on a unit that never emits the second form.
#:
#: The C# original spells both branches with the same three group names. Python's :mod:`re`
#: rejects a duplicated group name outright, so the second branch carries suffixed names and
#: :func:`_either` picks whichever matched. Nothing else about the pattern changed.
_DEVICE_TIME: Final = re.compile(
    r"(?P<scale>\b(?:UTC|GPS|LOCAL(?:\s+GPS)?|LCL(?:\s+GPS)?)\b)\s+"
    r"(?P<time>\d{1,2}:\d{2}:\d{2})\s*"
    r"(?P<provisional>[(\[]\s*\?\s*[)\]])?\s*"
    r"(?:(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3})\s+(?P<year>\d{4})"
    r"|(?P<year_first>\d{4})\s+(?P<month_last>[A-Za-z]{3})\s+(?P<day_last>\d{1,2}))",
    re.IGNORECASE,
)

#: The shape of a clock row, without requiring the date to follow the time.
#:
#: Used only to tell "the row is missing" from "the row is there and I could not read it", so it
#: is deliberately looser than :data:`_DEVICE_TIME` and is never used to extract a value. A time of
#: day after a scale name is enough to identify the line — ``GPS 1PPS Synchronized to UTC`` starts
#: with a scale name too and carries no clock.
_CLOCK_ROW_SHAPE: Final = re.compile(
    r"\b(?:UTC|GPS|LOCAL(?:\s+GPS)?|LCL(?:\s+GPS)?)\b\s+\d{1,2}:\d{2}:\d{2}", re.IGNORECASE
)

_CLOCK_ADVISORY: Final = re.compile(
    r"(?:GPS\s+1PPS|1PPS\s+CLK)\s+(?P<advisory>\S.*?)\s*$", re.IGNORECASE
)
_LEAP_PENDING: Final = re.compile(r"\bLEAP\b[^-+]*(?P<sign>[-+])", re.IGNORECASE)
_ANGLE: Final = re.compile(
    r"\b(?P<label>LAT|LON)\b\s+(?P<hemisphere>[NSEW])\s*"
    r"(?P<deg>\d{1,3}):(?P<min>\d{1,2}):(?P<sec>[\d.]+)",
    re.IGNORECASE,
)
_HEIGHT: Final = re.compile(
    r"\bHGT\b\s+(?P<value>[-+]?[\d.]+)\s*m\b\s*(?P<datum>\([^)]*\))?", re.IGNORECASE
)
_POSITION_MODE: Final = re.compile(r"\bMODE\b\s+(?P<body>\S.*?)\s*$", re.IGNORECASE)
_PERCENT: Final = re.compile(r"(?P<value>[\d.]+)\s*%")
_SUSPENDED: Final = re.compile(r"\bSuspended:\s*(?P<reason>\S.*?)\s*$", re.IGNORECASE)
_POSITION_QUALIFIER: Final = re.compile(r"\((?P<qualifier>Init\w*|Aver\w*|Held)\)", re.IGNORECASE)

#: The SmartClock family's own way of saying the position is a survey average.
#:
#: Anchored on the label rather than the line, because the position block shares its lines with
#: the satellite table — ``AVG LAT`` appears after eight columns of PRN, elevation and azimuth on
#: a screen tracking eight satellites.
_AVERAGED_POSITION_LABEL: Final = re.compile(r"\bAVG\s+(?:LAT|LON|HGT)\b", re.IGNORECASE)

_PAIR_SEPARATOR: Final = re.compile(r"\s{2,}")
_WIDE_GAP: Final = re.compile(r" {3,}")
_WHITESPACE_RUN: Final = re.compile(r"\s+")

#: Splits a screen into lines on either line-ending character, exactly as C#'s
#: ``Split(['\r', '\n'], StringSplitOptions.None)`` does — so a CRLF yields an empty line between,
#: and the line indices match on both implementations.
_LINE_BREAK: Final = re.compile(r"[\r\n]")

#: The header tokens that make up a satellite column group, besides ``PRN`` which opens one.
#:
#: Deliberately a closed set. Scanning stops at the first token that is not one of these, which is
#: what keeps the right-hand time and position panel — whose text shares these lines — out of the
#: table's column model.
_COLUMN_LABELS: Final = frozenset({"el", "elev", "az", "azm", "c/n", "s/n", "ss"})

#: The header tokens that mark a column as carrying signal strength.
_STRENGTH_LABELS: Final = frozenset({"c/n", "s/n", "ss"})

#: The banner lines that end a section, so table scanning stops at one.
_SECTION_BOUNDARIES: Final = ("health monitor", "synchronization", "acquisition", "elev mask")

#: Month abbreviations, spelled out rather than left to ``strptime``.
#:
#: ``%b`` follows the process locale, so on a machine running a non-English locale the receiver's
#: ``Dec`` would stop parsing and every date on the screen would silently become an em dash. The
#: receiver is not localised, and neither is this.
_MONTHS: Final[MappingProxyType[str, int]] = MappingProxyType(
    {
        "jan": 1,
        "feb": 2,
        "mar": 3,
        "apr": 4,
        "may": 5,
        "jun": 6,
        "jul": 7,
        "aug": 8,
        "sep": 9,
        "oct": 10,
        "nov": 11,
        "dec": 12,
    }
)

#: Multipliers onto seconds for each unit the receiver prints.
_UNIT_SECONDS: Final[MappingProxyType[str, float]] = MappingProxyType(
    {
        "ps": 1e-12,
        "ns": 1e-9,
        "us": 1e-6,
        "µs": 1e-6,
        "μs": 1e-6,
        "ms": 1e-3,
        "s": 1.0,
        "sec": 1.0,
    }
)

_KNOWN_FAILURE_VERDICTS: Final = frozenset({"bad", "fail", "failed", "err"})


class _Token(NamedTuple):
    """A whitespace-delimited run of characters, with its extent. ``end`` is inclusive."""

    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _FieldExtent:
    """A character range within a line, with both ends inclusive."""

    start: int
    end: int

    def slice(self, line: str) -> str | None:
        """This field's text from *line*, or ``None`` if the line is too short or the field blank.

        Short lines are ordinary rather than exceptional: the receiver stops padding once the
        right-hand panel runs out of content, so the last rows of a long not-tracking table are
        routinely shorter than the header that defined the columns.
        """
        if self.start >= len(line):
            return None

        end = min(self.end, len(line) - 1)
        if end < self.start:
            return None

        text = line[self.start : end + 1].strip()
        return text or None


@dataclass(frozen=True, slots=True)
class _ColumnGroup:
    """One ``PRN / El / Az [/ C-N]`` column group within the acquisition table."""

    prn: _FieldExtent
    elevation: _FieldExtent | None
    azimuth: _FieldExtent | None
    strength: _FieldExtent | None
    strength_label: str | None


class StatusScreenParser:
    """Parses ``:SYST:STAT?`` screens.

    :param clock: Supplies "now" for :attr:`ReceiverStatus.captured_at` and for the §7.4
        week-rollover comparison. Injected rather than read from :mod:`datetime` so fixture tests
        can pin it — the rollover logic is meaningless against a moving clock.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def parse(self, screen: str | None) -> ReceiverStatus:
        """Parse one complete status screen.

        :param screen: The response to ``:SYST:STAT?`` with the transaction framing already
            removed — no prompt, no echoed command. Line endings may be CRLF, CR or LF; leading
            and trailing whitespace *within* a line is significant and must not have been trimmed.
        :returns: A populated :class:`ReceiverStatus`. Never ``None``, and this method never
            raises: an unrecognisable screen yields a status whose fields are all ``None`` or
            their unknown member, and whose :attr:`~ReceiverStatus.parse_warnings` says so.
        """
        captured_at = self._clock.utc_now()
        warnings: list[str] = []

        try:
            if screen is None or not screen.strip():
                warnings.append("The status screen was empty.")
                return ReceiverStatus(captured_at=captured_at, parse_warnings=tuple(warnings))

            lines = _LINE_BREAK.split(screen)
            return _parse_lines(lines, captured_at, warnings)
        except Exception as exception:
            # §11.1: the parser never raises. A defect here must not take down the polling loop,
            # so the failure is reported through the same channel a bad field would use.
            warnings.append(
                f"The parser failed unexpectedly and the screen was discarded: {exception}"
            )
            return ReceiverStatus(captured_at=captured_at, parse_warnings=tuple(warnings))


def _parse_lines(lines: list[str], captured_at: datetime, warnings: list[str]) -> ReceiverStatus:
    outputs, gps_one_pps_valid, health_ok = _parse_banners(lines, warnings)
    mode, mode_detail = _parse_mode(lines)
    tracked, not_tracked, strength_kind = _parse_satellite_table(lines, warnings)

    device_time, time_scale, provisional_time = _parse_device_time(lines, warnings)
    epochs, corrected = _apply_week_rollover(device_time, captured_at)
    advisory = _parse_clock_advisory(lines, warnings)
    position, datum = _parse_position(lines, warnings)
    position_mode, survey_percent, suspended = _parse_position_mode(lines, warnings)

    return ReceiverStatus(
        outputs=outputs,
        mode=mode,
        mode_detail=mode_detail,
        tfom=_find_integer(lines, _TFOM),
        ffom=_find_integer(lines, _FFOM),
        one_pps_ti_nanoseconds=_find_scaled_value(lines, _ONE_PPS_TI, nanoseconds=True),
        hold_threshold_seconds=_find_scaled_value(lines, _HOLD_THRESHOLD, nanoseconds=False),
        holdover_predicted_seconds=_find_scaled_value(lines, _HOLDOVER_PREDICT, nanoseconds=False),
        holdover_present_seconds=_find_scaled_value(lines, _HOLDOVER_PRESENT, nanoseconds=False),
        # Read from the screen since 28 Aug 2026, when pulling the antenna produced the holdover
        # fixture this was waiting for. The label is "Holdover Duration:" and it shares a line
        # with the present uncertainty:
        #
        #     Holdover Duration:  0m 03s   Present  1.0 us
        holdover_duration=_find_holdover_duration(lines),
        gps_one_pps_valid=gps_one_pps_valid,
        tracked=tracked,
        not_tracked=not_tracked,
        elevation_mask_degrees=_find_integer(lines, _ELEVATION_MASK),
        signal_strength_kind=strength_kind,
        time_scale=time_scale,
        device_date_time=device_time,
        device_time_is_provisional=provisional_time,
        week_rollover_epochs=epochs,
        corrected_date_time=corrected,
        one_pps_clock_advisory=advisory,
        antenna_delay_nanoseconds=_find_scaled_value(lines, _ANTENNA_DELAY, nanoseconds=True),
        leap_pending=_parse_leap_pending(lines),
        position_mode=position_mode,
        survey_percent_complete=survey_percent,
        survey_suspended_reason=suspended,
        position=position,
        position_qualifier=_parse_position_qualifier(lines),
        height_datum=datum,
        health_ok=health_ok,
        health_items=_parse_health_items(lines, warnings),
        captured_at=captured_at,
        parse_warnings=tuple(warnings),
    )


# ---------------------------------------------------------------------------------------------
# Banners
# ---------------------------------------------------------------------------------------------


def _parse_banners(lines: list[str], warnings: list[str]) -> tuple[OutputValidity, bool, bool]:
    """Read the three section banners, each of which carries its headline verdict in brackets:
    ``SYNCHRONIZATION ... [ Outputs Valid ]``, ``ACQUISITION ... [ GPS 1PPS Valid ]`` and
    ``HEALTH MONITOR ... [ OK ]``."""
    outputs = OutputValidity.UNKNOWN
    gps_one_pps_valid = False
    health_ok = False
    saw_health_banner = False

    for line in lines:
        annotation = _banner_annotation(line)
        if annotation is None:
            continue

        trimmed = line.lstrip().lower()
        folded = annotation.lower()

        if trimmed.startswith("synchronization"):
            # "Reduced" is tested first because its text contains "Valid" as a substring, so the
            # looser match would swallow it and report full accuracy on a degraded receiver.
            if "reduced" in folded:
                outputs = OutputValidity.VALID_REDUCED
            elif "invalid" in folded:
                outputs = OutputValidity.INVALID
            elif "valid" in folded:
                outputs = OutputValidity.VALID
            else:
                outputs = OutputValidity.UNKNOWN
                warnings.append(f"Unrecognised synchronization banner: '{annotation}'.")
        elif trimmed.startswith("acquisition"):
            # Same ordering trap as above: "Invalid" contains "Valid".
            gps_one_pps_valid = "invalid" not in folded and "valid" in folded
        elif trimmed.startswith("health monitor"):
            saw_health_banner = True
            health_ok = annotation.strip().lower() == "ok"

    if not saw_health_banner:
        warnings.append("No health monitor banner was found; health is reported as not OK.")

    return outputs, gps_one_pps_valid, health_ok


def _banner_annotation(line: str) -> str | None:
    """The text between the final brackets on a banner line, or ``None`` if it is not one."""
    open_bracket = line.rfind("[")
    close_bracket = line.rfind("]")
    if open_bracket >= 0 and close_bracket > open_bracket:
        return line[open_bracket + 1 : close_bracket].strip()
    return None


# ---------------------------------------------------------------------------------------------
# SmartClock mode
# ---------------------------------------------------------------------------------------------


def _parse_mode(lines: list[str]) -> tuple[SmartClockMode, str | None]:
    """Read the active SmartClock mode.

    The screen prints all four modes as a menu and marks the live one with ``>>``, so the marker
    is what is searched for — not any mode word, which would match the three inactive rows just
    as well.
    """
    for line in lines:
        trimmed = line.lstrip()
        if not trimmed.startswith(">>"):
            continue

        # The mode occupies the left-hand column, and the same physical line carries the
        # reference-outputs panel on its right — the live mode row reads
        # ">> Locked to GPS: stabilizing frequency       TFOM     3             FFOM     1".
        # The panels are separated by a run of three or more spaces while the mode text uses
        # single ones, so cutting at the first wide gap keeps "TFOM 3 FFOM 1" out of the detail
        # without knowing where the column happens to start on this firmware.
        body = _cut_at_wide_gap(trimmed[2:].strip())
        colon = body.find(":")
        name = body[:colon].strip() if colon >= 0 else body
        detail = _collapse_spaces(body[colon + 1 :]) if colon >= 0 else None

        folded = name.lower()
        if "locked" in folded:
            mode = SmartClockMode.LOCKED
        elif "recovery" in folded:
            mode = SmartClockMode.RECOVERY
        elif "holdover" in folded:
            mode = SmartClockMode.HOLDOVER
        elif "power" in folded:
            mode = SmartClockMode.POWER_UP
        else:
            mode = SmartClockMode.UNKNOWN

        return mode, (detail or None)

    return SmartClockMode.UNKNOWN, None


# ---------------------------------------------------------------------------------------------
# Satellite table
# ---------------------------------------------------------------------------------------------


def _parse_satellite_table(
    lines: list[str], warnings: list[str]
) -> tuple[tuple[TrackedSatellite, ...], tuple[PredictedSatellite, ...], SignalStrengthKind]:
    """Parse the acquisition table into its tracked and not-tracked halves, deriving every column
    boundary from the header row (§11.1)."""
    header_index = _find_header_row(lines)
    if header_index < 0:
        warnings.append(
            "No satellite table header row was found; the acquisition table was skipped."
        )
        return (), (), SignalStrengthKind.UNKNOWN

    groups = _build_column_groups(lines[header_index])
    if not groups:
        warnings.append("The satellite table header carried no usable columns.")
        return (), (), SignalStrengthKind.UNKNOWN

    # A group that has a signal-strength column is a tracking group; one that has none is a
    # prediction group, because an untracked satellite has no signal to report. That structural
    # difference is what identifies the halves without depending on their order, and §11.1's
    # "count the PRN occurrences" falls out of it: any number of groups on either side works.
    kind = SignalStrengthKind.UNKNOWN
    for group in groups:
        if group.strength_label is not None:
            kind = _strength_kind_for(group.strength_label)
            break

    tracked: list[TrackedSatellite] = []
    not_tracked: list[PredictedSatellite] = []

    for line in lines[header_index + 1 :]:
        if _is_section_boundary(line):
            break

        for group in groups:
            prn_text = group.prn.slice(line)

            # The receiver marks a satellite it is trying to acquire with a leading asterisk, and
            # says so in the screen's own legend: "*attempting to track". Parsed as a plain
            # integer that row yields None and the satellite is dropped — so a power-up screen
            # reporting "Not Tracking: 10" produced five, because five of the ten were starred
            # (#4). The marker is a fact about the satellite, not noise: it is kept.
            attempting = prn_text is not None and prn_text.lstrip().startswith("*")
            prn = parse_integer(
                prn_text.lstrip().lstrip("*") if attempting and prn_text else prn_text
            )
            if prn is None:
                continue

            elevation = parse_integer(group.elevation.slice(line) if group.elevation else None)
            azimuth = parse_integer(group.azimuth.slice(line) if group.azimuth else None)

            if group.strength_label is None:
                not_tracked.append(
                    PredictedSatellite(
                        prn=prn,
                        elevation_degrees=elevation,
                        azimuth_degrees=azimuth,
                        attempting_to_track=attempting,
                    )
                )
            else:
                tracked.append(
                    TrackedSatellite(
                        prn=prn,
                        elevation_degrees=elevation,
                        azimuth_degrees=azimuth,
                        signal_strength=parse_integer(
                            group.strength.slice(line) if group.strength else None
                        ),
                    )
                )

    _cross_check_counts(lines, len(tracked), len(not_tracked), warnings)
    return tuple(tracked), tuple(not_tracked), kind


def _find_header_row(lines: list[str]) -> int:
    """The header row is the first line carrying a ``PRN`` token.

    Searching for the token rather than for a whole-line pattern is what allows the row to also
    carry the right-hand panel's text, which it does on every real screen.
    """
    for index, line in enumerate(lines):
        for token in _tokenize(line):
            if token.text.lower() == "prn":
                return index
    return -1


def _build_column_groups(header_line: str) -> list[_ColumnGroup]:
    """Derive the column groups from the header row's token positions.

    Each field runs from one past the previous column's last character to its own last character.
    Extending leftwards into the gap rather than using the header token's own extent is what
    handles a value wider than its label — a three-digit azimuth under ``Az`` is the case that
    occurs on every screen with a satellite east or west of the receiver, and slicing the header's
    two characters would silently read 219 as 19.
    """
    groups: list[_ColumnGroup] = []
    tokens = _tokenize(header_line)

    # Where the previous column ended, so the next one knows how far left it may reach. Starts at
    # -1 so the very first column's field begins at index 0.
    previous_end = -1

    index = 0
    while index < len(tokens):
        if tokens[index].text.lower() != "prn":
            index += 1
            continue

        prn = _FieldExtent(previous_end + 1, tokens[index].end)
        previous_end = tokens[index].end

        elevation: _FieldExtent | None = None
        azimuth: _FieldExtent | None = None
        strength: _FieldExtent | None = None
        strength_label: str | None = None

        following = index + 1
        while following < len(tokens):
            text = tokens[following].text
            folded = text.lower()
            if folded not in _COLUMN_LABELS:
                # Not a column label, so the group has ended and this token belongs to the
                # right-hand panel. Stop rather than skip: scanning on would let a stray word
                # that happens to read "SS" pull the panel into the table.
                break

            extent = _FieldExtent(previous_end + 1, tokens[following].end)
            previous_end = tokens[following].end

            if folded in _STRENGTH_LABELS:
                strength = extent
                strength_label = text
            elif folded.startswith("el"):
                elevation = extent
            else:
                azimuth = extent

            following += 1

        groups.append(_ColumnGroup(prn, elevation, azimuth, strength, strength_label))
        index = following

    return groups


def _cross_check_counts(
    lines: list[str], tracked: int, not_tracked: int, warnings: list[str]
) -> None:
    """Compare the parsed row counts against the ``Tracking:`` and ``Not Tracking:`` figures the
    receiver prints above the table, and record a warning if they disagree.

    The counts are the receiver's own view, so a mismatch means the column model has slipped on
    this firmware revision — exactly the failure §11.1's header-relative rule exists to prevent,
    and worth surfacing in Diagnostics rather than discovering from a wrong sky plot.
    """
    declared_tracked = _find_integer(lines, _TRACKING_COUNT)
    declared_not_tracked = _find_integer(lines, _NOT_TRACKING_COUNT)

    if declared_tracked is not None and declared_tracked != tracked:
        warnings.append(
            f"The screen reported {declared_tracked} tracked satellites but {tracked} rows parsed."
        )

    if declared_not_tracked is not None and declared_not_tracked != not_tracked:
        warnings.append(
            f"The screen reported {declared_not_tracked} satellites not tracked but "
            f"{not_tracked} rows parsed."
        )


def _strength_kind_for(label: str) -> SignalStrengthKind:
    return (
        SignalStrengthKind.SIGNAL_STRENGTH
        if label.lower() == "ss"
        else SignalStrengthKind.CARRIER_TO_NOISE
    )


def _is_section_boundary(line: str) -> bool:
    """True for the banner lines that end a section, so table scanning stops at one."""
    trimmed = line.lstrip().lower()
    return trimmed.startswith(_SECTION_BOUNDARIES)


# ---------------------------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------------------------


def _either(match: re.Match[str], first: str, second: str) -> str | None:
    """Whichever of two alternation branches matched. See :data:`_DEVICE_TIME`."""
    return match.group(first) or match.group(second)


def _parse_device_time(
    lines: list[str], warnings: list[str]
) -> tuple[datetime | None, TimeScale, bool]:
    """Read the clock row — a time scale, a time of day, and a date, as in
    ``UTC      14:45:02     27 Dec 2006``.

    Matched on the whole shape rather than on the leading word alone, because ``GPS 1PPS
    Synchronized to UTC`` sits two lines below and starts with a scale name too.
    """
    for line in lines:
        match = _DEVICE_TIME.search(line)
        if match is None:
            continue

        scale_text = _collapse_spaces(match.group("scale")) or ""
        scale = _parse_time_scale(scale_text)

        parsed = _build_instant(
            day=_either(match, "day", "day_last"),
            month=_either(match, "month", "month_last"),
            year=_either(match, "year", "year_first"),
            time_of_day=match.group("time"),
        )
        if parsed is None:
            warnings.append(f"The clock row did not parse as a date and time: '{line.strip()}'.")
            return None, scale, False

        if scale in (TimeScale.LOCAL, TimeScale.LOCAL_GPS):
            # The receiver prints local time without saying what offset produced it, so the
            # instant cannot be reconstructed. The value is kept at face value and the caveat
            # recorded rather than a host-machine offset being invented for it.
            warnings.append(
                "The receiver is reporting local time, so the UTC offset is unknown and zero "
                "was assumed."
            )

        # The marker is carried out with the value rather than warned about. §11.1 puts
        # parse_warnings in Diagnostics, which nobody reads while looking at a clock — and this is
        # a property of the reading that the UI has to show next to it, not a parse problem.
        provisional = match.group("provisional") is not None

        return parsed, scale, provisional

    # A clock row that is present but unreadable is a different report from an absent one, and the
    # difference is the whole value of the warning. §11.1 puts parse_warnings in Diagnostics so a
    # field report about an odd firmware revision is actionable; "no clock row was found" sends
    # the reader looking for a line that is sitting right there in the capture.
    #
    # The case that prompted this was a power-up screen (#245): the receiver prints
    #     GPS      05:10:04 (?) 12 Jan 2007
    # and the (?) between the time and the date used to defeat the full pattern. That row now
    # parses, and the marker is carried on device_time_is_provisional — but this fallback is kept,
    # because the reason it was written has not gone away. A row this loop finds and the full
    # pattern does not is a shape nobody has seen yet, and saying so beats denying the line exists.
    for line in lines:
        if _CLOCK_ROW_SHAPE.search(line):
            warnings.append(
                f"A clock row was found but did not parse: '{line.strip()}'. The time was not read."
            )
            return None, TimeScale.UNKNOWN, False

    warnings.append("No clock row was found on the status screen.")
    return None, TimeScale.UNKNOWN, False


def _build_instant(
    day: str | None, month: str | None, year: str | None, time_of_day: str
) -> datetime | None:
    """Assemble the matched groups into an aware UTC instant, or ``None`` if they do not make one.

    ``None`` covers a month abbreviation outside the table and a date that does not exist — 31
    February matches the pattern perfectly well. C# reports both through the same failed
    ``TryParseExact``.
    """
    if day is None or month is None or year is None:
        return None

    month_number = _MONTHS.get(month.lower())
    if month_number is None:
        return None

    hours, minutes, seconds = time_of_day.split(":")
    try:
        return datetime(
            int(year),
            month_number,
            int(day),
            int(hours),
            int(minutes),
            int(seconds),
            tzinfo=UTC,
        )
    except ValueError:
        return None


def _parse_time_scale(text: str) -> TimeScale:
    folded = text.lower()
    if "local" in folded or "lcl" in folded:
        return TimeScale.LOCAL_GPS if "gps" in folded else TimeScale.LOCAL
    if "utc" in folded:
        return TimeScale.UTC
    if "gps" in folded:
        return TimeScale.GPS
    return TimeScale.UNKNOWN


def _apply_week_rollover(
    device_time: datetime | None, now: datetime
) -> tuple[int, datetime | None]:
    """Apply §7.4's week-rollover correction: if the device's date is close to a whole number of
    1024-week epochs behind the host clock, report how many and what the corrected instant is.

    The correction is reported, never substituted. §7.4 is explicit that the raw device date must
    stay visible, because a user who sees a date two decades out with no explanation reasonably
    concludes the hardware has failed. Time of day and the 1 PPS itself are unaffected.
    """
    if device_time is None:
        return 0, None

    delta = now - device_time
    # Both C#'s Math.Round(double) and Python's round() are banker's rounding, so this needs no
    # adjustment — unlike the coordinate seconds, where C# asks for AwayFromZero explicitly.
    epochs = round(delta / gps_week_rollover.EPOCH)

    if epochs <= 0:
        return 0, device_time

    residual = delta - gps_week_rollover.EPOCH * epochs
    if abs(residual) > gps_week_rollover.TOLERANCE:
        # A large gap that is not a multiple of the epoch is a receiver with the wrong date set,
        # not a rollover, and inventing a correction for it would be worse than showing what the
        # device said.
        return 0, device_time

    return epochs, device_time + gps_week_rollover.EPOCH * epochs


def _parse_clock_advisory(lines: list[str], warnings: list[str]) -> ClockAdvisory:
    """Read the ``1PPS CLK`` advisory and decode it to one of the §11.3 values."""
    for line in lines:
        # The acquisition banner reads "ACQUISITION ... [ GPS 1PPS Valid ]" and would otherwise
        # match first, yielding "Valid ]" as the advisory. Banners are excluded by their brackets,
        # which no panel line carries.
        if _banner_annotation(line) is not None:
            continue

        # The mode row is excluded for the same reason and was found the same way. In holdover it
        # reads ">> Holdover: GPS 1PPS invalid", which this pattern matches and then runs to the
        # end of the line, taking the reference-outputs panel with it — the 28 Aug fixture
        # produced the advisory 'invalid HOLD THR 1.000 us', warned that it was unrecognised, and
        # never reached the real advisory two panels below.
        #
        # Only holdover puts that phrase on the mode row, which is why five earlier fixtures and
        # §11.3's own tests all passed.
        if line.lstrip().startswith(">>"):
            continue

        match = _CLOCK_ADVISORY.search(line)
        if match is None:
            continue

        text = _collapse_spaces(match.group("advisory"))
        if not text:
            continue

        advisory = _classify_advisory(text)
        if advisory is ClockAdvisory.OTHER:
            # §11.3 keeps no string form of the advisory on the model, so this is the only place
            # the device's own wording survives — and it is the only place it is worth having,
            # because an advisory the table does not cover is exactly what a field report about an
            # unfamiliar firmware revision needs to quote.
            warnings.append(f"Unrecognised 1PPS advisory: '{text}'.")

        return advisory

    return ClockAdvisory.NONE


def _classify_advisory(text: str) -> ClockAdvisory:
    # "Assessing stability" animates with nought to three trailing dots on the device's own
    # screen. They carry no information and would otherwise make four distinct strings of one
    # state.
    normalised = text.rstrip(". ").lower()

    if "synchronized to utc" in normalised:
        return ClockAdvisory.SYNCHRONIZED_TO_UTC
    if "synchronized to gps" in normalised:
        return ClockAdvisory.SYNCHRONIZED_TO_GPS_TIME
    if "assessing stability" in normalised:
        return ClockAdvisory.ASSESSING_STABILITY
    if "questionable accuracy" in normalised:
        return ClockAdvisory.QUESTIONABLE_ACCURACY
    if "not tracking" in normalised:
        return ClockAdvisory.INACCURATE_NOT_TRACKING
    if "inacc position" in normalised:
        return ClockAdvisory.INACCURATE_INACCURATE_POSITION
    if "absent or freq error" in normalised:
        return ClockAdvisory.ABSENT_OR_FREQUENCY_ERROR
    if "gps rcvr err" in normalised:
        return ClockAdvisory.INVALID_GPS_RECEIVER_ERROR
    return ClockAdvisory.OTHER


def _parse_leap_pending(lines: list[str]) -> LeapSecondPending:
    """Read a pending leap-second announcement.

    No captured screen carries one — they appear a few times a decade — so this matches the label
    and its sign rather than a known full line, and reports :attr:`LeapSecondPending.NONE` when
    there is nothing to read. That is the correct answer on every screen so far.
    """
    for line in lines:
        match = _LEAP_PENDING.search(line)
        if match is not None:
            return LeapSecondPending.MINUS if match.group("sign") == "-" else LeapSecondPending.PLUS

    return LeapSecondPending.NONE


# ---------------------------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------------------------


def _parse_position(
    lines: list[str], warnings: list[str]
) -> tuple[GeoPosition | None, HeightDatum]:
    """Read latitude, longitude and height, converting the receiver's degrees-minutes-seconds
    into the signed decimal degrees every consumer wants."""
    latitude: float | None = None
    longitude: float | None = None
    height: float | None = None
    datum = HeightDatum.UNKNOWN
    saw_any = False

    for line in lines:
        angle = _ANGLE.search(line)
        if angle is not None:
            saw_any = True
            value = _to_decimal_degrees(angle, warnings, line)
            if angle.group("label").lower() == "lat":
                latitude = value
            else:
                longitude = value
            continue

        height_match = _HEIGHT.search(line)
        if height_match is not None:
            saw_any = True
            metres = parse_decimal(height_match.group("value"))
            if metres is not None:
                height = metres
            else:
                warnings.append(f"The height did not parse: '{line.strip()}'.")

            qualifier = (height_match.group("datum") or "").lower()
            if "msl" in qualifier:
                datum = HeightDatum.MSL
            elif "gps" in qualifier:
                datum = HeightDatum.GPS_ELLIPSOID
            else:
                datum = HeightDatum.UNKNOWN

    if not saw_any:
        return None, HeightDatum.UNKNOWN

    return (
        GeoPosition(
            latitude_degrees=latitude,
            longitude_degrees=longitude,
            height_metres=height,
        ),
        datum,
    )


def _to_decimal_degrees(match: re.Match[str], warnings: list[str], line: str) -> float | None:
    """Convert a matched ``N  47:31:18.822`` into signed decimal degrees."""
    degrees = parse_integer(match.group("deg"))
    minutes = parse_integer(match.group("min"))
    seconds = parse_decimal(match.group("sec"))

    if degrees is None or minutes is None or seconds is None:
        warnings.append(f"The coordinate did not parse: '{line.strip()}'.")
        return None

    magnitude = degrees + minutes / 60.0 + seconds / 3600.0
    hemisphere = match.group("hemisphere").upper()
    return -magnitude if hemisphere in ("S", "W") else magnitude


def _parse_position_mode(
    lines: list[str], warnings: list[str]
) -> tuple[PositionMode, float | None, SurveySuspendedReason]:
    """Read the position mode row and any survey progress or suspension it carries."""
    mode = PositionMode.UNKNOWN
    percent: float | None = None

    for line in lines:
        match = _POSITION_MODE.search(line)
        if match is None:
            continue

        body = match.group("body")
        folded = body.lower()
        if "survey" in folded:
            candidate = PositionMode.SURVEY
        elif "hold" in folded:
            candidate = PositionMode.HOLD
        else:
            # "SmartClock Mode ___..." heads the synchronization panel and matches the label just
            # as well as the position row does. Keep looking rather than stopping on it — the row
            # that names a mode is the one that means anything.
            continue

        mode = candidate

        progress = _PERCENT.search(body)
        if progress is not None:
            value = parse_decimal(progress.group("value"))
            if value is not None:
                percent = value

        break

    return mode, percent, _parse_survey_suspension(lines, warnings)


def _parse_survey_suspension(lines: list[str], warnings: list[str]) -> SurveySuspendedReason:
    for line in lines:
        match = _SUSPENDED.search(line)
        if match is None:
            continue

        text = _collapse_spaces(match.group("reason"))
        if not text:
            continue

        folded = text.lower()
        if "sats" in folded or "track <" in folded:
            reason = SurveySuspendedReason.TOO_FEW_SATELLITES
        elif "geometry" in folded:
            reason = SurveySuspendedReason.POOR_GEOMETRY
        elif "no track data" in folded:
            reason = SurveySuspendedReason.NO_TRACK_DATA
        else:
            reason = SurveySuspendedReason.OTHER
            warnings.append(f"Unrecognised survey suspension: '{text}'.")

        return reason

    return SurveySuspendedReason.NONE


def _find_holdover_duration(lines: list[str]) -> timedelta | None:
    """Read how long the receiver has been degraded, or ``None`` if the screen does not say.

    **This counts holdover and recovery together.** The Z3801A guide says so twice — "the
    duration that the Receiver has been operating in holdover (and recovery)", and "the cumulative
    duration of holdover and recovery operations". So it keeps running after the antenna is
    reconnected, until lock is regained, and a caller must not present it as "time since the
    signal was lost" once the receiver has moved on to recovery.

    ``None`` when absent rather than a zero duration, which is the same distinction the holdover
    view model already draws: a dash says the screen did not report it, and a zero would claim no
    time has passed.
    """
    for line in lines:
        match = _HOLDOVER_DURATION.search(line)
        if match is None:
            continue

        # Routed through parse_integer rather than int(), and the result guarded, because neither
        # conversion is as total as it looks: int() raises above 4300 digits, and timedelta raises
        # OverflowError past 999999999 days. Both are reachable from a corrupted read, and both
        # used to cost the whole screen — the catch-all in StatusScreenParser.parse would discard
        # a perfectly good mode, satellite table and position over one unreadable duration.
        # §11.1's rule is that an unparseable *field* becomes None, so it does.
        def part(name: str, match: re.Match[str] = match) -> int | None:
            captured = match.group(name)
            return 0 if not captured else parse_integer(captured)

        parts = {name: part(name) for name in ("days", "hours", "minutes", "seconds")}
        if any(value is None for value in parts.values()):
            return None

        try:
            return timedelta(
                days=parts["days"] or 0,
                hours=parts["hours"] or 0,
                minutes=parts["minutes"] or 0,
                seconds=parts["seconds"] or 0,
            )
        except OverflowError:
            return None

    return None


def _parse_position_qualifier(lines: list[str]) -> PositionQualifier:
    """Read the position qualifier if the screen states one, in either form the family uses.

    A held position prints no qualifier on this receiver, so :attr:`PositionQualifier.UNKNOWN`
    stays the ordinary result rather than a failure.

    **Two forms, because the parenthesised one is not what the Z3805A prints.** The documented
    form qualifies the value — ``(Average)``, ``(Init)``, ``(Held)`` — and is kept for the models
    that use it. The SmartClock screens captured on 27 Aug 2026 qualify the *label* instead, and
    only while a survey is running::

        holding:    LAT      N  47:31:18.822
        surveying:  AVG LAT  N  47:31:18.640

    ``AVG`` does not match ``Aver\\w*``, so both surveying fixtures in the corpus read as having
    no qualifier at all — the one distinction this function exists to draw, lost on the only
    screens that draw it.
    """
    for line in lines:
        match = _POSITION_QUALIFIER.search(line)
        if match is not None:
            word = match.group("qualifier").lower()
            if word.startswith("init"):
                return PositionQualifier.INIT
            if word.startswith("aver"):
                return PositionQualifier.AVERAGE
            return PositionQualifier.HELD

        if _AVERAGED_POSITION_LABEL.search(line):
            return PositionQualifier.AVERAGE

    return PositionQualifier.UNKNOWN


# ---------------------------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------------------------


def _parse_health_items(lines: list[str], warnings: list[str]) -> Mapping[str, bool]:
    """Read the health item list, which the receiver prints as label-and-verdict pairs on one or
    more lines below the health banner.

    Pairs are separated by runs of two or more spaces while labels contain single spaces ("Self
    Test", "Int Pwr"), so the run length is what splits them. The labels are kept as the device
    spells them rather than mapped onto a fixed set of fields: the list differs across the family,
    and an item this build has never seen must still reach the Diagnostics page.
    """
    items: dict[str, bool] = {}
    #: Folded label against the spelling first seen, so a second mention of an item differing only
    #: in case updates the original entry instead of adding a second one. That is what C#'s
    #: ``Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase)`` does for free.
    seen: dict[str, str] = {}

    banner_index = -1
    for index, line in enumerate(lines):
        if line.lstrip().lower().startswith("health monitor"):
            banner_index = index
            break

    if banner_index < 0:
        return MappingProxyType(items)

    for line in lines[banner_index + 1 :]:
        if not line.strip():
            continue

        for chunk in _PAIR_SEPARATOR.split(line.strip()):
            colon = chunk.find(":")
            if colon <= 0:
                continue

            label = chunk[:colon].strip()
            verdict = chunk[colon + 1 :].strip()
            if not label or not verdict:
                continue

            ok = verdict.lower() == "ok"
            if not ok and verdict.lower() not in _KNOWN_FAILURE_VERDICTS:
                warnings.append(
                    f"Unrecognised health verdict '{verdict}' for '{label}'; treated as a failure."
                )

            key = seen.setdefault(label.lower(), label)
            items[key] = ok

    return MappingProxyType(items)


# ---------------------------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------------------------


def _find_integer(lines: list[str], pattern: re.Pattern[str]) -> int | None:
    """The integer group of the first line matching *pattern*."""
    for line in lines:
        match = pattern.search(line)
        if match is not None:
            value = parse_integer(match.group("value"))
            if value is not None:
                return value

    return None


def _find_scaled_value(
    lines: list[str], pattern: re.Pattern[str], *, nanoseconds: bool
) -> float | None:
    """The value of the first line matching *pattern*, converted using the unit printed beside it.

    The unit is read rather than assumed because the receiver switches it with the magnitude: the
    same holdover field reads ``2.5 us`` on one screen and ``1.4 ms`` on another, and a fixed
    scale factor would be wrong by a thousand exactly when the number matters most.
    """
    for line in lines:
        match = pattern.search(line)
        if match is None:
            continue

        value = parse_decimal(match.group("value"))
        if value is None:
            continue

        seconds = _to_seconds(value, match.group("unit"))
        if seconds is None:
            continue

        return seconds * 1e9 if nanoseconds else seconds

    return None


def _to_seconds(value: float, unit: str) -> float | None:
    multiplier = _UNIT_SECONDS.get(unit.strip().lower())
    return None if multiplier is None else value * multiplier


# ---------------------------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------------------------


def _tokenize(line: str) -> list[_Token]:
    """Split a line into whitespace-delimited tokens, keeping each one's character extent."""
    tokens: list[_Token] = []
    index = 0

    while index < len(line):
        if line[index].isspace():
            index += 1
            continue

        start = index
        while index < len(line) and not line[index].isspace():
            index += 1

        tokens.append(_Token(line[start:index], start, index - 1))

    return tokens


def _cut_at_wide_gap(text: str) -> str:
    """The text up to the first run of three or more spaces, which is how the screen separates two
    side-by-side panels sharing a physical line."""
    gap = _WIDE_GAP.search(text)
    return text[: gap.start()] if gap else text


def _collapse_spaces(text: str | None) -> str | None:
    """Trim a value and reduce internal whitespace runs to single spaces."""
    return None if text is None else _WHITESPACE_RUN.sub(" ", text).strip()
