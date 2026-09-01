"""§10.7.1's oscillator drift advisory: what the fit can support, and what it refuses.

**The refusals are the feature.** A slope without a sense of scatter is a number pretending to be a
measurement, and the failure mode this card is built to avoid is a confident projection drawn from
four minutes of a warming oscillator. So the advisory withholds a projection the window cannot
support, drops the daily term where the window is too short to separate it from the trend, and
names its evidence in every case.

Three units decisions, all from §10.7.1 and all measured rather than argued:

**Figures are in ppm of control range, the projection in per cent.** EFC is already a percentage
*of* the range, so one per cent of range is 10 000 ppm and ppm here needs no second reference.
#182 recorded what per cent cost: a secular drift of −0.00086 %/day, a diurnal amplitude of
0.00034 % and a residual of 0.00324 % printed as ``−0.001 %/day``, ``±0.00 %`` and ``0.00 %``. The
arithmetic was right, and the card could not say that a double-oven oscillator holding 0.05 % of
range across two days is the *good* case. The same three figures in ppm are −8.6, ±3.4 and 32.4.

**The rails stay at ±100 %.** A projection is about reaching them, and saying so in ppm would be
arithmetic for its own sake.

**Spans round down, never to nearest.** #184: selecting 24 h produced *"spanning 24.0 hours … a
daily swing cannot be separated from the trend in under a day of data"* — a label and a verdict
contradicting each other in one sentence, because the true span was 23.98 hours and the evidence
line rounded up. A figure sitting beside a verdict about a threshold must never round across it.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from smartclock_monitor.services.trend_store import Series
from smartclock_monitor.themes.severity import Severity

#: One per cent of control range, in ppm of control range.
PPM_PER_PERCENT: Final = 10_000.0

#: Where the control range ends. §10.7.1: the rails are at ±100 % and stay there.
RAIL_PERCENT: Final = 100.0

#: §10.7.1: *"The fit's window is the drawn range plus a small fixed margin."*
#:
#: A window of exactly *n* hours holds a span of slightly under *n* hours, because its oldest
#: sample sits just inside the leading edge rather than on it. Without this the 24 h range could
#: never satisfy the day-long separability rule below, and the range named for a day could not
#: reach the day-based analysis this card is built around.
FIT_MARGIN: Final = timedelta(minutes=5)

#: How long a span must be before a daily component can be told apart from a straight line. One
#: cycle. Below it the fit drops to a plain line and says so, rather than reporting a daily
#: amplitude of zero — which would be a measurement.
SEPARABLE: Final = timedelta(days=1)

#: How many standard errors the slope must clear before a projection is offered.
#:
#: Two, which is the conventional bar and the one worth defending here: below it the fit cannot
#: tell the slope from zero, and a projection drawn from a slope indistinguishable from zero is a
#: date invented out of scatter.
SLOPE_CONFIDENCE: Final = 2.0

#: Beyond this the projection stops meaning anything. A rate that reaches the rail in four hundred
#: years is a flat oscillator described at great length.
PROJECTION_HORIZON_DAYS: Final = 36_525.0

#: The shortest span a projection may be made from.
#:
#: **Found against the receiver.** Fifteen minutes of readings produced *"Drift +1680.6 ppm/day —
#: consistent with reaching +100 % in about 693 days"*: a two-year forecast from a quarter of an
#: hour. The statistical gate passed honestly — the scatter really was 0.6 ppm and the slope really
#: did clear two standard errors — because over fifteen minutes a quantised EFC reading is locally
#: almost a straight line. What that gate cannot see is that the quantity being projected is a rate
#: *per day*, and a window shorter than a day has not observed one.
#:
#: The same threshold as :data:`SEPARABLE`, for a related reason: below a day the fit cannot tell a
#: daily cycle from a trend, so any slope it reports may be a few hours of one.
PROJECTION_MINIMUM_SPAN: Final = timedelta(days=1)

#: How far past the observed span a projection may reach, as a multiple of it.
#:
#: The second half of the same defect: a day of readings is enough to observe a rate per day and
#: still not enough to carry it out two years. A hundredfold is generous by the standards of any
#: other extrapolation, and still refuses the 693-days-from-15-minutes case by three orders of
#: magnitude.
PROJECTION_REACH: Final = 100.0

#: The two hardware register bits §10.7.1 surfaces here. They are the alarm; the slope is the
#: gauge. Read from the receiver rather than recomputed — a bit the hardware sets is a different
#: claim from an inference drawn from the same data.
EFC_NEAR_FULL_SCALE_BIT: Final = 6
EFC_AT_FULL_SCALE_BIT: Final = 7


@dataclass(frozen=True, slots=True)
class DriftFit:
    """The arithmetic, separately from the words."""

    #: Secular slope, ppm of control range per day.
    slope_ppm_per_day: float

    #: Standard error of that slope, same units. What the projection is gated on.
    slope_error_ppm_per_day: float

    #: Residual rms about the fit, ppm of range. §10.7.1's "unexplained scatter".
    residual_ppm: float

    #: Half the peak-to-peak daily swing, ppm of range, or ``None`` where the window was too short
    #: to separate one from the trend. Never 0.0 for "we did not look" — that is a measurement.
    diurnal_ppm: float | None

    #: Where the fit says the oscillator is now, per cent.
    current_percent: float

    #: How many readings the fit used, after exclusions.
    count: int

    #: The span it actually fitted.
    span: timedelta

    #: How many readings were dropped for sitting inside the settling window.
    excluded_settling: int


@dataclass(frozen=True, slots=True)
class Projection:
    """When the trend reaches a rail, if the window can support saying."""

    days: float
    when: datetime
    rail_percent: float


@dataclass(frozen=True, slots=True)
class DriftAdvisory:
    """What the card renders.

    Severity travels as a :class:`Severity` rather than as a colour: §9.13 item 10 makes
    ``SeverityPill`` the one severity renderer, and handing a page a brush would route around it.
    """

    severity: Severity

    #: The headline beside the pill.
    headline: str

    #: The evidence, one sentence per line. §10.7.1: the advisory names its evidence and hedges its
    #: wording — it is consistent-with, never is.
    lines: tuple[str, ...]

    #: ``None`` where there was not enough to fit at all.
    fit: DriftFit | None = None

    projection: Projection | None = None


# ---- The fit ------------------------------------------------------------------------------------


def _solve(matrix: list[list[float]], vector: list[float]) -> tuple[list[float], list[float]]:
    """Gauss-Jordan with partial pivoting: the coefficients, and the inverse's diagonal.

    The diagonal is what the slope's standard error needs, and it comes almost free once the
    elimination is being done anyway. Hand-rolled because the device layer's dependency discipline
    is worth extending upwards where the cost is thirty lines — a linear solve for four unknowns
    is not a reason to put NumPy in the wheel.
    """
    size = len(vector)
    augmented = [
        row[:] + [1.0 if i == j else 0.0 for j in range(size)] for i, row in enumerate(matrix)
    ]
    right = vector[:]

    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-300:
            raise ZeroDivisionError("singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        right[column], right[pivot] = right[pivot], right[column]

        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        right[column] /= scale

        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0.0:
                continue
            augmented[row] = [
                value - factor * other
                for value, other in zip(augmented[row], augmented[column], strict=True)
            ]
            right[row] -= factor * right[column]

    inverse_diagonal = [augmented[index][size + index] for index in range(size)]
    return right, inverse_diagonal


def _basis(days: float, *, diurnal: bool) -> list[float]:
    """The design row for one sample. Time is in days, centred by the caller."""
    row = [1.0, days]
    if diurnal:
        angle = 2.0 * math.pi * days
        row += [math.cos(angle), math.sin(angle)]
    return row


def fit_drift(
    series: Series,
    *,
    settling_until: datetime | None = None,
) -> DriftFit | None:
    """Fit EFC against time, with a daily term where the span can support one.

    :param settling_until: The end of a power-up settling window. Samples before it are dropped
        and counted — §10.7.1 excludes the first 24 h after a power-up because the loop is settling
        and those readings bend the fit. Computed by the caller from
        :meth:`TrendStore.last_power_up`, because the store can look further back than the window.

    Returns ``None`` where there is not enough to fit. That is a different answer from a flat fit
    and the caller must be able to tell them apart.
    """
    times: list[float] = []
    values: list[float] = []
    excluded = 0

    for index, value in enumerate(series.efc_percent):
        if not math.isfinite(value):
            continue
        moment = series.moment_at(index)
        if settling_until is not None and moment < settling_until:
            excluded += 1
            continue
        times.append(series.at[index])
        values.append(value)

    if len(values) < 3:
        return None

    span = timedelta(seconds=times[-1] - times[0])
    diurnal = span >= SEPARABLE

    # Centre the time axis. Epoch seconds are around 1.8e9 and the spans here are hours, so an
    # uncentred fit asks the solver to separate a slope from an intercept that differ by ten orders
    # of magnitude — which it does badly, in the last digits, exactly where the answer lives.
    origin = math.fsum(times) / len(times)
    in_days = [(moment - origin) / 86_400.0 for moment in times]

    terms = 4 if diurnal else 2
    if len(values) <= terms:
        return None

    rows = [_basis(day, diurnal=diurnal) for day in in_days]
    normal = [
        [math.fsum(row[i] * row[j] for row in rows) for j in range(terms)] for i in range(terms)
    ]
    target = [
        math.fsum(row[i] * value for row, value in zip(rows, values, strict=True))
        for i in range(terms)
    ]

    try:
        coefficients, inverse_diagonal = _solve(normal, target)
    except ZeroDivisionError:
        # Every sample at one instant, or a window so short the columns are collinear. Not an
        # error — just a window that cannot answer the question.
        return None

    residuals = [
        value - math.fsum(c * b for c, b in zip(coefficients, row, strict=True))
        for value, row in zip(values, rows, strict=True)
    ]
    degrees = len(values) - terms
    residual_variance = math.fsum(r * r for r in residuals) / degrees
    residual = math.sqrt(residual_variance)

    slope = coefficients[1]
    slope_error = math.sqrt(max(0.0, residual_variance * inverse_diagonal[1]))

    amplitude: float | None = None
    if diurnal:
        amplitude = math.hypot(coefficients[2], coefficients[3]) * PPM_PER_PERCENT

    # Where the fit says the oscillator is *now*, which is the end of the window rather than its
    # centre — the projection starts from here.
    last_row = _basis(in_days[-1], diurnal=diurnal)
    current = math.fsum(c * b for c, b in zip(coefficients, last_row, strict=True))

    return DriftFit(
        slope_ppm_per_day=slope * PPM_PER_PERCENT,
        slope_error_ppm_per_day=slope_error * PPM_PER_PERCENT,
        residual_ppm=residual * PPM_PER_PERCENT,
        diurnal_ppm=amplitude,
        current_percent=current,
        count=len(values),
        span=span,
        excluded_settling=excluded,
    )


def project(fit: DriftFit, from_moment: datetime) -> Projection | None:
    """When the trend reaches a rail, or ``None`` where the window cannot support saying.

    Withheld in five cases: the window is shorter than the rate it would be projecting, the slope
    is not distinguishable from zero, the oscillator is already past a rail, the projection reaches
    too far beyond what was observed, or the rate is so slow that the date is arithmetic rather
    than a forecast.
    """
    if fit.span < PROJECTION_MINIMUM_SPAN:
        return None

    slope = fit.slope_ppm_per_day
    if abs(slope) <= SLOPE_CONFIDENCE * fit.slope_error_ppm_per_day:
        return None

    rail = RAIL_PERCENT if slope > 0 else -RAIL_PERCENT
    remaining_percent = rail - fit.current_percent
    if remaining_percent == 0.0 or (remaining_percent > 0) != (slope > 0):
        return None

    days = remaining_percent / (slope / PPM_PER_PERCENT)
    if not math.isfinite(days) or days <= 0.0 or days > PROJECTION_HORIZON_DAYS:
        return None
    if days > PROJECTION_REACH * (fit.span / timedelta(days=1)):
        return None

    return Projection(days=days, when=from_moment + timedelta(days=days), rail_percent=rail)


# ---- The words ----------------------------------------------------------------------------------


def _floor_to(value: float, places: int) -> float:
    """Round **down**, per #184. See the module docstring."""
    scale = 10.0**places
    return math.floor(abs(value) * scale) / scale * (-1.0 if value < 0 else 1.0)


