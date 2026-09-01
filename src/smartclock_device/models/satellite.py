"""The two halves of the status screen's acquisition table.

Elevation, azimuth and signal strength have no individual SCPI query — they exist only inside
``:SYST:STAT?`` — which is why §7.3 makes the status screen the sole source for the Satellites
page.
"""

from __future__ import annotations

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
