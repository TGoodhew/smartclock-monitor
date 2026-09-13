r"""The UCCM status screen (D7, #63).

**Written against somebody else's receiver.** Everything here is read out of
[`tests/fixtures/uccm/`](../../../tests/fixtures/uccm) — seven sittings with a Trimble UCCM-P
captured in WinZ3805A — and D7's rule holds: a field that does not appear in those captures is not
parsed, however plausible it would be.

**Labels, not columns.** The SmartClock parser derives its satellite columns from the position of
tokens in a header row, which is right for a screen whose tables are the whole layout. This screen
is a two-column poster of labelled values — `TFOM     2`, `ANT DLY  0 ns`, `MODE     Hold` — laid
out beside a satellite table, and the corpus has one firmware revision. Keying on labels means a
revision that shifts a column by a space costs nothing, where keying on columns would cost every
field to its right.

**Every line arrives with a NUL in front of it**, and that is the receiver's own framing rather
than corruption: the captured bytes read `0D 0A 00` at every line break, 26 times in one screen.
It is a *different* NUL from the ones inside a `C5`..`CA` time code, which
`transport/frames.py` takes out before any of this runs — those are payload bytes in a binary
packet; these are part of how this receiver terminates a line of text. Both have to be dealt with,
in different places, and conflating them would leave one of the two unhandled.

The first draft of this parser read zero satellites from a screen whose header said seven, because
`\s` does not match a NUL and every table row began with one.

**Never raises** (§11.1). Every field is optional and an unreadable one becomes ``None``.
"""

from __future__ import annotations

import re
from typing import Final

from smartclock_device.clock import Clock
from smartclock_device.models.position import PositionMode
from smartclock_device.models.receiver_status import (
    OutputValidity,
    ReceiverStatus,
    SignalStrengthKind,
    SmartClockMode,
    TimeScale,
)
from smartclock_device.models.satellite import PredictedSatellite, TrackedSatellite
from smartclock_device.parsing.status_screen import parse_position_block

#: The banner the screen prints when the 1 PPS output is good.
#:
#: `ACQUISITION ....[GPS 1PPS Valid]` in every capture. The bracketed token is what is read; the
#: leading word is not, because no capture shows it in any other state and guessing at its other
#: values is exactly what D7 forbids.
_ONE_PPS_VALID: Final = "GPS 1PPS Valid"

#: `UCCM A Status[ACTIVE]`. **ACTIVE is the only value in the corpus** — eighteen screens, one
#: value — so anything else is carried through as text rather than mapped to a meaning nobody here
#: has seen.
_STATUS = re.compile(r"UCCM\s+\w+\s+Status\[([^\]]*)\]")

#: `>> GPS: [phase:+2.1E-08]`, the disciplining phase offset in seconds.
_PHASE = re.compile(r">>\s*GPS:\s*\[phase:\s*([+-]?[0-9.Ee+-]+)\]")


#: A labelled scalar — `TFOM     2`, `FFOM      0`, `ELEV MASK  5 deg`, `ANT DLY  0 ns`.
def _labelled(screen: str, label: str) -> str | None:
    match = re.search(rf"(?m)^.*\b{re.escape(label)}\s+(\S.*?)\s*$", screen)
    return match.group(1) if match else None


def _integer(screen: str, label: str) -> int | None:
    raw = _labelled(screen, label)
    if raw is None:
        return None
    digits = re.match(r"[+-]?\d+", raw.strip())
    return int(digits.group(0)) if digits else None


def _counts(line: str, label: str) -> int | None:
    match = re.search(rf"{re.escape(label)}:\s*(\d+)", line)
    return int(match.group(1)) if match else None