def _hours(span: timedelta) -> str:
    return f"{_floor_to(span.total_seconds() / 3600.0, 1):.1f}"


def _signed(value: float, places: int = 1) -> str:
    """A signed figure with U+2212 for negatives, §9.5.3's typesetting."""
    text = f"{value:+.{places}f}"
    return text.replace("-", "\N{MINUS SIGN}")


def advise(
    series: Series,
    *,
    now: datetime,
    settling_until: datetime | None = None,
    register_bits: Sequence[bool] | None = None,
) -> DriftAdvisory:
    """§10.7.1's advisory: the fit, the projection, and the sentences that hedge them.

    :param register_bits: The hardware status register, if it has been read. ``None`` means it has
        not been, and the advisory says so rather than reporting the bits as clear — an unread bit
        and a clear bit are different facts, and reporting the first as the second is how an alarm
        gets missed.
    """
    fit = fit_drift(series, settling_until=settling_until)
    alarm = _register_line(register_bits)

    if fit is None:
        return DriftAdvisory(
            severity=Severity.NEUTRAL,
            headline="Not enough history yet",
            lines=(
                "There are too few stored readings in this window to fit a trend.",
                alarm,
            ),
        )

    projection = project(fit, now)
    lines = [
        f"Drift {_signed(fit.slope_ppm_per_day)} ppm/day — " + _projection_line(fit, projection),
        f"From {fit.count:,} settled readings spanning {_hours(fit.span)} hours."
        + (
            f" {fit.excluded_settling:,} excluded as still settling after a power-up."
            if fit.excluded_settling
            else ""
        ),
        f"Unexplained scatter {fit.residual_ppm:.1f} ppm of range. " + _diurnal_line(fit),
        alarm,
    ]

    severity, headline = _verdict(fit, projection, register_bits)
    return DriftAdvisory(
        severity=severity,
        headline=headline,
        lines=tuple(lines),
        fit=fit,
        projection=projection,
    )


