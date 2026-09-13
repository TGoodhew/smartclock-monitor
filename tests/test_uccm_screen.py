"""The UCCM status screen, against the sitting it was written from (D7, #63).

`trimble-uccm-p-2026-09-11.txt` is *"the screen `UccmStatusParser` is written against and tested
on"*, in the corpus README's own words. This file reads the same one.

**Nobody here has a UCCM.** Where a field is asserted below, the value comes from that capture. No
field is parsed that the capture does not show, however plausible it would be — that is D7's rule
and it is what keeps this driver honest about being unverified.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from smartclock_device.clock import FixedClock
from smartclock_device.models.position import HeightDatum, PositionMode
from smartclock_device.models.receiver_status import (
    OutputValidity,
    SignalStrengthKind,
    SmartClockMode,
    TimeScale,
)
from smartclock_device.parsing.uccm_screen import UccmScreenParser, counts

CAPTURES: Final = Path(__file__).parent / "fixtures" / "uccm"
NOW: Final = datetime(2026, 9, 13, tzinfo=UTC)

#: The sitting the corpus README names as the one the parser is written against.
SCREEN_CAPTURE: Final = "trimble-uccm-p-2026-09-11"


def screen(name: str = SCREEN_CAPTURE, command: str = "SYST:STAT?") -> str:
    """One reply out of an annotated transcript, as the decoded lines the harness recorded.

    The `---- LINES` block rather than the hex, because the hex is the same bytes and the lines are
    what a reader can check an assertion against. The NUL each line begins with is left in: taking
    it out here would test a screen the receiver never sent.
    """
    text = (CAPTURES / f"{name}.txt").read_text(encoding="latin-1")
    block = text.split(f"==== SENT: {command}")[1].split("---- LINES")[1].split("====")[0]
    rows = [
        match.group(2)
        for line in block.splitlines()
        if (match := re.match(r"\s*\[(Payload|Complete)\]\s?(.*)$", line))
    ]
    return "\r\n".join(rows)


def parsed(name: str = SCREEN_CAPTURE):  # type: ignore[no-untyped-def]
    return UccmScreenParser(FixedClock(NOW)).parse(screen(name))


def test_the_capture_still_has_the_shape_these_tests_read() -> None:
    """Guarding the guard: every assertion below rests on this block being extractable."""
    text = screen()

    assert "UCCM A Status[ACTIVE]" in text
    assert "Tracking: 7" in text
    assert "\x00" in text, "the NUL line prefix is part of what is being tested"


def test_the_figures_of_merit() -> None:
    status = parsed()

    assert status.tfom == 2
    assert status.ffom == 0


def test_the_antenna_delay_and_elevation_mask() -> None:
    status = parsed()

    assert status.antenna_delay_nanoseconds == 0
    assert status.elevation_mask_degrees == 5


def test_the_one_pps_banner() -> None:
    status = parsed()

    assert status.gps_one_pps_valid is True
    assert status.outputs is OutputValidity.VALID


def test_the_status_token_is_carried_as_the_receiver_s_own_word() -> None:
    """`ACTIVE` is the only value in the corpus — eighteen screens, one value.

    Mapping it onto a meaning would be inventing the other values, so it is carried through as
    text and §9 renders it as the receiver's own word.
    """
    assert parsed().mode_detail == "ACTIVE"


def test_the_mode_is_not_guessed_at() -> None:
    """**The misreading #534 corrected upstream, not repeated here.**

    The header's `mode` field says `LINK`, and what that means is documented nowhere this port can
    cite. The sibling shipped a coasting module reported as *Locked to GPS* because one field was
    read as if it settled the question. A mode this port cannot interpret is `UNKNOWN`.
    """
    assert parsed().mode is SmartClockMode.UNKNOWN


def test_the_clock_is_on_the_gps_scale_and_says_so() -> None:
    """§10.14: saying UTC here would be a silent error of eighteen seconds."""
    assert parsed().time_scale is TimeScale.GPS


def test_the_surveyed_position() -> None:
    """Mt Warrigal, from the sitting's own note: S 34:32:39.019, E 150:50:25.107, +49.72 m MSL."""
    status = parsed()

    assert status.position is not None
    assert status.position.latitude_degrees == pytest.approx(-34.5441719, abs=1e-6)
    assert status.position.longitude_degrees == pytest.approx(150.8403075, abs=1e-6)
    assert status.position.height_metres == pytest.approx(49.72)
    assert status.height_datum is HeightDatum.MSL
    assert status.position_mode is PositionMode.HOLD


def test_the_position_block_is_read_by_the_smartclock_s_own_parser() -> None:
    """Not a second sexagesimal converter. Two would not be wrong in the same way."""
    from smartclock_device.parsing.status_screen import parse_position_block

    direct, _ = parse_position_block(screen().splitlines())

    assert direct is not None
    assert parsed().position == direct


def test_the_satellite_table_matches_the_count_the_screen_prints() -> None:
    """The header is the receiver's own count, so a disagreement is a parser bug rather than a
    receiver one. That is the whole reason both are read."""
    status = parsed()
    tracking, not_tracking = counts(screen())

    assert (tracking, not_tracking) == (7, 4)
    assert len(status.tracked) == tracking
    assert len(status.not_tracked) == not_tracking


def test_the_tracked_satellites_carry_their_readings() -> None:
    status = parsed()

    assert [s.prn for s in status.tracked] == [12, 13, 24, 19, 21, 6, 11]
    first = status.tracked[0]
    assert (first.elevation_degrees, first.azimuth_degrees, first.signal_strength) == (60, 214, 40)
    assert status.signal_strength_kind is SignalStrengthKind.CARRIER_TO_NOISE


def test_the_satellites_in_view_carry_no_strength() -> None:
    """The structural difference that tells the two groups apart, as on the other family's
    screen."""
    status = parsed()

    assert [s.prn for s in status.not_tracked] == [22, 25, 29, 5]
    assert all(not hasattr(s, "signal_strength") for s in status.not_tracked)


def test_the_nul_line_prefix_is_what_made_the_table_unreadable() -> None:
    """The bug this parser had on its first run, pinned so it cannot come back.

    Every line of this screen begins with a NUL — the receiver's own framing, `0D 0A 00`, 26 times
    in one screen. `\\s` does not match it, so every table row failed to parse and a screen whose
    header said seven satellites produced none.

    This is a *different* NUL from the ones inside a `C5`..`CA` time code, which
    `transport/frames.py` removes before any of this runs.
    """
    without_prefix = screen().replace("\x00", "")

    assert len(parsed().tracked) == 7, "the parser must cope with the receiver's own framing"
    assert len(UccmScreenParser(FixedClock(NOW)).parse(without_prefix).tracked) == 7


@pytest.mark.parametrize("text", ["", "   ", "not a screen", "\x00\x00\x00", "Tracking: 7"])
def test_nothing_unreadable_raises(text: str) -> None:
    """§11.1, which binds this family as it binds every other."""
    status = UccmScreenParser(FixedClock(NOW)).parse(text)

    assert status.captured_at == NOW
