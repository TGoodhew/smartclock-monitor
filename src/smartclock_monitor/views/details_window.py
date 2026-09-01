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

from collections.abc import Callable

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

from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.preferences import Preferences
from smartclock_monitor.services.trend_store import TrendStore
from smartclock_monitor.themes.qss import stylesheet
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import Theme, palette_for
from smartclock_monitor.views.console_page import ConsolePage
from smartclock_monitor.views.diagnostics_page import DiagnosticsPage
from smartclock_monitor.views.holdover_page import HoldoverPage
from smartclock_monitor.views.pages import (
    OverviewPage,
    Page,
    PositionPage,
    SatellitesPage,
    TimingPage,
)
from smartclock_monitor.views.registers_page import StatusRegistersPage
from smartclock_monitor.views.settings_page import SettingsPage
from smartclock_monitor.views.time_page import TimePage

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
        self._runner: CommandRunner | None = None
        self._preferences = Preferences()

        self.setWindowTitle("Details")
        # §9.6.2's minimum for the two-column arrangement: the sky plot caps at 360 and the table
        # goes beside it.
        self.setMinimumSize(900, 560)

        self._pages: list[Page] = [
            OverviewPage(palette_for(theme)),
            SatellitesPage(palette_for(theme)),
            PositionPage(palette_for(theme)),
            TimingPage(palette_for(theme)),
            HoldoverPage(palette_for(theme)),
            DiagnosticsPage(palette_for(theme)),
            StatusRegistersPage(palette_for(theme)),
            TimePage(palette_for(theme)),
            SettingsPage(palette_for(theme)),
        ]

        #: §10.13: the switch **adds and removes the destination** rather than hiding it, so a
        #: disabled console is not an item a keyboard user can still reach.
        self._console = ConsolePage(palette_for(theme))

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

        settings = self.page_named(SettingsPage.title)
        assert isinstance(settings, SettingsPage)
        settings.on_change(self._preferences_changed)

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

    #: Called when the user changes a preference, so the owner can persist it. Set by whoever
    #: constructed this window; ``None`` means nobody is saving, which is what a test wants.
    settings_changed: Callable[[Preferences], None] | None = None

    def _preferences_changed(self, updated: Preferences) -> None:
        self.apply_preferences(updated)
        if self.settings_changed is not None:
            self.settings_changed(updated)

    def apply_preferences(self, preferences: Preferences) -> None:
        """Add or remove §10.11's console, and remember the rest.

        §10.13: the switch adds and removes the destination rather than merely hiding it. If the
        console is showing when it is switched off, the pane falls back to the first destination
        rather than leaving the frame on a page it no longer lists.
        """
        self._preferences = preferences
        showing = preferences.advanced_console
        present = self._console in self._pages

        if showing and not present:
            self._pages.append(self._console)
            item = QListWidgetItem(self._console.title)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, self._console.title)
            self._navigation.addItem(item)
            self._stack.addWidget(_scrolled(self._console))
            self._console.set_command_runner(self._runner)
        elif not showing and present:
            index = self._pages.index(self._console)
            was_showing = self._navigation.currentRow() == index
            self._pages.pop(index)
            self._navigation.takeItem(index)
            holder = self._stack.widget(index)
            if holder is not None:
                self._stack.removeWidget(holder)
                holder.setParent(None)
            if was_showing:
                self._navigation.setCurrentRow(0)

        settings = self.page_named(SettingsPage.title)
        if isinstance(settings, SettingsPage) and settings.preferences != preferences:
            settings.set_preferences(preferences)

    @property
    def preferences(self) -> Preferences:
        return self._preferences

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        """Give the pages that send commands something to send them with.

        Asked of every page rather than of a named few: which pages issue commands is a fact about
        those pages, and a list here would be a second place to update when one starts.
        """
        self._runner = runner
        for page in self._pages:
            setter = getattr(page, "set_command_runner", None)
            if setter is not None:
                setter(runner)

    def set_trend_store(self, store: TrendStore | None) -> None:
        """Forwarded to whichever pages want history. Only §10.7's does today; asking every page
        keeps the wiring one line when a second one does."""
        for page in self._pages:
            setter = getattr(page, "set_trend_store", None)
            if setter is not None:
                setter(store)

    def show_reading(self, reading: Reading) -> None:
        """Feed every page, visible or not — see the module docstring."""
        for page in self._pages:
            page.show_reading(reading)

        bar = self.statusBar()
        if bar is not None:
            bar.showMessage(
                f"Updated {(reading.captured_at or reading.status.captured_at):%H:%M:%S}"
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