def _projection_line(fit: DriftFit, projection: Projection | None) -> str:
    """Why there is no projection, when there is none.

    Each refusal is a different fact about the window, and someone deciding whether to leave the
    receiver running for another day needs to know which one they are looking at.
    """
    if projection is None:
        if fit.span < PROJECTION_MINIMUM_SPAN:
            return (
                "no projection: a rate per day cannot be carried forward from less than a day "
                "of readings."
            )
        if abs(fit.slope_ppm_per_day) <= SLOPE_CONFIDENCE * fit.slope_error_ppm_per_day:
            return "no projection: the trend is not separable from the scatter in this window."
        return (
            "no projection: the trend is flat, heading away from both rails, or would reach one "
            "too far beyond what has been observed."
        )

    rail = "+100 %" if projection.rail_percent > 0 else "\N{MINUS SIGN}100 %"
    return (
        f"consistent with reaching {rail} in about {_floor_to(projection.days, 0):.0f} days "
        f"({projection.when:%Y-%m-%d})."
    )


def _diurnal_line(fit: DriftFit) -> str:
    """§10.7.1: the daily component is *inferred*, and the interface must say so — a user who
    reads "diurnal" will otherwise assume something measured it. There is no internal temperature
    query on this receiver."""
    if fit.diurnal_ppm is None:
        return (
            "A daily swing cannot be separated from the trend in under a day of data, "
            "so none is reported."
        )
    return (
        f"Daily swing about ±{fit.diurnal_ppm:.1f} ppm, inferred from the reading's own "
        f"24-hour periodicity — no temperature is reported."
    )


