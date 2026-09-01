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

from smartclock_monitor.themes.spacing import MINIMUM_POINTER_TARGET, Radius, Spacing
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
    color: {palette.text_primary};
    font-family: {body};
    font-size: {Type.BODY.size}pt;
}}

QMainWindow, QDialog {{
    background-color: {palette.page_background};
}}

/* Labels never paint their own ground. A QLabel that inherits a background-color from QWidget
   draws a filled rectangle the width of its layout cell, which reads as a row of grey bars
   sitting behind the text rather than as text on a card. */
QLabel {{
    background: transparent;
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
    min-height: {MINIMUM_POINTER_TARGET}px;
}}

QPushButton:hover {{
    border-color: {palette.accent};
}}

QPushButton:focus {{
    border: 2px solid {palette.accent};
}}

/* §9.12's A11Y-5: pointer targets are at least 32 px **at all times**, and that binds every
   control a pointer can hit rather than only the buttons. Measured rather than assumed — the gate
   in tests/test_accessibility.py found checkboxes at 15 px and spin boxes at 25 px on a build
   whose buttons were already compliant, which is exactly the shape §9.4.5's note describes. */
QCheckBox, QRadioButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox {{
    min-height: {MINIMUM_POINTER_TARGET}px;
}}

/* Text and number entry. **Colours, not only a height** — these carried the pointer-target rule
   above and nothing else, so they kept Qt's own light defaults and a Dark-theme spin box was a
   white rectangle with a value in it nobody could read. The combo box two rules down had the full
   set from the start, which is what made the gap invisible in review: the page looked themed
   because the control beside the broken one was. */
QLineEdit, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextEdit {{
    background-color: {palette.card_fill_secondary};
    color: {palette.text_primary};
    border: 1px solid {palette.stroke_default};
    border-radius: {Radius.CONTROL}px;
    padding: {Spacing.TIGHT}px {Spacing.SMALL}px;
    selection-background-color: {palette.accent};
    selection-color: {palette.accent_foreground};
}}

QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus,
QPlainTextEdit:focus, QTextEdit:focus {{
    border: 2px solid {palette.accent};
}}

QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{
    color: {palette.text_disabled};
    border-color: {palette.stroke_subtle};
}}

/* Placeholder text is its own colour and does not follow `color`. Left alone it renders at Qt's
   default mid-grey, which is a contrast failure against a dark fill rather than a subtlety. */
QLineEdit {{
    placeholder-text-color: {palette.text_tertiary};
}}

/* The steppers are drawn from the palette, not the stylesheet, unless the fill is named. */
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    background-color: {palette.card_fill_secondary};
    border: none;
    width: {Spacing.MEDIUM}px;
}}

/* Progress. Found by the gate below this rule's absence — it paints its own ground and had none,
   so §10.12's auto-detect bar and the self-test bar were Qt's white on both themes. */
QProgressBar {{
    background-color: {palette.card_fill_secondary};
    color: {palette.text_primary};
    border: 1px solid {palette.stroke_default};
    border-radius: {Radius.CONTROL}px;
    text-align: center;
}}

QProgressBar::chunk {{
    background-color: {palette.accent};
    border-radius: {Radius.CONTROL}px;
}}

/* §9.7.4's command bar. It is a **top-level** surface — not inside any card, inheriting nothing
   from one — so with no rule of its own it took the *desktop's* palette: on Dark that was a light
   system strip carrying this theme's light text, grey on near-white, the worst contrast anywhere
   in the application and on the one row visible from every page.

   QToolBar rather than QMenuBar, which this application does not use. A rule for a class nothing
   instantiates is a rule that enforces nothing and reads as coverage. */
QToolBar {{
    background-color: {palette.layer_fill};
    color: {palette.text_primary};
    border: none;
    border-bottom: 1px solid {palette.stroke_subtle};
    spacing: {Spacing.TIGHT}px;
    padding: {Spacing.TIGHT}px;
}}

QToolButton {{
    background: transparent;
    color: {palette.text_primary};
    border: 1px solid transparent;
    border-radius: {Radius.CONTROL}px;
    padding: {Spacing.TIGHT}px {Spacing.SMALL}px;
    /* §9.12's pointer-target floor. These are commands like any other button. */
    min-height: {MINIMUM_POINTER_TARGET}px;
}}

