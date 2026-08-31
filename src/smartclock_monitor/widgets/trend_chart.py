"""§9.10.2's ``TrendChart``: a hand-drawn line chart with a time axis and two y-axis modes.

Hand-drawn is the design rather than a fallback — OQ-5 (#38) rejected a charting library, and the
requirements this has to meet are ones a general-purpose library makes harder rather than easier:
min/max decimation that cannot drop an excursion, a colour break pinned to exactly zero, and an
axis whose three labels are snapped so they can be stated truthfully at a fixed precision.

**All the arithmetic lives in ``chart_geometry``.** This file positions the result and paints it.
That split is what lets the properties worth asserting — that a one-second glitch survives the
7-day range, that the EFC midpoint lands on a label it can state — be tested without a display.

**No animation.** The medallion's sparkline says so explicitly (§9.10.2) and the same reasoning
applies here: a trace that eases into place is a trace that is wrong for the duration of the ease,
on a chart someone is reading to find out when something happened.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from smartclock_monitor.services.trend_store import Series, empty_series
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.themes.typography import Type
from smartclock_monitor.widgets.chart_geometry import (
    Axis,
    Column,
    decimate,
    framed_axis,
    unlocked_runs,
    zero_anchored_axis,
)

#: Room on the left for the three axis labels. §9.6's scale does not have a token for "as wide as
#: the widest label", so this is a reserved gutter rather than a measured one — a gutter that
#: changed width with the data would make two stacked charts disagree about where time starts.
_GUTTER = 56

#: How tall the chart is, minimum. Below this the three axis labels collide with each other.
_MINIMUM_HEIGHT = 96

#: Which categorical entry the framed chart's single stroke takes.
#:
#: §10.7.1: the EFC series "carries no colour-borne value at all — its diagnostic content is
#: entirely in the shape of the trace", so the stroke needs to be one colour and always the same
#: one. Fixed by index rather than chosen per theme, because §9.4.4 binds a hue to an index in
#: both themes precisely so a series does not change identity when the desktop theme does.
_FRAMED_SERIES: Final = 6


class AxisMode(Enum):
    """Which of §10.7.1's two axis treatments this chart uses.

    Two modes rather than a flag on one, mirroring ``chart_geometry``: #183 records what happened
    when the EFC chart was drawn through the zero-anchored path, and the enum is the reason a
    caller has to say which it means.
    """

    #: Symmetric about exactly 0, with the §9.4.4 diverging fill. The 1 PPS chart.
    ZERO_ANCHORED = "zero-anchored"

    #: Framed on the window's own data, with a single categorical stroke. The EFC chart.
    FRAMED = "framed"


@dataclass(frozen=True, slots=True)
class Plot:
    """What one paint pass decided to draw. Read by tests, which should assert the decisions
    rather than the pixels they produce."""

    axis: Axis
    columns: tuple[Column, ...]
    unlocked: tuple[tuple[float, float], ...]
    start: float
    end: float


class TrendChart(QWidget):
    """One series against time."""

    def __init__(
        self,
        title: str,
        mode: AxisMode,
        unit: str,
        palette: Palette = LIGHT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._mode = mode
        self._unit = unit
        self._palette = palette
        self._series: Series = empty_series()
        self._shade_unlocked = mode is AxisMode.ZERO_ANCHORED

        self.setMinimumHeight(_MINIMUM_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAccessibleName(title)
        self._describe()

    # -- What the page sets ------------------------------------------------------------------

    def set_palette_tokens(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def show_series(self, series: Series) -> None:
        self._series = series
        self._describe()
        self.update()

    @property
    def series(self) -> Series:
        return self._series

    @property
    def mode(self) -> AxisMode:
        return self._mode

    # -- What it works out -------------------------------------------------------------------

    def _values(self) -> Sequence[float]:
        if self._mode is AxisMode.ZERO_ANCHORED:
            return self._series.ti_nanoseconds
        return self._series.efc_percent

    def axis(self) -> Axis:
        values = self._values()
        if self._mode is AxisMode.ZERO_ANCHORED:
            return zero_anchored_axis(values)
        return framed_axis(values)

    def plot(self, width: int | None = None) -> Plot:
        """Everything a paint pass needs, without painting.

        Exposed because it is the honest seam for a test: the questions worth asking of a chart —
        does the axis contain the data, did the excursion survive, is the unlocked stretch shaded
        — are all answered here, and none of them is a question about pixels.
        """
        series = self._series
        columns_available = max(1, (self.width() if width is None else width) - _GUTTER)

        if not series:
            return Plot(axis=self.axis(), columns=(), unlocked=(), start=0.0, end=0.0)

        start, end = series.at[0], series.at[-1]
        values = self._values()

        return Plot(
            axis=self.axis(),
            columns=decimate(series.at, values, columns_available, start=start, end=end),
            unlocked=unlocked_runs(series) if self._shade_unlocked else (),
            start=start,
            end=end,
        )

    def _describe(self) -> None:
        """The text alternative. A11Y-12's rule is that meaning never rests on colour alone, and a
        chart is the case where it would rest on *shape* alone — so the summary states the range
        the trace covers and how much of the requested window was found."""
        series = self._series
        if not series:
            self.setAccessibleDescription(f"{self._title}: no readings stored yet.")
            return

        values = [value for value in self._values() if math.isfinite(value)]
        if not values:
            self.setAccessibleDescription(f"{self._title}: no readings in this window.")
            return

        hours = series.span.total_seconds() / 3600.0
        self.setAccessibleDescription(
            f"{self._title}: {len(values)} readings over {hours:.1f} hours, "
            f"from {min(values):.2f} to {max(values):.2f} {self._unit}."
        )

    # -- Painting ----------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's own casing
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        plot = self.plot()
        frame = QRectF(
            _GUTTER,
            Spacing.TIGHT,
            max(1.0, self.width() - _GUTTER - Spacing.TIGHT),
            max(1.0, self.height() - 2 * Spacing.TIGHT),
        )

        self._paint_labels(painter, plot.axis, frame)
        self._paint_unlocked(painter, plot, frame)
        self._paint_midline(painter, plot.axis, frame)
        self._paint_columns(painter, plot, frame)

        painter.end()

    def _y_of(self, axis: Axis, value: float, frame: QRectF) -> float:
        fraction = min(1.0, max(0.0, axis.fraction_of(value)))
        return frame.bottom() - fraction * frame.height()

    def _paint_labels(self, painter: QPainter, axis: Axis, frame: QRectF) -> None:
        font = QFont(painter.font())
        font.setPointSize(Type.CAPTION.size)
        painter.setFont(font)
        painter.setPen(QPen(QColor(self._palette.text_tertiary), 1))

        low, middle, high = axis.labels()
        for text, value in ((high, axis.high), (middle, axis.midpoint), (low, axis.low)):
            y = self._y_of(axis, value, frame)
            box = QRectF(0.0, y - 9.0, _GUTTER - Spacing.SMALL, 18.0)
            painter.drawText(box, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, text)

    def _paint_midline(self, painter: QPainter, axis: Axis, frame: QRectF) -> None:
        """The midpoint gridline. On the 1 PPS chart this is zero, and it is the reference the
        whole diverging fill is read against."""
        pen = QPen(QColor(self._palette.stroke_default), 1)
        pen.setStyle(Qt.PenStyle.DashLine)
        painter.setPen(pen)
        y = self._y_of(axis, axis.midpoint, frame)
        painter.drawLine(QPointF(frame.left(), y), QPointF(frame.right(), y))

    def _paint_unlocked(self, painter: QPainter, plot: Plot, frame: QRectF) -> None:
        """§10.7.1's shading. Drawn under the trace so it reads as ground rather than as ink."""
        if not plot.unlocked or plot.end <= plot.start:
            return

        shade = QColor(self._palette.card_fill_secondary)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(shade)
        span = plot.end - plot.start

        for opened, closed in plot.unlocked:
            left = frame.left() + (opened - plot.start) / span * frame.width()
            right = frame.left() + (closed - plot.start) / span * frame.width()
            painter.drawRect(QRectF(left, frame.top(), max(1.0, right - left), frame.height()))

    def _paint_columns(self, painter: QPainter, plot: Plot, frame: QRectF) -> None:
        if not plot.columns:
            return

        axis = plot.axis
        columns_available = max(1, int(frame.width()))
        baseline = self._y_of(axis, axis.midpoint, frame)

        for column in plot.columns:
            x = frame.left() + (column.index + 0.5) / columns_available * frame.width()
            top = self._y_of(axis, column.high, frame)
            bottom = self._y_of(axis, column.low, frame)

            if self._mode is AxisMode.ZERO_ANCHORED:
                # A diverging area anchored on the midline: the bar runs from zero to the reading,
                # so its length is the departure and its colour is the sign and size of it.
                extreme = column.high if abs(column.high) >= abs(column.low) else column.low
                painter.setPen(QPen(self._diverging_for(extreme, axis), 1.0))
                painter.drawLine(QPointF(x, baseline), QPointF(x, self._y_of(axis, extreme, frame)))
                painter.drawLine(QPointF(x, top), QPointF(x, bottom))
            else:
                painter.setPen(QPen(QColor(self._palette.series[_FRAMED_SERIES]), 1.0))
                painter.drawLine(QPointF(x, top), QPointF(x, max(bottom, top + 1.0)))

    def _diverging_for(self, value: float, axis: Axis) -> QColor:
        """One of §9.4.4's five diverging stops, never a blend of two.

        Every colour drawn is therefore a token, which is what keeps §9.13's first prohibition
        checkable — an interpolated ramp would paint colours that appear nowhere in the table and
        the gate could not tell those from a hard-coded one.

        The middle stop is reserved for values at the midpoint, so on the 1 PPS chart it means
        *exactly zero* and cannot drift onto a merely small reading.
        """
        stops = self._palette.diverging
        if axis.high <= axis.midpoint:
            return QColor(stops[2])

        fraction = (value - axis.midpoint) / (axis.high - axis.midpoint)
        if fraction <= -0.5:
            return QColor(stops[0])
        if fraction < 0.0:
            return QColor(stops[1])
        if fraction == 0.0:
            return QColor(stops[2])
        if fraction < 0.5:
            return QColor(stops[3])
        return QColor(stops[4])
