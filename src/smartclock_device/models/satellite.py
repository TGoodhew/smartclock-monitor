"""The two halves of the status screen's acquisition table.

Elevation, azimuth and signal strength have no individual SCPI query — they exist only inside
``:SYST:STAT?`` — which is why §7.3 makes the status screen the sole source for the Satellites
page.
"""

from __future__ import annotations

import enum
import functools
from dataclasses import dataclass
from typing import Final

#: The PRN numbers GPS assigns, inclusive at both ends.
#:
#: A fact about **GPS**, not about any receiver family — every GPS receiver sees the same
#: constellation — so it lives with the satellite model rather than in a command catalog or behind
#: a driver. It was in the catalog because the exclusion commands bound their arguments with it;
#: those still do, from here.
FIRST_PRN: Final = 1
LAST_PRN: Final = 32


class Constellation(enum.Enum):
    """Which system a satellite number belongs to (#57).

    **Nothing outside the NMEA driver sets this.** A SmartClock reports bare PRNs and its exclusion
    commands take bare PRNs, so its satellites are :attr:`UNKNOWN` and every surface renders them
    exactly as it did before — which is also §9.10.2's own wording. It is the honest answer for a
    ``$GNGSV`` page too, where the talker declines to say.
    """

    #: The receiver did not say, or had no way to. Rendered as a bare number.
    UNKNOWN = 0

    #: The United States' GPS. NMEA talker ``GP``.
    GPS = 1

    #: A satellite-based augmentation system — WAAS, EGNOS, MSAS. NMEA numbers these 33–64 inside
    #: the GPS talker rather than giving them one of their own.
    SBAS = 2

    #: Russia's GLONASS. NMEA talker ``GL``.
    GLONASS = 3

    #: Europe's Galileo. NMEA talker ``GA``.
    GALILEO = 4

    #: China's BeiDou. NMEA talker ``GB``, and ``BD`` on some older firmware.
    BEIDOU = 5

    #: Japan's QZSS. NMEA talker ``GQ``.
    QZSS = 6

    #: India's NavIC, formerly IRNSS. NMEA talker ``GI``.
    NAVIC = 7


#: The RINEX system letter for each constellation, empty where there is none.
#:
#: RINEX's rather than invented: it is what u-center, the IGS products and Lady Heather all use, so
#: a user who knows one knows this.
CODES: Final[dict[Constellation, str]] = {
    Constellation.GPS: "G",
    Constellation.SBAS: "S",
    Constellation.GLONASS: "R",
    Constellation.GALILEO: "E",
    Constellation.BEIDOU: "C",
    Constellation.QZSS: "J",
    Constellation.NAVIC: "I",
}

#: The constellation's name as a reader knows it. Empty where it is not known, so a caller can
#: leave it unsaid rather than saying "unknown".
NAMES: Final[dict[Constellation, str]] = {
    Constellation.GPS: "GPS",
    Constellation.SBAS: "SBAS",
    Constellation.GLONASS: "GLONASS",
    Constellation.GALILEO: "Galileo",
    Constellation.BEIDOU: "BeiDou",
    Constellation.QZSS: "QZSS",
    Constellation.NAVIC: "NavIC",
}


