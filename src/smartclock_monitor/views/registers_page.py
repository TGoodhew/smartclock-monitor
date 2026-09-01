"""§10.10's Status Registers page: five registers, five fields each, and three of them writable.

**Where a bit meaning is unknown, the raw state is shown and the label says "(see documentation)"
rather than inventing one.** OQ-1 was answered by transcribing all five registers from the guide's
Command Reference 5-36 to 5-39, so the fallback is now the exception — Hardware bit 5 is documented
as not used — rather than most of the page.

**Condition and event are not writable.** They are what the hardware is reporting; a setter for
either would be an offer to change the world by editing the instrument panel. Only the enable, PTr
and NTr masks are checkboxes, and the catalog has no entry for the other two, so this is a fact
about the data rather than a rule this page enforces.

*Discard changes* puts the checkboxes back to what the receiver last reported. It exists because
the alternative — a page whose only way out of a half-made edit is to navigate away and back — is
how someone applies a mask they did not mean to.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.commands import catalog
from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.models import status_register_map as registers
from smartclock_device.models.status_register_map import StatusRegisterMap
from smartclock_device.models.status_register_reading import StatusRegisterReading
from smartclock_device.parsing.scalars import parse_integer
from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.session import CommandOutcome
from smartclock_monitor.themes.spacing import TABLE_ROW_TARGET, Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.views.capability import gate
from smartclock_monitor.views.confirm_dialog import ask
from smartclock_monitor.views.pages import DASH, Page, card, label

#: The table's columns, in §10.10's own order.
_COLUMNS = ("Bit", "Cond", "Event", "Enab", "PTr", "NTr", "Meaning")

#: Which columns hold an editable mask, and which catalog field each maps to.
_EDITABLE: tuple[tuple[int, str], ...] = ((3, "ENAB"), (4, "PTR"), (5, "NTR"))

#: How many bits a register has. The receiver reports a 15-bit value.
_BITS = 15


class StatusRegistersPage(Page):
    """§10.10."""

    title = "Status Registers"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._runner: CommandRunner | None = None
        self._register: StatusRegisterMap = registers.ALL[0]
        self._reading = StatusRegisterReading(register=self._register)
        self._boxes: dict[tuple[int, str], QCheckBox] = {}

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)

        holder, holder_layout = card("Registers")

        chooser = QHBoxLayout()
        self._chooser = QComboBox()
        self._chooser.setAccessibleName("Which register to show")
        for register in registers.ALL:
            self._chooser.addItem(register.name, register.node)
        self._chooser.currentIndexChanged.connect(self._choose)
        chooser.addWidget(label("Register", "caption"))
        chooser.addWidget(self._chooser, 1)

        self._refresh = QPushButton("Refresh all")
        self._refresh.setAccessibleName("Re-read every field of this register")
        self._refresh.clicked.connect(self.refresh)
        chooser.addWidget(self._refresh)
        holder_layout.addLayout(chooser)

        self._summary = label("", "caption")
        self._summary.setWordWrap(True)
        holder_layout.addWidget(self._summary)

        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(list(_COLUMNS))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAccessibleName("Status register bits")
        header = self._table.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(len(_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        # The table is the page. Given no stretch it took its default height and showed five of
        # sixteen bits with three hundred pixels of empty page under it — on §10.10, whose entire
        # content is this table.
        # Its rows carry checkboxes and are interaction targets, so they take the same floor.
        header = self._table.verticalHeader()
        if header is not None:
            header.setMinimumSectionSize(TABLE_ROW_TARGET)
            header.setDefaultSectionSize(TABLE_ROW_TARGET)
        holder_layout.addWidget(self._table, 1)

        self._raw = label("", "device")
        self._raw.setAccessibleName("The raw register values")
        holder_layout.addWidget(self._raw)

        self._note = label(
            "Bit meanings are from the guide's Command Reference 5-36 to 5-39. "
            "Unmapped bits show their raw state.",
            "tertiary",
        )
        self._note.setWordWrap(True)
        holder_layout.addWidget(self._note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self._discard = QPushButton("Discard changes")
        self._discard.setAccessibleName("Put the masks back to what the receiver reported")
        self._discard.clicked.connect(self._redraw_masks)
        self._apply = QPushButton("Apply mask changes")
        self._apply.setProperty("role", "destructive")
        self._apply.setAccessibleName("Send the changed masks to the receiver")
        self._apply.clicked.connect(self._apply_masks)
        buttons.addWidget(self._discard)
        buttons.addWidget(self._apply)
        holder_layout.addLayout(buttons)

        layout.addWidget(holder, 1)

        self._rebuild()
        self._retune()

    # -- Wiring ----------------------------------------------------------------------------------

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        self._runner = runner
        self._retune()
        if runner is not None:
            self.refresh()

    def show_reading(self, reading: Reading) -> None:
        """The registers are read on demand, not polled.

        §7.3's schedule is two tiers and twenty-five register reads are in neither. Adding them
        would cost five round trips a second on a 9600-baud link whose full status screen already
        takes 3.5 s of its 10 s window — for values almost nobody is looking at.
        """
        del reading
        self._retune()

    def _retune(self) -> None:
        live = self._runner is not None and self._runner.is_connected
        driver = self._runner.driver if live and self._runner is not None else None

        gate(self._refresh, driver, *[command for command, _ in self._field_queries()])
        # Every mask setter, not any: a control whose action sends three commands and can send two
        # would do half of what it says.
        if gate(self._apply, driver, *catalog.REGISTER_SETTERS):
            self._apply.setEnabled(self._reading.has_any_value)
        self._discard.setEnabled(self._reading.has_any_value)

    # -- Reading ---------------------------------------------------------------------------------

    def _choose(self, index: int) -> None:
        self._register = registers.ALL[index]
        self._reading = StatusRegisterReading(register=self._register)
        self._rebuild()
        self.refresh()

    def _field_queries(self) -> list[tuple[ScpiCommand, object]]:
        root = f":STAT:{self._register.node}"
        found: list[tuple[ScpiCommand, object]] = []
        for field, _ in catalog.REGISTER_FIELDS:
            command = catalog.register_query(root, field)
            if command is not None:
                found.append((command, None))
        return found

    def refresh(self) -> None:
        """Read all five fields of the selected register."""
        runner = self._runner
        if runner is None or not runner.is_connected:
            return

        self._summary.setText("Reading…")
        runner.run(self._field_queries(), self._absorb)

    def _absorb(self, outcomes: Sequence[CommandOutcome]) -> None:
        """Fold the five answers in.

        **A field that did not answer stays ``None``**, and §11.1 renders it as a dash. Defaulting
        it to zero would draw every bit of that column clear, which is a claim about the receiver
        rather than about the read.
        """
        values: dict[str, int | None] = {}
        for outcome in outcomes:
            field = outcome.command.mnemonic.rsplit(":", 1)[-1].rstrip("?")
            line = outcome.transaction.first_line if outcome.transaction is not None else None
            values[field] = parse_integer(line) if outcome.transaction is not None else None

        self._reading = StatusRegisterReading(
            register=self._register,
            condition=values.get("COND"),
            events=values.get("EVEN"),
            enable=values.get("ENAB"),
            positive_transition=values.get("PTR"),
            negative_transition=values.get("NTR"),
        )
        self._rebuild()
        self._retune()

        answered = sum(1 for value in values.values() if value is not None)
        self._summary.setText(
            f"{self._register.summary} — {answered} of {len(catalog.REGISTER_FIELDS)} fields read."
        )

    # -- Drawing ---------------------------------------------------------------------------------

    def _rebuild(self) -> None:
        self._boxes.clear()
        self._table.setRowCount(_BITS)

        rows = self._reading.rows
        for bit in range(_BITS):
            row = rows[bit] if bit < len(rows) else None
            self._table.setItem(bit, 0, QTableWidgetItem(str(bit)))
            self._table.setItem(bit, 1, QTableWidgetItem(_mark(row.condition if row else None)))
            self._table.setItem(bit, 2, QTableWidgetItem(_mark(row.event if row else None)))

            for column, field in _EDITABLE:
                box = QCheckBox()
                box.setTristate(False)
                box.setAccessibleName(f"Bit {bit} {_COLUMNS[column]}")
                self._boxes[(bit, field)] = box
                holder = QWidget()
                centred = QHBoxLayout(holder)
                centred.setContentsMargins(0, 0, 0, 0)
                centred.setAlignment(Qt.AlignmentFlag.AlignCenter)
                centred.addWidget(box)
                self._table.setCellWidget(bit, column, holder)

            meaning = row.meaning_text if row is not None else "(see documentation)"
            self._table.setItem(bit, 6, QTableWidgetItem(meaning))

        self._redraw_masks()
        self._redraw_raw()

    def _redraw_masks(self) -> None:
        """Put every checkbox back to what the receiver last reported."""
        for (bit, field), box in self._boxes.items():
            mask = self._mask(field)
            # A field the receiver did not answer leaves its column clear rather than guessing.
            # pending_changes() then refuses to send it, so "unread" never becomes "set to zero".
            box.setChecked(mask is not None and bool(mask >> bit & 1))
        self._retune()

    def _redraw_raw(self) -> None:
        parts = []
        for field, _ in catalog.REGISTER_FIELDS:
            value = self._mask(field)
            parts.append(f"{field} {DASH if value is None else f'+{value}'}")
        self._raw.setText("   ".join(parts))

    def _mask(self, field: str) -> int | None:
        return {
            "COND": self._reading.condition,
            "EVEN": self._reading.events,
            "ENAB": self._reading.enable,
            "PTR": self._reading.positive_transition,
            "NTR": self._reading.negative_transition,
        }.get(field)

    # -- Writing ---------------------------------------------------------------------------------

    def edited_masks(self) -> dict[str, int]:
        """What the checkboxes currently say, per writable field."""
        composed: dict[str, int] = {}
        for (bit, field), box in self._boxes.items():
            composed[field] = composed.get(field, 0) | (1 << bit if box.isChecked() else 0)
        return composed

    def pending_changes(self) -> list[tuple[str, int]]:
        """Only the fields whose mask differs from what the receiver reported.

        **Unchanged fields are not sent**, which is not an optimisation: every one of these is a
        tier C command, and sending three where one changed would put two unnecessary writes on an
        instrument for each deliberate one.

        A field the receiver never answered is not sent either. Its checkboxes are all clear
        because there was nothing to draw, and writing that back would be applying a mask of zero
        the user never chose.
        """
        edited = self.edited_masks()
        changes: list[tuple[str, int]] = []
        for field, _ in catalog.REGISTER_FIELDS:
            if field not in dict(_EDITABLE).values():
                continue
            current = self._mask(field)
            if current is None:
                continue
            if edited.get(field, 0) != current:
                changes.append((field, edited.get(field, 0)))
        return changes

    def _apply_masks(self) -> None:
        runner = self._runner
        changes = self.pending_changes()
        if runner is None or not changes:
            return

        root = f":STAT:{self._register.node}"
        commands = []
        lines = []
        for field, value in changes:
            command = catalog.register_setter(root, field)
            rendered = command.rendered(value) if command is not None else None
            if command is None or rendered is None:
                continue
            commands.append((command, value))
            lines.append(rendered)

        if not commands:
            return

        # One confirmation for one user action, listing every command it will send. §8.3 gives the
        # three mask setters a single sentence, and three dialogs for one Apply would be three
        # chances to click through rather than three chances to think.
        if not ask(commands[0][0], commands[0][1], self._palette, self, detail=lines):
            return

        runner.run(commands, lambda _outcomes: self.refresh())

    def csv_rows(self) -> Sequence[Sequence[str]]:
        """The selected register's table.

        The register is named in every row rather than only in a title, because a file of fifteen
        numbered bits with no register name is a file nobody can identify a week later.
        """
        if not self._reading.has_any_value:
            return ()

        editable = dict(_EDITABLE)
        rows: list[Sequence[str]] = [["Register", *_COLUMNS]]
        for bit in range(self._table.rowCount()):
            cells = [self._register.name]
            for column in range(len(_COLUMNS)):
                if column in editable:
                    box = self._boxes.get((bit, editable[column]))
                    cells.append("1" if box is not None and box.isChecked() else "0")
                    continue
                item = self._table.item(bit, column)
                cells.append(item.text() if item is not None else "")
            rows.append(cells)
        return rows

    # -- What a test may read --------------------------------------------------------------------

    @property
    def table(self) -> QTableWidget:
        return self._table

    @property
    def reading(self) -> StatusRegisterReading:
        return self._reading

    @property
    def register(self) -> StatusRegisterMap:
        return self._register

    def box(self, bit: int, field: str) -> QCheckBox | None:
        return self._boxes.get((bit, field))


def _mark(state: bool | None) -> str:
    """§10.10's filled and hollow marks, and §11.1's dash for a field that did not answer.

    Three states, not two: a bit that is clear and a bit nobody read are different facts, and a
    hollow circle for both would report the second as the first.
    """
    if state is None:
        return DASH
    return "\N{BLACK CIRCLE}" if state else "\N{WHITE CIRCLE}"
