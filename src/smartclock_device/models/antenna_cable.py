"""A coaxial cable's propagation delay per metre, for §10.7's antenna-delay calculator.

The receiver cannot know how far its antenna is; it subtracts whatever delay it is told
(``:GPS:REF:ADEL``). Getting that number wrong shifts the 1 PPS output by exactly the error, so
20 m of guessing is 78 ns of systematic offset that nothing downstream will flag.

**Sourced from the 58503A guide, page 2-12.** "The RG 213 propagation delay is 1.54 nanoseconds
per foot (5.05 ns/meter). The 9913 propagation delay is 1.2 nanoseconds per foot (3.94 ns/meter)."
Those are the two cables HP recommends for this antenna system. LMR-400 is not in that manual —
§10.7 substitutes it, reasonably, since it is what a modern installation is likely to use and
Belden 9913 is long out of production — so both are offered here rather than one replacing the
other.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Final

#: The speed of light expressed as a delay: 1 / c, in nanoseconds per metre.
#:
#: 3.3356 ns/m is one metre at the speed of light in vacuum. A cable's delay is this divided by its
#: velocity factor, which is where every figure in the preset table comes from and how a custom
#: cable is computed (§10.7).
VACUUM_DELAY_NS_PER_METRE: Final = 3.3356

#: The range ``:GPS:REF:ADEL`` accepts, in nanoseconds (§10.7).
_MAX_ACCEPTABLE_DELAY_NS: Final = 999_999.0


@dataclass(frozen=True, slots=True)
class AntennaCable:
    """One cable, by name or computed from a velocity factor."""

    #: What the cable is called.
    name: str

    #: Propagation delay in nanoseconds per metre.
    delay_ns_per_metre: float

    #: Where the figure came from, shown beside the choice.
    source: str

    def delay_for(self, metres: float) -> float | None:
        """The delay for a given run of this cable, in nanoseconds.

        Negative lengths and nonsense give no answer rather than a negative delay.

        P0-11's acceptance criterion: LMR-400 at 20 m gives 78.7 ns ± 0.5, and 20 m at 3.93 ns/m
        is 78.6.
        """
        if not math.isfinite(metres) or metres < 0:
            return None
        return metres * self.delay_ns_per_metre


def from_velocity_factor(velocity_factor: float) -> AntennaCable | None:
    """A cable described by its velocity factor rather than by name.

    :param velocity_factor: The fraction of the speed of light the signal travels at, between 0
        and 1 exclusive. Foam dielectric coax is around 0.85, solid polyethylene around 0.66.
    :return: The cable, or ``None`` if the factor is not a usable one.

    ``None`` rather than an exception for a bad factor: this is fed straight from a text box, and a
    user halfway through typing ``0.`` has not made an error worth raising over.
    """
    if math.isnan(velocity_factor) or velocity_factor <= 0 or velocity_factor >= 1:
        return None

    return AntennaCable(
        name=f"Custom, velocity factor {velocity_factor:.2f}",
        delay_ns_per_metre=VACUUM_DELAY_NS_PER_METRE / velocity_factor,
        source="computed from the velocity factor",
    )


def is_acceptable_delay(nanoseconds: float | None) -> bool:
    """Whether the receiver will accept this delay, per ``:GPS:REF:ADEL``'s range.

    §10.7 gives the field a range of 0 – 999 999 ns. Rejecting client-side is §10.6's rule for
    position and applies just as well here: a device error for a value the app could have caught
    tells the user nothing they can act on.
    """
    return (
        nanoseconds is not None
        and math.isfinite(nanoseconds)
        and 0 <= nanoseconds <= _MAX_ACCEPTABLE_DELAY_NS
    )


#: RG-213, the 58503A guide's first recommendation.
RG213: Final = AntennaCable(
    name="RG-213 / Belden 8267",
    delay_ns_per_metre=5.05,
    source="58503A guide, 1.54 ns/ft",
)

#: Belden 9913, the guide's second recommendation.
BELDEN_9913: Final = AntennaCable(
    name="Belden 9913",
    delay_ns_per_metre=3.94,
    source="58503A guide, 1.2 ns/ft",
)

#: LMR-400, which §10.7 offers in the guide's place for a modern installation.
LMR400: Final = AntennaCable(
    name="LMR-400",
    delay_ns_per_metre=3.93,
    source="§10.7, velocity factor 0.85",
)

#: The presets.
#:
#: §10.7 lists RG-213, LMR-400 and Custom, in that order, and the first two lead here. Belden 9913
#: is offered as well, from the guide's own second recommendation (see the module docstring); §10.7
#: does not yet list it.
PRESETS: Final[tuple[AntennaCable, ...]] = (RG213, LMR400, BELDEN_9913)
