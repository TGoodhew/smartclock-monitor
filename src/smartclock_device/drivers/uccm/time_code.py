"""The UCCM's 44-byte time code, decoded as far as the captures establish and no further (D7).

A UCCM-P broadcasts one of these every two seconds, unasked. `transport/frames.py` lifts them out
of the byte stream; this reads them.

**Five of the forty-four bytes mean anything this port can defend**, and that number is a finding
rather than a limitation of effort. `transitions-13sep2026` is the only capture of this family in
any state but locked-and-settled — every earlier sitting caught a module that had been up for hours
on a good antenna, so forty of the forty-four bytes never moved and the corpus could say nothing
about what any of them meant. Offsets 1–26 and 37–40 were constant across all 785 frames and remain
unknown; they are not guessed at here.

**The trailing pair is a checksum and is not read.** Offsets 41–42 are uniform over the full 16-bit
range with a mean consecutive delta of 21,861 against 21,845 predicted for independent uniform
draws — the signature of a checksum output. Thirty standard constructions fail against all 285
frames tested, and the function is not affine over GF(2), which excludes every CRC. So the frame is
**not** checksum-validated here: a validator that always rejects is worse than none.

**Never raises** (§11.1). A frame that is not the right shape decodes to ``None``.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final

from smartclock_device.transport.frames import END, LENGTH, START

#: Where the seconds counter sits, big-endian, four bytes.
#:
#: Confirmed twice independently: once by the 12 Sep sitting, and again by `transitions-13sep2026`,
#: whose frames agree with their own capture timestamps **to the second** once the retained leap
#: offset is applied in the right direction.
_SECONDS: Final = slice(27, 31)

#: The five bytes that move, and what each one is.
_LEAP: Final = 32
_PPS: Final = 33
_ANTENNA: Final = 34
_LOCK: Final = 35
_DATE: Final = 36

#: GPS time zero. The counter is seconds since this, on the GPS scale.
GPS_EPOCH: Final = datetime(1980, 1, 6, tzinfo=UTC)

#: What the counter reads when the module has never had a fix: a fixed base plus seconds since
#: power-up. Recorded because a reader who does not know it would take a 1999 timestamp for a
#: decoding error rather than for the receiver saying "I do not know what time it is".
NO_FIX_BASE: Final = datetime(1999, 8, 22, tzinfo=UTC)


class PpsState(enum.Enum):
    """Offset 33. `41` while the phase is settling, `60` once it is stable."""

    UNKNOWN = "unknown"
    SETTLING = "settling"
    STABLE = "stable"


class AntennaState(enum.Enum):
    """Offset 34, and the one byte where this bench's capture found a value nobody had recorded."""

    UNKNOWN = "unknown"

    #: `00` at power-up, and again on a cold reconnect before the module has validated it.
    STARTING = "starting"

    #: `04`, the ordinary good-antenna value.
    GOOD = "good"

    #: `0C`, open or shorted.
    FAULT = "open or shorted"

    #: `08` — **powered up with no antenna attached.** In neither Lady Heather's list nor the
    #: sibling's until this sitting produced it. The two reconnects took different paths and the
    #: difference is the finding: from cold the byte went `08 → 00 → 04` over about three minutes,
    #: while from holdover it went `0C → 04` at once.
    ABSENT_SINCE_POWER_UP = "absent since power-up"


class UccmState(enum.Enum):
    """What the module is doing, as the five bytes settle it."""

    UNKNOWN = "unknown"

    #: No leap offset yet, so it has never had a fix since power-up.
    COLD = "cold"

    #: It has had a fix — the leap offset is present — and the phase is still settling.
    ACQUIRING = "acquiring"

    #: Locked.
    LOCKED = "locked"

    #: **It had a fix and has lost it.** Leap present and PPS stable say it had one; the lock byte
    #: says it does not now.
    HOLDOVER = "holdover"


#: Offset 33.
_PPS_STATES: Final[dict[int, PpsState]] = {0x41: PpsState.SETTLING, 0x60: PpsState.STABLE}

#: Offset 34.
_ANTENNA_STATES: Final[dict[int, AntennaState]] = {
    0x00: AntennaState.STARTING,
    0x04: AntennaState.GOOD,
    0x08: AntennaState.ABSENT_SINCE_POWER_UP,
    0x0C: AntennaState.FAULT,
}

#: Offset 35. `45` is locked; `4F` is not.
_LOCKED: Final = 0x45

#: Offset 36. `80` is a valid date; `90` is not.
_DATE_VALID: Final = 0x80


@dataclass(frozen=True, slots=True)
class UccmTimeCode:
    """One decoded frame, carrying only what the corpus establishes."""

    #: Offset 32 as a count of seconds — `0x12` is 18, the current GPS − UTC offset.
    #:
    #: ``None`` before the module has a fix, where the byte reads `00`. That is the *absence* of an
    #: offset rather than an offset of zero, and the two must not render the same.
    leap_seconds: int | None

    pps: PpsState
    antenna: AntennaState
    locked: bool
    date_valid: bool

    #: Seconds since :data:`GPS_EPOCH`, on the GPS scale.
    gps_seconds: int

    @property
    def state(self) -> UccmState:
        """What the five bytes together say, which the text screen does not.

        **Holdover is invisible to the text and plain in the bytes**, and that is the whole reason
        this decoder exists: fourteen minutes with no antenna and the module never degraded TFOM or
        FFOM past 2, never moved off `UCCM A Status[ACTIVE]`, and answered `LED:GPSL?` with `1`
        throughout. The sibling shipped a coasting module reported as *Locked to GPS* because the
        lock byte alone cannot tell holdover from lock and nothing else was being read (#534).
        """
        if self.locked:
            return UccmState.LOCKED
        if self.leap_seconds is None:
            return UccmState.COLD
        if self.pps is PpsState.STABLE:
            # Leap present and phase stable: it had a fix. Not locked now: it has lost it.
            return UccmState.HOLDOVER
        return UccmState.ACQUIRING

    @property
    def gps_time(self) -> datetime:
        """The counter as an instant on the **GPS** scale, which is not UTC."""
        return GPS_EPOCH + timedelta(seconds=self.gps_seconds)

    @property
    def utc_time(self) -> datetime | None:
        """The same instant on UTC, or ``None`` before the module knows the offset.

        Subtracting nothing would be an error of eighteen seconds presented as a fact, which is
        precisely the kind of silent wrongness a timing application must not produce.
        """
        if self.leap_seconds is None:
            return None
        return self.gps_time - timedelta(seconds=self.leap_seconds)

    @property
    def has_ever_had_a_fix(self) -> bool:
        """Whether the module has had one since power-up, which the leap offset settles."""
        return self.leap_seconds is not None


def decode(frame: bytes) -> UccmTimeCode | None:
    """One frame to a time code, or ``None`` if it is not one. **Never raises.**"""
    if len(frame) != LENGTH or frame[0] != START or frame[-1] != END:
        return None

    leap = frame[_LEAP]
    return UccmTimeCode(
        leap_seconds=None if leap == 0 else leap,
        pps=_PPS_STATES.get(frame[_PPS], PpsState.UNKNOWN),
        antenna=_ANTENNA_STATES.get(frame[_ANTENNA], AntennaState.UNKNOWN),
        locked=frame[_LOCK] == _LOCKED,
        date_valid=frame[_DATE] == _DATE_VALID,
        gps_seconds=int.from_bytes(frame[_SECONDS], "big"),
    )
