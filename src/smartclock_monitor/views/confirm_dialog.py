"""§9.7.4's tier C confirmation, and §8.3's sentences.

**The button roles are the safety mechanism, not the styling.** §9.7.4 amends §8.3 specifically to
say so: the destructive action is the *primary* button styled destructively, and **Cancel is the
default button**, so Enter and initial focus land on the safe option. Accent means "the safe thing
to do next", which a destructive action is not — and §8.3's own note records that anyone reading
that section in order and implementing from it would have built the opposite.

Escape always cancels. The four strong variants gate the destructive button behind a tick.

**The sentence comes from the command, never from here.** §8.3's amendment note is the reason:
``:IGN:NONE`` shared the exclusion sentence for a command that *clears* the exclusion list, so a
user confirming it would reasonably believe they were excluding satellites. A dialog that
assembled its own text from a template would reintroduce exactly that, one template at a time.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_monitor.themes.qss import stylesheet
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.widgets.severity_pill import SeverityPill

#: What the tick says. One sentence, and it has to be an assertion the user is making rather than a
#: restatement of the warning — "I understand" is a claim about them, which is the point of it.
ACKNOWLEDGEMENT = "I understand what this will do."


class ConfirmDialog(QDialog):
    """Ask before sending a tier C command."""

    def __init__(
        self,
        command: ScpiCommand,
        argument: object = None,
        palette: Palette = LIGHT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._command = command
        self._palette = palette

        self.setWindowTitle("Confirm")
        self.setModal(True)
        self.setStyleSheet(stylesheet(palette))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)
        layout.setSpacing(Spacing.MEDIUM)

        # Colour and shape and text, through the one renderer §9.13 item 10 allows.
        layout.addWidget(SeverityPill(Severity.CAUTION, "Confirm", palette))

        sentence = QLabel(command.confirmation or f"Send {command.mnemonic}?")
        sentence.setWordWrap(True)
        sentence.setAccessibleName("What this will do")
        layout.addWidget(sentence)

        # What is actually going to be sent. §9.5.1's device-literal rule: this is machine text and
        # a user checking a destructive command against the manual needs it exactly.
        rendered = command.rendered(argument)
        self._detail = QLabel(rendered or "")
        self._detail.setProperty("role", "device")
        self._detail.setAccessibleName("The command that will be sent")
        self._detail.setVisible(bool(rendered))
        layout.addWidget(self._detail)

        self._tick: QCheckBox | None = None
        if command.requires_acknowledgement:
            self._tick = QCheckBox(ACKNOWLEDGEMENT)
            self._tick.toggled.connect(self._retune)
            layout.addWidget(self._tick)

        layout.addLayout(self._build_buttons())
        self._retune()

    def _build_buttons(self) -> QHBoxLayout:
        """Cancel on the right as the default; the destructive action beside it, never accented.

        Built by hand rather than from ``QDialogButtonBox``'s standard roles: the box decides
        which button is default from the role, and the role that would give this dialog its
        destructive action is exactly the one §9.7.4 forbids being default.
        """
        row = QHBoxLayout()
        row.setSpacing(Spacing.SMALL)
        row.addStretch(1)

        self._confirm = QPushButton(_verb(self._command))
        # §9.7.4: WzDestructiveButtonStyle — critical foreground, default stroke, transparent fill,
        # a leading warning glyph. Never AccentButtonStyle.
        self._confirm.setProperty("role", "destructive")
        self._confirm.setAutoDefault(False)
        self._confirm.setDefault(False)
        self._confirm.clicked.connect(self.accept)

        self._cancel = QPushButton("Cancel")
        self._cancel.setAutoDefault(True)
        self._cancel.setDefault(True)
        self._cancel.clicked.connect(self.reject)

        row.addWidget(self._confirm)
        row.addWidget(self._cancel)
        # Initial focus lands on the safe option, which is the other half of §9.7.4's rule — a
        # default button nobody is focused on is not where Enter goes.
        self._cancel.setFocus(Qt.FocusReason.OtherFocusReason)
        return row

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 - Qt's own casing
        """Put focus on Cancel as the dialog appears.

        Qt assigns focus when a widget becomes visible, so setting it in the constructor is
        setting it on something with no window — the value is discarded and the user gets whatever
        the tab order happens to start with, which is the destructive button.
        """
        super().showEvent(event)
        self._cancel.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def _retune(self) -> None:
        self._confirm.setEnabled(self._tick is None or self._tick.isChecked())

    # -- What a test may read ----------------------------------------------------------------

    @property
    def confirm_button(self) -> QPushButton:
        return self._confirm

    @property
    def cancel_button(self) -> QPushButton:
        return self._cancel

    @property
    def acknowledgement(self) -> QCheckBox | None:
        return self._tick

    @property
    def command(self) -> ScpiCommand:
        return self._command


def _verb(command: ScpiCommand) -> str:
    """The destructive button's label.

    **Not "OK".** §9.7.4 puts the destructive action on the primary button precisely so a user can
    see what they are about to do without re-reading the sentence, and "OK" undoes that. Taken from
    the command's own summary, which §10.11's picker already shows.
    """
    summary = command.summary.strip()
    return summary[0].upper() + summary[1:] if summary else "Send"


def ask(
    command: ScpiCommand,
    argument: object = None,
    palette: Palette = LIGHT,
    parent: QWidget | None = None,
) -> bool:
    """Show the dialog and say whether the user confirmed.

    A tier S command is not asked about — §8.2 is explicit that those execute on click — so this
    answers ``True`` for one without showing anything. That keeps the decision in the catalog
    rather than at each call site, where it would eventually be got wrong.
    """
    if not command.needs_confirmation:
        return True

    dialog = ConfirmDialog(command, argument, palette, parent)
    return dialog.exec() == QDialog.DialogCode.Accepted
