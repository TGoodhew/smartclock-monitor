"""Generates the Qt stylesheet from the token table (§6.4's QSS note).

**QSS is not XAML resources.** It has no theme dictionaries and no live resource resolution, so a
stylesheet cannot reference a token and re-resolve it when the theme changes. The answer §6.4
gives, and the one implemented here: generate the whole sheet from the token table at startup and
on every theme change, and re-apply it to the application.

The corollary matters as much: **custom widgets do not take their colours from QSS at all.** They
are handed a :class:`~smartclock_monitor.themes.tokens.Palette` and repaint. A widget that painted
from a stylesheet would keep the old theme's colours until it was recreated.

Nothing here writes a colour. Every value comes from the palette, which is what keeps §9.13's "no
hex outside the token file" checkable rather than aspirational.
"""

from __future__ import annotations

from smartclock_monitor.themes.spacing import Radius, Spacing
from smartclock_monitor.themes.tokens import Palette
from smartclock_monitor.themes.typography import Type, TypeStyle


def font_stack(style: TypeStyle) -> str:
    """A CSS font-family list, quoted, with the system default left unquoted and first."""
    names = [name for name in style.family if name]
    quoted = ", ".join(f'"{name}"' for name in names)
    return quoted or "sans-serif"


def stylesheet(palette: Palette) -> str:
    """The whole application stylesheet for one theme.

    Regenerated and re-applied on every theme change. It is cheap — a few kilobytes of string
    formatting — and it is the only way QSS can carry a token system at all.
    """
    body = font_stack(Type.BODY)
    mono = font_stack(Type.DEVICE)

    return f"""
QWidget {{
    background-color: {palette.page_background};
    color: {palette.text_primary};
    font-family: {body};
    font-size: {Type.BODY.size}pt;
}}

QMainWindow, QDialog {{
    background-color: {palette.page_background};
}}

/* L2 card. The one surface the whole layout is built out of. */
QFrame[card="true"] {{
    background-color: {palette.card_fill};
    border: 1px solid {palette.stroke_subtle};
    border-radius: {Radius.CARD}px;
}}

QFrame[card="recessed"] {{
    background-color: {palette.card_fill_secondary};
    border: 1px solid {palette.stroke_subtle};
    border-radius: {Radius.CARD}px;
}}

QLabel[role="title"] {{
    font-size: {Type.TITLE.size}pt;
    font-weight: {Type.TITLE.weight};
    color: {palette.text_primary};
}}

QLabel[role="subtitle"] {{
    font-size: {Type.SUBTITLE.size}pt;
    font-weight: {Type.SUBTITLE.weight};
    color: {palette.text_primary};
}}

QLabel[role="caption"] {{
    font-size: {Type.CAPTION.size}pt;
    color: {palette.text_secondary};
}}

QLabel[role="tertiary"] {{
    font-size: {Type.CAPTION.size}pt;
    color: {palette.text_tertiary};
}}

QLabel[role="readout"] {{
    font-size: {Type.READOUT.size}pt;
    font-weight: {Type.READOUT.weight};
    color: {palette.text_primary};
}}

QLabel[role="readout-small"] {{
    font-size: {Type.READOUT_SMALL.size}pt;
    font-weight: {Type.READOUT_SMALL.weight};
    color: {palette.text_primary};
}}

/* Device-literal text: anything the receiver itself emitted. §9.5's split. */
QLabel[role="device"], QPlainTextEdit[role="device"], QTextEdit[role="device"] {{
    font-family: {mono};
    font-size: {Type.DEVICE.size}pt;
    color: {palette.text_primary};
}}

QPlainTextEdit, QTextEdit {{
    background-color: {palette.card_fill_secondary};
    border: 1px solid {palette.stroke_default};
    border-radius: {Radius.CONTROL}px;
    padding: {Spacing.SMALL}px;
}}

QPushButton {{
    background-color: {palette.card_fill_secondary};
    color: {palette.text_primary};
    border: 1px solid {palette.stroke_default};
    border-radius: {Radius.CONTROL}px;
    padding: {Spacing.SMALL}px {Spacing.MEDIUM}px;
    /* §9.12's pointer-target floor is declared, never inherited from whatever a stock style
       happens to supply. */
    min-height: {Spacing.LARGE}px;
}}

QPushButton:hover {{
    border-color: {palette.accent};
}}

QPushButton:focus {{
    border: 2px solid {palette.accent};
}}

QPushButton:disabled {{
    color: {palette.text_disabled};
    border-color: {palette.stroke_subtle};
}}

QListWidget {{
    background-color: {palette.card_fill};
    border: 1px solid {palette.stroke_subtle};
    border-radius: {Radius.CARD}px;
    padding: {Spacing.TIGHT}px;
}}

QListWidget::item {{
    padding: {Spacing.SMALL}px;
    border-radius: {Radius.CONTROL}px;
    min-height: {Spacing.LARGE}px;
}}

QListWidget::item:selected {{
    background-color: {palette.accent};
    color: {palette.accent_foreground};
}}

QHeaderView::section {{
    background-color: {palette.card_fill_secondary};
    color: {palette.text_secondary};
    border: none;
    border-bottom: 1px solid {palette.stroke_default};
    padding: {Spacing.SMALL}px;
}}

QTableWidget, QTableView {{
    background-color: {palette.card_fill};
    gridline-color: {palette.stroke_subtle};
    border: none;
}}

QStatusBar {{
    color: {palette.text_tertiary};
    border-top: 1px solid {palette.stroke_subtle};
}}

QToolTip {{
    background-color: {palette.overlay_fill};
    color: {palette.text_primary};
    border: 1px solid {palette.stroke_default};
    padding: {Spacing.TIGHT}px;
}}

QScrollBar:vertical {{
    background: {palette.page_background};
    width: {Spacing.MEDIUM}px;
}}

QScrollBar::handle:vertical {{
    background: {palette.stroke_default};
    border-radius: {Radius.CONTROL}px;
    min-height: {Spacing.LARGE}px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
}}
"""
