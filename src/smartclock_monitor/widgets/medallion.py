"""The §9.10.2 status medallion: the control the main window is built around.

A ring that carries the receiver's state, with the thing a user actually leans in to read at its
centre. G1 measures the main window on exactly this: mode and tracked-satellite count legible at
two metres, in a window no larger than 420 by 260.

**The centre shows the tracked-satellite count, not the mode.** §9.6.2 keeps only two things in the
compact layout — the mode text and the count — and both have to be legible at two metres. The count
is the number that changes and the one that answers "is it working right now", so it takes the
centre; the mode is the ring's colour and the label beneath it.

**Severity is never the ring's colour alone.** The ring carries the colour, the label beneath
carries the word, and the tick marks carry a shape that differs per state — three channels, per
§9.13.

The geometry is separated from the painting so it can be tested with no display, which is what the
original does with ``MedallionRingMath`` for the same reason.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from smartclock_monitor.themes.severity import Severity, colour_for
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.themes.typography import Type

#: How thick the ring is, as a fraction of its diameter.
_RING_FRACTION = 0.11

#: How many ticks the ring carries. Twelve reads as a dial without looking like a clock face.
_TICKS = 12


@dataclass(frozen=True, slots=True)
class RingGeometry:
    """Where the ring is drawn, given a widget size.

    Pure arithmetic, no Qt drawing, so the layout is testable headlessly.
    """

    centre_x: float
    centre_y: float
    radius: float
    thickness: float

    @property
    def bounds(self) -> QRectF:
        return QRectF(
            self.centre_x - self.radius,
            self.centre_y - self.radius,
            self.radius * 2,
            self.radius * 2,
        )


def ring_geometry(width: float, height: float) -> RingGeometry:
    """The ring for a widget of this size.

    Always a circle inscribed in the shorter side, so the medallion never distorts when the window
    is resized to an awkward shape — §9.6.1's breakpoints move the layout around it rather than
    stretching it.
    """
    shorter = max(1.0, min(width, height))
    thickness = shorter * _RING_FRACTION
    radius = (shorter - thickness) / 2
    return RingGeometry(width / 2, height / 2, radius, thickness)


def tick_positions(geometry: RingGeometry, count: int = _TICKS) -> list[tuple[QPointF, QPointF]]:
    """The inner and outer end of each tick, clockwise from the top."""
    ticks: list[tuple[QPointF, QPointF]] = []
    outer = geometry.radius + geometry.thickness / 2
    inner = geometry.radius + geometry.thickness / 6

    for index in range(count):
        angle = -math.pi / 2 + (2 * math.pi * index / count)
        cos, sin = math.cos(angle), math.sin(angle)
        ticks.append(
            (
                QPointF(geometry.centre_x + inner * cos, geometry.centre_y + inner * sin),
                QPointF(geometry.centre_x + outer * cos, geometry.centre_y + outer * sin),
            )
        )
    return ticks


#: How much of the ring each severity fills, and how many ticks it draws.
#:
#: The **shape channel**: a locked receiver draws a complete ring with every tick, holdover draws a
#: broken one with a quarter of them. Someone who cannot separate the green from the red can still
#: separate a full ring from a broken one at two metres.
_SWEEP: dict[Severity, tuple[float, int]] = {
    Severity.SUCCESS: (1.0, _TICKS),
    Severity.CAUTION: (0.66, _TICKS // 2),
    Severity.CRITICAL: (0.33, _TICKS // 4),
    Severity.INFO: (0.5, _TICKS // 2),
    Severity.NEUTRAL: (0.0, 0),
}


class StatusMedallion(QWidget):
    """The signature control."""

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._severity = Severity.NEUTRAL
        self._centre_value = "—"
        self._caption = "Disconnected"
        self.setMinimumSize(96, 96)
        self._apply_accessible_name()

    def set_state(self, severity: Severity, centre_value: str, caption: str) -> None:
        """All three channels at once. There is no setter for the colour alone, on purpose."""
        self._severity = severity
        self._centre_value = centre_value
        self._caption = caption
        self._apply_accessible_name()
        self.update()

    def set_palette_tokens(self, palette: Palette) -> None:
        self._palette = palette
        self.update()

    @property
    def palette_tokens(self) -> Palette:
        """Which token set this is painting with. Named to avoid colliding with
        ``QWidget.palette``, which is Qt's own and a different thing entirely."""
        return self._palette

    @property
    def severity(self) -> Severity:
        return self._severity

    def _apply_accessible_name(self) -> None:
        """§9.12. The medallion is the primary readout, so it has to say what it shows in words."""
        self.setAccessibleName(f"{self._caption}, {self._centre_value} satellites tracked")

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's own casing
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        geometry = ring_geometry(self.width(), self.height())
        colour = QColor(colour_for(self._severity, self._palette))
        sweep, ticks = _SWEEP[self._severity]

        # The track the ring sits in, so an incomplete ring reads as incomplete rather than as a
        # rendering failure.
        painter.setPen(QPen(QColor(self._palette.stroke_subtle), geometry.thickness))
        painter.drawArc(geometry.bounds, 0, 360 * 16)

        if sweep > 0:
            pen = QPen(colour, geometry.thickness)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            # Qt measures arcs in sixteenths of a degree, anticlockwise from three o'clock.
            painter.drawArc(geometry.bounds, 90 * 16, -int(360 * 16 * sweep))

        painter.setPen(QPen(colour, max(1.0, geometry.thickness / 4)))
        for start, end in tick_positions(geometry, ticks) if ticks else []:
            painter.drawLine(start, end)

        # The centre: the number G1 is measured on.
        font = QFont(painter.font())
        font.setPointSize(max(Type.READOUT_SMALL.size, int(geometry.radius * 0.6)))
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(self._palette.text_primary))
        painter.drawText(
            geometry.bounds,
            int(Qt.AlignmentFlag.AlignCenter),
            self._centre_value,
        )
        painter.end()