class UccmScreenParser:
    """One status screen to a :class:`ReceiverStatus`. Never raises."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def parse(self, text: str) -> ReceiverStatus:
        """Read what the corpus establishes, and leave the rest ``None``."""
        screen = _readable(text or "")
        lines = screen.splitlines()

        tracked, not_tracked = _satellites(lines)
        position, datum = parse_position_block(lines)

        return ReceiverStatus(
            captured_at=self._clock.utc_now(),
            mode=_mode(screen),
            mode_detail=_status_token(screen),
            outputs=(OutputValidity.VALID if _ONE_PPS_VALID in screen else OutputValidity.UNKNOWN),
            gps_one_pps_valid=_ONE_PPS_VALID in screen,
            tfom=_integer(screen, "TFOM"),
            ffom=_integer(screen, "FFOM"),
            antenna_delay_nanoseconds=_integer(screen, "ANT DLY"),
            elevation_mask_degrees=_integer(screen, "ELEV MASK"),
            tracked=tracked,
            not_tracked=not_tracked,
            # The screen's C/N column is carrier-to-noise in dB-Hz, as the header says outright.
            signal_strength_kind=SignalStrengthKind.CARRIER_TO_NOISE,
            time_scale=_time_scale(screen),
            device_date_time=None,
            corrected_date_time=None,
            position=position,
            position_mode=_position_mode(screen),
            height_datum=datum,
        )


#: The control bytes this receiver puts in its text, which carry no meaning to a reader.
#:
#: NUL is the line prefix described in the module docstring. The rest are swept up with it because
#: a screen is text: any C0 control that is not a line ending is either framing or noise, and
#: neither is a value.
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _readable(text: str) -> str:
    """The screen with its framing bytes taken out and its line endings left alone."""
    return _CONTROL.sub("", text)


def _mode(screen: str) -> SmartClockMode:
    """The disciplining mode, from the header's `mode` field.

    **`LINK` is the only value in the corpus**, and what it means is not documented anywhere this
    port can cite. It is therefore *not* mapped onto `LOCKED`: the sibling shipped a misreading of
    exactly this shape — a coasting module reported as *Locked to GPS* because one byte was read
    as if it settled the question — and #534 is the correction. A mode this port cannot interpret
    is `UNKNOWN`, and §11.1 renders that honestly.
    """
    del screen
    return SmartClockMode.UNKNOWN


def _status_token(screen: str) -> str | None:
    """`ACTIVE`, carried through as the receiver's own word rather than mapped to a meaning."""
    match = _STATUS.search(screen)
    return match.group(1).strip() or None if match else None


def _time_scale(screen: str) -> TimeScale:
    """`GPS` beside the clock, which is a scale and not a decoration.

    §10.14 renders the scale because UTC and GPS differ by the accumulated leap seconds, and this
    screen labels its clock `GPS` outright. Saying UTC would be a silent error of eighteen seconds.
    """
    labelled = re.search(r"(?m)^.*\bGPS\s+\d\d:\d\d:\d\d", screen)
    return TimeScale.GPS if labelled else TimeScale.UNKNOWN


def _position_mode(screen: str) -> PositionMode:
    raw = _labelled(screen, "MODE")
    if raw is None:
        return PositionMode.UNKNOWN
    return PositionMode.HOLD if raw.strip().upper().startswith("HOLD") else PositionMode.UNKNOWN


#: One row of the satellite table: `  12  60 214   40    22   6  58`.
#:
#: The left group is tracked and carries a C/N; the right is in view and does not. That is the same
#: structural difference the SmartClock screen uses, and it is what lets the two be told apart
#: without counting columns.
_ROW = re.compile(r"^\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)(?:\s+(\d+)\s+(\d+)\s+(\d+))?\s*$")


def _satellites(
    lines: list[str],
) -> tuple[tuple[TrackedSatellite, ...], tuple[PredictedSatellite, ...]]:
    """Both column groups, from the rows between the table header and the blank that ends it."""
    tracked: list[TrackedSatellite] = []
    predicted: list[PredictedSatellite] = []

    for line in lines:
        # The right-hand third of the screen is a different table entirely — the Time and Position
        # panel — so a row is only a row up to the point that panel begins.
        row = _ROW.match(line[:46])
        if row is None:
            continue

        tracked.append(
            TrackedSatellite(
                prn=int(row.group(1)),
                elevation_degrees=int(row.group(2)),
                azimuth_degrees=int(row.group(3)),
                signal_strength=int(row.group(4)),
            )
        )
        if row.group(5) is not None:
            predicted.append(
                PredictedSatellite(
                    prn=int(row.group(5)),
                    elevation_degrees=int(row.group(6)),
                    azimuth_degrees=int(row.group(7)),
                )
            )

    return tuple(tracked), tuple(predicted)


def counts(screen: str) -> tuple[int | None, int | None]:
    """What the screen *says* it is tracking, as distinct from how many rows it drew.

    Both are kept because they can disagree, and a disagreement is a parser bug rather than a
    receiver one — the header is the receiver's own count.
    """
    line = next((x for x in screen.splitlines() if "Tracking:" in x), "")
    return _counts(line, "Tracking"), _counts(line, "Not Tracking")
