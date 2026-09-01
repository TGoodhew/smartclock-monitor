"""The main window (§10.3): the surface a user leaves open for weeks, and the one G1 measures.

G1's acceptance criterion is specific: **mode and tracked-satellite count legible at two metres**,
in a window no larger than 420 by 260, updating within two seconds of a state change. Everything
here follows from that — the medallion is large, the readouts are tabular, and nothing competes
with the two things that have to be readable across a room.

**Every severity is colour + shape + text** (§9.13). The medallion carries a ring whose completeness
differs per state, the pills carry a shape, and both carry the word.

**Device-literal text is monospace** (§9.5). The receiver's own strings — the identity, the mode
detail — are set in the device face so that "what the machine said" stays visually distinct from
"what the app says about it".
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.models.receiver_status import (
    OutputValidity,
    ReceiverStatus,
    SmartClockMode,
)
from smartclock_monitor.platform import tray
from smartclock_monitor.services import preferences
from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.preferences import Preferences
from smartclock_monitor.services.supervisor import Supervisor
from smartclock_monitor.services.trend_store import TrendStore
from smartclock_monitor.themes.qss import stylesheet
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import ALL_THEMES, Theme, palette_for
from smartclock_monitor.views.connection_dialog import ConnectionChoice, ConnectionDialog
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.views.help_window import HelpWindow
from smartclock_monitor.widgets.medallion import StatusMedallion
from smartclock_monitor.widgets.severity_pill import SeverityPill

#: The application's name, read from **one** constant.
#:
#: §6.3 forbids hard-coding it, and the reason survives the loss of the API that used to supply it
#: (``Package.Current.DisplayName``, which has no Linux equivalent): the name appears in the title
#: bar, the about surface and the guide, and a rename that has to be made in nine places gets made
#: in eight.
#: §9.6.2's minimum **content** sizes, in effective pixels.
#:
#: On Qt those are also the units ``setMinimumSize`` takes — logical pixels already have the device
#: ratio applied — so §9.6.2's conversion, its recomputation on a scaling change and its work-area
#: cap are Windows-specific arithmetic that does not arise here.
MAIN_MINIMUM = (380, 240)
COMPACT_MINIMUM = (380, 144)

APPLICATION_NAME = "SmartClock Monitor"

#: The em dash a missing value renders as (§11.1). Never a zero, which would claim a reading.
DASH = "—"

#: How the §9.4.3 severities map onto what the receiver is doing.
_MODE_SEVERITY: dict[SmartClockMode, Severity] = {
    SmartClockMode.LOCKED: Severity.SUCCESS,
    SmartClockMode.RECOVERY: Severity.CAUTION,
    SmartClockMode.HOLDOVER: Severity.CRITICAL,
    SmartClockMode.POWER_UP: Severity.NEUTRAL,
    SmartClockMode.UNKNOWN: Severity.NEUTRAL,
}

_MODE_LABEL: dict[SmartClockMode, str] = {
    SmartClockMode.LOCKED: "Locked to GPS",
    SmartClockMode.RECOVERY: "Recovering",
    SmartClockMode.HOLDOVER: "Holdover",
    SmartClockMode.POWER_UP: "Powering up",
    SmartClockMode.UNKNOWN: "Unknown",
}


def _card(parent: QWidget | None = None) -> QFrame:
    """An L2 card. The one surface the whole layout is built from."""
    frame = QFrame(parent)
    frame.setProperty("card", "true")
    return frame


def _label(text: str, role: str, parent: QWidget | None = None) -> QLabel:
    """A label carrying a QSS role rather than an inline style.

    The role is what the generated stylesheet targets, which is how a label's type and colour come
    from the token table instead of from here — §9.13's rule, made structural.
    """
    label = QLabel(text, parent)
    label.setProperty("role", role)
    return label


class Readout(QWidget):
    """A labelled value, in the type the §9.5 ramp gives it."""

    def __init__(self, caption: str, unit: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unit = unit

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(Spacing.TIGHT)

        self._value = _label(DASH, "readout-small", self)
        self._caption = _label(caption, "caption", self)

        layout.addWidget(self._value)
        layout.addWidget(self._caption)
        self.setAccessibleName(caption)

    @property
    def value_text(self) -> str:
        """What is currently shown, dash included. The assertion surface for §11.1."""
        return self._value.text()

    def set_value(self, text: str) -> None:
        shown = f"{text} {self._unit}".strip() if text != DASH else DASH
        self._value.setText(shown)
        self.setAccessibleName(f"{self._caption.text()}: {shown}")


class MainWindow(QMainWindow):
    """§10.3's glanceable window."""

    def __init__(self, theme: Theme = Theme.DARK) -> None:
        super().__init__()
        self._theme = theme

        self._last_reading: Reading | None = None

        self.setWindowTitle(APPLICATION_NAME)
        # G1's box. A floor rather than a fixed size: §9.6.1's breakpoints grow the layout, and the
        # acceptance criterion is that it *fits* in 420 by 260, not that it is stuck there.
        self.setMinimumSize(*MAIN_MINIMUM)

        self._medallion = StatusMedallion(palette_for(theme))
        self._mode_pill = SeverityPill(Severity.NEUTRAL, "Disconnected", palette_for(theme))
        self._outputs_pill = SeverityPill(Severity.NEUTRAL, "Outputs unknown", palette_for(theme))
        self._health_pill = SeverityPill(Severity.NEUTRAL, "Health unknown", palette_for(theme))

        self._tfom = Readout("Time figure of merit")
        self._ffom = Readout("Frequency figure of merit")
        self._interval = Readout("1 PPS interval", "ns")
        self._efc = Readout("Oscillator EFC", "%")

        self._detail = _label("", "device")
        self._detail.setWordWrap(True)

        self._details: DetailsWindow | None = None
        # Held here rather than in the details window because the details window is created on
        # demand and the store is opened at startup — and because a run whose store failed to open
        # must reach the page as None rather than as an absent attribute.
        self._store: TrendStore | None = None
        self._runner: CommandRunner | None = None
        self._supervisor: Supervisor | None = None
        self._tray: tray.Tray | None = None
        self._told_about_hiding = False
        self._compact = False
        self._help: HelpWindow | None = None
        # Loaded once at startup. §10.13: a missing or unreadable file reads as the defaults, and
        # the default for anything advanced is off.
        self._preferences = preferences.load()
        # §9.11's connection-lost state: a countdown that cannot be cut short is thirty seconds
        # of an application looking hung. Hidden until there is a supervisor to ask.
        self._retry = QPushButton("Retry now")
        self._retry.setAccessibleName("Try reconnecting immediately")
        self._retry.clicked.connect(self.retry_now)
        self._retry.setVisible(False)

        self._connect_button = QPushButton("Connect…")
        self._connect_button.setAccessibleName("Choose a port and connect")
        self._connect_button.setToolTip("Choose a serial port and connect (Ctrl+Shift+C)")
        self._connect_button.clicked.connect(self.choose_connection)

        self._details_button = QPushButton("Details…")
        self._details_button.setAccessibleName("Open the details window")
        self._details_button.setToolTip("Satellites, position and timing (Ctrl+D)")
        self._details_button.clicked.connect(self.open_details)
        QShortcut(QKeySequence("Ctrl+D"), self, self.open_details)
        # §9.7.5's remaining accelerators. They open the details window first, because that is
        # where the commands live — a shortcut that silently did nothing because the wrong window
        # had focus is the failure a keyboard-only user cannot diagnose.
        QShortcut(QKeySequence("F5"), self, lambda: self._in_details("refresh_current"))
        QShortcut(QKeySequence("Ctrl+E"), self, lambda: self._in_details("export_current"))
        QShortcut(QKeySequence("Ctrl+,"), self, lambda: self._in_details("show_settings"))
        QShortcut(QKeySequence("Ctrl+Shift+C"), self, self.choose_connection)
        QShortcut(QKeySequence("Ctrl+Shift+M"), self, self.toggle_compact)
        QShortcut(QKeySequence("F1"), self, self.open_help)
        QShortcut(QKeySequence("Esc"), self, self.leave_compact)

        self._theme_picker = QComboBox()
        for available in ALL_THEMES:
            self._theme_picker.addItem(available.value.replace("-", " ").title(), available)
        self._theme_picker.setCurrentIndex(list(ALL_THEMES).index(theme))
        self._theme_picker.setAccessibleName("Theme")
        self._theme_picker.currentIndexChanged.connect(self._on_theme_changed)

        self.setStatusBar(QStatusBar())
        self.setCentralWidget(self._build())
        self.apply_theme(theme)
        self.set_connection_text("Not connected")

    # -- What a test, or a future page, may read ------------------------------------------------

    @property
    def medallion(self) -> StatusMedallion:
        return self._medallion

    @property
    def mode_pill(self) -> SeverityPill:
        return self._mode_pill

    @property
    def readouts(self) -> dict[str, Readout]:
        """The figures of merit, by the caption they carry."""
        return {
            "tfom": self._tfom,
            "ffom": self._ffom,
            "interval": self._interval,
            "efc": self._efc,
        }

    # -- Layout --------------------------------------------------------------------------------

    def _build(self) -> QWidget:
        root = QWidget()
        outer = QVBoxLayout(root)
        outer.setContentsMargins(
            Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING
        )
        outer.setSpacing(Spacing.MEDIUM)

        header = QHBoxLayout()
        header.setSpacing(Spacing.SMALL)
        header.addWidget(_label(APPLICATION_NAME, "title"))
        header.addStretch(1)
        header.addWidget(self._connect_button)
        header.addWidget(self._retry)
        header.addWidget(self._details_button)
        header.addWidget(_label("Theme", "caption"))
        header.addWidget(self._theme_picker)
        outer.addLayout(header)

        # The glanceable row: the medallion, and the two words beside it. Nothing else competes.
        glance = _card()
        glance_layout = QHBoxLayout(glance)
        glance_layout.setContentsMargins(
            Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING
        )
        glance_layout.setSpacing(Spacing.CARD_PADDING)

        self._medallion.setMinimumSize(132, 132)
        self._medallion.setMaximumHeight(180)
        glance_layout.addWidget(self._medallion, 0, Qt.AlignmentFlag.AlignVCenter)

        states = QVBoxLayout()
        states.setSpacing(Spacing.SMALL)
        states.addWidget(self._mode_pill)
        states.addWidget(self._outputs_pill)
        states.addWidget(self._health_pill)
        states.addWidget(self._detail)
        states.addStretch(1)
        glance_layout.addLayout(states, 1)

        outer.addWidget(glance)

        # The figures of merit.
        readouts = _card()
        grid = QGridLayout(readouts)
        grid.setContentsMargins(
            Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING
        )
        grid.setHorizontalSpacing(Spacing.LARGE)
        grid.setVerticalSpacing(Spacing.MEDIUM)
        grid.addWidget(self._tfom, 0, 0)
        grid.addWidget(self._ffom, 0, 1)
        grid.addWidget(self._interval, 1, 0)
        grid.addWidget(self._efc, 1, 1)
        outer.addWidget(readouts)
        self._readouts = readouts

        outer.addStretch(1)
        return root

    # -- §9.6.2's compact mode -------------------------------------------------------------------

    def set_compact(self, compact: bool) -> None:
        """§9.6.2's compact state: a 64 px medallion, the mode text, and nothing else.

        **Collapsed, not clipped and not scrolled** — the readout row is removed from the layout,
        so nothing stays focusable or hit-testable off-screen (A11Y-1, A11Y-6). A hidden widget in
        Qt is out of the layout and out of the tab order, which is the behaviour that rule wants;
        merely shrinking the window would have left both.

        **The figures here are content sizes in effective pixels**, which is what §9.6.2's
        amendment spends four paragraphs establishing — and on Qt they are also what
        ``setMinimumSize`` takes, because Qt's logical pixels already have the device ratio
        applied. The conversion, the recomputation on a scaling change and the work-area cap that
        amendment requires are all Windows-specific arithmetic that does not arise here. This is a
        case where the platform difference makes the port simpler, and it is worth saying so
        rather than leaving the next reader to wonder where the conversion went.
        """
        self._compact = compact
        self._readouts.setVisible(not compact)
        self._health_pill.setVisible(not compact)
        self._detail.setVisible(not compact)

        if compact:
            self._medallion.setMinimumSize(64, 64)
            self._medallion.setMaximumHeight(64)
            self.setMinimumSize(*COMPACT_MINIMUM)
            self.resize(*COMPACT_MINIMUM)
        else:
            self._medallion.setMinimumSize(132, 132)
            self._medallion.setMaximumHeight(180)
            self.setMinimumSize(*MAIN_MINIMUM)

    def toggle_compact(self) -> None:
        self.set_compact(not self._compact)

    def leave_compact(self) -> None:
        """``Esc`` exits compact mode (§9.7.5) and does nothing otherwise.

        Nothing, rather than closing the window: Escape closes a dialog and a flyout, and a window
        that also vanished on it would be surprising in a way the other two are not.
        """
        if self._compact:
            self.set_compact(False)

    @property
    def is_compact(self) -> bool:
        return self._compact

    @property
    def readouts_card(self) -> QWidget:
        return self._readouts

    # -- Theme ---------------------------------------------------------------------------------

    def apply_theme(self, theme: Theme) -> None:
        """Regenerate the stylesheet and repaint the custom widgets.

        Both halves are needed and neither is enough: QSS carries the ordinary widgets and cannot
        re-resolve, so it is regenerated; the custom widgets never read QSS at all, so they are
        handed the palette.
        """
        self._theme = theme
        palette = palette_for(theme)

        self.setStyleSheet(stylesheet(palette))
        for widget in (self._medallion, self._mode_pill, self._outputs_pill, self._health_pill):
            widget.set_palette_tokens(palette)

        # The details window is a separate top-level window and inherits neither the stylesheet nor
        # the palette, so it is told as well.
        if self._details is not None:
            self._details.apply_theme(theme)

    def _on_theme_changed(self, index: int) -> None:
        theme = self._theme_picker.itemData(index)
        if isinstance(theme, Theme):
            self.apply_theme(theme)

    # -- The details window ----------------------------------------------------------------------

    def open_details(self) -> None:
        """Open the details window, or raise the one that is already open.

        Created lazily and kept, rather than rebuilt each time: it holds the sky plot's marker
        widgets and the satellite table's selection, and throwing those away on close would lose
        the row a user had picked while they went to look at the main window.
        """
        if self._details is None:
            self._details = DetailsWindow(self._theme, self)
            self._details.setWindowFlag(Qt.WindowType.Window, True)
            self._details.set_trend_store(self._store)
            self._details.set_command_runner(self._runner)
            self._details.apply_preferences(self._preferences)
            self._details.exit_requested = self.exit_application
            self._details.set_can_keep_running(self.can_keep_running)
            self._details.help_requested = self.open_help
            self._details.settings_changed = self._remember_preferences
            if self._last_reading is not None:
                self._details.show_reading(self._last_reading)

        self._details.show()
        self._details.raise_()
        self._details.activateWindow()

    @property
    def preferences(self) -> Preferences:
        return self._preferences

    #: Set by whoever owns the window, to hear about a preference the user changed. ``None`` means
    #: nobody is listening, which is what a test wants.
    on_preferences_changed: Callable[[Preferences], None] | None = None

    # -- §10.3.1 closing, and staying alive --------------------------------------------------------

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's own casing
        """Hide rather than exit, **where there is a way back to the window**.

        §10.3.1 makes hiding the default so the trend keeps filling and P1-9's notifications keep
        arriving while the window is out of the way — §9.1's user leaves this docked beside a
        spectrum analyser for weeks. But its own argument for the Settings *Exit* button is that an
        application whose only exit is an invisible icon is quittable in principle and by Task
        Manager in practice. On a desktop with **no tray at all** that goes further: a hidden
        window with no icon cannot be reached by any means the user has, so hiding would not be an
        inconvenience but a loss of the application.

        So the tray decides, and where there is none this closes.
        """
        if not self._preferences.keep_running_when_closed or self._tray is None:
            event.accept()
            return

        # **The notice goes up while the window is still visible.** A notice put over a window that
        # has already gone is a notice nobody reads, which spends the single chance and leaves the
        # user just as surprised — which is §10.3.1's whole point about telling them once.
        if not self._told_about_hiding:
            self._told_about_hiding = True
            self._explain_hiding()

        event.ignore()
        self.hide()

    def _explain_hiding(self) -> None:
        """Say what just happened, and offer the exit they may have meant.

        Silently turning close into hide is the well-known way to annoy people, so §10.3.1 requires
        this once — and only once.
        """
        notice = QMessageBox(self)
        notice.setWindowTitle("Still running")
        notice.setText(
            "SmartClock Monitor is still running and still polling the receiver, so the trend "
            "keeps filling while the window is out of the way."
        )
        notice.setInformativeText(
            "Open it again from the notification icon, or use Exit there or in Settings to stop."
        )
        keep = notice.addButton("Keep running", QMessageBox.ButtonRole.AcceptRole)
        notice.addButton("Exit now", QMessageBox.ButtonRole.DestructiveRole)
        notice.setDefaultButton(keep)
        notice.exec()

        if notice.clickedButton() is not keep:
            self.exit_application()

    def exit_application(self) -> None:
        """Stop, without asking again.

        §10.3.1: **no confirmation on exit.** Polling is not a transaction and the trend store
        commits as it goes, so there is nothing to lose by stopping — and a prompt would be the
        second interruption in a job whose first one already asked a question.
        """
        if self._tray is not None:
            self._tray.hide()
        application = QApplication.instance()
        if application is not None:
            application.quit()

    def attach_tray(self) -> bool:
        """Register the notification icon if this desktop has one. Returns whether it did."""
        if not tray.is_available():
            return False

        self._tray = tray.Tray(
            palette_for(self._theme),
            on_open=self._reopen,
            on_exit=self.exit_application,
            parent=self,
        )
        self._tray.show()
        return True

    def open_help(self) -> None:
        """§9.7.5's F1, from either window. Kept rather than rebuilt, so a reader keeps their
        scroll position when they go back to the application and press it again."""
        if self._help is None:
            self._help = HelpWindow(palette_for(self._theme), self)
            self._help.setWindowFlag(Qt.WindowType.Window, True)
        self._help.show()
        self._help.raise_()
        self._help.activateWindow()

    @property
    def help_window(self) -> HelpWindow | None:
        return self._help

    def _reopen(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    @property
    def tray(self) -> tray.Tray | None:
        return self._tray

    @property
    def can_keep_running(self) -> bool:
        """Whether hiding on close is possible at all here. The Settings page asks this."""
        return self._tray is not None

    def _remember_preferences(self, updated: Preferences) -> None:
        """§10.13: a write that fails is not reported. A preference is by definition something the
        user can set again, and nothing load-bearing lives in one of these files."""
        self._preferences = updated
        preferences.save(updated)
        if self.on_preferences_changed is not None:
            self.on_preferences_changed(updated)

    def set_supervisor(self, supervisor: Supervisor | None) -> None:
        """§9.11's connection-lost state offers *Retry now* and *Stop retrying* beside the
        countdown. This is what those reach."""
        self._supervisor = supervisor
        self._retry.setVisible(supervisor is not None)

    def _in_details(self, command: str) -> None:
        """Run one of the details window's commands, opening it if it is not already up."""
        self.open_details()
        details = self._details
        if details is None:
            return
        getattr(details, command)()

    #: Set by whoever owns the window. Called with what the user chose in §10.12's dialog; it is
    #: the owner that knows how to open a port, not the window.
    on_connection_chosen: Callable[[ConnectionChoice], None] | None = None

    def choose_connection(self) -> ConnectionChoice | None:
        """§10.12's dialog. Returns what was chosen, or ``None`` if the user cancelled."""
        dialog = ConnectionDialog(palette_for(self._theme), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        choice = dialog.choice()
        if choice is None:
            return None

        self.set_connection_text(
            f"Connecting to {choice.port}"
            + ("" if choice.is_automatic else f" @ {choice.settings}")
            + "…"
        )
        if self.on_connection_chosen is not None:
            self.on_connection_chosen(choice)
        return choice

    def retry_now(self) -> None:
        if self._supervisor is not None:
            self._supervisor.retry_now()

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        """Held for a details window opened later, forwarded to one already open."""
        self._runner = runner
        if self._details is not None:
            self._details.set_command_runner(runner)

    def set_trend_store(self, store: TrendStore | None) -> None:
        """Hand the window its history. Forwarded to the details window if one is already open,
        and remembered for one opened later."""
        self._store = store
        if self._details is not None:
            self._details.set_trend_store(store)

    @property
    def details(self) -> DetailsWindow | None:
        """The details window, if it has been opened. ``None`` before that — it is created on
        demand, because most sessions never open it."""
        return self._details

    # -- What the poll loop tells it -------------------------------------------------------------

    def set_connection_text(self, text: str) -> None:
        bar = self.statusBar()
        if bar is not None:
            bar.showMessage(text)

    def show_reading(self, reading: Reading) -> None:
        """Render one sweep. Called on the event loop, never from a worker thread."""
        self._last_reading = reading
        if self._details is not None:
            self._details.show_reading(reading)

        status = reading.status
        severity = _MODE_SEVERITY.get(status.mode, Severity.NEUTRAL)
        label = _MODE_LABEL.get(status.mode, "Unknown")

        tracked = reading.tracked_count
        if tracked is None:
            tracked = len(status.tracked) or None

        self._medallion.set_state(severity, DASH if tracked is None else str(tracked), label)
        self._mode_pill.set_state(severity, label)
        self._outputs_pill.set_state(*_outputs_state(status))
        self._health_pill.set_state(*_health_state(status))

        self._detail.setText(status.mode_detail or "")
        self._tfom.set_value(_number(status.tfom))
        self._ffom.set_value(_number(status.ffom))
        self._interval.set_value(_nanoseconds(status.one_pps_ti_nanoseconds))
        self._efc.set_value(_number(reading.efc_percent, decimals=1))


def _outputs_state(status: ReceiverStatus) -> tuple[Severity, str]:
    match status.outputs:
        case OutputValidity.VALID:
            return Severity.SUCCESS, "Outputs valid"
        case OutputValidity.INVALID:
            return Severity.CRITICAL, "Outputs not valid"
        case _:
            return Severity.NEUTRAL, "Outputs unknown"


def _health_state(status: ReceiverStatus) -> tuple[Severity, str]:
    if not status.health_items:
        return Severity.NEUTRAL, "Health unknown"
    if status.health_ok:
        return Severity.SUCCESS, "Health OK"
    failed = [name for name, ok in status.health_items.items() if not ok]
    return Severity.CRITICAL, f"Health: {', '.join(failed)}"


def _number(value: float | int | None, decimals: int = 0) -> str:
    """A value, or the em dash. **Never a zero for a missing reading** — §11.1's whole point is
    that "not reported" and "reported as nought" are different claims."""
    if value is None:
        return DASH
    return f"{value:.{decimals}f}"


def _nanoseconds(value: float | None) -> str:
    if value is None:
        return DASH
    return f"{value:+.1f}"


def format_timestamp(moment: datetime | None) -> str:
    """A device timestamp, or the dash."""
    return DASH if moment is None else moment.strftime("%Y-%m-%d %H:%M:%S")
