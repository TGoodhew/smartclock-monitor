"""NMEA 0183 sentence parsing, to the extent §11.2's model has somewhere to put it.

**This parser never raises**, for the same reason the status-screen parser does not (§11.1): a
talker on a shared bus emits sentences from other devices, at other revisions, sometimes truncated
by a reconnect. A field that will not parse becomes ``None`` and renders as an em dash.

**The checksum is required, and a bad or absent one is refused.** Unlike the SmartClock's
prompt-terminated exchange, there is no framing here beyond ``$…*hh`` — a line that arrived with a
byte flipped looks exactly like a valid line with different numbers in it, and the checksum is the
only thing that says otherwise. Which means a line carrying *no* checksum has nothing saying it is
not that, so it is refused too: accepting one would take in exactly the garbage the check exists to
keep out. Every talker in service sends one.

**What NMEA does not carry, this does not invent.** There is no 1 PPS time interval, no oscillator
EFC, no TFOM or FFOM, no holdover — those are disciplined-oscillator concepts and a GNSS talker has
none of them. §11.1's rule is what makes that safe: every consumer already handles ``None``, so the
pages show dashes rather than plausible numbers with nothing behind them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: The sentences this driver understands, keyed as plan entries.
#:
#: **GGA is the boundary.** §12 requires the plan's first fast-tier entry to be a line the talker
#: sends exactly once per cycle, every cycle — GGA is the fix sentence and is the one every talker
#: emits, which is why it is the discriminator as well as the boundary.
GGA: Final = "GGA"
GSA: Final = "GSA"
GSV: Final = "GSV"
RMC: Final = "RMC"

#: Every key the plan may name.
KEYS: Final[tuple[str, ...]] = (GGA, GSA, GSV, RMC)


@dataclass(frozen=True, slots=True)
class Sentence:
    """One checksum-valid sentence, split into fields."""

    #: The talker identifier — ``GP`` for GPS, ``GN`` for a mixed constellation, and so on.
    talker: str

    #: The three-letter sentence type, upper-cased.
    kind: str

    #: The comma-separated fields after the type, with empty fields preserved as empty strings.
    fields: tuple[str, ...]

    def field(self, index: int) -> str | None:
        """One field, or ``None`` where it is absent or empty.

        NMEA leaves a field empty rather than omitting it when it has nothing to say, so an empty
        string is *"no fix yet"* rather than *"zero"* — and telling those apart is the whole of
        §11.1 restated for a different wire format.
        """
        if index >= len(self.fields):
            return None
        value = self.fields[index].strip()
        return value or None


def checksum_of(body: str) -> int:
    """NMEA's checksum: XOR of every byte between ``$`` and ``*``."""
    result = 0
    for character in body:
        result ^= ord(character)
    return result & 0xFF


def parse(line: str | None) -> Sentence | None:
    """One line to a sentence, or ``None`` for anything that is not a valid one.

    ``None`` covers: not a sentence, a bad checksum, a truncated line, a type shorter than three
    characters. All of them are the same fact to a caller — *this line is not usable* — and
    distinguishing them would produce a diagnostic nobody could act on for a talker that is
    working correctly and sharing a bus.
    """
    if line is None:
        return None

    text = line.strip()
    if not text.startswith(("$", "!")) or len(text) < 7:
        return None

    body, star, given = text[1:].partition("*")
    if not star:
        # **Required, not optional.** The reasoning above only works if it is: a line with no
        # checksum has nothing saying it is not a byte-flipped one, so accepting it would take
        # exactly the garbage the check exists to refuse. Every talker in service sends one; a
        # line without is truncated, or is not a sentence.
        return None

    try:
        if int(given.strip()[:2], 16) != checksum_of(body):
            return None
    except ValueError:
        return None

    parts = body.split(",")
    header = parts[0]
    if len(header) < 5:
        return None

    return Sentence(talker=header[:-3].upper(), kind=header[-3:].upper(), fields=tuple(parts[1:]))


def parse_degrees(value: str | None, hemisphere: str | None) -> float | None:
    """NMEA's ``ddmm.mmmm`` to signed decimal degrees.

    The format packs degrees and minutes into one number with no separator, which is the single
    most common thing to get wrong about NMEA — reading it as a decimal gives a position that is
    plausible, wrong, and wrong by a different amount at every latitude.
    """
    if value is None or hemisphere is None:
        return None

    try:
        packed = float(value)
    except ValueError:
        return None

    degrees, minutes = divmod(abs(packed), 100.0)
    if minutes >= 60.0:
        # Not a coordinate. A malformed field that happens to be numeric is exactly the case
        # §11.1 exists for.
        return None

    decimal = degrees + minutes / 60.0
    return -decimal if hemisphere.upper() in {"S", "W"} else decimal


def parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except ValueError:
        return None
