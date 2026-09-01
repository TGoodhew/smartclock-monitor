"""§10.5's *Save image*: the sky card as a PNG, for a calibration record.

OQ-D6 assumed no image export in v1 on the grounds that "export is CSV only", and #47 overturned
that as answering a different question than the one asked. A CSV of azimuth, elevation and signal
strength is a *table*; a calibration record wants evidence of **what the sky looked like from this
antenna**, and the argument #185 settled — a rack mean of 1.94 satellites against a backyard mean
of 6.59 — is not one anybody makes with a spreadsheet.

Three properties §10.5 makes normative rather than incidental:

1. **The capture is the live card**, grabbed from the element already on screen. Not a second
   renderer — a separate drawing path is free to disagree with the one the user reviewed, and a
   record that differs from the screen it claims to record is worse than no record.
2. **The image carries a caption the screen does not**: product name, capture time **in UTC**,
   tracked and predicted counts, and the elevation mask in force. The mask is not decoration — the
   same sky under a 10° mask and a 25° mask produces two legitimate plots with different
   satellites missing, so a record omitting it cannot be compared with anything.
3. **No theme substitution.** The export is whatever theme the user is in. A picture that came
   back in colours the user had not chosen would not be the thing they were looking at, and
   §9.4.3's colour + shape + text encoding is what keeps a greyscale printout readable — so
   nothing is lost by declining to force a light theme on the way out.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QWidget

from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import Palette
from smartclock_monitor.themes.typography import Type

#: How tall the caption band is.
_CAPTION_HEIGHT = 56


@dataclass(frozen=True, slots=True)
class Caption:
    """What the image says that the screen does not."""

    captured_at: datetime | None
    tracked: int
    predicted: int
    elevation_mask_degrees: int | None

    #: §10.5: offered only while the plot has satellites on it. An empty export is a picture of
    #: three rings, which reads as a working antenna seeing nothing rather than as a receiver that
    #: is not connected.
    @property
    def is_worth_saving(self) -> bool:
        return self.tracked + self.predicted > 0

    def lines(self) -> tuple[str, str]:
        when = (
            "capture time unknown"
            if self.captured_at is None
            else self.captured_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        )
        mask = (
            "elevation mask not reported"
            if self.elevation_mask_degrees is None
            else f"elevation mask {self.elevation_mask_degrees}\N{DEGREE SIGN}"
        )
        return (
            "SmartClock Monitor — sky plot",
            f"{when} · {self.tracked} tracked, {self.predicted} predicted · {mask}",
        )


def render(card: QWidget, caption: Caption, palette: Palette) -> QImage:
    """Grab the card and add the caption band beneath it.

    The palette is the one the card is already drawn in — passed rather than chosen, so the caption
    cannot end up in a different theme from the plot above it.
    """
    plot = card.grab().toImage()

    image = QImage(
        plot.width(), plot.height() + _CAPTION_HEIGHT, QImage.Format.Format_ARGB32_Premultiplied
    )
    image.fill(QColor(palette.card_fill))

    painter = QPainter(image)
    painter.drawImage(0, 0, plot)

    painter.setPen(QColor(palette.stroke_subtle))
    painter.drawLine(0, plot.height(), plot.width(), plot.height())

    title, detail = caption.lines()

    font = QFont(painter.font())
    font.setPointSize(Type.CAPTION.size)
    font.setWeight(QFont.Weight.DemiBold)
    painter.setFont(font)
    painter.setPen(QColor(palette.text_primary))
    painter.drawText(
        Spacing.MEDIUM,
        plot.height() + Spacing.LARGE,
        title,
    )

    font.setWeight(QFont.Weight.Normal)
    painter.setFont(font)
    painter.setPen(QColor(palette.text_secondary))
    painter.drawText(
        Spacing.MEDIUM,
        plot.height() + Spacing.LARGE + Spacing.CARD_PADDING,
        detail,
    )
    painter.end()

    return image


def suggested_name(captured_at: datetime | None) -> str:
    stamp = "unknown" if captured_at is None else captured_at.strftime("%Y%m%d-%H%M%S")
    return f"smartclock-sky-{stamp}.png"
