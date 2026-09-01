"""§9.7.4's right-click layer: *Copy value* on a readout, *Copy table as CSV* on a card.

**Nothing unique lives here**, and that rule is what makes the layer safe to have. Every value it
copies is on screen and every table it copies is the document ``Ctrl+E`` already writes, so a user
who never discovers the right-click loses a keystroke and no capability.

**A copied value is data leaving the application, not a readout.** §9.5.3's minus sign and hair
space are right on screen and make a spreadsheet cell *text*, so the copy path undoes both —
except for device-literal text, which §9.5.3 rule 4 exempts because it is reproduced verbatim and
"correcting" it would make the copy disagree with the transcript it came from.

**A value that is not there copies as nothing, and the item is disabled.** §11.1's em dash is the
*absence* of data; pasting a dash into a sheet would make it look like a reading that happened to
be a dash.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QLabel, QMenu, QWidget

from smartclock_monitor.services.export import EM_DASH, machine_rows, to_csv, to_machine_text


def copy_to_clipboard(text: str) -> None:
    """Put text on the clipboard, if there is one.

    ``QGuiApplication.clipboard()`` is ``None`` under an offscreen platform and on a headless
    session, which is an ordinary state for a test rather than a failure to report.
    """
    clipboard = QGuiApplication.clipboard()
    if clipboard is not None:
        clipboard.setText(text)


def value_menu_text(source: QLabel, *, device_literal: bool = False) -> str:
    """What *Copy value* would put on the clipboard for this label."""
    if device_literal:
        # §9.5.3 rule 4: raw device text is reproduced verbatim, sign included.
        return source.text().strip()
    return to_machine_text(source.text())


def attach_value_menu(
    target: QLabel, *, device_literal: bool = False, parent: QWidget | None = None
) -> None:
    """Give a readout a *Copy value* menu.

    The target is made hit-testable first. **An element with no background is not hit-testable in
    Qt any more than it is in WinUI**, so a menu attached to one is a menu the pointer can never
    reach — the original recorded exactly this defect on `ReadoutTile`, and a transparent
    background is the fix in both.
    """
    target.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    target.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def show(point: QPoint) -> None:
        menu = QMenu(parent or target)
        action = QAction("Copy value", menu)
        text = value_menu_text(target, device_literal=device_literal)
        # Disabled rather than absent: an item that vanishes for some values teaches a user the
        # menu is unreliable, where a greyed one says "there is nothing here".
        action.setEnabled(bool(text) and target.text().strip() != EM_DASH)
        action.triggered.connect(lambda: copy_to_clipboard(text))
        menu.addAction(action)
        menu.exec(target.mapToGlobal(point))

    target.customContextMenuRequested.connect(show)


def attach_table_menu(
    target: QWidget, rows: Callable[[], Sequence[Sequence[str]]], parent: QWidget | None = None
) -> None:
    """Give a card a *Copy table as CSV* menu.

    **On the card, not on the rows**, and that was measured rather than assumed in the original: a
    label with text selection carries its own selection flyout, so a right-click on a row opens
    that one and a menu on the container above it never appears. That is the right outcome rather
    than a defeat — on a row you want that row's text, on the card around it you want the table —
    and the two menus divide the surface instead of one shadowing the other.
    """
    target.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

    def show(point: QPoint) -> None:
        menu = QMenu(parent or target)
        action = QAction("Copy table as CSV", menu)
        content = rows()
        action.setEnabled(len(content) > 1)
        action.triggered.connect(lambda: copy_to_clipboard(to_csv(machine_rows(content))))
        menu.addAction(action)
        menu.exec(target.mapToGlobal(point))

    target.customContextMenuRequested.connect(show)
