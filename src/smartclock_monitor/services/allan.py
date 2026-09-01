"""§10.7.2: overlapping Allan deviation over the logged 1 PPS time-interval series.

The standard stability measure for this class of instrument, and it answers the question the chart
cannot: whether the loop is noisier at one averaging time than at another. A trace can look calm
and be dominated by random walk; σy(τ) is what tells them apart.

Four rules §10.7.2 makes normative, each of which changes the answer rather than the presentation:

**Overlapping, not plain.** Both estimators are correct. The overlapping form uses every available
second difference at each τ, so its confidence at large τ holds on a capture of the length this
application collects — on a 47-hour series the difference at long τ is between an estimate and a
rumour.

**Gap-aware, because the logged series is not uniform.** The store writes a row per poll and the
poll cadence moves with the connection state, so this pairs samples by their *recorded times*: a
gap contributes nothing, rather than being silently treated as adjacent seconds. That would not
fail — it would return a number about the gaps instead of about the oscillator.

**Fed the raw series, never the decimated one.** §9.10.2's decimation keeps each pixel column's
extremes, which is right for drawing a shape and wrong for a statistic: a second difference taken
across a bucket's extremes measures the decimation (#63).

**Phase in, deviation out.** The receiver reports 1 PPS time interval, which is phase. The second
difference converts it, so nothing here may be handed a frequency series.
"""

from __future__ import annotations

import math
from bisect import bisect_left
from dataclasses import dataclass
from itertools import pairwise
from typing import Final

from smartclock_monitor.services.trend_store import Series

#: Nanoseconds to seconds. The receiver reports phase in nanoseconds and σy is dimensionless, so
#: the conversion has to happen before the division by τ or the answer is out by 1e9.
_NANOSECONDS: Final = 1e-9

#: How many second differences a τ needs before its estimate is worth printing.
#:
#: Confidence goes roughly as 1/√N, so three is already a weak estimate — but §10.7.2 requires the
#: count to be shown beside the value, which lets a reader discount it. Below three the figure is
#: not weak, it is arbitrary.
MINIMUM_DIFFERENCES: Final = 3

#: τ runs in octaves. The conventional spacing for a stability plot, and the one that puts a
#: readable number of rows on a card — a decade spacing gives three rows on a two-day capture.
_OCTAVE: Final = 2.0


@dataclass(frozen=True, slots=True)
class AllanPoint:
    """One row of §10.7.2's table."""

    #: Averaging time, seconds throughout — never switching to minutes down the column. A curve is
    #: read by comparing rows, and a column that changes unit halfway is what §9.5.3 rule 6 is
    #: about.
    tau_seconds: float

    #: σy(τ), dimensionless.
    deviation: float

    #: How many second differences the estimate averaged. Part of the reading rather than a
    #: footnote: confidence goes roughly as 1/√N.
    differences: int

    def formatted(self) -> str:
        """§10.7.2: scientific notation, fixed two-decimal mantissa, U+2212 exponent sign.

        σy is **dimensionless**, so where §9.5.3 rule 6 would have the unit change down a column,
        the exponent does that job instead and the mantissa stays comparable row to row.
        """
        if not math.isfinite(self.deviation) or self.deviation < 0.0:
            return "\N{MINUS SIGN}"
        if self.deviation == 0.0:
            # A real measurement, not an absent one: every second difference at this τ cancelled,
            # which on quantised data means the instability is below the receiver's resolution.
            # §10.7.2 drops a τ the series *cannot support*; this one it supported and the answer
            # was zero, so it keeps its row and its count.
            return "0.00e+0"

        exponent = math.floor(math.log10(self.deviation))
        mantissa = self.deviation / (10.0**exponent)
        # Rounding the mantissa can carry it to 10.00; normalise rather than print that.
        if round(mantissa, 2) >= 10.0:
            mantissa /= 10.0
            exponent += 1

        return f"{mantissa:.2f}e{exponent:+d}".replace("-", "\N{MINUS SIGN}")


