"""Summary statistics over a stored series.

Separate from ``trend_store`` because storage and inference are different jobs, and separate from
``chart_geometry`` because these are statements about the receiver rather than about a drawing.

**Everything here ignores holes and says how many values it actually used.** A deviation over
3,000 readings and one over 12 are not the same figure, and §10.7 requires the count to travel
beside the value rather than as a footnote — so it is part of the return type and cannot be
dropped by a caller that forgot to ask.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Deviation:
    """A standard deviation and the evidence behind it."""

    #: ``None`` where fewer than two values were available — a deviation over one sample is not a
    #: small number, it is not a number, and rendering it as 0.0 would say the receiver was
    #: perfectly stable.
    value: float | None

    #: How many finite values went into it.
    count: int

    @property
    def is_measured(self) -> bool:
        return self.value is not None


def deviation(values: Sequence[float]) -> Deviation:
    """The sample standard deviation of the finite values, and how many there were.

    **Sample rather than population** — the ``n − 1`` denominator. The readings are a sample of the
    receiver's behaviour rather than the whole of it, and at the counts where the difference
    matters (a handful of readings, which §10.7 says is the routine case for a freshly started
    application) the population form understates the scatter, which is the direction that flatters
    the instrument.

    Computed in two passes rather than from the sum of squares. The one-pass form loses most of its
    significant digits when the mean is far from zero relative to the spread, which is exactly this
    data: EFC sits near −16.83 % and varies by 0.05.
    """
    finite = [value for value in values if math.isfinite(value)]
    if len(finite) < 2:
        return Deviation(value=None, count=len(finite))

    mean = math.fsum(finite) / len(finite)
    variance = math.fsum((value - mean) ** 2 for value in finite) / (len(finite) - 1)

    return Deviation(value=math.sqrt(variance), count=len(finite))
