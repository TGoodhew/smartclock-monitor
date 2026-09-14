"""The time code `:PTIM:TCOD?` answers with, decoded (#113).

**A third account of one instant.** The status screen prints the figures of merit; the status
registers carry the conditions behind them; and this carries both figures again, with the time of
the next 1 PPS and three flags, in twenty-three characters. The sitting under test holds all three,
taken in one pass by `tools/capture_registers.py`, which is what makes "they agree" assertable at
all.

The decode is a citation confirmed two ways. Lady Heather's SCPI decoder reads the message as a
fixed-width sequence (#98); `models/time_code_format.py`, written here from the Z3801A guide months
earlier and without reference to her, records the message lengths as 19 and 23 characters. Those
agree exactly with her field widths. The bench then agrees with both on the two fields it can check
independently — TFOM and FFOM, against `:SYNC:TFOM?`, `:SYNC:FFOM?` and the screen.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Final

import pytest

from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.models.receiver_status import LeapSecondPending, ReceiverStatus
from smartclock_device.models.time_code_format import TimeCodeFormat
from smartclock_device.parsing import time_code
from smartclock_device.parsing.scalars import parse_integer
from smartclock_device.parsing.status_screen import StatusScreenParser
from test_registers_against_screen import transcript

SITTING: Final = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "smartclock"
    / "locked-with-time-code-13sep2026.txt"
)

REPLIES: Final = transcript(SITTING)
MESSAGES: Final = REPLIES[catalog.TIME_CODE.mnemonic]

#: Any instant; nothing here is clock-dependent, and an unpinned one would make a failure depend on
#: the day it ran.
NOW: Final = datetime(2026, 9, 14, 1, 47, tzinfo=UTC)


@pytest.fixture(scope="module")
def screen() -> ReceiverStatus:
    text = "\r\n".join(REPLIES[catalog.STATUS_SCREEN.mnemonic])
    return StatusScreenParser(FixedClock(NOW)).parse(text)


# ---- The sitting -------------------------------------------------------------------------------


def test_the_sitting_holds_a_run_of_messages() -> None:
    """One message proves a decode; a run proves the checksum."""
    assert len(MESSAGES) == 8


def test_the_receiver_is_in_the_format_the_messages_carry() -> None:
    """The format query and the message header are two spellings of one fact, and the page shows
    both because a user comparing them has to recognise them as the same thing."""
    assert REPLIES[catalog.TIME_CODE_FORMAT.mnemonic] == ("F2",)
    assert all(message.startswith("T2") for message in MESSAGES)


def test_every_captured_message_decodes_and_checks_out() -> None:
    for message in MESSAGES:
        code = time_code.from_capture(message)
        assert code.format is TimeCodeFormat.T2, message
        assert code.checksum_ok is True, message
        assert code.when is not None, message
        assert code.tfom is not None and code.ffom is not None, message


def test_the_messages_advance_one_second_at_a_time() -> None:
    """They were asked for back to back and the receiver emits one a second, so a gap would mean a
    message had been missed — which is the failure a decoder built on fixed offsets cannot see."""
    stamps = [time_code.from_capture(message).when for message in MESSAGES]

    assert all(stamp is not None for stamp in stamps)
    gaps = {(b - a).total_seconds() for a, b in pairwise(stamps) if a is not None and b is not None}
    assert gaps == {1.0}


def test_the_checksum_rule_survives_a_carry() -> None:
    """The strongest evidence in the sitting, and the reason a run was captured rather than a pair.

    Consecutive messages usually differ in one digit, so a checksum that merely advanced by one
    would match a counter just as well as a sum. Across ``49`` → ``50`` two digits change and the
    sum goes **down** by eight: `0x47` → `0x3F`. A counter cannot do that.
    """
    at_49 = next(m for m in MESSAGES if m[14:16] == "49")
    at_50 = next(m for m in MESSAGES if m[14:16] == "50")

    assert at_49.endswith("47")
    assert at_50.endswith("3F")
    assert time_code.from_capture(at_49).checksum_ok is True
    assert time_code.from_capture(at_50).checksum_ok is True


# ---- Against the other two accounts ------------------------------------------------------------


def test_the_figures_of_merit_are_the_screen_s(screen: ReceiverStatus) -> None:
    """Three routes to two numbers: the screen's own text, the scalar queries, and the message."""
    code = time_code.from_capture(MESSAGES[0])

    assert code.tfom == screen.tfom
    assert code.ffom == screen.ffom
    assert code.tfom == parse_integer(REPLIES[catalog.TIME_FIGURE_OF_MERIT.mnemonic][0])
    assert code.ffom == parse_integer(REPLIES[catalog.FREQUENCY_FIGURE_OF_MERIT.mnemonic][0])