def _median_spacing(times: list[float]) -> float | None:
    """The typical gap between consecutive samples, which sets the shortest τ worth asking for.

    The **median**, not the mean: one twenty-minute disconnection in an hour of one-second polling
    drags a mean to something no pair of samples is actually spaced by, and every τ derived from it
    would then miss every sample it looked for.
    """
    gaps = sorted(later - earlier for earlier, later in pairwise(times) if later > earlier)
    if not gaps:
        return None
    return gaps[len(gaps) // 2]


def _nearest(times: list[float], target: float, tolerance: float) -> int | None:
    """The index of the sample closest to ``target``, if one is within ``tolerance``."""
    position = bisect_left(times, target)

    best: int | None = None
    best_distance = tolerance
    for candidate in (position - 1, position):
        if 0 <= candidate < len(times):
            distance = abs(times[candidate] - target)
            if distance <= best_distance:
                best, best_distance = candidate, distance

    return best


def allan_deviation(series: Series, *, maximum_points: int = 12) -> tuple[AllanPoint, ...]:
    """Overlapping Allan deviation of the 1 PPS series, one point per octave of τ.

    Returns an empty tuple where the series can support no τ at all. §10.7.2: *"A τ the series
    cannot support is dropped, not dashed."* Unlike a field the receiver declined to answer, a τ
    with no estimate is not a hole in the data — it is a question this series cannot speak to, and
    a row of dashes would imply otherwise.
    """
    times: list[float] = []
    phase: list[float] = []
    for index, value in enumerate(series.ti_nanoseconds):
        if math.isfinite(value):
            times.append(series.at[index])
            phase.append(value * _NANOSECONDS)

    if len(times) < 2 * MINIMUM_DIFFERENCES:
        return ()

    base = _median_spacing(times)
    if base is None or base <= 0.0:
        return ()

    # Half a nominal spacing: near enough to be the sample the estimator was looking for, and near
    # enough that it cannot silently be its neighbour.
    tolerance = base / 2.0
    span = times[-1] - times[0]

    points: list[AllanPoint] = []
    tau = base
    while len(points) < maximum_points and 2.0 * tau <= span:
        point = _estimate(times, phase, tau, tolerance)
        if point is not None:
            points.append(point)
        tau *= _OCTAVE

    return tuple(points)


def _estimate(
    times: list[float], phase: list[float], tau: float, tolerance: float
) -> AllanPoint | None:
    """One τ, by the overlapping estimator, skipping any triple the record does not hold.

    ``σy²(τ) = Σ (x[t+2τ] − 2·x[t+τ] + x[t])² / (2 τ² M)`` over the M triples that exist.
    """
    total = 0.0
    used = 0

    for index, start in enumerate(times):
        middle = _nearest(times, start + tau, tolerance)
        end = _nearest(times, start + 2.0 * tau, tolerance)
        if middle is None or end is None or middle <= index or end <= middle:
            # The record has a gap here. It contributes nothing rather than being treated as though
            # the samples either side of it were adjacent.
            continue

        second_difference = phase[end] - 2.0 * phase[middle] + phase[index]
        total += second_difference * second_difference
        used += 1

    if used < MINIMUM_DIFFERENCES:
        return None

    variance = total / (2.0 * tau * tau * used)
    if variance < 0.0 or not math.isfinite(variance):
        return None

    return AllanPoint(tau_seconds=tau, deviation=math.sqrt(variance), differences=used)


def summarise(points: tuple[AllanPoint, ...], series: Series) -> str:
    """The card's sentence, for when the table is empty or nearly so.

    §10.7.2: *"When the series is too short for any τ, the card's summary sentence says so in
    words."* Saying it in words rather than showing an empty table is the difference between a
    card that is waiting and one that looks broken.
    """
    if not points:
        stored = sum(1 for value in series.ti_nanoseconds if math.isfinite(value))
        if stored == 0:
            return "No 1 PPS readings have been stored in this window yet."
        return (
            f"{stored:,} stored readings is not yet enough to estimate stability at any "
            f"averaging time. It needs a span of several polls."
        )

    shortest, longest = points[0], points[-1]
    trend = (
        "improving with averaging, which is what a disciplined oscillator should do"
        if longest.deviation < shortest.deviation
        else "not improving with averaging, which is consistent with drift or random walk"
    )
    return f"Stability from {shortest.tau_seconds:.0f} s to {longest.tau_seconds:.0f} s is {trend}."
