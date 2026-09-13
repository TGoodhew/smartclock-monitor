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

import math
from dataclasses import dataclass

from smartclock_device.models.satellite import SatelliteId


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