@functools.total_ordering
@dataclass(frozen=True, slots=True)
class SatelliteId:
    """A satellite's identity: its number, and the constellation that number belongs to.

    **A number alone is not an identity.** The NMEA driver deduped a cycle's satellites on the bare
    number, so against a receiver that numbers per constellation the second claimant of a number was
    silently discarded — *every one* of the 632 cycles in ``form8n-wsl-bench.nmea`` and 1,217 of the
    1,800 in ``form8n-gps-beidou-outdoors.nmea``. The user-visible symptom is the bad part: the sky
    plot and the satellite count under-report, which reads as poor reception rather than as a
    parsing choice, and sends someone onto the roof.

    Keeping the number as the identity and deduping per talker was the alternative, and it is worse:
    it puts two satellites numbered 4 into the model and draws two markers that both say 4.

    **Ordered by number first and constellation second**, so §9.10.2's keyboard order stays
    number-ascending and two claimants of one number land next to each other.
    """

    #: The satellite's number within its constellation.
    prn: int

    #: Which constellation that number belongs to.
    constellation: Constellation = Constellation.UNKNOWN

    @property
    def designation(self) -> str:
        """How the satellite is written — ``G04``, ``C04`` — or the bare number when unknown."""
        code = CODES.get(self.constellation, "")
        return f"{code}{self.prn:02d}" if code else str(self.prn)

    @property
    def spoken(self) -> str:
        """The satellite as a sentence names it — ``GPS 4``, ``BeiDou 4``, or ``PRN 4``.

        The unknown case is **§9.10.2's own wording**, whose example sentence reads *"PRN 19,
        elevation 65 degrees, azimuth 52 degrees, carrier to noise 49, tracked."* — so a
        SmartClock's satellite is spoken exactly as the specification says it should be.

        Naming the constellation where one is known extends into ground the specification had no
        receiver for. "PRN 4" spoken twice in one plot, for two different satellites, is the failure
        this whole change exists to prevent, and a screen reader has no shape or colour to fall
        back on.
        """
        name = NAMES.get(self.constellation, "")
        return f"{name} {self.prn}" if name else f"PRN {self.prn}"

    def __lt__(self, other: object) -> bool:
        """Number first, constellation second.

        Written out rather than taken from ``order=True`` because :class:`Constellation` is a plain
        ``Enum`` and its members do not compare — a generated ``__lt__`` would raise ``TypeError``
        the first time two satellites shared a number, which is precisely the case this type
        exists for. Ordering on ``value`` keeps the enum's declaration order without making it an
        ``IntEnum``, whose members would then compare equal to bare integers.
        """
        if not isinstance(other, SatelliteId):
            return NotImplemented
        return (self.prn, self.constellation.value) < (other.prn, other.constellation.value)


@dataclass(frozen=True, slots=True)
class TrackedSatellite:
    """A satellite the receiver is currently tracking.

    From the left-hand column group of the acquisition table. Every field except :attr:`prn` is
    optional because §11.1 forbids the parser from raising: a firmware revision that widens a
    column or prints a dash must degrade to a missing value rather than a crash.
    """

    #: The satellite's PRN number. The row would not exist without one, so this is required.
    prn: int

    #: Elevation above the horizon in degrees, or ``None`` if the column did not parse.
    elevation_degrees: int | None = None

    #: Azimuth in degrees clockwise from true north, or ``None`` if the column did not parse.
    azimuth_degrees: int | None = None

    #: The signal-strength reading, on whichever scale
    #: :attr:`ReceiverStatus.signal_strength_kind` names.
    #:
    #: Deliberately a bare number with no unit attached. §11.1 warns that the two scales are not
    #: interchangeable — 26–55 with ≥ 35 good on 58503B-class units, 0–255 with 20–30 weak on
    #: 59551A-class units — so anything that renders this value must read the kind first.
    signal_strength: int | None = None

    #: Which constellation :attr:`prn` belongs to, or ``UNKNOWN`` where the receiver had no way to
    #: say. A SmartClock never says, so its satellites render exactly as they always have.
    constellation: Constellation = Constellation.UNKNOWN

    @property
    def identity(self) -> SatelliteId:
        """The pair that actually identifies this satellite. Never the number alone (#57)."""
        return SatelliteId(prn=self.prn, constellation=self.constellation)


@dataclass(frozen=True, slots=True)
class PredictedSatellite:
    """A satellite the receiver expects to be visible but is not tracking.

    From the "Not Tracking" column group. That group carries no signal-strength column — there is
    no signal to report — which is the structural difference that lets the parser tell the two
    groups apart even when a firmware revision reorders them.
    """

    #: The satellite's PRN number.
    prn: int

    #: Predicted elevation in degrees, or ``None`` if the column did not parse.
    elevation_degrees: int | None = None

    #: Predicted azimuth in degrees clockwise from true north, or ``None`` if the column did not
    #: parse.
    azimuth_degrees: int | None = None

    #: Whether the receiver marked this satellite as one it is attempting to track.
    #:
    #: The screen prints an asterisk before the PRN and explains it in its own legend —
    #: ``*attempting to track``. It is only seen while acquiring, which is why nothing had met it
    #: until a receiver was power-cycled with a clear sky (#4).
    attempting_to_track: bool = False

    #: Which constellation :attr:`prn` belongs to, or ``UNKNOWN``.
    constellation: Constellation = Constellation.UNKNOWN

    @property
    def identity(self) -> SatelliteId:
        """The pair that actually identifies this satellite. Never the number alone (#57)."""
        return SatelliteId(prn=self.prn, constellation=self.constellation)
