"""The §9.10 severity pill: colour **and** shape **and** text, drawn once and reused.

§9.13's third prohibition — severity never renders as colour alone — is implemented here and
nowhere else. Every severity surface in the application uses this control rather than hand-rolling
a coloured dot, which is the only way a rule like that survives contact with a growing UI.

The shapes are drawn as geometry rather than as glyphs from a font. §9.4.3 is explicit about why:
a glyph depends on a font being present and on the renderer picking the right face, and under high
contrast a path resolves to an outline while a glyph may not resolve at all.

**Colours come from the palette, never from QSS.** A widget that painted from a stylesheet would
keep the old theme's colours until it was recreated, so this takes a palette and repaints.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget

from smartclock_monitor.themes.severity import SHAPE_BOX, Severity, Shape, colour_for
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette


def shape_path(shape: Shape, box: float) -> QPainterPath:
    """The geometry for one severity shape, on a square of side ``box``.

    Separated from the painting so the geometry is testable without a display — the same reason
    §9.10's maths lives apart from its drawing in the original.
    """
    path = QPainterPath()
    half = box / 2

    match shape:
        case Shape.CIRCLE:
            path.addEllipse(QRectF(0, 0, box, box))
        case Shape.TRIANGLE:
            path.moveTo(half, 0)
            path.lineTo(box, box)
            path.lineTo(0, box)
            path.closeSubpath()
        case Shape.HEXAGON:
            # Flat-topped, so it reads as distinct from the circle at small sizes.
            quarter = box / 4
            path.moveTo(quarter, 0)
            path.lineTo(box - quarter, 0)
            path.lineTo(box, half)
            path.lineTo(box - quarter, box)
            path.lineTo(quarter, box)
            path.lineTo(0, half)
            path.closeSubpath()
        case Shape.INFO:
            # A circle with a bar through it: distinguishable from plain circle by silhouette.
            path.addEllipse(QRectF(0, 0, box, box))
            path.addRect(QRectF(half - box / 10, box * 0.3, box / 5, box * 0.45))
        case Shape.RING:
            path.addEllipse(QRectF(0, 0, box, box))
            path.addEllipse(QRectF(box / 4, box / 4, half, half))

    return path


class SeverityPill(QWidget):
    """One severity, rendered as all three channels at once."""

    def __init__(
        self,
        severity: Severity = Severity.NEUTRAL,
        text: str = "",
        palette: Palette = LIGHT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._severity = severity
        self._text = text
        self._palette = palette
        self.setMinimumHeight(Spacing.LARGE)
        self._apply_accessible_name()

    def set_state(self, severity: Severity, text: str) -> None:
        """Change what is shown. Both channels together, because one without the other is the
        defect this control exists to prevent."""
        self._severity = severity
        self._text = text
        self._apply_accessible_name()
        self.update()

    def set_palette_tokens(self, palette: Palette) -> None:
        """Repaint in a new theme."""
        self._palette = palette
        self.update()

    @property
    def severity(self) -> Severity:
        return self._severity

    @property
    def text(self) -> str:
        return self._text

    @property
    def palette_tokens(self) -> Palette:
        """Which token set this is painting with. Named to avoid colliding with ``QWidget.palette``,
        which is Qt's own and a different thing entirely."""
        return self._palette

    def _apply_accessible_name(self) -> None:
        """§9.12: the severity reaches an assistive technology as words, not as a colour.

        A screen reader cannot see the shape either, so the name carries both the severity and the
        label — the text channel is what survives when neither visual channel does.
        """
        label = self._text or self._severity.name.title()
        self.setAccessibleName(f"{self._severity.name.title()}: {label}")

    def sizeHint(self):  # type: ignore[no-untyped-def]  # noqa: N802 - Qt's own casing
        metrics = self.fontMetrics()
        width = SHAPE_BOX + Spacing.SMALL + metrics.horizontalAdvance(self._text) + Spacing.SMALL
        return QRectF(0, 0, width, max(Spacing.LARGE, metrics.height())).size().toSize()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802 - Qt's own casing
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        colour = QColor(colour_for(self._severity, self._palette))
        shape, default_label = _shape_and_label(self._severity)

        # Channel 1 and 2: colour and shape, together.
        box = float(SHAPE_BOX)
        top = (self.height() - box) / 2
        painter.save()
        painter.translate(QPointF(0, top))
        path = shape_path(shape, box)
        painter.setBrush(colour)
        painter.setPen(QPen(colour, 1))
        painter.drawPath(path)
        painter.restore()

        # Channel 3: the word. Never omitted — §9.13's rule is a triple, not a pair.
        painter.setPen(QColor(self._palette.text_primary))
        text_left = box + Spacing.SMALL
        painter.drawText(
            QRectF(text_left, 0, self.width() - text_left, self.height()),
            int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft),
            self._text or default_label,
        )
        painter.end()


def _shape_and_label(severity: Severity) -> tuple[Shape, str]:
    from smartclock_monitor.themes.severity import SEVERITY_SHAPES

    return SEVERITY_SHAPES[severity]
