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
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QScrollArea,
    QStackedWidget,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.export import machine_rows, suggested_filename, to_csv
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

#: §9.7.5: Ctrl+1 … Ctrl+9. There is no Ctrl+10 — §10.2's cap is twelve destinations but only the
#: first nine can carry an accelerator, so the pane's order decides which are one keystroke away.
_MAX_ACCELERATED = 9


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
        self._last_reading_at: datetime | None = None

        self.setWindowTitle("Details")
        # §9.6.2's minimum for the two-column arrangement: the sky plot caps at 360 and the table
        # goes beside it.
        #
        # **Measured, with margin.** At 900 the Satellites page was 196 px too narrow for itself and
        # scrolled *sideways*, taking the sky plot off the edge with the table. A window that opens
        # too small to show its own first page is a worse answer than one that asks for the room it
        # needs. (Stacking the plot above the table below a breakpoint is a §10.5 layout decision
        # rather than a defect fix, and is not what this is.)
        #
        # Satellites is the widest at 966 — the sky plot's own 240 px minimum beside the table —
        # and the other nine want between 468 and 808. The margin on top is not decoration:
        # **1100 was tried first and CI rejected it**, because the runner resolves a slightly wider
        # font at the same point size and the number had been measured here. 1160 leaves 78 px
        # rather than 24, which is worth having for something no local run can see.
        self.setMinimumSize(1160, 620)

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
        settings.on_exit = self._exit

        self._build_commands()
        self.setStatusBar(QStatusBar())
        self.setCentralWidget(self._build())
        self.apply_theme(theme)

    def _build_commands(self) -> None:
        """§9.7.4's title-bar commands and §9.7.5's accelerators.

        **Attached to the window rather than to the buttons**, which is the same conclusion the
        original reached: a control that lives in a collapsible area takes its accelerator with it
        when it collapses — precisely the state a keyboard-only user needs it in. The tooltips
        carry the key by hand for the same reason.
        """
        bar = QToolBar("Commands")
        bar.setMovable(False)
        self.addToolBar(bar)

        self._refresh_action = QAction("Refresh", self)
        self._refresh_action.setShortcut(QKeySequence("F5"))
        self._refresh_action.setToolTip("Re-read the full status now (F5)")
        self._refresh_action.triggered.connect(self.refresh_current)
        bar.addAction(self._refresh_action)

        self._export_action = QAction("Export…", self)
        self._export_action.setShortcut(QKeySequence.StandardKey.Save)
        self._export_action.setShortcut(QKeySequence("Ctrl+E"))
        self._export_action.setToolTip("Export what this page is showing, as CSV (Ctrl+E)")
        self._export_action.triggered.connect(self.export_current)
        bar.addAction(self._export_action)

        self._settings_action = QAction("Settings", self)
        self._settings_action.setShortcut(QKeySequence("Ctrl+,"))
        self._settings_action.setToolTip("Settings (Ctrl+,)")
        self._settings_action.triggered.connect(self.show_settings)
        bar.addAction(self._settings_action)

        self._help_action = QAction("Help", self)
        self._help_action.setShortcut(QKeySequence("F1"))
        self._help_action.setToolTip("How to use SmartClock Monitor (F1)")
        self._help_action.triggered.connect(self._open_help)
        bar.addAction(self._help_action)

        for action in (
            self._refresh_action,
            self._export_action,
            self._settings_action,
            self._help_action,
        ):
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            self.addAction(action)

        # §9.7.5: Ctrl+1 … Ctrl+9 jump to a destination, and there is no Ctrl+10 — only the first
        # nine can carry an accelerator, so the pane's order decides which are one keystroke away.
        self._jumps: list[QAction] = []
        for index in range(_MAX_ACCELERATED):
            action = QAction(f"Destination {index + 1}", self)
            action.setShortcut(QKeySequence(f"Ctrl+{index + 1}"))
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
            action.triggered.connect(lambda _checked=False, row=index: self._jump_to(row))
            self.addAction(action)
            self._jumps.append(action)

        self._navigation.currentRowChanged.connect(lambda _row: self._retune_commands())

    #: Set by whoever owns this window: F1 opens one guide, and which window it belongs to is not
    #: this one's decision.
    help_requested: Callable[[], None] | None = None

    def _open_help(self) -> None:
        if self.help_requested is not None:
            self.help_requested()

    def _jump_to(self, row: int) -> None:
        if 0 <= row < self._navigation.count():
            self._navigation.setCurrentRow(row)

    def _retune_commands(self) -> None:
        """§9.11: a command that looks like it works and does nothing is worse than a disabled one.

        Export is disabled where the current page has nothing to give, which is a real state — a
        page whose first reading has not arrived, a register nobody has read, a log that is empty.
        """
        page = self.current_page()
        self._export_action.setEnabled(bool(page is not None and page.csv_rows()))
        self._refresh_action.setEnabled(
            page is not None and hasattr(page, "refresh") and self._runner is not None
        )

    def current_page(self) -> Page | None:
        row = self._navigation.currentRow()
        return self._pages[row] if 0 <= row < len(self._pages) else None

    def refresh_current(self) -> None:
        """F5. Asks the current page to re-read, where it has anything to re-read."""
        page = self.current_page()
        refresh = getattr(page, "refresh", None)
        if refresh is not None:
            refresh()

    def show_settings(self) -> None:
        """Ctrl+,."""
        for row, page in enumerate(self._pages):
            if page.title == SettingsPage.title:
                self._navigation.setCurrentRow(row)
                return

    def export_current(self) -> str | None:
        """Ctrl+E. Writes the current page's rows, and returns the path it wrote.

        ``None`` where the user cancelled or there was nothing to write. The rows go through
        :func:`machine_rows` first — §9.5.3's minus sign and hair space are right on screen and
        make a spreadsheet cell text.
        """
        page = self.current_page()
        if page is None:
            return None

        rows = page.csv_rows()
        if not rows:
            return None

        stamp = self._stamp()
        suggested = str(Path.home() / suggested_filename(page.title, stamp))
        chosen, _filter = QFileDialog.getSaveFileName(
            self, f"Export {page.title}", suggested, "CSV files (*.csv)"
        )
        if not chosen:
            return None

        try:
            Path(chosen).write_text(to_csv(machine_rows(rows)), encoding="utf-8", newline="")
        except OSError as error:
            bar = self.statusBar()
            if bar is not None:
                bar.showMessage(f"Could not write {chosen}: {error}")
            return None

        bar = self.statusBar()
        if bar is not None:
            bar.showMessage(f"Exported {len(rows) - 1} rows to {chosen}")
        return chosen

    def _stamp(self) -> str:
        """The timestamp in an exported filename.

        Taken from the last reading rather than from a clock, because there is no clock here and
        §7.4 is the reason there is not: the instant that matters is the one the data came from.
        """
        moment = self._last_reading_at
        return "unknown" if moment is None else moment.strftime("%Y%m%d-%H%M%S")

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

    #: Called when the user presses Exit on the Settings page.
    exit_requested: Callable[[], None] | None = None

    def _exit(self) -> None:
        if self.exit_requested is not None:
            self.exit_requested()

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

        diagnostics = self.page_named(DiagnosticsPage.title)
        if isinstance(diagnostics, DiagnosticsPage):
            diagnostics.set_experimental_visible(preferences.undocumented_queries)

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
        self._last_reading_at = reading.captured_at or reading.status.captured_at
        for page in self._pages:
            page.show_reading(reading)
        self._retune_commands()

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