def _register_line(bits: Sequence[bool] | None) -> str:
    if bits is None:
        return "Hardware bits 6 and 7 have not been read this run."

    near = _bit(bits, EFC_NEAR_FULL_SCALE_BIT)
    full = _bit(bits, EFC_AT_FULL_SCALE_BIT)
    if full:
        return "Hardware bit 7 is set: EFC voltage at full scale."
    if near:
        return "Hardware bit 6 is set: EFC voltage near full scale."
    return "Hardware bits 6 and 7 are both clear."


def _bit(bits: Sequence[bool], index: int) -> bool:
    return index < len(bits) and bool(bits[index])


def _verdict(
    fit: DriftFit, projection: Projection | None, bits: Sequence[bool] | None
) -> tuple[Severity, str]:
    """§10.7.1: the bits are the alarm, the slope is the gauge.

    So a set bit outranks the fit however flat the trend looks — the hardware is reporting a state
    and the fit is inferring one.
    """
    if bits is not None and _bit(bits, EFC_AT_FULL_SCALE_BIT):
        return Severity.CRITICAL, "EFC at full scale"
    if bits is not None and _bit(bits, EFC_NEAR_FULL_SCALE_BIT):
        return Severity.CAUTION, "EFC near full scale"
    if projection is not None and projection.days < 365.0:
        return Severity.CAUTION, "Trending towards a control rail"
    return Severity.SUCCESS, "Nothing remarkable"
