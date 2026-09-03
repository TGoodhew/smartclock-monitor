"""§10.12's connection dialog: pick a port, and either let it walk or say what to use.

**Auto-detect is the fresh-install default.** §7.1's whole point is that a second-hand receiver's
serial settings are not knowable in advance — a Z3805A leaves the factory at 9600-8-N-1 and a
Z3801A at 19200-7-O-1 — so the dialog opens on the option that finds out rather than the one that
asks the user to already know.

**Manual does not fall back to the walk.** Someone who has picked a setting is asserting something
about their hardware, and quietly trying seven others would make the picker a suggestion.

**The walk is cancellable and reports where it has got to.** Eight combinations at a two-second
probe is about sixteen seconds against a port with nothing on it, which is long enough that a
dialog with no progress reads as hung.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.transport.settings import (
    DEFAULT,
    SUPPORTED_BAUD_RATES,
    SUPPORTED_DATA_BITS,
    Parity,
    SerialSettings,
    StopBits,
)
from smartclock_monitor.themes.qss import stylesheet
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette


@dataclass(frozen=True, slots=True)
class ConnectionChoice:
    """What the user asked for."""

    port: str

    #: ``None`` means walk §7.1's sequence; a value means use exactly this.
    settings: SerialSettings | None

    reconnect_automatically: bool = True
    connect_on_launch: bool = True

    @property
    def is_automatic(self) -> bool:
        return self.settings is None


#: Lists the ports. Injected so the dialog can be built without a serial library present — which
#: is also how ``--list-ports`` works on a machine with no Qt.
PortLister = Callable[[], Sequence[tuple[str, str]]]


def _ports() -> list[tuple[str, str]]:
    """Every serial port, as ``(device, label)``.

    Imported inside the function because the dialog must be constructible where pyserial is not
    installed — the same reason ``--list-ports`` imports it late.
    """
    try:
        from smartclock_device.transport.serial_port import available_ports
    except ImportError:
        return []

    return [(port.device, port.label) for port in available_ports()]


class ConnectionDialog(QDialog):
    """§10.12."""

    def __init__(
        self,
        palette: Palette = LIGHT,
        parent: QWidget | None = None,
        list_ports: PortLister | None = None,
        preselect: str | None = None,
    ) -> None:
        super().__init__(parent)
        self._list_ports = list_ports or _ports
        #: The port to start on. `refresh_ports` already keeps a selection across a refresh, but
        #: that memory dies with the dialog — and the dialog is rebuilt every time it opens, so a
        #: user who disconnects and reconnects was offered whichever port happened to sort first.
        self._preselect = preselect
        self._palette = palette

        self.setWindowTitle("Connect to receiver")
        self.setModal(True)
        self.setStyleSheet(stylesheet(palette))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)
        layout.setSpacing(Spacing.MEDIUM)

        layout.addWidget(self._build_port())
        layout.addWidget(self._build_mode())
        layout.addWidget(self._build_options())
        layout.addWidget(self._build_progress())
        layout.addLayout(self._build_buttons())

        self.refresh_ports()
        self._retune()

    # -- Building --------------------------------------------------------------------------------

    def _build_port(self) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Port"))
        self._ports = QComboBox()
        self._ports.setAccessibleName("Which serial port the receiver is on")
        row.addWidget(self._ports, 1)
        self._refresh = QPushButton("Refresh")
        self._refresh.setAccessibleName("Look for serial ports again")
        self._refresh.clicked.connect(self.refresh_ports)
        row.addWidget(self._refresh)
        return holder

    def _build_mode(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)

        self._mode = QButtonGroup(holder)
        self._automatic = QRadioButton("Auto-detect settings")
        self._automatic.setAccessibleName("Try each known combination until the receiver answers")
        self._manual = QRadioButton("Manual")
        self._manual.setAccessibleName("Use exactly the settings below")
        self._mode.addButton(self._automatic, 0)
        self._mode.addButton(self._manual, 1)
        # §10.12: the dialog opens on Auto-detect on a fresh install.
        self._automatic.setChecked(True)
        self._mode.idToggled.connect(lambda _id, _on: self._retune())
        column.addWidget(self._automatic)
        column.addWidget(self._manual)

        grid = QHBoxLayout()
        self._baud = self._picker("Baud", [str(rate) for rate in SUPPORTED_BAUD_RATES], grid)
        self._data = self._picker("Data", [str(bits) for bits in SUPPORTED_DATA_BITS], grid)
        self._parity = self._picker("Parity", [member.value for member in Parity], grid)
        self._stop = self._picker("Stop", [member.value for member in StopBits], grid)
        column.addLayout(grid)

        self._baud.setCurrentText(str(DEFAULT.baud_rate))
        self._data.setCurrentText(str(DEFAULT.data_bits))
        self._parity.setCurrentText(DEFAULT.parity.value)
        self._stop.setCurrentText(DEFAULT.stop_bits.value)
        return holder

    def _picker(self, name: str, items: list[str], into: QHBoxLayout) -> QComboBox:
        into.addWidget(QLabel(name))
        box = QComboBox()
        box.setAccessibleName(name)
        box.addItems(items)
        into.addWidget(box)
        return box

    def _build_options(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        self._reconnect = QCheckBox("Reconnect automatically")
        self._reconnect.setChecked(True)
        self._on_launch = QCheckBox("Connect to this device on launch")
        self._on_launch.setChecked(True)
        column.addWidget(self._reconnect)
        column.addWidget(self._on_launch)
        return holder

    def _build_progress(self) -> QWidget:
        holder = QWidget()
        column = QVBoxLayout(holder)
        column.setContentsMargins(0, 0, 0, 0)
        self._progress = QProgressBar()
        self._progress.setAccessibleName("How far through the settings it has got")
        # The walk supplies the real total on its first callback, and the bar is hidden until then.
        # It used to be seeded from the SmartClock's own sequence, which stopped being the length of
        # the walk the moment §10.12's union had a second family in it.
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._status = QLabel("")
        self._status.setWordWrap(True)
        column.addWidget(self._progress)
        column.addWidget(self._status)
        holder.setVisible(False)
        self._progress_holder = holder
        return holder

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch(1)
        self._connect = QPushButton("Connect")
        self._connect.clicked.connect(self.accept)
        self._cancel = QPushButton("Cancel")
        # Same rule as the confirmation dialog: Escape and Enter land on the way out, not on the
        # action. This one is not destructive, but a dialog that behaves differently from its
        # sibling teaches the wrong reflex.
        self._cancel.setDefault(True)
        self._cancel.clicked.connect(self.reject)
        row.addWidget(self._connect)
        row.addWidget(self._cancel)
        return row

    # -- Behaviour -------------------------------------------------------------------------------

    def refresh_ports(self) -> None:
        """Re-list the ports, keeping the current selection where it survives."""
        wanted = self._ports.currentData() or self._preselect
        self._ports.clear()
        for device, label in self._list_ports():
            self._ports.addItem(label, device)

        if wanted is not None:
            index = self._ports.findData(wanted)
            if index >= 0:
                self._ports.setCurrentIndex(index)

        if self._ports.count() == 0:
            # §9.11: say what is wrong rather than offering an empty picker and a live button.
            self._status.setText("No serial ports found. Check the adapter is plugged in.")
            self._progress_holder.setVisible(True)
        self._retune()

    def _retune(self) -> None:
        manual = self._manual.isChecked()
        for box in (self._baud, self._data, self._parity, self._stop):
            box.setEnabled(manual)
        self._connect.setEnabled(self._ports.count() > 0)

    def choice(self) -> ConnectionChoice | None:
        """What the user picked, or ``None`` if there was no port to pick."""
        device = self._ports.currentData()
        if device is None:
            return None

        return ConnectionChoice(
            port=str(device),
            settings=self.manual_settings() if self._manual.isChecked() else None,
            reconnect_automatically=self._reconnect.isChecked(),
            connect_on_launch=self._on_launch.isChecked(),
        )

    def manual_settings(self) -> SerialSettings:
        return SerialSettings(
            baud_rate=int(self._baud.currentText()),
            data_bits=int(self._data.currentText()),
            parity=Parity(self._parity.currentText()),
            stop_bits=StopBits(self._stop.currentText()),
        )

    def show_progress(self, settings: SerialSettings, index: int, total: int) -> None:
        """Called by the walk before each attempt."""
        self._progress_holder.setVisible(True)
        self._progress.setRange(0, total)
        self._progress.setValue(index)
        self._status.setText(f"Trying {settings} — {index} of {total}…")

    def show_failure(self, message: str) -> None:
        self._progress_holder.setVisible(True)
        self._progress.setValue(0)
        self._status.setText(message)

    # -- What a test may read --------------------------------------------------------------------

    @property
    def port_box(self) -> QComboBox:
        return self._ports

    @property
    def automatic(self) -> QRadioButton:
        return self._automatic

    @property
    def manual(self) -> QRadioButton:
        return self._manual

    @property
    def connect_button(self) -> QPushButton:
        return self._connect

    @property
    def cancel_button(self) -> QPushButton:
        return self._cancel

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def baud_box(self) -> QComboBox:
        return self._baud

    def showEvent(self, event: object) -> None:  # noqa: N802 - Qt's own casing
        super().showEvent(event)  # type: ignore[arg-type]
        self._cancel.setFocus(Qt.FocusReason.ActiveWindowFocusReason)