QToolButton:hover {{
    background-color: {palette.card_fill_secondary};
    border-color: {palette.stroke_default};
}}

QToolButton:focus {{
    border: 2px solid {palette.accent};
}}

QToolButton:disabled {{
    color: {palette.text_disabled};
}}

/* A context menu is a separate top-level window, the same way the combo popup is, so it needs its
   own rule for the same reason. §10's copy menus and the tray menu are both these. */
QMenu {{
    background-color: {palette.overlay_fill};
    color: {palette.text_primary};
    border: 1px solid {palette.stroke_default};
    padding: {Spacing.TIGHT}px;
}}

QMenu::item {{
    padding: {Spacing.TIGHT}px {Spacing.MEDIUM}px;
    border-radius: {Radius.CONTROL}px;
}}

QMenu::item:selected {{
    background-color: {palette.accent};
    color: {palette.accent_foreground};
}}

QMenu::item:disabled {{
    color: {palette.text_disabled};
}}

QMenu::separator {{
    height: 1px;
    background-color: {palette.stroke_subtle};
    margin: {Spacing.TIGHT}px 0;
}}

QPushButton:disabled {{
    color: {palette.text_disabled};
    border-color: {palette.stroke_subtle};
}}

/* §9.7.4's WzDestructiveButtonStyle: critical foreground, default stroke, transparent fill.
   **Never the accent style** — accent means "the safe thing to do next", which a tier C command is
   not. §8.3's own amendment note records that the specification said the opposite for a while and
   anyone implementing from it in order would have built it. */
QPushButton[role="destructive"] {{
    background-color: transparent;
    color: {palette.critical};
    border: 1px solid {palette.stroke_default};
}}

QPushButton[role="destructive"]:hover {{
    border-color: {palette.critical};
}}

QPushButton[role="destructive"]:disabled {{
    color: {palette.text_disabled};
    border-color: {palette.stroke_subtle};
}}

QComboBox {{
    background-color: {palette.card_fill_secondary};
    color: {palette.text_primary};
    border: 1px solid {palette.stroke_default};
    border-radius: {Radius.CONTROL}px;
    padding: {Spacing.TIGHT}px {Spacing.SMALL}px;
    /* §9.12's pointer-target floor, declared rather than inherited. */
    min-height: {MINIMUM_POINTER_TARGET}px;
    min-width: {Spacing.PAGE}px;
}}

QComboBox:focus {{
    border: 2px solid {palette.accent};
}}

QComboBox::drop-down {{
    border: none;
    width: {Spacing.LARGE}px;
}}

/* The popup is a separate top-level window and does not inherit the combo's own rules. */
QComboBox QAbstractItemView {{
    background-color: {palette.overlay_fill};
    color: {palette.text_primary};
    border: 1px solid {palette.stroke_default};
    selection-background-color: {palette.accent};
    selection-color: {palette.accent_foreground};
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
    min-height: {MINIMUM_POINTER_TARGET}px;
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

/* The scrolling viewport. A page shorter than its window leaves the viewport showing, and with no
   rule of its own it painted Qt's light grey — so on Dark every page whose content did not reach
   the bottom had a pale block under it. Found by looking at Status Registers, whose one card is
   short; the pages that happen to fill their height hid it completely.

   The viewport is a child widget rather than the scroll area itself, so both are named: styling
   only QScrollArea leaves the ground it actually paints untouched.

   **QScrollArea, not QAbstractScrollArea.** The base class is also what QListWidget and
   QTableWidget are, and Qt gives two plain type selectors equal specificity — so the later rule
   wins, and naming the base here took the card ground off the navigation pane and the tables. */
QScrollArea {{
    background-color: {palette.page_background};
    border: none;
}}

QScrollArea > QWidget > QWidget {{
    background-color: {palette.page_background};
}}

QScrollBar:vertical {{
    background: {palette.page_background};
    width: {Spacing.MEDIUM}px;
}}

QScrollBar::handle:vertical {{
    background: {palette.stroke_default};
    border-radius: {Radius.CONTROL}px;
    min-height: {MINIMUM_POINTER_TARGET}px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
}}
"""
