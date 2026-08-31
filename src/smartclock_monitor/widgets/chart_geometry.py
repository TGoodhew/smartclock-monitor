"""What a trend chart needs to work out before it can draw anything.

Qt-free and palette-free, like ``sky_plot_geometry`` beside ``sky_plot`` and for the same reason:
the decimation and the axis arithmetic are where a chart is right or wrong, and neither needs a
display to be tested. A test asserting that a one-second excursion survives the 7-day range should
not have to start a window to find out.

**Decimation is by minimum and maximum per pixel column, never by sampling** (§9.10.2). This is
the whole reason the module exists. Drawing every hundredth sample is the obvious thing to do and
it silently deletes the events a timing engineer opened the chart to find: at the 7-day range one
pixel column is about two minutes of readings, so a one-second glitch has about a 1-in-120 chance
of surviving a sampled decimation and a certainty of surviving this one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_monitor.services.trend_store import Series

#: The step sizes an axis bound may snap to, per decade. §9.10.2 asks for bounds "snapped to a
#: round step"; these are the conventional ones, and they are what makes an axis readable at a
#: glance rather than merely correct.
_NICE: Final[tuple[float, ...]] = (1.0, 2.0, 2.5, 5.0, 10.0)

#: §10.7.1 by way of §9.10.2's medallion ring, which has the same floor for the same reason: a calm
#: loop must not be magnified into noise. Without it a receiver holding ±2 ns would be drawn against
#: a ±2 ns axis and look like it was falling apart.
TI_FLOOR_NANOSECONDS: Final = 50.0

#: §10.7.1, measured: the bench receiver's EFC step is about 0.00018 %, from 280 distinct values
#: across 0.0516 %, so 0.01 % is about 55 codes. Below this the chart would be drawing the
#: converter's least significant bit rather than the oscillator.
EFC_MINIMUM_SPAN_PERCENT: Final = 0.01

#: §10.7.1 fixes the precision per chart rather than per range — §9.5.3 item 6 forbids a precision
#: that varies with the window. One decimal place cannot separate −16.86 from −16.80.
EFC_DECIMALS: Final = 2

#: Nanoseconds are whole numbers on this axis; the wireframe's labels are ``+50 ns``, ``0``,
#: ``−50 ns``.
TI_DECIMALS: Final = 0


@dataclass(frozen=True, slots=True)
class Column:
    """One pixel column's worth of samples, reduced to its extremes.

    ``low`` and ``high`` are the smallest and largest values in the bucket, not the first and last.
    A column holding a single sample has ``low == high``, which is how a sparse range draws as a
    line rather than as a band.
    """

    #: Which pixel column, from 0.
    index: int

    #: The middle of the bucket in epoch seconds, for positioning the column on the time axis.
    at: float

    low: float
    high: float

    #: How many samples went into it. Zero-count columns are never emitted — see :func:`decimate`.
    count: int


@dataclass(frozen=True, slots=True)
class Axis:
    """Bounds and labels for one chart's value axis.

    §9.10.2: three labels, the two bounds and the midpoint, at a precision fixed per chart. The
    midpoint is exact rather than rounded for display — the bounds are snapped so that it lands on
    a value the label can state truthfully, which is the reason :func:`framed_axis` snaps the
    centre as well as the extent.
    """

    low: float
    high: float
    decimals: int

    @property
    def midpoint(self) -> float:
        return (self.low + self.high) / 2.0

    @property
    def span(self) -> float:
        return self.high - self.low

    def fraction_of(self, value: float) -> float:
        """Where ``value`` sits between the bounds, 0.0 at ``low`` and 1.0 at ``high``.

        Not clamped. A caller drawing into a rectangle should clamp; a caller deciding whether a
        sample fell outside the axis needs to be able to tell.
        """
        if self.span <= 0:
            return 0.5
        return (value - self.low) / self.span

    def labels(self) -> tuple[str, str, str]:
        """Low, middle, high — in that order, bottom to top."""
        return (
            _format(self.low, self.decimals),
            _format(self.midpoint, self.decimals),
            _format(self.high, self.decimals),
        )


def _format(value: float, decimals: int) -> str:
    """A number for an axis label, with U+2212 for the sign.

    §9.5.3's typesetting rules apply to an axis as much as to a readout, and a hyphen is not a
    minus. ``-0`` is normalised away: an axis whose midpoint is zero must not label it ``−0``.
    """
    text = f"{value:.{decimals}f}"
    if set(text) <= {"-", "0", ".", ","}:
        text = text.lstrip("-")
    return text.replace("-", "\N{MINUS SIGN}")


def _nice_ceiling(value: float) -> float:
    """The smallest conventional step that is at least ``value``."""
    if value <= 0 or not math.isfinite(value):
        return 0.0

    exponent = math.floor(math.log10(value))
    base = 10.0**exponent
    for multiple in _NICE:
        step = multiple * base
        if value <= step * (1.0 + 1e-12):
            return step
    return 10.0 * base


def _next_nice(step: float) -> float:
    """The step after this one. Used to widen an axis that does not yet contain its data."""
    if step <= 0:
        return 1.0
    exponent = math.floor(math.log10(step * (1.0 + 1e-12)))
    base = 10.0**exponent
    for multiple in _NICE:
        candidate = multiple * base
        if candidate > step * (1.0 + 1e-12):
            return candidate
    return 10.0 * base


def _finite(values: Sequence[float]) -> list[float]:
    return [value for value in values if math.isfinite(value)]


def zero_anchored_axis(
    values: Sequence[float],
    *,
    floor: float = TI_FLOOR_NANOSECONDS,
    decimals: int = TI_DECIMALS,
) -> Axis:
    """Symmetric about zero, for the 1 PPS chart.

    §10.7.1: the diverging fill's neutral midpoint must map to **exactly 0 ns**, which it can only
    do on an axis whose midpoint is zero. That is the whole reason this is a separate function
    from :func:`framed_axis` rather than a flag on it — anchoring the EFC chart this way is the
    defect #183 recorded, where 0.05 percentage points of real structure occupied a thousandth of
    the plot height.
    """
    finite = _finite(values)
    extent = max((abs(value) for value in finite), default=0.0)
    high = _nice_ceiling(max(extent, floor))
    return Axis(low=-high, high=high, decimals=decimals)


def framed_axis(
    values: Sequence[float],
    *,
    minimum_span: float = EFC_MINIMUM_SPAN_PERCENT,
    decimals: int = EFC_DECIMALS,
) -> Axis:
    """Framed on the window's own data, for the oscillator-control chart.

    §10.7.1: 0 % is one end of a control range whose absolute position is arbitrary, so the
    diagnostic content is the deviation and the axis follows the data. The minimum span keeps a
    quiet oscillator from being magnified into noise.

    **The centre is snapped as well as the extent**, and that is not tidiness. Snapping only the
    half-span leaves a midpoint like −16.825 on a chart whose labels are fixed at two decimals,
    so the middle gridline would be labelled −16.83 and sit somewhere else. An axis label that
    disagrees with its own gridline is worse than a coarse axis.
    """
    finite = _finite(values)
    if not finite:
        return Axis(low=0.0, high=minimum_span, decimals=decimals)

    lowest, highest = min(finite), max(finite)
    half = _nice_ceiling(max((highest - lowest) / 2.0, minimum_span / 2.0))
    centre = (lowest + highest) / 2.0

    # Widen until the snapped bounds actually contain the data. Snapping the centre can push a
    # bound past an extreme by up to half a step, so this is a loop rather than an assertion.
    for _ in range(8):
        snapped = round(centre / half) * half
        low, high = snapped - half, snapped + half
        if low <= lowest and highest <= high:
            return Axis(low=low, high=high, decimals=decimals)
        half = _next_nice(half)

    return Axis(low=lowest, high=highest, decimals=decimals)


def decimate(
    at: Sequence[float],
    values: Sequence[float],
    columns: int,
    *,
    start: float | None = None,
    end: float | None = None,
) -> tuple[Column, ...]:
    """Reduce a series to one column per pixel, keeping each column's extremes.

    §9.10.2, and the reason it is spelled out there: *"decimate by min/max per pixel column, never
    by sampling, or a 1-second glitch vanishes at the 7-day range."*

    ``start`` and ``end`` bound the time axis. They default to the data's own extent, and are
    parameters because a chart drawing a fixed range wants its columns to line up with that range
    rather than with whatever happened to be recorded in it — otherwise two charts sharing a range
    selector would disagree about where a given moment sits.

    **Empty columns are omitted rather than emitted as gaps of zero.** A column with no samples is
    a stretch when nothing was recorded, and the chart draws a break there; a zero would be a
    reading, and a reading of zero on a 1 PPS chart says the receiver was perfect.
    """
    if columns <= 0 or not len(at):
        return ()

    lower = at[0] if start is None else start
    upper = at[-1] if end is None else end
    span = upper - lower

    if span <= 0:
        # Every sample at one instant — a single reading, or a window one poll wide.
        finite = _finite(values)
        if not finite:
            return ()
        return (Column(index=0, at=lower, low=min(finite), high=max(finite), count=len(finite)),)

    width = span / columns
    lows: dict[int, float] = {}
    highs: dict[int, float] = {}
    counts: dict[int, int] = {}

    for moment, value in zip(at, values, strict=True):
        if not math.isfinite(value):
            continue
        index = int((moment - lower) / width)
        # A sample exactly on the upper bound belongs to the last column, not to one past the end.
        index = min(columns - 1, max(0, index))

        if index in lows:
            lows[index] = min(lows[index], value)
            highs[index] = max(highs[index], value)
            counts[index] += 1
        else:
            lows[index] = highs[index] = value
            counts[index] = 1

    return tuple(
        Column(
            index=index,
            at=lower + (index + 0.5) * width,
            low=lows[index],
            high=highs[index],
            count=counts[index],
        )
        for index in sorted(lows)
    )


def unlocked_runs(series: Series) -> tuple[tuple[float, float], ...]:
    """The stretches where the receiver was not locked, as epoch-second ranges.

    §10.7.1 shades these on the 1 PPS chart. Returned as ranges rather than as a per-sample flag so
    the chart draws one rectangle per stretch — at the 7-day range a per-sample flag would be
    604 800 decisions to make the same shape.

    A run is closed at the first locked sample after it, so a stretch that is still open at the end
    of the window runs to the last sample rather than to the window's edge: the record ends where
    the readings end, and drawing past that would claim knowledge of a period nothing was recorded
    in.
    """
    runs: list[tuple[float, float]] = []
    opened: float | None = None

    for index, mode in enumerate(series.mode):
        if mode is not SmartClockMode.LOCKED:
            if opened is None:
                opened = series.at[index]
        elif opened is not None:
            runs.append((opened, series.at[index]))
            opened = None

    if opened is not None and len(series.at):
        runs.append((opened, series.at[-1]))

    return tuple(runs)
