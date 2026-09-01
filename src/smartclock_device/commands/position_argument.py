"""§10.6's nine-part position argument, and the exact text the receiver wants.

**The wire format is a fact that was looked up, not a decision that was taken.** Issue #12 held
this command out of the catalog because neither the specification nor this repository stated how
the nine parts are joined, and §8.3's own confirmation says an incorrect position degrades every
timing solution — so a plausible guess would be either rejected or, worse, accepted and wrong.

It is settled from the sibling implementation, which built and tested it:
``src/WinZ3805A/Views/PositionPage.xaml.cs`` joins the parts with commas, and its own note records
that the separator was the blocker there too (#147) and was resolved the same way — the 58503A
programming guide gives the sibling commands literally, ``:GPS:INITial:DATE <year>,<month>,<day>``,
with worked examples.

    :GPS:POSition N,47,31,18.822,W,122,12,22.152,38.00

**Every number is formatted in the C locale and nothing else.** A comma decimal separator would
split a field in a comma-separated argument, turning one position into ten fields of nonsense that
the receiver would either reject or misread. Python's format mini-language is locale-independent,
which is what makes this safe here; the C# original has to say ``CultureInfo.InvariantCulture`` at
every call site for the same reason.

**Height asserts no datum of its own.** The manual is not consistent with itself: its syntax line
takes a height above mean sea level while its prose puts the position on WGS-84, and the two differ
by the geoid separation — tens of metres across most of the inhabited world. §10.6's #114
correction is that the field states the datum *the receiver itself reported* and asks for the value
on that one, rather than picking a side. Nothing here converts between them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: §10.6's ranges, which are the 58503A manual's own table.
#:
#: Per-field, and deliberately not cross-checked. The receiver is the authority on whether a
#: position is sensible, and a half-version of that judgement here would reject things it accepts.
LATITUDE_DEGREES: Final = (0, 90)
LONGITUDE_DEGREES: Final = (0, 180)
MINUTES: Final = (0, 59)
SECONDS: Final = (0.0, 59.999)
HEIGHT_METRES: Final = (-1000.0, 18000.0)

#: Which way from the equator, and which way from Greenwich.
LATITUDE_HEMISPHERES: Final = ("N", "S")
LONGITUDE_HEMISPHERES: Final = ("E", "W")


@dataclass(frozen=True, slots=True)
class PositionArgument:
    """One position, in the nine parts and the order the receiver wants them.

    Frozen, because a command's argument is a value: something that composed it half-way and then
    mutated it is a bug that reaches the wire.
    """

    latitude_hemisphere: str
    latitude_degrees: int
    latitude_minutes: int
    latitude_seconds: float

    longitude_hemisphere: str
    longitude_degrees: int
    longitude_minutes: int
    longitude_seconds: float

    #: On whatever datum the receiver reported. See the module docstring.
    height_metres: float

    def is_valid(self) -> bool:
        """Whether every part is one the receiver's own table permits."""
        return self.rendered() is not None

    def rendered(self) -> str | None:
        """The argument text, or ``None`` if any part is out of range.

        ``None`` rather than an exception, for the reason §11.1 gives on the way in: a value out of
        range is the ordinary case of somebody typing one, and refusing it is not an error.
        """
        if self.latitude_hemisphere not in LATITUDE_HEMISPHERES:
            return None
        if self.longitude_hemisphere not in LONGITUDE_HEMISPHERES:
            return None

        whole = (
            (self.latitude_degrees, LATITUDE_DEGREES),
            (self.latitude_minutes, MINUTES),
            (self.longitude_degrees, LONGITUDE_DEGREES),
            (self.longitude_minutes, MINUTES),
        )
        for value, (low, high) in whole:
            if not isinstance(value, int) or isinstance(value, bool):
                return None
            if not low <= value <= high:
                return None

        fractional = (
            (self.latitude_seconds, SECONDS),
            (self.longitude_seconds, SECONDS),
            (self.height_metres, HEIGHT_METRES),
        )
        for measure, (low_f, high_f) in fractional:
            if isinstance(measure, bool) or not isinstance(measure, int | float):
                return None
            if not low_f <= float(measure) <= high_f:
                return None

        return ",".join(
            (
                self.latitude_hemisphere,
                f"{self.latitude_degrees:d}",
                f"{self.latitude_minutes:d}",
                _seconds(self.latitude_seconds),
                self.longitude_hemisphere,
                f"{self.longitude_degrees:d}",
                f"{self.longitude_minutes:d}",
                _seconds(self.longitude_seconds),
                # Two decimals always, matching the sibling's "0.00". Centimetres are past what any
                # of this can justify, and the receiver takes what it is given.
                f"{float(self.height_metres):.2f}",
            )
        )

    def spoken(self) -> str:
        """The same position in words, for a confirmation dialog and an accessible name.

        Separate from :meth:`rendered` on purpose: what is *sent* is the receiver's format and what
        is *read back* to the user is not. §8.3 requires the consequence in words, and a raw
        comma-separated string is not words.
        """
        return (
            f"{self.latitude_hemisphere} {self.latitude_degrees}° {self.latitude_minutes}′ "
            f"{_seconds(self.latitude_seconds)}″, "
            f"{self.longitude_hemisphere} {self.longitude_degrees}° {self.longitude_minutes}′ "
            f"{_seconds(self.longitude_seconds)}″, "
            f"{float(self.height_metres):.2f} m"
        )


def _seconds(value: float) -> str:
    """Up to three decimals, trailing zeros dropped — the sibling's ``0.###``.

    Three because §10.6's own range stops at 59.999, and a fourth would be precision the field
    cannot express. At this latitude a thousandth of a second of arc is about 30 mm.
    """
    return f"{float(value):.3f}".rstrip("0").rstrip(".")
