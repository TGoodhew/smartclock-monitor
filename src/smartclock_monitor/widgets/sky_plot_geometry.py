"""The polar arithmetic behind the sky plot (§10.5), with no Qt in it.

Separated from the drawing for the same reason the original separates ``SkyPlotGeometry``: the
mapping from a satellite's elevation and azimuth to a point on a disc is the part that can be
wrong in ways a screenshot will not show, and it is testable with no display at all.

**North up, 0° elevation at the rim, 90° at the centre.** A satellite directly overhead sits in the
middle; one on the horizon sits on the edge. That is the convention every GPS receiver's own plot
uses, and inverting it would make the display actively misleading to someone who knows the
instrument.

**A marker's position is the data.** It is the satellite's actual place in the sky, which is what
makes the plot worth having over a table: an obstruction shows up as a hole in a particular
direction, and no list of numbers shows that.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

from smartclock_device.models.receiver_status import SignalStrengthKind

#: How large a marker can get, in pixels across.
MAX_MARKER = 18.0

#: How small. §9.12's pointer-target floor applies to the hit area, not to the ink — a marker this
#: size still gets a target big enough to click.
MIN_MARKER = 8.0

#: The two signal-strength scales, as §11.1 gives them.
#:
#: **They are not interchangeable**, which is why the kind travels with the reading and this takes
#: it as an argument rather than assuming one. A 30 that means "good" on one scale means "weak" on
#: the other, and a plot that guessed would size its markers backwards on half the family.
_SCALES: Final[dict[SignalStrengthKind, tuple[float, float]]] = {
    SignalStrengthKind.CARRIER_TO_NOISE: (26.0, 55.0),
    SignalStrengthKind.SIGNAL_STRENGTH: (0.0, 255.0),
}


@dataclass(frozen=True, slots=True)
class Disc:
    """Where the plot's disc sits inside a widget."""

    centre_x: float
    centre_y: float
    radius: float


def disc_for(width: float, height: float, margin: float = 0.0) -> Disc:
    """The largest disc that fits, centred.

    The plot is always circular: §9.6.1 caps it at 360 px and stacks the table beneath rather than
    letting it stretch, because an elliptical sky plot misplaces every satellite on it.
    """
    radius = max(0.0, (min(width, height) - 2 * margin) / 2)
    return Disc(width / 2, height / 2, radius)


def position(disc: Disc, elevation_degrees: float, azimuth_degrees: float) -> tuple[float, float]:
    """Where a satellite sits on the disc.

    :param elevation_degrees: 0 at the horizon, 90 overhead. Clamped, because a receiver reporting
        a negative elevation for a satellite it is still tracking is reporting one below the
        horizon, and drawing that outside the disc would be worse than drawing it on the rim.
    :param azimuth_degrees: Clockwise from true north.
    """
    elevation = min(90.0, max(0.0, elevation_degrees))
    fraction = (90.0 - elevation) / 90.0
    angle = math.radians(azimuth_degrees % 360.0)

    return (
        disc.centre_x + disc.radius * fraction * math.sin(angle),
        disc.centre_y - disc.radius * fraction * math.cos(angle),
    )


def elevation_ring(disc: Disc, elevation_degrees: float) -> float:
    """The radius of the circle at a given elevation — the mask ring, and the 30/60 gridlines."""
    elevation = min(90.0, max(0.0, elevation_degrees))
    return disc.radius * (90.0 - elevation) / 90.0


def marker_size(strength: int | None, kind: SignalStrengthKind) -> float:
    """How large to draw a marker, from its signal strength.

    **Area scales with strength, so the diameter scales with its square root.** Scaling the
    diameter directly would make a strong satellite look four times the signal of a middling one
    rather than twice, which is the classic way a bubble chart lies.

    A satellite with no reading gets the smallest marker rather than none: it is still up there,
    and omitting it would put a hole in the plot that reads as an obstruction.
    """
    if strength is None or kind is SignalStrengthKind.UNKNOWN:
        return MIN_MARKER

    low, high = _SCALES[kind]
    span = high - low
    fraction = 0.0 if span <= 0 else min(1.0, max(0.0, (strength - low) / span))

    return MIN_MARKER + (MAX_MARKER - MIN_MARKER) * math.sqrt(fraction)


def describe(
    prn: int,
    elevation: int | None,
    azimuth: int | None,
    strength: int | None,
    kind: SignalStrengthKind,
    tracked: bool,
) -> str:
    """The sentence a screen reader reads for one marker (§9.10.2).

    The specification gives the form verbatim: *"PRN 19, elevation 65 degrees, azimuth 52 degrees,
    carrier to noise 49, tracked."* An unreported field is **omitted rather than read as a dash**,
    because "elevation dash degrees" is noise where leaving it out is a fact.

    The strength is named by its scale, not by a generic word, for the same reason the marker size
    takes the kind: the two are not interchangeable and a listener needs to know which they heard.
    """
    parts = [f"PRN {prn}"]

    if elevation is not None:
        parts.append(f"elevation {elevation} degrees")
    if azimuth is not None:
        parts.append(f"azimuth {azimuth} degrees")

    if strength is not None:
        match kind:
            case SignalStrengthKind.CARRIER_TO_NOISE:
                parts.append(f"carrier to noise {strength}")
            case SignalStrengthKind.SIGNAL_STRENGTH:
                parts.append(f"signal strength {strength}")
            case _:
                parts.append(f"signal {strength}")

    parts.append("tracked" if tracked else "not tracked")
    return ", ".join(parts) + "."