def test_the_message_carries_the_same_rolled_over_date_as_the_screen(
    screen: ReceiverStatus,
) -> None:
    """**The first independent route to a receiver date this port has had.**

    §7.4's correction was written against the status screen and has only ever been checked against
    it. The message reaches the date through a different query and a different encoding, and it is
    rolled over in exactly the same way — which is what makes the correction a fact about the
    receiver rather than about the screen parser.
    """
    code = time_code.from_capture(MESSAGES[0])
    reported = screen.device_date_time

    assert code.when is not None and reported is not None
    assert code.when.date() == reported.date()
    assert code.when.year == 2007
    # The screen is read first and takes a page and a half at 9600 baud; ten queries follow it.
    assert 0 <= (code.when - reported).total_seconds() <= 120


def test_the_message_agrees_that_the_time_is_valid(screen: ReceiverStatus) -> None:
    """The flag and the screen's ``(?)`` marker are the same claim, and the screen is not marked."""
    code = time_code.from_capture(MESSAGES[0])

    assert code.time_valid is True
    assert screen.device_time_is_provisional is False
    assert code.leap_pending is LeapSecondPending.NONE
    assert code.service_requested is False


# ---- What it does with anything else -----------------------------------------------------------


def test_a_corrupted_checksum_is_reported_and_the_fields_still_decode() -> None:
    """**Reported, not enforced.** A message whose checksum fails is still the receiver's own bytes,
    and dropping it would turn a corrupted read into a missing one — the harder of the two to
    diagnose."""
    code = time_code.parse(MESSAGES[0][:-2] + "FF")

    assert code.checksum_ok is False
    assert code.when is not None
    assert code.tfom is not None


def test_a_message_of_the_wrong_length_is_not_decoded() -> None:
    """Fixed-offset decoding is only safe behind a length check: one character short and every
    field after the gap would be read from its neighbour, which is the failure mode that produces
    confident nonsense rather than a dash."""
    code = time_code.parse(MESSAGES[0][:-1])

    assert code.format is TimeCodeFormat.UNKNOWN
    assert code.when is None
    assert code.notes and "23" in code.notes[0]


def test_an_impossible_date_decodes_to_no_date_and_keeps_the_flags() -> None:
    code = time_code.parse("T2" + "20079931" + "014749" + "30000" + "47")

    assert code.format is TimeCodeFormat.T2
    assert code.when is None
    assert code.tfom == 3
    assert code.notes


def test_a_t1_message_decodes_from_the_documented_structure() -> None:
    """**Constructed, not captured, and the only test here that is.**

    The bench receiver is in T2 and the setter that would change it is deliberately not catalogued
    (§10.14.1), so the T1 path rests on Lady Heather's field widths agreeing with the 19-character
    length this repository recorded from the Z3801A guide. The message below is built to that
    structure with a real checksum, which makes this a test of the decoder and **not** evidence
    about the hardware.
    """
    body = "T1#H" + f"{0x1D6C_2A00:08X}" + "30000"
    message = body + f"{sum(ord(c) for c in body) % 256:02X}"

    code = time_code.from_capture(message)

    assert len(message) == 19
    assert code.format is TimeCodeFormat.T1
    assert code.checksum_ok is True
    assert code.when == time_code.GPS_EPOCH + timedelta(seconds=0x1D6C_2A00)
    assert code.tfom == 3


def test_a_t1_message_without_its_hex_marker_keeps_its_flags_and_loses_its_date() -> None:
    body = "T1XX" + "1D6C2A00" + "30000"
    message = body + f"{sum(ord(c) for c in body) % 256:02X}"

    code = time_code.from_capture(message)

    assert code.format is TimeCodeFormat.T1
    assert code.when is None
    assert code.tfom == 3
    assert any("#H" in note for note in code.notes)


@pytest.mark.parametrize(
    "text",
    [None, "", "   ", "T2", "rubbish", "T3" + "0" * 21, "\x00" * 23, "9" * 23],
    ids=["none", "empty", "spaces", "header-only", "words", "unknown-format", "nulls", "digits"],
)
def test_anything_else_decodes_to_nothing_rather_than_raising(text: str | None) -> None:
    code = time_code.parse(text)

    assert code.when is None
    assert code.tfom is None or code.format is not TimeCodeFormat.UNKNOWN
