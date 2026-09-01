"""§10.11's Advanced Console: **a command picker, not a text box.**

The dropdown is populated from the catalog, so §8.4's exclusions are absent from it for the same
reason they are absent from everywhere else — they are not entries. Enabling this page adds no
command the application could not already send; it changes what is *reachable*, never what is
permitted.

Tier C commands selected here raise their confirmation like anywhere else. A console that skipped
the dialog because the user had opted into an advanced surface would be treating "I want to see the
commands" as "I have read the consequence of this one".

**The picker is the connected driver's allowlist, and it is rebound when the driver changes.**
Not the SmartClock catalog: §12's #304 item 2 records that a stale picker offers a family commands
it has never heard of, which with a talker connected would mean ninety-eight SCPI mnemonics on a
device that would read every one of them as noise in the middle of its own stream. Unbound, or
bound to a family with no command parser, the picker is **empty** — which is the honest thing for it
to be, rather than another family's list.

**There is no free-text entry, and there must never be one.** If a future version adds it, §10.11
specifies the shape it has to take: every submission through a validator that requires a catalog
match on the normalised mnemonic *and* rejects anything the driver's ``is_blocked`` answers true
for, logging the attempt. Allowlist semantics, not blocklist.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.commands.scpi_command import ArgumentKind, ScpiCommand
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.session import CommandOutcome
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.views.confirm_dialog import ask
from smartclock_monitor.views.pages import Page, card, label

#: How many transcript lines to keep. Long enough to see a sequence, short enough that the widget
#: does not become the application's memory profile.
_TRANSCRIPT_LINES = 500


class ConsolePage(Page):
    """§10.11."""

    title = "Advanced Console"

    def __init__(
        self,
        palette: Palette = LIGHT,
        parent: QWidget | None = None,
        *,
        driver: ReceiverDriver | None = None,
    ) -> None:
        super().__init__(palette, parent)
        self._runner: CommandRunner | None = None
        self._driver = driver
        self._lines: list[str] = []

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)
        layout.addWidget(self._build_picker())
        layout.addWidget(self._build_transcript(), 1)

        self._repopulate()
        self._choose(0)

    # -- The picker ------------------------------------------------------------------------------

    def _build_picker(self) -> QWidget:
        holder, holder_layout = card("Command")

        self._filter = QLineEdit()
        self._filter.setPlaceholderText("filter…")
        self._filter.setAccessibleName("Filter the command list")
        self._filter.textChanged.connect(self._repopulate)
        holder_layout.addWidget(self._filter)

        self._commands = QComboBox()
        self._commands.setAccessibleName("Which command to send")
        self._commands.currentIndexChanged.connect(self._choose)
        holder_layout.addWidget(self._commands)

        self._summary = label("", "caption")
        self._summary.setWordWrap(True)
        holder_layout.addWidget(self._summary)

        parameter = QHBoxLayout()
        self._parameter_label = label("Parameter", "caption")
        parameter.addWidget(self._parameter_label)
        self._integer = QSpinBox()
        self._integer.setAccessibleName("Parameter")
        self._decimal = QDoubleSpinBox()
        self._decimal.setDecimals(9)
        self._decimal.setAccessibleName("Parameter")
        self._keyword = QComboBox()
        self._keyword.setAccessibleName("Parameter")
        for editor in (self._integer, self._decimal, self._keyword):
            editor.setVisible(False)
            parameter.addWidget(editor)
        self._integer.valueChanged.connect(lambda _v: self._redraw_preview())
        self._decimal.valueChanged.connect(lambda _v: self._redraw_preview())
        self._keyword.currentIndexChanged.connect(lambda _v: self._redraw_preview())
        self._range = label("", "tertiary")
        parameter.addWidget(self._range)
        parameter.addStretch(1)
        holder_layout.addLayout(parameter)

        send_row = QHBoxLayout()
        self._preview = label("", "device")
        self._preview.setAccessibleName("What will be sent")
        send_row.addWidget(self._preview, 1)
        self._send = QPushButton("Send")
        self._send.clicked.connect(self._send_selected)
        send_row.addWidget(self._send)
        holder_layout.addLayout(send_row)

        self._repopulate()
        return holder

    def _build_transcript(self) -> QWidget:
        holder, holder_layout = card("Transcript")

        row = QHBoxLayout()
        row.addStretch(1)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear_transcript)
        row.addWidget(clear)
        holder_layout.addLayout(row)

        self._transcript = QPlainTextEdit()
        self._transcript.setReadOnly(True)
        self._transcript.setProperty("role", "device")
        self._transcript.setAccessibleName("What has been sent and received")
        holder_layout.addWidget(self._transcript)
        return holder

    # -- Populating ------------------------------------------------------------------------------

    def _matching(self) -> list[ScpiCommand]:
        needle = self._filter.text().strip().lower()
        return [
            command
            for command in self._offered()
            if not needle or needle in command.mnemonic.lower() or needle in command.summary.lower()
        ]

    def _offered(self) -> tuple[ScpiCommand, ...]:
        """The connected family's allowlist, or nothing.

        Nothing rather than a default catalog: a console with no receiver has no allowlist to show,
        and showing one family's while another is connected is precisely the staleness §12's #304
        item 2 names.
        """
        return () if self._driver is None else self._driver.commands

    def _rebind(self) -> None:
        """Follow the session's driver, so a reconnect onto a different family repopulates.

        Taken from the runner on every reading, the same way the Details pages take it for their
        capability gates: which family is connected is the session's fact, and a copy kept here
        would be a second one to go stale.
        """
        live = (
            self._runner.driver if self._runner is not None and self._runner.is_connected else None
        )
        if live is None or live is self._driver:
            return
        self._driver = live
        self._repopulate()

    def _repopulate(self) -> None:
        selected = self.selected()
        self._commands.blockSignals(True)
        self._commands.clear()
        for command in self._matching():
            self._commands.addItem(f"{command.mnemonic}  —  {command.summary}", command.mnemonic)
        self._commands.blockSignals(False)

        # Keep the selection across a filter change where it survives the filter.
        if selected is not None:
            index = self._commands.findData(selected.mnemonic)
            if index >= 0:
                self._commands.setCurrentIndex(index)
        self._choose(self._commands.currentIndex())

    def selected(self) -> ScpiCommand | None:
        wanted = self._commands.currentData()
        return next((command for command in self._offered() if command.mnemonic == wanted), None)

    def _choose(self, index: int) -> None:
        del index
        command = self.selected()
        if command is None:
            self._summary.setText("")
            self._preview.setText("")
            return

        self._summary.setText(command.summary)
        for editor in (self._integer, self._decimal, self._keyword):
            editor.setVisible(False)
        self._range.setText("")

        match command.argument:
            case ArgumentKind.INTEGER:
                self._integer.setVisible(True)
                self._integer.setRange(int(command.minimum or 0), int(command.maximum or 0))
                self._range.setText(f"({command.minimum:g} – {command.maximum:g})")
            case ArgumentKind.DECIMAL:
                self._decimal.setVisible(True)
                self._decimal.setRange(command.minimum or 0.0, command.maximum or 0.0)
                self._range.setText(f"({command.minimum:g} – {command.maximum:g})")
            case ArgumentKind.KEYWORD:
                self._keyword.setVisible(True)
                self._keyword.clear()
                for word in command.keywords:
                    self._keyword.addItem(word)
            case _:
                pass

        self._parameter_label.setVisible(command.argument is not ArgumentKind.NONE)
        self._redraw_preview()

    def argument(self) -> object:
        command = self.selected()
        if command is None:
            return None
        match command.argument:
            case ArgumentKind.INTEGER:
                return self._integer.value()
            case ArgumentKind.DECIMAL:
                return self._decimal.value()
            case ArgumentKind.KEYWORD:
                return self._keyword.currentText()
            case _:
                return None

    def _redraw_preview(self) -> None:
        command = self.selected()
        rendered = command.rendered(self.argument()) if command is not None else None
        # §10.11's "Will send:" line. Exactly the text that goes out, so a user can check it
        # against the manual before committing to it.
        self._preview.setText(rendered or "")
        self._send.setEnabled(
            rendered is not None and self._runner is not None and self._runner.is_connected
        )

    # -- Sending ---------------------------------------------------------------------------------

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        self._runner = runner
        self._rebind()
        self._redraw_preview()

    def show_reading(self, reading: Reading) -> None:
        del reading
        self._rebind()
        self._redraw_preview()

    def _send_selected(self) -> None:
        runner = self._runner
        command = self.selected()
        if runner is None or command is None:
            return

        argument = self.argument()
        # Tier C still confirms. Opting into an advanced surface is not the same as having read the
        # consequence of a particular command.
        if not ask(command, argument, self._palette, self):
            return

        self._append(f"> {command.rendered(argument)}")
        runner.run([(command, argument)], self._absorb)

    def _absorb(self, outcomes: Sequence[CommandOutcome]) -> None:
        for outcome in outcomes:
            if outcome.refusal is not None:
                self._append(f"! {outcome.refusal.reason}")
                continue
            if outcome.transaction is None:
                self._append("! no answer")
                continue
            for line in outcome.transaction.lines or ("",):
                self._append(f"< {line}")
            if outcome.error:
                self._append(f"! {outcome.error}")

    def _append(self, line: str) -> None:
        self._lines.append(line)
        del self._lines[:-_TRANSCRIPT_LINES]
        self._transcript.setPlainText("\n".join(self._lines))

    def clear_transcript(self) -> None:
        self._lines.clear()
        self._transcript.setPlainText("")

    # -- What a test may read --------------------------------------------------------------------

    @property
    def transcript(self) -> str:
        return self._transcript.toPlainText()

    @property
    def preview_text(self) -> str:
        return self._preview.text()

    @property
    def command_box(self) -> QComboBox:
        return self._commands

    @property
    def filter_box(self) -> QLineEdit:
        return self._filter

    @property
    def send_button(self) -> QPushButton:
        return self._send

    def select(self, mnemonic: str) -> bool:
        """Pick a command by mnemonic. Returns whether it was there to pick."""
        index = self._commands.findData(mnemonic)
        if index < 0:
            return False
        self._commands.setCurrentIndex(index)
        return True
