"""The details window (§10.2's inventory): a navigation list and a stack of pages.

``NavigationView`` has no Qt equivalent, so this is the translation the port plan gives — a list
beside a :class:`QStackedWidget`. The list is a real list rather than a row of buttons, which is
what makes it one keyboard stop with arrow-key traversal inside it instead of one tab stop per
page.

**It is a second window, not a mode of the first.** §10.2 keeps them separate because the main
window is the one left open on a second monitor for weeks and the details window is opened to
answer a question and closed again. Making the main window grow into this would cost G1's
glanceability, which is the whole point of it.

Every page is fed the same :class:`Reading`, including the ones that are not visible. That is
deliberate: a page that only updated while shown would display a stale value for one poll interval
after being switched to, which is exactly when someone is looking at it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from smartclock_monitor.services.polling import Reading
from smartclock_monitor.themes.qss import stylesheet
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import Theme, palette_for
from smartclock_monitor.views.pages import (
    OverviewPage,
    Page,
    PositionPage,
    SatellitesPage,
    TimingPage,
)

#: How wide the navigation pane is. §9.6.1 gives 260 for the Medium breakpoint.
_NAVIGATION_WIDTH = 260


def _scrolled(page: Page) -> QScrollArea:
    """Wrap a page so a short window scrolls rather than clipping its cards.

    §9.6.2's minimum sizes assume the content fits; below them the honest behaviour is a scrollbar,
    not a card squeezed until its text is half a line high. The frame is removed because the cards
    already carry the §9.4.1 stroke and a second border around them reads as a nested surface.
    """
    area = QScrollArea()
    area.setWidget(page)
    area.setWidgetResizable(True)
    area.setFrameShape(QScrollArea.Shape.NoFrame)
    area.setAccessibleName(page.title)
    return area


class DetailsWindow(QMainWindow):
    """The pages behind the main window's glance."""

    def __init__(self, theme: Theme = Theme.DARK, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme = theme

        self.setWindowTitle("Details")
        # §9.6.2's minimum for the two-column arrangement: the sky plot caps at 360 and the table
        # goes beside it.
        self.setMinimumSize(900, 560)

        self._pages: list[Page] = [
            OverviewPage(palette_for(theme)),
            SatellitesPage(palette_for(theme)),
            PositionPage(palette_for(theme)),
            TimingPage(palette_for(theme)),
        ]

        self._navigation = QListWidget()
        self._navigation.setFixedWidth(_NAVIGATION_WIDTH)
        self._navigation.setAccessibleName("Pages")
        self._stack = QStackedWidget()

        for page in self._pages:
            item = QListWidgetItem(page.title)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, page.title)
            self._navigation.addItem(item)
            self._stack.addWidget(_scrolled(page))

        self._navigation.currentRowChanged.connect(self._stack.setCurrentIndex)
        self._navigation.setCurrentRow(0)

        self.setStatusBar(QStatusBar())
        self.setCentralWidget(self._build())
        self.apply_theme(theme)

    def _build(self) -> QWidget:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(
            Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING
        )
        layout.setSpacing(Spacing.CARD_PADDING)
        layout.addWidget(self._navigation)

        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(0, 0, 0, 0)
        holder_layout.addWidget(self._stack)
        layout.addWidget(holder, 1)
        return root

    # -- Theme and data --------------------------------------------------------------------------

    def apply_theme(self, theme: Theme) -> None:
        self._theme = theme
        palette = palette_for(theme)
        self.setStyleSheet(stylesheet(palette))
        for page in self._pages:
            page.set_palette_tokens(palette)

    def show_reading(self, reading: Reading) -> None:
        """Feed every page, visible or not — see the module docstring."""
        for page in self._pages:
            page.show_reading(reading)

        bar = self.statusBar()
        if bar is not None:
            bar.showMessage(
                f"Updated {reading.status.captured_at.strftime('%H:%M:%S')}"
                + (" — one reading suppressed, see Timing" if reading.suppressed else "")
            )

    # -- What a test may read --------------------------------------------------------------------

    @property
    def pages(self) -> tuple[Page, ...]:
        return tuple(self._pages)

    @property
    def navigation(self) -> QListWidget:
        return self._navigation

    def page_named(self, title: str) -> Page:
        """The page with this title. Raises rather than returning ``None``: a caller asking for a
        page that does not exist has a bug, and handing back ``None`` would hide it."""
        for page in self._pages:
            if page.title == title:
                return page
        raise KeyError(f"No page titled {title!r}.")
