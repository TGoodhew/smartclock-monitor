"""Renders decimal degrees back into the degrees–minutes–seconds form the receiver prints.

The parser stores signed decimal degrees, which is what every consumer wants to compute with.
§10.6 shows the position the way the receiver does — ``N 47° 31′ 18.822″`` — because that is the
form a user compares against a survey sheet, a map, or the front panel of another instrument.

**The carry is the whole difficulty.** Rounding seconds to three decimals can produce 60.000,
which must become the next minute rather than being printed; and that carry can cascade into the
degree. Getting it wrong shifts a position by a minute of arc — about 1.8 km of latitude —
silently, in the one field a timing receiver exists to hold fixed.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, NamedTuple

#: U+00B0 DEGREE SIGN.
DEGREE_SIGN: Final = "\N{DEGREE SIGN}"

#: U+2032 PRIME, which is the minute mark. Not an apostrophe.
MINUTE_SIGN: Final = "\N{PRIME}"

#: U+2033 DOUBLE PRIME, which is the second mark. Not a quotation mark.
SECOND_SIGN: Final = "\N{DOUBLE PRIME}"

#: Three decimals, which is what the receiver itself prints.
_QUANTUM: Final = Decimal("0.001")


class DmsParts(NamedTuple):
    """Signed decimal degrees, split into the parts an instrument displays."""

    hemisphere: str
    degrees: int
    minutes: int
    seconds: float


def split(
    value: float | None,
    positive: str,
    negative: str,
    maximum_degrees: int,
) -> DmsParts | None:
    """Split signed decimal degrees into hemisphere, degrees, minutes and seconds.

    :param value: Signed decimal degrees.
    :param positive: The hemisphere letter for a positive value.
    :param negative: The hemisphere letter for a negative value.
    :param maximum_degrees: 90 for latitude, 180 for longitude.
    """
    if not positive or not negative:
        raise ValueError("A hemisphere letter is required for each side.")

    if value is None or not math.isfinite(value):
        return None

    # Zero is on the positive side of the line. There is no "negative zero" hemisphere, and a
    # receiver sitting on the equator or the prime meridian must not flip letters on noise.
    # -0.0 < 0 is False in Python as it is in C#, so this needs no special case — but it is the
    # kind of thing a later "simplification" removes, so the test pins it.
    hemisphere = negative if value < 0 else positive
    magnitude = abs(value)

    whole_degrees = int(magnitude)
    remaining_minutes = (magnitude - whole_degrees) * 60.0
    whole_minutes = int(remaining_minutes)
    seconds = (remaining_minutes - whole_minutes) * 60.0

    # Round first, then carry. Rounding 59.9996 to three decimals gives 60.000, which is not a
    # number of seconds — it is the next minute.
    #
    # Python's round() is banker's rounding: round(0.0005, 3) is 0.0, not 0.001. C# asks for
    # MidpointRounding.AwayFromZero here, and a coordinate rendered a half-millisecond of arc
    # out on every other midpoint would be a quiet, permanent disagreement with the C# build.
    # Decimal with ROUND_HALF_UP is away-from-zero for a magnitude, which this always is.
    seconds = float(Decimal(seconds).quantize(_QUANTUM, rounding=ROUND_HALF_UP))

    if seconds >= 60.0:
        seconds -= 60.0
        whole_minutes += 1

    if whole_minutes >= 60:
        whole_minutes -= 60
        whole_degrees += 1

    # A value past the pole or the antimeridian is not a position this can render honestly.
    # §11.1 forbids raising, so it degrades to "no value" the way an unparsed field does.
    #
    # The comparison has to include the minutes and seconds, not just the whole degrees: 90.5
    # splits into 90 degrees and 30 minutes, which is half a degree past the pole and would
    # otherwise render as a perfectly ordinary-looking "N 90° 30′ 00.000″".
    past_the_limit = whole_degrees > maximum_degrees or (
        whole_degrees == maximum_degrees and (whole_minutes > 0 or seconds > 0)
    )

    return None if past_the_limit else DmsParts(hemisphere, whole_degrees, whole_minutes, seconds)


def latitude(degrees: float | None) -> str | None:
    """Format a latitude, or return ``None`` if there is none.

    :param degrees: Signed decimal degrees, positive north.
    """
    return _format(degrees, "N", "S", maximum_degrees=90)


def longitude(degrees: float | None) -> str | None:
    """Format a longitude, or return ``None`` if there is none.

    :param degrees: Signed decimal degrees, positive east.
    """
    return _format(degrees, "E", "W", maximum_degrees=180)


def _format(value: float | None, positive: str, negative: str, maximum_degrees: int) -> str | None:
    parts = split(value, positive, negative, maximum_degrees)
    if parts is None:
        return None

    # Fixed widths so a column of coordinates stays aligned (§9.5.3): minutes and seconds always
    # carry two integer digits, and the seconds always carry the receiver's own three decimals.
    # Degrees are not padded — they are the significant part.
    return (
        f"{parts.hemisphere} {parts.degrees}{DEGREE_SIGN} "
        f"{parts.minutes:02d}{MINUTE_SIGN} "
        f"{parts.seconds:06.3f}{SECOND_SIGN}"
    )
