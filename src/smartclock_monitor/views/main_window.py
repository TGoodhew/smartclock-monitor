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

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
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
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.themes.qss import stylesheet
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import ALL_THEMES, Theme, palette_for
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.widgets.medallion import StatusMedallion
from smartclock_monitor.widgets.severity_pill import SeverityPill

#: The application's name, read from **one** constant.
#:
#: §6.3 forbids hard-coding it, and the reason survives the loss of the API that used to supply it
#: (``Package.Current.DisplayName``, which has no Linux equivalent): the name appears in the title
#: bar, the about surface and the guide, and a rename that has to be made in nine places gets made
#: in eight.
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
        self.setMinimumSize(420, 260)

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
        self._details_button = QPushButton("Details…")
        self._details_button.setAccessibleName("Open the details window")
        self._details_button.setToolTip("Satellites, position and timing (Ctrl+D)")
        self._details_button.clicked.connect(self.open_details)
        QShortcut(QKeySequence("Ctrl+D"), self, self.open_details)

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

        outer.addStretch(1)
        return root

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
            if self._last_reading is not None:
                self._details.show_reading(self._last_reading)

        self._details.show()
        self._details.raise_()
        self._details.activateWindow()

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
