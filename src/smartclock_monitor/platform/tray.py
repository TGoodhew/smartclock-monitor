"""§10.3.1's notification icon, where the desktop has one.

**Hiding a window is only safe if there is a way back to it.** §10.3.1 makes close-hides-rather-
than-exits the default, and its own argument for the Settings *Exit* button is that Windows 11 does
not promote a newly registered icon — *"an application whose only exit is an invisible icon is
quittable in principle and by Task Manager in practice"*. On a desktop with **no tray at all** that
argument goes further: a hidden window with no icon is not reachable by any means the user has, so
hiding would not be an inconvenience but a loss of the application.

So the tray decides. Where one exists, close hides and the icon offers *Open* and *Exit*. Where none
does, close exits and the preference says why it cannot do otherwise — which is §9.11's rule about a
control that looks like it works, applied to a switch.

**Qt makes this portable and this module makes it decidable at runtime**, which is a narrower claim
than issue #6 has to settle: what is still open there is the *badge* and the artwork, not whether an
icon can be registered at all. ``QSystemTrayIcon.isSystemTrayAvailable()`` is asked once, at the
moment it matters, rather than inferred from the platform name — WSLg reports no tray on a system
that calls itself Linux, and a check on ``sys.platform`` would have got that wrong.

**The menu holds *Open* and *Exit* and nothing else** (§10.3.1). Anything that touches the receiver
reaches it through §8's tiers with §8.3's consequence text, and a shell context menu is not a place
any of that can be shown.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from smartclock_monitor.themes.severity import SEVERITY_SHAPES, Severity, colour_for
from smartclock_monitor.themes.tokens import Palette
from smartclock_monitor.widgets.severity_pill import shape_path

#: How large the icon is drawn. Shells scale it; 32 is what #274 used and is enough for the shape
#: to survive the scaling either way.
_SIZE = 32


def is_available() -> bool:
    """Whether this desktop offers a notification area at all.

    Asked at the moment it matters rather than inferred from the platform: WSLg reports no tray on
    a system that calls itself Linux, and a check on ``sys.platform`` would have got that wrong.
    """
    return bool(QSystemTrayIcon.isSystemTrayAvailable())


def render_icon(severity: Severity, palette: Palette) -> QIcon:
    """§9.4.3's shape in the severity colour — **the same vocabulary as everywhere else**.

    §9.4.3.1: both shell surfaces draw from one rasteriser, so a hexagon cannot come to mean
    different things in two places. Here that means the shape comes from ``shape_path``, which is
    what ``SeverityPill`` draws with.
    """
    pixmap = QPixmap(_SIZE, _SIZE)
    # Transparent, not white: a shell composites this over whatever its own background is, and a
    # white square would be a white square on half the desktops that exist.
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        shape, _label = SEVERITY_SHAPES[severity]
        # colour_for hands back a token *string*; the brush needs a QColor. The type: ignore that
        # was here hid that, and the paint device could then not be destroyed because the painter
        # never ended.
        painter.fillPath(shape_path(shape, _SIZE), QColor(colour_for(severity, palette)))
    finally:
        painter.end()

    return QIcon(pixmap)


class Tray:
    """The icon, its menu, and the sentence it tells assistive technology."""

    def __init__(
        self,
        palette: Palette,
        *,
        on_open: Callable[[], None],
        on_exit: Callable[[], None],
        parent: QWidget | None = None,
    ) -> None:
        self._palette = palette
        self._icon = QSystemTrayIcon(parent)

        menu = QMenu(parent)
        self._open = QAction("Open", menu)
        self._open.triggered.connect(lambda: on_open())
        self._exit = QAction("Exit", menu)
        self._exit.triggered.connect(lambda: on_exit())
        menu.addAction(self._open)
        menu.addAction(self._exit)
        self._icon.setContextMenu(menu)

        self._icon.activated.connect(lambda _reason: on_open())
        self.describe(Severity.NEUTRAL, "Not connected to a receiver.")

    def describe(self, severity: Severity, sentence: str) -> None:
        """Set the icon and its tooltip.

        **The description is set in every state**, which §9.4.3.1 records the reason for: a badge
        cleared with a null description leaves the *previous* one as the button's help text, so a
        receiver that went from disconnected to locked showed a clean icon and still told a screen
        reader it was disconnected. A sighted user saw the truth and a screen-reader user did not,
        which is the inversion those criteria exist to prevent.

        Whole sentences, in the style of the medallion's automation name: "Holdover" alone is this
        application's vocabulary, and someone meeting it through a screen reader on a shell surface
        has no other context to read it in.
        """
        self._icon.setIcon(render_icon(severity, self._palette))
        self._icon.setToolTip(sentence)

    def set_palette_tokens(self, palette: Palette) -> None:
        self._palette = palette

    def show(self) -> None:
        self._icon.show()

    def hide(self) -> None:
        self._icon.hide()

    @property
    def tooltip(self) -> str:
        return self._icon.toolTip()
