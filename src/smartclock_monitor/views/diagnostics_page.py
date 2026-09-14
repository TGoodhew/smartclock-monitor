"""§10.9's Diagnostics page: the self-test, the log, the error queue, and the lifetime counter.

**An ALL run credits every subsystem; a single test credits its own.** ``:DIAGnostic:TEST?`` has its
own reply — a single value where the manual says "0 indicates test passed" — and of the parameter
the manual says *"ALL returns test information for all of the tests"*, so the sweep's answer is a
verdict over the set and every row carries it. The earlier reading took ``:DIAG:TEST:RES?`` as the
answer instead, which reports one pair for whichever test ran last, and so ran every test and then
showed twelve dashes — which looks like the run failed.

**What is not claimed is attribution on a failure.** A non-zero sweep says something in the set did
not pass and does not say which, so the rows carry the only figure the receiver gave and the summary
names the sweep. A user who needs attribution runs the subsystems individually.

**Individually is not the default, and the manual says why:** *"When invoked manually, any of these
diagnostics should be considered to be destructive tests."* One sweep is one disruption, measured at
12.4 s; eleven separate runs would be eleven disruptions of a disciplined oscillator.

**The log is bounded and scrolled, not grown.** The receiver holds up to 222 entries, and a card as
tall as all of them puts the filter box and the buttons a screen and a half away from someone
reading it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import ClassVar, Final

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.capability import Capability, CommandGroup, ReceiverReading
from smartclock_device.models import status_register_map as registers
from smartclock_device.models.diagnostic_log_entry import DiagnosticLogEntry
from smartclock_device.models.status_register_map import faults_with_no_health_label
from smartclock_device.parsing import gps_engine
from smartclock_device.parsing.diagnostic_log import parse_all
from smartclock_device.parsing.scalars import parse_boolean, parse_integer
from smartclock_device.transport.transaction import Transaction
from smartclock_monitor.platform.paths import log_directory
from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.session import CommandOutcome
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.views.capability import command_for, explain, gate
from smartclock_monitor.views.confirm_dialog import ask
from smartclock_monitor.views.pages import DASH, Page, card, label
from smartclock_monitor.widgets.severity_pill import SeverityPill

#: SCPI's code for a mnemonic the receiver does not have, as its error queue words it.
#:
#: Measured on the bench Z3805A: five of §8.5's six answer `-113,"Undefined header"` when the
#: queue is drained first, and the sixth answers normally. Matched on the number rather than the
#: words, because the words are the receiver's and a firmware may phrase them differently.
UNDEFINED_HEADER: Final = "-113"

#: The Operation register's only fault bit: *diagnostic log almost full* (#110).
#:
#: Named rather than written as a literal at the test, and taken from the map rather than typed,
#: so a correction to the map reaches the reading instead of leaving the two to disagree.
_LOG_ALMOST_FULL: Final = next(bit.bit for bit in registers.OPERATION.bits if bit.is_fault)

#: §10.9: about fourteen entries. The log alternates *GPS lock started* and *Holdover started* as
#: the receiver cycles, so fourteen is roughly six events — enough to see a pattern without the
#: card owning the page.
_LOG_HEIGHT = 360

_LOG_COLUMNS = ("", "#", "When", "Entry")


class DiagnosticsPage(Page):
    """§10.9."""

    needs = (
        ReceiverReading.DIAGNOSTIC_LOG,
        ReceiverReading.ERROR_QUEUE,
        ReceiverReading.STATUS_SCREEN,
        ReceiverReading.HEALTH_MONITOR,
    )

    title = "Diagnostics"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._runner: CommandRunner | None = None
        self._entries: tuple[DiagnosticLogEntry, ...] = ()
        self._last_test: datetime | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)
        layout.addWidget(self._build_self_test())
        layout.addWidget(self._build_log())
        layout.addWidget(self._build_conditions())
        layout.addWidget(self._build_queue())
        layout.addWidget(self._build_lifetime())
        layout.addWidget(self._build_front_panel())
        layout.addWidget(self._build_gps_engine())
        layout.addWidget(self._build_application_log())
        layout.addWidget(self._build_experimental())
        layout.addStretch(1)

        self._retune()

    # -- The cards -------------------------------------------------------------------------------

    def _build_self_test(self) -> QWidget:
        holder, holder_layout = card("Self test")

        row = QHBoxLayout()
        row.addWidget(label("Subsystem", "caption"))
        self._subsystem = QComboBox()
        self._subsystem.setAccessibleName("Which subsystem to test")
        # Filled from the connected family's own command — its keywords *are* the subsystem list,
        # so there is no second place for them to be listed and go stale. See _retune.
        row.addWidget(self._subsystem, 1)
        self._run = QPushButton("Run test")
        # §8.3 classes this tier C: the receiver leaves lock entirely and returns to power-up with
        # TFOM 9, then re-acquires over several minutes.
        self._run.setProperty("role", "destructive")
        self._run.setAccessibleName("Run the selected diagnostic")
        self._run.clicked.connect(self._run_self_test)
        row.addWidget(self._run)
        holder_layout.addLayout(row)

        self._test_result = SeverityPill(Severity.NEUTRAL, "Not run this session", self._palette)
        holder_layout.addWidget(self._test_result)
        self._test_detail = label("", "caption")
        self._test_detail.setWordWrap(True)
        holder_layout.addWidget(self._test_detail)
        return holder

    def _build_log(self) -> QWidget:
        holder, holder_layout = card("Diagnostic log")

        row = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("filter…")
        self._filter.setAccessibleName("Filter the log")
        self._filter.textChanged.connect(self._redraw_log)
        row.addWidget(self._filter, 1)
        self._refresh_log = QPushButton("Refresh")
        self._refresh_log.clicked.connect(self.refresh)
        row.addWidget(self._refresh_log)
        self._clear_log = QPushButton("Clear")
        self._clear_log.setProperty("role", "destructive")
        self._clear_log.setAccessibleName("Clear the receiver's diagnostic log")
        self._clear_log.clicked.connect(self._clear)
        row.addWidget(self._clear_log)
        holder_layout.addLayout(row)

        self._log = QTableWidget(0, len(_LOG_COLUMNS))
        self._log.setHorizontalHeaderLabels(list(_LOG_COLUMNS))
        self._log.verticalHeader().setVisible(False)
        self._log.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._log.setAccessibleName("The receiver's diagnostic log")
        # MaxHeight and not Height, so a receiver with four entries shows four rather than four and
        # a wall of empty card.
        self._log.setMaximumHeight(_LOG_HEIGHT)
        header = self._log.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(len(_LOG_COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        holder_layout.addWidget(self._log)

        self._log_summary = label("", "caption")
        holder_layout.addWidget(self._log_summary)

        #: The count is a number; this is the receiver's own verdict on it (#110).
        #:
        #: Three states, because "not read" and "read and fine" are different claims and a pill
        #: that appeared only on the fault would make them look the same.
        self._log_condition = SeverityPill(
            Severity.NEUTRAL, "Log condition not read", self._palette
        )
        holder_layout.addWidget(self._log_condition)
        return holder

    def _build_conditions(self) -> QWidget:
        """§10.4's health monitor has six labels; the Hardware register has twelve bits (#112).

        This card is for the difference. *Time interval measurement failed* and *EEPROM write
        failed* have no label on the health block, so a receiver with either prints
        `HEALTH MONITOR ... [ OK ]` and the Overview page draws six green ticks — the fault is real,
        the register has it, and the page a user watches cannot say so.

        **Here rather than on §10.4**, which is where a user would see it soonest, because §10.4 is
        filled by the poll and the poll's full tier reads one command. Moving the register into it
        is a poll-plan change, and poll-plan changes are measured rather than argued (#58a).
        """
        holder, holder_layout = card("Hardware conditions")
        holder_layout.addWidget(
            label(
                "What the hardware register reports that the health monitor has no label for.",
                "tertiary",
            )
        )
        self._conditions_layout = holder_layout
        self._condition_pills: list[SeverityPill] = []
        self._show_conditions([SeverityPill(Severity.NEUTRAL, "Not read", self._palette)])
        return holder

    def _show_conditions(self, pills: list[SeverityPill]) -> None:
        for pill in self._condition_pills:
            pill.setParent(None)
            pill.deleteLater()
        self._condition_pills = pills
        for pill in pills:
            self._conditions_layout.addWidget(pill)

    def _build_queue(self) -> QWidget:
        holder, holder_layout = card("Error queue")
        row = QHBoxLayout()
        self._queue = label("No errors read this session.", "body")
        self._queue.setWordWrap(True)
        row.addWidget(self._queue, 1)
        self._read_errors = QPushButton("Read errors")
        self._read_errors.clicked.connect(self._read_error_queue)
        row.addWidget(self._read_errors)
        holder_layout.addLayout(row)
        return holder

    def _build_lifetime(self) -> QWidget:
        holder, holder_layout = card("Lifetime")
        self._lifetime = label(DASH, "readout-small")
        self._lifetime.setAccessibleName("Power-on hours")
        holder_layout.addWidget(self._lifetime)
        holder_layout.addWidget(
            label(
                "Worth watching on an instrument whose oscillator ages with running time.",
                "tertiary",
            )
        )
        return holder

    def _build_application_log(self) -> QWidget:
        """§10.9's first omitted card: **what this application saw**, as distinct from what the
        receiver logged.

        The two are different records and the page carries both, because the question "did the
        receiver drop out" and the question "did we lose the port" look identical from the outside
        and have completely different answers.
        """
        holder, holder_layout = card("Application log")
        row = QHBoxLayout()
        self._log_path = label(str(log_directory()), "device")
        self._log_path.setWordWrap(True)
        row.addWidget(self._log_path, 1)
        self._show_folder = QPushButton("Show log folder")
        self._show_folder.setAccessibleName("Open the folder this application logs into")
        self._show_folder.clicked.connect(self.open_log_folder)
        row.addWidget(self._show_folder)
        holder_layout.addLayout(row)
        holder_layout.addWidget(
            label(
                "The port opening, the settings auto-detect settled on, every connection change, "
                "and the receiver's mode and satellite count whenever they move.",
                "tertiary",
            )
        )
        return holder

    def _build_experimental(self) -> QWidget:
        """§8.5's card. Present only while the Settings switch is on.

        **Exactly six, fixed on every model**, and each runs on explicit click — never on a poll
        timer. Results are shown as raw text and any SCPI error is displayed rather than swallowed:
        ``E-113`` is SCPI's *undefined header*, which for a card whose entire purpose is asking
        undocumented questions is a result, and the most useful one available for five of the six.
        """
        holder, holder_layout = card("Undocumented read-only queries")
        holder_layout.addWidget(
            label(
                "These are present in the receiver's command parser but absent from the published "
                "manual. They may return errors or nonsense. No setting is changed.",
                "caption",
            )
        )

        # **Built from the connected family, not from a catalog.** §8.5 has six of these for this
        # receiver and a different family may have none — the set is the family's, so the card is
        # rebuilt when the driver changes rather than drawn once from one family's list.
        self._experimental_rows: dict[str, QLabel] = {}
        self._experimental_buttons: list[QPushButton] = []
        self._experimental_shown: tuple[ScpiCommand, ...] = ()
        #: Which queries this receiver has said it does not have, for this session.
        #:
        #: Per connection rather than per model: §8.5's queries are undocumented, so no model
        #: number predicts which a given firmware has. Asking the receiver is the only thing that
        #: is true of whatever is actually plugged in — and it costs one error read per click.
        self._experimental_absent: set[str] = set()
        self._experimental_asked: ScpiCommand | None = None
        self._experimental_layout = holder_layout

        holder.setVisible(False)
        self._experimental_card = holder
        return holder

    def _refill_subsystems(self, self_test: ScpiCommand | None) -> None:
        """The subsystem list is the self-test command's own keywords.

        Taken from the command rather than kept beside it: a second list saying the same thing is
        a second list to go stale, and §8.1 already has the command declaring what it accepts.
        """
        wanted = list(self_test.keywords) if self_test is not None else []
        if wanted == [self._subsystem.itemText(i) for i in range(self._subsystem.count())]:
            return

        self._subsystem.clear()
        self._subsystem.addItems(wanted)

    def _rebuild_experimental(self, driver: ReceiverDriver | None) -> None:
        """Draw one row per query the connected family actually has.

        §8.5's six belong to this receiver. A card drawn from one family's list and then greyed for
        another would be six controls naming commands that family has never heard of — §9.11's
        "disabled and explained" is about a control the *page* offers, not about inventing controls
        for a receiver to disappoint.
        """
        offered = () if driver is None else driver.commands_for(CommandGroup.EXPERIMENTAL)
        if offered == self._experimental_shown:
            return

        for button in self._experimental_buttons:
            button.setParent(None)
        for answer in self._experimental_rows.values():
            answer.setParent(None)
        self._experimental_rows.clear()
        self._experimental_buttons.clear()
        self._experimental_shown = offered
        # A different family, or a reconnection, knows nothing about the last receiver's firmware.
        self._experimental_absent.clear()

        for command in offered:
            row = QHBoxLayout()
            row.addWidget(label(command.mnemonic, "device"))
            answer = label(DASH, "device")
            self._experimental_rows[command.mnemonic] = answer
            row.addWidget(answer, 1)
            run = QPushButton("Run")
            run.setAccessibleName(f"Run {command.mnemonic}")
            run.clicked.connect(lambda _checked=False, c=command: self._run_experimental(c))
            self._experimental_buttons.append(run)
            row.addWidget(run)
            self._experimental_layout.addLayout(row)

    def set_experimental_visible(self, shown: bool) -> None:
        """§8.5's opt-in. The card is added and removed rather than merely greyed, so a switch
        that is off leaves nothing for a keyboard user to tab into."""
        self._experimental_card.setVisible(shown)

    #: How many queued errors to clear before asking, so the answer afterwards is **this query's**.
    #:
    #: §7.2 measured the problem this exists for: with a single error queued, three successive
    #: commands that each succeeded carried an `E-113` prompt, because the prompt names a queued
    #: error rather than a verdict on the last command. So the card could show the token and — quite
    #: correctly — refuse to say what it meant.
    #:
    #: **Asked by capability, never by mnemonic.** `test_layering.py` caught the first version of
    #: this reaching `commands.catalog` directly, which is §12's #304 defect exactly — a page that
    #: names one family's spelling works only until another family is connected. The gate is right
    #: and the driver answers the question.
    #:
    #: Draining first makes it attributable. Three is chosen because a queue deeper than that has
    #: not been seen on the bench; if one were, the reading below would name an older error and the
    #: row would say so wrongly, which is why the queue's own answer is shown rather than a verdict
    #: invented from it.
    _DRAIN_BEFORE_ASKING: ClassVar[int] = 3

    def _run_experimental(self, command: ScpiCommand) -> None:
        """Ask one undocumented query, with the error queue cleared first and read straight after.

        **The reading afterwards is what makes this card able to say anything.** Asked cold, five of
        this receiver's six answer with the prompt alone and the prompt is a queue indicator — so
        the card could show `E-113` and not know whose it was. Drained and then read, `-113` is
        this query's, and *undefined header* is a fact about the firmware rather than a token.
        """
        runner = self._runner
        if runner is None:
            return
        self._experimental_rows[command.mnemonic].setText("Running…")
        self._experimental_asked = command
        drains = [(Capability.ERROR_QUEUE, None)] * self._DRAIN_BEFORE_ASKING
        runner.run(
            [*drains, (command, None), (Capability.ERROR_QUEUE, None)], self._absorb_experimental
        )

    def _absorb_experimental(self, outcomes: Sequence[CommandOutcome]) -> None:
        """The query's own answer, and the error the queue raised **for it**."""
        asked = self._experimental_asked
        self._experimental_asked = None
        if asked is None:
            return

        answered = next((o for o in outcomes if o.command is asked), None)
        row = self._experimental_rows.get(asked.mnemonic)
        if row is None:
            return
        if answered is None or answered.transaction is None:
            row.setText("no answer")
            return

        body = answered.transaction.text.strip()
        if body:
            row.setText(body)
            return

        # No body, so the answer is whatever the queue raised — and it is attributable because the
        # queue was drained immediately before.
        raised = ""
        for outcome in reversed(outcomes):
            if outcome.capability is Capability.ERROR_QUEUE and outcome.transaction is not None:
                raised = (outcome.transaction.first_line or "").strip()
                break

        if UNDEFINED_HEADER in raised:
            # **A fact about this firmware, not a failure of the query.** §8.5's whole point is
            # asking undocumented questions, and "this receiver does not have it" is the most
            # useful answer available — so the row says it and the button stops offering.
            self._experimental_absent.add(asked.mnemonic)
            row.setText("This receiver does not have this query.")
            self._retune_experimental_buttons()
            return

        row.setText(raised or _experimental_answer(answered.transaction))

    def _retune_experimental_buttons(self) -> None:
        """Stop offering a query the receiver has said it does not have.

        Disabled rather than removed: §9.11's rule is that an absent thing is explained where it
        was, and the row beside it carries the explanation. Removing the button would leave a
        sentence with nothing to attach to.
        """
        for button, command in zip(
            self._experimental_buttons, self._experimental_shown, strict=False
        ):
            if command.mnemonic in self._experimental_absent:
                button.setEnabled(False)
                button.setToolTip("This receiver answered 'undefined header' for this query.")

    def open_log_folder(self) -> str:
        """Open the log folder in the desktop's file manager, and return the path either way."""
        path = log_directory()
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
        return str(path)

    # -- Wiring ----------------------------------------------------------------------------------

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        self._runner = runner
        self._retune()
        if runner is not None:
            self.refresh()

    def show_reading(self, reading: Reading) -> None:
        """Read on demand, not polled. The log is up to 222 entries over a 9600-baud link."""
        del reading
        self._retune()

    def _build_front_panel(self) -> QWidget:
        """§10.9's Front panel card: a toggle for the Active lamp.

        **The manual half of the lamp feature.** It is the escape hatch for a lamp left lit by an
        application that closed unexpectedly, and the only way to exercise `:LED:ACTive` at all
        until something drives it automatically (#123).

        Tier S, so no confirmation — §8.2's ruling is that the command changes no receiver
        behaviour, and a confirmation would be asking permission to change nothing. §9.11's other
        half follows: a Safe setter gets no success bar, so **the toggle's own position is the
        feedback**, and a write that fails puts it back.
        """
        holder, holder_layout = card("Front panel")
        self._lamp = QCheckBox("Active indicator")
        self._lamp.setAccessibleName("The receiver's front-panel Active indicator")
        self._lamp.clicked.connect(self._write_lamp)
        holder_layout.addWidget(self._lamp)
        self._lamp_note = label(
            "The receiver takes about a second to answer a lamp write, so the switch settles a "
            "moment after you click it.",
            "tertiary",
        )
        self._lamp_note.setWordWrap(True)
        holder_layout.addWidget(self._lamp_note)
        return holder

    def _write_lamp(self, wanted: bool) -> None:
        """Write the lamp, and put the switch back if the receiver does not take it."""
        runner = self._runner
        if runner is None or not runner.is_connected:
            self._lamp.setChecked(not wanted)
            return
        runner.run(
            [(Capability.SET_ACTIVE_LAMP, "ON" if wanted else "OFF")],
            lambda outcomes: self._absorb_lamp_write(outcomes, wanted),
        )

    def _absorb_lamp_write(self, outcomes: Sequence[CommandOutcome], wanted: bool) -> None:
        wrote = next((o for o in outcomes if o.capability is Capability.SET_ACTIVE_LAMP), None)
        if wrote is None or wrote.transaction is None or not wrote.transaction.succeeded:
            # **Back where it was, and a sentence saying why.** A switch that stayed where a user
            # put it while the lamp did not move would be the one lie this card can tell.
            self._lamp.setChecked(not wanted)
            self._lamp_note.setText("The receiver did not take that; the switch is back as it was.")

    def _build_gps_engine(self) -> QWidget:
        """§10.9's third card: what GPS receiver is inside the instrument.

        One line per populated field, in receiver order and in the receiver's own words, because
        the answer assigns no meaning to position — see `parsing/gps_engine.py`.
        """
        holder, holder_layout = card("GPS receiver")
        self._gps_engine = label("", "body")
        self._gps_engine.setWordWrap(True)
        self._gps_engine.setAccessibleName("GPS receiver inside the instrument")
        holder_layout.addWidget(self._gps_engine)
        self._gps_engine_note = label("", "caption")
        self._gps_engine_note.setWordWrap(True)
        holder_layout.addWidget(self._gps_engine_note)
        self._gps_engine_card = holder
        return holder

    def _show_gps_engine(self, fields: tuple[str, ...], asked: bool) -> None:
        """Three states, and only one of them is a list.

        Not asked at all — the connected family has no second receiver inside it — is a sentence
        rather than an empty card. Asked and answered with nothing is also a sentence, and a
        different one: the instrument has the query and filled none of it in.
        """
        self._gps_engine.setText("\n".join(fields))
        self._gps_engine.setVisible(bool(fields))
        if fields:
            self._gps_engine_note.setVisible(False)
            return
        self._gps_engine_note.setText(
            "This receiver is the GPS receiver — there is no separate engine inside it."
            if not asked
            else "The instrument answered, and filled none of the fields in."
        )
        self._gps_engine_note.setVisible(True)

    def _retune(self) -> None:
        live = self._runner is not None and self._runner.is_connected
        driver = self._runner.driver if live and self._runner is not None else None

        gate(self._run, driver, Capability.RUN_SELF_TEST)
        gate(self._clear_log, driver, Capability.CLEAR_DIAGNOSTIC_LOG)
        gate(self._refresh_log, driver, Capability.DIAGNOSTIC_LOG)
        gate(self._read_errors, driver, Capability.ERROR_QUEUE)
        if not gate(self._lamp, driver, Capability.ACTIVE_LAMP, Capability.SET_ACTIVE_LAMP):
            self._lamp_note.setText(explain(driver))

        if driver is not None and driver.command(Capability.OPERATION_CONDITION) is None:
            self._decline_conditions()

        self._rebuild_experimental(driver)
        self._refill_subsystems(command_for(self._runner, Capability.RUN_SELF_TEST))

    def set_palette_tokens(self, palette: Palette) -> None:
        """Repaint the pills this page owns.

        Custom widgets take their colours from a palette object rather than from QSS, so a theme
        change has to reach each one. The page had no override at all, which left the self-test
        verdict painted in the old theme until it was re-run.
        """
        super().set_palette_tokens(palette)
        for pill in (self._test_result, self._log_condition, *self._condition_pills):
            pill.set_palette_tokens(palette)

    # -- Reading ---------------------------------------------------------------------------------

    def refresh(self) -> None:
        """The on-demand read: the log, its count, the lifetime counter and the two condition
        registers, together.

        The registers are here rather than in the poll because they are read on demand with
        everything else this page shows, and because the full tier reads one command (#58a).
        """
        runner = self._runner
        if runner is None or not runner.is_connected:
            return

        runner.run(
            [
                (Capability.DIAGNOSTIC_LOG, None),
                (Capability.LOG_COUNT, None),
                (Capability.LIFETIME_HOURS, None),
                (Capability.GPS_ENGINE, None),
                (Capability.OPERATION_CONDITION, None),
                (Capability.HARDWARE_CONDITION, None),
                (Capability.ACTIVE_LAMP, None),
            ],
            self._absorb,
        )

    def _absorb(self, outcomes: Sequence[CommandOutcome]) -> None:
        # Keyed by **capability**, which is what was asked for. Keying by mnemonic meant the page
        # knowing the connected family's spelling of its own question.
        answered = {outcome.capability: outcome for outcome in outcomes if outcome.capability}

        log = answered.get(Capability.DIAGNOSTIC_LOG)
        if log is not None and log.transaction is not None and log.transaction.succeeded:
            self._entries = parse_all(log.transaction.text)
            self._redraw_log()

        hours = answered.get(Capability.LIFETIME_HOURS)
        value = None
        if hours is not None and hours.transaction is not None:
            value = parse_integer(hours.transaction.first_line)
        # §11.1: an unread or unparseable answer renders a dash rather than "0 h" — a zero being a
        # claim about the hardware where a dash is a statement about the read.
        self._lifetime.setText(DASH if value is None else f"{value:,} h")

        lamp = answered.get(Capability.ACTIVE_LAMP)
        if lamp is not None and lamp.transaction is not None and lamp.transaction.succeeded:
            lit = parse_boolean(lamp.transaction.first_line)
            if lit is not None:
                # Without the guard the click handler fires on every refresh and writes the lamp
                # back to where it already is, once a second, for ever.
                self._lamp.blockSignals(True)
                self._lamp.setChecked(lit)
                self._lamp.blockSignals(False)

        self._absorb_conditions(answered)

        engine = answered.get(Capability.GPS_ENGINE)
        self._show_gps_engine(
            gps_engine.parse(engine.transaction.first_line)
            if engine is not None and engine.transaction is not None
            else (),
            asked=engine is not None,
        )

        count = answered.get(Capability.LOG_COUNT)
        reported = None
        if count is not None and count.transaction is not None:
            reported = parse_integer(count.transaction.first_line)
        self._log_summary.setText(
            f"{len(self._entries):,} entries shown"
            + (f", {reported:,} reported by the receiver." if reported is not None else ".")
        )

    def _decline_conditions(self) -> None:
        """§9.11: a family with no status registers is told so, where the reading would be.

        A talker has no register to read and never will, which is a different sentence from "not
        read yet" and has to stay a different sentence — the first is about the receiver and the
        second is about this application.
        """
        sentence = explain(None if self._runner is None else self._runner.driver)
        self._log_condition.set_state(Severity.NEUTRAL, sentence)
        self._show_conditions([SeverityPill(Severity.NEUTRAL, sentence, self._palette)])

    def _absorb_conditions(self, answered: Mapping[Capability, CommandOutcome]) -> None:
        """What the two condition registers said, as sentences rather than as numbers.

        #110 and #112. Both registers are already documented bit by bit in
        `status_register_map.py` and already have a page that shows them raw (§10.10); what was
        missing is anything that **reads** them and says what they mean where a user would look.
        """
        if _declined(answered.get(Capability.OPERATION_CONDITION)):
            # The runner answers a capability the connected family has no command for with a
            # refusal rather than silence, and the two mean different things: this family will
            # never have this reading, where silence is a read that has not happened yet.
            self._decline_conditions()
            return

        operation = _register_reading(answered.get(Capability.OPERATION_CONDITION))
        if operation is None:
            self._log_condition.set_state(Severity.NEUTRAL, "Log condition not read")
        elif operation & (1 << _LOG_ALMOST_FULL):
            # §9.13: colour, shape and text, and the text says what to do about it. CAUTION rather
            # than CRITICAL — the log is still recording, and the receiver is still disciplining.
            self._log_condition.set_state(
                Severity.CAUTION, "Log almost full — clear it to keep recording"
            )
        else:
            self._log_condition.set_state(Severity.SUCCESS, "Log has room")

        hardware = _register_reading(answered.get(Capability.HARDWARE_CONDITION))
        if hardware is None:
            self._show_conditions([SeverityPill(Severity.NEUTRAL, "Not read", self._palette)])
            return

        unlabelled = faults_with_no_health_label(hardware)
        if not unlabelled:
            self._show_conditions(
                [
                    SeverityPill(
                        Severity.SUCCESS,
                        "Nothing the health monitor cannot show",
                        self._palette,
                    )
                ]
            )
            return
        self._show_conditions(
            [SeverityPill(Severity.CRITICAL, bit.meaning, self._palette) for bit in unlabelled]
        )

    def _redraw_log(self) -> None:
        needle = self._filter.text().strip().lower()
        shown = [entry for entry in self._entries if not needle or needle in entry.message.lower()]

        self._log.setRowCount(len(shown))
        for row, entry in enumerate(shown):
            severity = _severity_of(entry)
            # §10.9 as amended by #225: severity is shape **and** colour, never colour alone. The
            # amber-and-red pair is the one §9.4.3 singles out — they converge under protanopia and
            # deuteranopia, which is reason enough on its own now that D3 has removed the
            # high-contrast theme where they also shared a token.
            pill = SeverityPill(severity, "", self._palette)
            self._log.setCellWidget(row, 0, pill)
            self._log.setItem(row, 1, QTableWidgetItem(_index_text(entry)))
            self._log.setItem(row, 2, QTableWidgetItem(_when_text(entry)))
            self._log.setItem(row, 3, QTableWidgetItem(entry.message or entry.raw_text))

    def _read_error_queue(self) -> None:
        runner = self._runner
        if runner is None:
            return
        runner.run([(Capability.ERROR_QUEUE, None)], self._absorb_errors)

    def _absorb_errors(self, outcomes: Sequence[CommandOutcome]) -> None:
        if not outcomes or outcomes[0].transaction is None:
            self._queue.setText("The error queue could not be read.")
            return

        text = (outcomes[0].transaction.first_line or "").strip()
        if not text or text.startswith(("+0,", "0,")):
            self._queue.setText("No errors.")
        else:
            self._queue.setText(text)

    # -- Writing ---------------------------------------------------------------------------------

    def _run_self_test(self) -> None:
        runner = self._runner
        if runner is None:
            return

        subsystem = self._subsystem.currentText()
        if not ask(
            command_for(self._runner, Capability.RUN_SELF_TEST), subsystem, self._palette, self
        ):
            return

        self._test_result.set_state(Severity.NEUTRAL, "Running…")
        self._test_detail.setText(
            "The receiver drops out of lock for this and re-acquires over several minutes."
        )
        runner.run([(Capability.RUN_SELF_TEST, subsystem)], self._absorb_test)

    def _absorb_test(self, outcomes: Sequence[CommandOutcome]) -> None:
        if not outcomes or outcomes[0].transaction is None:
            self._test_result.set_state(Severity.NEUTRAL, "No answer")
            self._test_detail.setText("The receiver did not answer the test.")
            return

        code = parse_integer(outcomes[0].transaction.first_line)
        subsystem = self._subsystem.currentText()

        if code is None:
            self._test_result.set_state(Severity.NEUTRAL, "Unreadable")
            self._test_detail.setText(f"{subsystem}: the answer could not be read.")
            return

        if code == 0:
            self._test_result.set_state(Severity.SUCCESS, "Passed")
            self._test_detail.setText(
                f"{subsystem} passed."
                if subsystem != "ALL"
                else "Every subsystem passed — ALL returns a verdict over the set."
            )
            return

        self._test_result.set_state(Severity.CRITICAL, "Failed")
        # Attribution is deliberately not claimed: a non-zero sweep says something in the set did
        # not pass and does not say which, so the figure is presented as the sweep's own.
        self._test_detail.setText(
            f"{subsystem} returned {code}. "
            + (
                "A sweep does not say which subsystem failed — run them individually for that."
                if subsystem == "ALL"
                else "See the guide for what this code means."
            )
        )

    def _clear(self) -> None:
        runner = self._runner
        if runner is None:
            return
        if not ask(
            command_for(self._runner, Capability.CLEAR_DIAGNOSTIC_LOG), None, self._palette, self
        ):
            return
        runner.run([(Capability.CLEAR_DIAGNOSTIC_LOG, None)], lambda _o: self.refresh())

    def csv_rows(self) -> Sequence[Sequence[str]]:
        """The diagnostic log as shown, **filter included**.

        §9.7.4 scopes Export to the current view, so someone who has narrowed the log to
        "holdover" and pressed Export wants those entries — handing them all 222 would silently
        discard the narrowing they had just done.
        """
        if self._log.rowCount() == 0:
            return ()

        rows: list[Sequence[str]] = [["#", "When", "Entry"]]
        for row in range(self._log.rowCount()):
            cells = []
            for column in (1, 2, 3):
                item = self._log.item(row, column)
                cells.append(item.text() if item is not None else "")
            rows.append(cells)
        return rows

    # -- What a test may read --------------------------------------------------------------------

    @property
    def log_table(self) -> QTableWidget:
        return self._log

    @property
    def entries(self) -> tuple[DiagnosticLogEntry, ...]:
        return self._entries

    @property
    def lifetime_text(self) -> str:
        return self._lifetime.text()

    @property
    def queue_text(self) -> str:
        return self._queue.text()

    @property
    def test_result(self) -> SeverityPill:
        return self._test_result

    @property
    def lamp_switch(self) -> QCheckBox:
        return self._lamp

    @property
    def lamp_note_text(self) -> str:
        return self._lamp_note.text()

    @property
    def log_condition(self) -> tuple[Severity, str]:
        """The receiver's verdict on its own log, as both channels §9.13 requires."""
        return self._log_condition.severity, self._log_condition.text

    @property
    def hardware_conditions(self) -> list[tuple[Severity, str]]:
        """What the hardware register reports that §10.4's health monitor has no label for."""
        return [(pill.severity, pill.text) for pill in self._condition_pills]

    def palette_of_condition_pills(self) -> list[Palette]:
        return [pill.palette_tokens for pill in (self._log_condition, *self._condition_pills)]

    @property
    def test_detail_text(self) -> str:
        return self._test_detail.text()

    @property
    def filter_box(self) -> QLineEdit:
        return self._filter

    @property
    def subsystem_box(self) -> QComboBox:
        return self._subsystem


def _experimental_answer(transaction: Transaction) -> str:
    """What §8.5's card shows for one query.

    **A body is shown verbatim.** Where there is none, the receiver answered with the prompt
    alone, and the prompt's ``E-nnn`` token is what §8.5 expects for five of the six — SCPI's
    *undefined header*, which for a card whose purpose is asking undocumented questions is a
    result rather than a failure.

    **It is worded as the queue's state, not as this query's answer.** §7.2 measured the
    difference: with a single error queued, three successive commands that each succeeded and
    returned correct data all carried an ``E-113`` prompt, because the prompt names the *newest
    queued* error while ``:SYST:ERR?`` returns the oldest first. Writing "this returned E-113"
    would be a claim the prompt does not support.
    """
    body = transaction.text.strip()
    if body:
        return body

    token = transaction.prompt_status
    if token:
        return f"no answer; the receiver's error queue reported {token}"
    return "no answer"


def _declined(outcome: CommandOutcome | None) -> bool:
    """Whether the connected family answered *I have no command for that*."""
    return outcome is not None and outcome.command is None


def _register_reading(outcome: CommandOutcome | None) -> int | None:
    """One register's condition as a number, or ``None`` when it was not read or did not parse."""
    if outcome is None or outcome.transaction is None or not outcome.transaction.succeeded:
        return None
    return parse_integer(outcome.transaction.first_line)


def _severity_of(entry: DiagnosticLogEntry) -> Severity:
    """§10.9: power and mode transitions neutral, holdover amber, hardware or self-test failure red.

    Keyed on the entry's own text because that is all the receiver gives — there is no severity
    field in the log — and an entry this does not recognise stays neutral rather than being guessed
    into a colour.
    """
    text = entry.message.lower()
    if "fail" in text or "error" in text:
        return Severity.CRITICAL
    if "holdover" in text:
        return Severity.CAUTION
    return Severity.NEUTRAL


def _index_text(entry: DiagnosticLogEntry) -> str:
    return DASH if entry.number is None else f"{entry.number:03d}"


def _when_text(entry: DiagnosticLogEntry) -> str:
    return DASH if entry.timestamp is None else entry.timestamp.strftime("%Y-%m-%d %H:%M:%S")
