"""The UCCM time code, against the only sitting that ever saw this family move (D7, #63).

`transitions-13sep2026` is **the first capture of this family in any state other than locked and
settled**. Every earlier sitting caught a module that had been up for hours on a good antenna, so
forty of the forty-four bytes never moved and the corpus could say nothing about what any of them
meant. Everything asserted here traces to that sitting's own notes, which record what was done to
the receiver and when.

Nobody here has a UCCM.
"""

from __future__ import annotations

import collections
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest

from smartclock_device.drivers.uccm.time_code import (
    NO_FIX_BASE,
    AntennaState,
    PpsState,
    UccmState,
    decode,
)
from smartclock_device.transport.frames import LENGTH

CAPTURES: Final = Path(__file__).parent / "fixtures" / "uccm"

#: The eight state-byte combinations the sitting recorded, with the counts it observed.
#:
#: Written out because they are the evidence, and a test that regenerated them from the capture
#: would agree with whatever the capture said rather than with what was read off it that day.
OBSERVED: Final = {
    (0x00, 0x41, 0x08, 0x4F, 0x90): ("cold, antenna never present since power-up", 111),
    (0x00, 0x41, 0x00, 0x4F, 0x90): ("antenna just reconnected, not yet validated", 64),
    (0x12, 0x60, 0x0C, 0x4F, 0x90): ("TRUE HOLDOVER", 462),
    (0x12, 0x41, 0x04, 0x4F, 0x80): ("acquiring, PPS still settling", 50),
    (0x12, 0x60, 0x04, 0x45, 0x80): ("locked", 59),
    (0x12, 0x41, 0x00, 0x4F, 0x80): ("transitional", 25),
    (0x12, 0x60, 0x04, 0x4F, 0x90): ("the first ten seconds of holdover", 9),
    (0x00, 0x41, 0x00, 0x4F, 0x80): ("transitional", 5),
}


