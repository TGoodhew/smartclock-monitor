"""The §10.5 sky plot: where the satellites actually are.

**Markers are real focusable child objects, not painted geometry.** §9.10.2 requires this and the
port plan repeats it: *do not paint dots and bolt on a hand-written peer*. A marker that is a real
widget gets into the accessibility tree by construction, takes focus by construction, and reports
its own name — where a painted dot needs every one of those things reimplemented, and the
reimplementation is what rots.

Keyboard: arrow keys move between markers **in PRN order**, Enter selects. PRN order rather than
spatial order because it is stable — a spatial traversal reorders itself every time a satellite
moves, and a user who has learnt that the third stop is PRN 19 would be wrong a minute later.

§9.10.2 also requires a list alternate view for users who cannot use the spatial form. That lives
on the Satellites page, beside the plot, rather than as a toggle — the table is useful to everyone
and hiding it behind a mode switch would make it a second-class view of the same data.
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFocusEvent, QKeyEvent, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from smartclock_device.models.receiver_status import SignalStrengthKind
from smartclock_device.models.satellite import PredictedSatellite, TrackedSatellite
from smartclock_monitor.themes.spacing import MINIMUM_POINTER_TARGET, Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.widgets.sky_plot_geometry import (
    Disc,
    describe,
    disc_for,
    elevation_ring,
    marker_size,
    position,
)

#: The elevations that get a gridline, besides the rim and the mask.
_GRID_ELEVATIONS = (30.0, 60.0)


@dataclass(frozen=True, slots=True)
class Marker:
    """One satellite on the plot."""

    prn: int
    elevation: int | None
    azimuth: int | None
    strength: int | None
    tracked: bool

    @property
    def is_placeable(self) -> bool:
        """Whether it can be drawn at all.

        A satellite with no elevation or azimuth has no position, and putting it at the centre —
        which is what a ``None`` treated as zero would do — would claim it is directly overhead.
        It belongs in the table instead.
        """
        return self.elevation is not None and self.azimuth is not None


def markers_from(
    tracked: tuple[TrackedSatellite, ...], not_tracked: tuple[PredictedSatellite, ...]
) -> tuple[Marker, ...]:
    """Both column groups, in PRN order.

    Predicted satellites carry no signal strength — there is no signal to report — which is the
    structural difference the parser uses to tell the two groups apart, and it survives to here.
    """
    markers = [
        Marker(s.prn, s.elevation_degrees, s.azimuth_degrees, s.signal_strength, tracked=True)
        for s in tracked
    ]
    markers += [
        Marker(s.prn, s.elevation_degrees, s.azimuth_degrees, None, tracked=False)
        for s in not_tracked
    ]
    return tuple(sorted(markers, key=lambda marker: marker.prn))


class SatelliteMarker(QWidget):
    """One marker: a real widget, so the accessibility tree is correct by construction."""

    selected = Signal(int)

    def __init__(
        self,
        marker: Marker,
        kind: SignalStrengthKind,
        palette: Palette,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._marker = marker
        self._kind = kind
        self._palette = palette
        self._is_selected = False

        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        # §9.12's pointer-target floor. The ink may be 8 px; the target is not.
        self.setFixedSize(MINIMUM_POINTER_TARGET, MINIMUM_POINTER_TARGET)
        self.setAccessibleName(
            describe(
                marker.prn,
                marker.elevation,
                marker.azimuth,
                marker.strength,
                kind,
                tracked=marker.tracked,
            )
        )
        self.setToolTip(self.accessibleName())

    @property
    def marker(self) -> Marker:
        return self._marker

    def set_selected(self, selected: bool) -> None:
        self._is_selected = selected
        self.update()

    def set_palette_tokens(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 - Qt's own casing
        del event
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        self.selected.emit(self._marker.prn)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt's own casing
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.selected.emit(self._marker.prn)
            return
        # Arrow keys belong to the plot, which owns the PRN ordering.
        event.ignore()

    def focusInEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt's own casing
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802 - Qt's own casing
        super().focusOutEvent(event)
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's own casing
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        size = marker_size(self._marker.strength, self._kind)
        centre = self.rect().center()
        box = QRectF(centre.x() - size / 2, centre.y() - size / 2, size, size)

        # Tracked is filled; predicted is an outline. A second channel beside the colour, so the
        # two groups stay distinguishable in greyscale and under every theme.
        colour = QColor(self._palette.series[self._marker.prn % len(self._palette.series)])
        if self._marker.tracked:
            painter.setBrush(colour)
            painter.setPen(QPen(colour, 1))
        else:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            pen = QPen(QColor(self._palette.text_secondary), 1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
        painter.drawEllipse(box)

        if self._is_selected or self.hasFocus():
            # §9.12's focus visual: two strokes spanning the luminance range, so no accent colour
            # can hide the ring against whatever it lands on.
            outer = box.adjusted(-4, -4, 4, 4)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(self._palette.page_background), 3))
            painter.drawEllipse(outer)
            painter.setPen(QPen(QColor(self._palette.accent), 1.5))
            painter.drawEllipse(outer)

        painter.end()


class SkyPlot(QWidget):
    """The polar plot, and the markers that live on it."""

    satellite_selected = Signal(int)

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._markers: list[SatelliteMarker] = []
        self._kind = SignalStrengthKind.UNKNOWN
        self._mask_degrees: int | None = None
        self._selected_prn: int | None = None

        self.setMinimumSize(240, 240)
        # §9.6.1 caps it at 360 and stacks the table beneath rather than stretching it: an
        # elliptical sky plot misplaces every satellite on it.
        self.setMaximumSize(360, 360)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("Sky plot")

    # -- Data ----------------------------------------------------------------------------------

    def set_satellites(
        self,
        tracked: tuple[TrackedSatellite, ...],
        not_tracked: tuple[PredictedSatellite, ...],
        kind: SignalStrengthKind,
        mask_degrees: int | None,
    ) -> None:
        self._kind = kind
        self._mask_degrees = mask_degrees

        wanted = [marker for marker in markers_from(tracked, not_tracked) if marker.is_placeable]

        # Rebuilt rather than reconciled. The set changes rarely — once every ten seconds at most,
        # and usually not at all — and a reconciliation that got focus restoration subtly wrong
        # would be a bug nobody could reproduce.
        for existing in self._markers:
            existing.setParent(None)
            existing.deleteLater()
        self._markers = []

        for marker in wanted:
            widget = SatelliteMarker(marker, kind, self._palette, self)
            widget.selected.connect(self._on_marker_selected)
            widget.show()
            self._markers.append(widget)

        self._place_markers()
        self.update()

    def set_palette_tokens(self, palette: Palette) -> None:
        self._palette = palette
        for marker in self._markers:
            marker.set_palette_tokens(palette)
        self.update()

    @property
    def markers(self) -> tuple[SatelliteMarker, ...]:
        """In PRN order, which is the order the keyboard walks them in."""
        return tuple(self._markers)

    @property
    def selected_prn(self) -> int | None:
        return self._selected_prn

    # -- Layout --------------------------------------------------------------------------------

    def _disc(self) -> Disc:
        # The margin has to leave room for the compass labels *outside* the rim. At Spacing.MEDIUM
        # the "W" and "S" were drawn past the widget's own edge and clipped to half a glyph, which
        # read as a rendering fault rather than as a label.
        return disc_for(self.width(), self.height(), margin=Spacing.LARGE)

    def _place_markers(self) -> None:
        disc = self._disc()
        for widget in self._markers:
            marker = widget.marker
            if marker.elevation is None or marker.azimuth is None:  # pragma: no cover - filtered
                continue
            x, y = position(disc, marker.elevation, marker.azimuth)
            widget.move(QPoint(int(x - widget.width() / 2), int(y - widget.height() / 2)))

    def resizeEvent(self, event: object) -> None:  # noqa: N802 - Qt's own casing
        del event
        self._place_markers()

    # -- Interaction ---------------------------------------------------------------------------

    def _on_marker_selected(self, prn: int) -> None:
        self._selected_prn = prn
        for widget in self._markers:
            widget.set_selected(widget.marker.prn == prn)
        self.satellite_selected.emit(prn)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802 - Qt's own casing
        """Arrow keys walk the markers in PRN order.

        **PRN order, not spatial order**, because it is stable: a spatial traversal reorders itself
        every time a satellite moves, and a user who has learnt that the third stop is PRN 19 would
        be wrong a minute later.
        """
        if not self._markers:
            super().keyPressEvent(event)
            return

        step = {
            Qt.Key.Key_Right: 1,
            Qt.Key.Key_Down: 1,
            Qt.Key.Key_Left: -1,
            Qt.Key.Key_Up: -1,
        }.get(Qt.Key(event.key()))

        if step is None:
            super().keyPressEvent(event)
            return

        current = next(
            (index for index, w in enumerate(self._markers) if w.marker.prn == self._selected_prn),
            -1,
        )
        nxt = (current + step) % len(self._markers)
        self._markers[nxt].setFocus(Qt.FocusReason.OtherFocusReason)
        self._on_marker_selected(self._markers[nxt].marker.prn)

    # -- Painting ------------------------------------------------------------------------------

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's own casing
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        disc = self._disc()

        grid = QPen(QColor(self._palette.stroke_default), 1)
        painter.setPen(grid)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(_circle(disc, disc.radius))

        subtle = QPen(QColor(self._palette.stroke_subtle), 1)
        painter.setPen(subtle)
        for elevation in _GRID_ELEVATIONS:
            painter.drawEllipse(_circle(disc, elevation_ring(disc, elevation)))

        # The elevation mask, dashed, because it is a setting rather than a measurement — a
        # satellite below it is being ignored on purpose, and the line should read as a rule.
        if self._mask_degrees is not None:
            mask = QPen(QColor(self._palette.caution), 1.5)
            mask.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(mask)
            painter.drawEllipse(_circle(disc, elevation_ring(disc, self._mask_degrees)))

        painter.setPen(QPen(QColor(self._palette.text_tertiary), 1))
        # Half the label box sits outside the rim, which is why the disc's margin is a full
        # Spacing.LARGE: radius + MEDIUM + MEDIUM lands exactly on the widget's edge.
        half = Spacing.MEDIUM
        for label, (dx, dy) in (
            ("N", (0, -1)),
            ("E", (1, 0)),
            ("S", (0, 1)),
            ("W", (-1, 0)),
        ):
            x = disc.centre_x + dx * (disc.radius + half)
            y = disc.centre_y + dy * (disc.radius + half)
            painter.drawText(
                QRectF(x - half, y - half, half * 2, half * 2),
                int(Qt.AlignmentFlag.AlignCenter),
                label,
            )
        painter.end()


def _circle(disc: Disc, radius: float) -> QRectF:
    return QRectF(disc.centre_x - radius, disc.centre_y - radius, radius * 2, radius * 2)
