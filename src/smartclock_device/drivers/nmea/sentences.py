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

from smartclock_device.models.satellite import Constellation

#: The sentences this driver understands, keyed as plan entries.
GGA: Final = "GGA"
GNS: Final = "GNS"
GBS: Final = "GBS"
GSA: Final = "GSA"
GST: Final = "GST"
GSV: Final = "GSV"
RMC: Final = "RMC"

#: **The fix sentence, however this talker spells it** — and there are two spellings.
#:
#: §12 requires a cycle to be delimited by a line the talker sends exactly once per cycle, every
#: cycle, and this comment used to say that line is GGA because *"GGA is the fix sentence and is
#: the one every talker emits"*. **Two receivers in `tests/fixtures/nmea/` do not emit it at all**
#: — a VK-162 and a forM8N, each configured for GNS — and against those the boundary never came
#: round, no cycle ever closed, and the application showed nothing while connected to a talker
#: reporting a good fix every second (#58).
#:
#: A multi-constellation talker sends GNS where a GPS-only one sends GGA. The two carry the fix at
#: the same field positions and disagree about exactly one: GGA's field 5 is an integer quality,
#: GNS's is a **mode string with one character per constellation** — `DN` on the VK-162, `ANNN` on
#: the forM8N — where `N` is that constellation contributing nothing.
#:
#: Both are boundaries rather than one being folded into the other, so a talker that sent both
#: would still close one cycle per second: the listener closes when a boundary key repeats *its
#: own* key, so GGA,GNS,…,GGA closes on the second GGA with the GNS inside it. No receiver in the
#: corpus does that — twelve captures, every one strictly GGA or strictly GNS — but the cost of
#: being right about it was one tuple rather than one string.
FIX_KINDS: Final[tuple[str, ...]] = (GGA, GNS)

#: Every key the plan may name.
KEYS: Final[tuple[str, ...]] = (GGA, GNS, GBS, GSA, GST, GSV, RMC)


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


#: The NMEA 4.11 GNSS system id, as it appears in GSA's last field.
#:
#: Present on every ``GN`` GSA in `tests/fixtures/nmea/` — 7,976 of them — and absent from every
#: single-constellation one, where the talker names the system instead. That split is what makes
#: reading it safe rather than speculative.
SYSTEM_IDS: Final[dict[str, Constellation]] = {
    "1": Constellation.GPS,
    "2": Constellation.GLONASS,
    "3": Constellation.GALILEO,
    "4": Constellation.BEIDOU,
    "5": Constellation.QZSS,
    "6": Constellation.NAVIC,
}

#: Where NMEA puts satellite-based augmentation inside the GPS talker, inclusive.
SBAS_RANGE: Final = (33, 64)


def constellation_for(talker: str | None, prn: int) -> Constellation:
    """Which constellation a satellite number belongs to, from the sentence that carried it.

    **The talker is the only thing in a GSV page that says this.** The sentence carries no system
    field, and NMEA 4.11's trailing signal id names a *frequency* rather than a constellation. So
    ``GN`` — which a few receivers use for GSV — is answered ``UNKNOWN``: it means *combined*, and
    guessing from the number would be inventing the very attribution this exists to read.

    **The one number-based rule is the standard's own.** NMEA reserves 33–64 for satellite-based
    augmentation inside the GPS talker, and that is not a hypothesis: the VK-162 captures carry
    ``$GPGSV`` satellites 46 and 48, which are WAAS. Numbers outside that range in a ``GP`` page are
    left as GPS rather than guessed at, because a receiver using raw SBAS numbering is one nobody
    here has seen.
    """
    if talker == "GP":
        low, high = SBAS_RANGE
        return Constellation.SBAS if low <= prn <= high else Constellation.GPS
    return {
        "GL": Constellation.GLONASS,
        "GA": Constellation.GALILEO,
        "GB": Constellation.BEIDOU,
        "BD": Constellation.BEIDOU,
        "GQ": Constellation.QZSS,
        "GI": Constellation.NAVIC,
    }.get(talker or "", Constellation.UNKNOWN)
