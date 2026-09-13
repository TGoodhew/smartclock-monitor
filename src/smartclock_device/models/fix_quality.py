"""What the fix says about its own quality, which a status screen has no field for.

§10.6 shows where the receiver thinks it is. **These say how much to believe it**, and they are the
first readings in this port that a *talker* supplies and a *SmartClock* cannot — the driver seam
running the other way from every other case (#58).

A SmartClock prints a position and stops. A GNSS talker computes an error estimate for every fix
and NMEA broadcasts it in `GST`, with `GBS` carrying the receiver-autonomous integrity check
beside it. Dilution of precision is not the same thing and does not replace them: dilution is
*geometry*, and the capture these were built from has an HDOP between 0.65 and 0.82 — excellent —
while the error estimate sits near 2.7 m. Good geometry and poor ranging at the same moment, which
is exactly the disagreement a user needs to see rather than have averaged away.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from smartclock_device.models.satellite import SatelliteId


class FixQuality(enum.Enum):
    """*What kind* of fix this is, as distinct from whether there is one.

    `GGA` field 5 distinguishes a standalone fix from a differential one from an RTK one, and this
    port read it as a single bit — ``quality > 0`` — and threw the rest away. §10.6 has a row for
    it. All three of the values below appear in `vk162-cold-start.nmea`, in order, as the receiver
    acquires; `vk162-steady-state` is differential throughout and `vk162-wsl-bench`, the same
    module on the same desk five days later, is standalone throughout.

    **This is the receiver's claim about its own method**, and it pairs with — rather than
    duplicates — :class:`PositionUncertainty`. Quality says *what kind* of fix; the uncertainty
    says *how good*. The corpus has a sitting where the geometry is excellent and the ranging is
    not, which is exactly the disagreement neither field can express alone.
    """

    #: The receiver did not say, or the family has no such notion.
    UNKNOWN = "unknown"

    #: No fix. `GGA` quality 0, or a `GNS` mode of `N` on every constellation.
    NONE = "no fix"

    #: A standalone fix from the constellation alone. `GGA` quality 1, `GNS` mode `A`.
    AUTONOMOUS = "autonomous"

    #: Corrected against a reference station or SBAS. `GGA` quality 2, `GNS` mode `D`.
    DIFFERENTIAL = "differential"

    #: Real-time kinematic, integers resolved. `GGA` quality 4, `GNS` mode `R`.
    RTK_FIXED = "RTK fixed"

    #: Real-time kinematic, integers not resolved. `GGA` quality 5, `GNS` mode `F`.
    RTK_FLOAT = "RTK float"

    #: Propagated from the last fix rather than measured. `GGA` quality 6, `GNS` mode `E`.
    DEAD_RECKONING = "dead reckoning"


#: `GGA`'s field 5, which is an integer code.
GGA_QUALITIES: Final[dict[int, FixQuality]] = {
    0: FixQuality.NONE,
    1: FixQuality.AUTONOMOUS,
    2: FixQuality.DIFFERENTIAL,
    4: FixQuality.RTK_FIXED,
    5: FixQuality.RTK_FLOAT,
    6: FixQuality.DEAD_RECKONING,
}

#: `GNS`'s field 5, which is **one character per constellation** rather than a code.
#:
#: `DN` from a VK-162 with two systems, `ANNN` from a forM8N with four. The fix as a whole is the
#: best any constellation managed, because a receiver contributing a differential solution on GPS
#: and nothing on GLONASS has produced a differential fix.
GNS_MODES: Final[dict[str, FixQuality]] = {
    "N": FixQuality.NONE,
    "A": FixQuality.AUTONOMOUS,
    "D": FixQuality.DIFFERENTIAL,
    "R": FixQuality.RTK_FIXED,
    "F": FixQuality.RTK_FLOAT,
    "E": FixQuality.DEAD_RECKONING,
}

#: Best first, so a mixed `GNS` mode string resolves to the best any constellation managed.
_BEST_FIRST: Final[tuple[FixQuality, ...]] = (
    FixQuality.RTK_FIXED,
    FixQuality.RTK_FLOAT,
    FixQuality.DIFFERENTIAL,
    FixQuality.AUTONOMOUS,
    FixQuality.DEAD_RECKONING,
    FixQuality.NONE,
)


def best_of(qualities: Iterable[FixQuality]) -> FixQuality:
    """The best of several per-constellation qualities, or ``UNKNOWN`` if there are none.

    A receiver contributing a differential solution on GPS and nothing on GLONASS has produced a
    differential fix, so the whole is the best of its parts rather than the worst or the first.
    """
    found = set(qualities)
    for candidate in _BEST_FIRST:
        if candidate in found:
            return candidate
    return FixQuality.UNKNOWN


@dataclass(frozen=True, slots=True)
class PositionUncertainty:
    """One-sigma position error, per axis, in metres — `GST`'s standard deviations.

    **Every field is independently optional, and that is measured rather than defensive.** In all
    300 `GST` sentences of `form8n-gst-gbs.nmea` the error-ellipse fields — semi-major, semi-minor
    and orientation — are blank while the three per-axis deviations are filled. That is u-blox
    declining to publish an ellipse, not a truncation and not a parse failure, so a model that
    required them would refuse a sentence the receiver considers complete.
    """

    #: One-sigma latitude error in metres.
    latitude_metres: float | None = None

    #: One-sigma longitude error in metres.
    longitude_metres: float | None = None

    #: One-sigma altitude error in metres.
    altitude_metres: float | None = None

    @property
    def horizontal_metres(self) -> float | None:
        """The two horizontal deviations combined, or ``None`` if either is missing.

        **Built from the deviations and never from `GST`'s range RMS.** That field is not
        believable on the one receiver here that sends it: across 300 sentences from a module
        sitting still on one unbroken fix it runs from 17 to 3,179,277 — six orders of magnitude
        between one second and the next, 23 of them above a million — while the three deviations in
        those very same sentences stay between 1.6 and 4.1 m. Every one passes its checksum, so
        that is what the module sends. Nothing displays it.
        """
        if self.latitude_metres is None or self.longitude_metres is None:
            return None
        return math.hypot(self.latitude_metres, self.longitude_metres)


@dataclass(frozen=True, slots=True)
class ConstellationIntegrity:
    """`GBS`'s receiver-autonomous integrity check: whether a satellite is being excluded, and why.

    **A clean check and an absent one look identical on the wire**, and telling them apart is the
    whole reason this type is nullable rather than a bool. A receiver that was never asked for
    `GBS` sends nothing; a receiver reporting perfect health sends `GBS` with its fault fields
    blank. `ReceiverStatus.integrity` being ``None`` is the first; an instance with
    :attr:`faulted` ``None`` is the second — *asked, and nothing wrong*.

    Every cycle in the corpus is the second case, so **nothing here has met a real fault.** The
    faulted branch is covered by a synthetic sentence, and the test that does it says so in as many
    words rather than implying a receiver produced it.
    """

    #: The satellite the receiver would exclude, or ``None`` when it flagged none.
    faulted: SatelliteId | None = None

    #: Probability of a missed detection, as the sentence gives it.
    miss_probability: float | None = None

    #: The estimated bias on that satellite's range, in metres.
    bias_metres: float | None = None

    #: The standard deviation of that bias estimate, in metres.
    bias_deviation_metres: float | None = None

    @property
    def is_clean(self) -> bool:
        """Whether the check ran and found nothing. Never true of a receiver that was not asked."""
        return self.faulted is None