def frames() -> tuple[bytes, ...]:
    """Every frame the transitions sitting recorded, decoded from the hex it wrote them as."""
    found = []
    for raw in (
        (CAPTURES / "transitions-13sep2026.frames.txt").read_text(encoding="ascii").splitlines()
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # The file timestamps each frame; the hex is the trailing field.
        hexes = "".join(part for part in line.split() if len(part) == 2 and _is_hex(part))
        if len(hexes) == LENGTH * 2:
            found.append(bytes.fromhex(hexes))
    return tuple(found)


def _is_hex(token: str) -> bool:
    try:
        int(token, 16)
    except ValueError:
        return False
    return True


def a_frame(leap: int, pps: int, antenna: int, lock: int, date: int) -> bytes:
    """One synthetic frame carrying the five bytes that mean anything.

    Synthetic rather than drawn from the capture **only for the state table**, so a combination the
    sitting saw five times is tested as firmly as one it saw 462 times. The capture itself is
    replayed separately.
    """
    body = bytearray(b"\x00" * LENGTH)
    body[0], body[-1] = 0xC5, 0xCA
    body[32], body[33], body[34], body[35], body[36] = leap, pps, antenna, lock, date
    return bytes(body)


def test_the_capture_holds_the_frames_these_tests_read() -> None:
    """Guarding the guard. A file that stopped parsing would leave every test below vacuous."""
    assert len(frames()) > 700, "the sitting recorded 785 frames"
    assert all(len(f) == LENGTH for f in frames())


def test_every_frame_in_the_sitting_decodes() -> None:
    assert all(decode(f) is not None for f in frames())


def test_the_eight_combinations_the_sitting_saw_are_all_present() -> None:
    """And no ninth. A combination this port cannot classify would be a gap worth knowing about."""
    seen = collections.Counter((f[32], f[33], f[34], f[35], f[36]) for f in frames())

    assert set(seen) == set(OBSERVED), "the sitting's own table has eight rows and no more"


@pytest.mark.parametrize(
    ("bytes_", "expected"),
    [
        ((0x12, 0x60, 0x04, 0x45, 0x80), UccmState.LOCKED),
        ((0x12, 0x60, 0x0C, 0x4F, 0x90), UccmState.HOLDOVER),
        ((0x12, 0x60, 0x04, 0x4F, 0x90), UccmState.HOLDOVER),
        ((0x12, 0x41, 0x04, 0x4F, 0x80), UccmState.ACQUIRING),
        ((0x00, 0x41, 0x08, 0x4F, 0x90), UccmState.COLD),
        ((0x00, 0x41, 0x00, 0x4F, 0x90), UccmState.COLD),
    ],
)
def test_the_state_each_combination_means(bytes_: tuple[int, ...], expected: UccmState) -> None:
    code = decode(a_frame(*bytes_))

    assert code is not None
    assert code.state is expected


def test_holdover_is_invisible_to_the_text_and_plain_in_the_bytes() -> None:
    """**The misreading #534 corrected, and the reason this decoder exists at all.**

    Fourteen minutes with no antenna: the module never degraded TFOM or FFOM past 2, never moved
    off `UCCM A Status[ACTIVE]`, and answered `LED:GPSL?` with `1` throughout. The lock byte alone
    cannot tell holdover from lock — `4F` is simply *not locked*, which a cold module also reads.
    What separates them is that a coasting module **has** a leap offset and a stable phase.
    """
    holdover = decode(a_frame(0x12, 0x60, 0x0C, 0x4F, 0x90))
    cold = decode(a_frame(0x00, 0x41, 0x08, 0x4F, 0x90))

    assert holdover is not None and cold is not None
    assert holdover.locked is False and cold.locked is False, "the lock byte agrees on both"
    assert holdover.state is UccmState.HOLDOVER
    assert cold.state is UccmState.COLD
    assert holdover.has_ever_had_a_fix is True
    assert cold.has_ever_had_a_fix is False


def test_the_leap_offset_is_absent_rather_than_zero_before_a_fix() -> None:
    """`00` is the *absence* of an offset, not an offset of zero, and they must not render alike."""
    cold = decode(a_frame(0x00, 0x41, 0x08, 0x4F, 0x90))
    locked = decode(a_frame(0x12, 0x60, 0x04, 0x45, 0x80))

    assert cold is not None and locked is not None
    assert cold.leap_seconds is None
    assert locked.leap_seconds == 18, "0x12 is decimal 18, the current GPS − UTC offset"


def test_utc_is_none_until_the_offset_is_known() -> None:
    """Subtracting nothing would be an error of eighteen seconds presented as a fact."""
    cold = decode(a_frame(0x00, 0x41, 0x08, 0x4F, 0x90))

    assert cold is not None
    assert cold.utc_time is None
    assert cold.gps_time is not None, "the GPS-scale reading is still real"


def test_the_antenna_value_nobody_had_recorded() -> None:
    """`08`, powered up with no antenna attached — in neither Lady Heather's list nor the
    sibling's until this sitting produced it."""
    code = decode(a_frame(0x00, 0x41, 0x08, 0x4F, 0x90))

    assert code is not None
    assert code.antenna is AntennaState.ABSENT_SINCE_POWER_UP


def test_an_unrecorded_byte_value_is_unknown_rather_than_guessed() -> None:
    """D7: where the corpus is silent, so is this driver."""
    code = decode(a_frame(0x12, 0x77, 0x99, 0x4F, 0x80))

    assert code is not None
    assert code.pps is PpsState.UNKNOWN
    assert code.antenna is AntennaState.UNKNOWN


def test_the_seconds_counter_agrees_with_the_sitting_s_own_timestamps() -> None:
    """The sitting checked two frames against their capture timestamps and they agreed to the
    second. That is what confirms offsets 27–30, the byte order and the epoch — independently of
    the sitting that first established them."""
    # 0 delimiter, 1-26 constant, 27-30 counter, 31 constant, 32-36 state, 37-42 constant, 43 end.
    holdover = bytes.fromhex("C5" + "00" * 26 + "57D0B062" + "00" + "12600C4F90" + "00" * 6 + "CA")
    assert len(holdover) == LENGTH, "the frame layout in this test must match the real one"

    code = decode(holdover)

    assert code is not None
    assert code.gps_time == datetime(2026, 9, 13, 0, 27, 14, tzinfo=UTC)
    assert code.utc_time == datetime(2026, 9, 13, 0, 26, 56, tzinfo=UTC)


def test_with_no_fix_the_counter_reads_from_a_1999_base() -> None:
    """Recorded because a reader who does not know it takes a 1999 timestamp for a decoding error
    rather than for the receiver saying it does not know what time it is."""
    first_after_power = bytes.fromhex(
        "C5" + "00" * 26 + "24EA0002" + "00" + "0041084F90" + "00" * 6 + "CA"
    )

    code = decode(first_after_power)

    assert code is not None
    assert code.gps_time == NO_FIX_BASE + timedelta(seconds=2), (
        "two seconds past the base, which is exactly what the sitting recorded"
    )
    assert code.utc_time is None, "and it still does not know the offset"


@pytest.mark.parametrize("bad", [b"", b"\xc5", b"\xc5" + b"\x00" * 42, b"\x00" * LENGTH])
def test_anything_that_is_not_a_frame_decodes_to_none(bad: bytes) -> None:
    """§11.1: never raises."""
    assert decode(bad) is None


def test_the_checksum_pair_is_not_validated() -> None:
    """Thirty standard constructions fail against all 285 frames tested, and the function is not
    affine over GF(2), which excludes every CRC. **A validator that always rejects is worse than
    none**, so the frame is decoded on its shape and its delimiters alone."""
    tampered = bytearray(a_frame(0x12, 0x60, 0x04, 0x45, 0x80))
    tampered[41] = (tampered[41] + 1) & 0xFF

    assert decode(bytes(tampered)) is not None, "a frame is not rejected on a checksum nobody has"


# ---- Through the driver -------------------------------------------------------------------------


def a_driver() -> object:
    from smartclock_device.clock import FixedClock
    from smartclock_device.drivers.uccm import UccmDriver

    return UccmDriver(clock=FixedClock(datetime(2026, 9, 13, tzinfo=UTC)))


def test_the_screen_alone_cannot_say_what_the_module_is_doing() -> None:
    """Which is the point of the decoder, restated where the driver joins the two together."""
    from smartclock_device.models.receiver_status import SmartClockMode
    from smartclock_device.transport.transaction import Transaction, TransactionOutcome

    driver = a_driver()
    screen = Transaction(
        command="SYST:STAT?", outcome=TransactionOutcome.COMPLETED, lines=("UCCM A Status[ACTIVE]",)
    )

    from_screen = driver.parse_full(screen, None)  # type: ignore[attr-defined]

    assert from_screen.mode is SmartClockMode.UNKNOWN, "the text is silent about holdover"


@pytest.mark.parametrize(
    ("state_bytes", "expected"),
    [
        ((0x12, 0x60, 0x04, 0x45, 0x80), "LOCKED"),
        ((0x12, 0x60, 0x0C, 0x4F, 0x90), "HOLDOVER"),
        ((0x12, 0x41, 0x04, 0x4F, 0x80), "RECOVERY"),
        ((0x00, 0x41, 0x08, 0x4F, 0x90), "RECOVERY"),
    ],
)
def test_the_time_code_is_what_fills_the_mode_in(
    state_bytes: tuple[int, ...], expected: str
) -> None:
    from smartclock_device.models.receiver_status import ReceiverStatus

    driver = a_driver()
    blank = ReceiverStatus(captured_at=datetime(2026, 9, 13, tzinfo=UTC))

    folded = driver.apply_time_code(blank, a_frame(*state_bytes))  # type: ignore[attr-defined]

    assert folded.mode.name == expected


def test_a_coasting_module_is_not_reported_as_locked() -> None:
    """**The shipped misreading #534 corrected, asserted end to end.**"""
    from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode

    driver = a_driver()
    blank = ReceiverStatus(captured_at=datetime(2026, 9, 13, tzinfo=UTC))

    folded = driver.apply_time_code(blank, a_frame(0x12, 0x60, 0x0C, 0x4F, 0x90))  # type: ignore[attr-defined]

    assert folded.mode is SmartClockMode.HOLDOVER
    assert folded.gps_one_pps_valid is False, "a coasting module's 1 PPS is not GPS-valid"


def test_a_frame_that_does_not_decode_leaves_the_status_alone() -> None:
    """§11.1: a bad frame is not a reason to replace good readings with worse ones."""
    from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode

    driver = a_driver()
    known = ReceiverStatus(
        captured_at=datetime(2026, 9, 13, tzinfo=UTC), mode=SmartClockMode.LOCKED
    )

    assert driver.apply_time_code(known, b"not a frame") == known  # type: ignore[attr-defined]
