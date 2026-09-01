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

from collections.abc import Sequence
from datetime import datetime

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.commands import catalog
from smartclock_device.models.diagnostic_log_entry import DiagnosticLogEntry
from smartclock_device.parsing.diagnostic_log import parse_all
from smartclock_device.parsing.scalars import parse_integer
from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.session import CommandOutcome
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.views.confirm_dialog import ask
from smartclock_monitor.views.pages import DASH, Page, card, label
from smartclock_monitor.widgets.severity_pill import SeverityPill

#: §10.9: about fourteen entries. The log alternates *GPS lock started* and *Holdover started* as
#: the receiver cycles, so fourteen is roughly six events — enough to see a pattern without the
#: card owning the page.
_LOG_HEIGHT = 360

_LOG_COLUMNS = ("", "#", "When", "Entry")


class DiagnosticsPage(Page):
    """§10.9."""

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
        layout.addWidget(self._build_queue())
        layout.addWidget(self._build_lifetime())
        layout.addStretch(1)

        self._retune()

    # -- The cards -------------------------------------------------------------------------------

    def _build_self_test(self) -> QWidget:
        holder, holder_layout = card("Self test")

        row = QHBoxLayout()
        row.addWidget(label("Subsystem", "caption"))
        self._subsystem = QComboBox()
        self._subsystem.setAccessibleName("Which subsystem to test")
        for keyword in catalog.SELF_TEST_SUBSYSTEMS:
            self._subsystem.addItem(keyword)
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
        return holder

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

    def _retune(self) -> None:
        live = self._runner is not None and self._runner.is_connected
        for button in (self._run, self._refresh_log, self._clear_log, self._read_errors):
            button.setEnabled(live)

    # -- Reading ---------------------------------------------------------------------------------

    def refresh(self) -> None:
        """The on-demand read: the log, its count, and the lifetime counter together."""
        runner = self._runner
        if runner is None or not runner.is_connected:
            return

        runner.run(
            [
                (catalog.DIAGNOSTIC_LOG, None),
                (catalog.LOG_COUNT, None),
                (catalog.LIFETIME_HOURS, None),
            ],
            self._absorb,
        )

    def _absorb(self, outcomes: Sequence[CommandOutcome]) -> None:
        by_mnemonic = {outcome.command.mnemonic: outcome for outcome in outcomes}

        log = by_mnemonic.get(catalog.DIAGNOSTIC_LOG.mnemonic)
        if log is not None and log.transaction is not None and log.transaction.succeeded:
            self._entries = parse_all(log.transaction.text)
            self._redraw_log()

        hours = by_mnemonic.get(catalog.LIFETIME_HOURS.mnemonic)
        value = None
        if hours is not None and hours.transaction is not None:
            value = parse_integer(hours.transaction.first_line)
        # §11.1: an unread or unparseable answer renders a dash rather than "0 h" — a zero being a
        # claim about the hardware where a dash is a statement about the read.
        self._lifetime.setText(DASH if value is None else f"{value:,} h")

        count = by_mnemonic.get(catalog.LOG_COUNT.mnemonic)
        reported = None
        if count is not None and count.transaction is not None:
            reported = parse_integer(count.transaction.first_line)
        self._log_summary.setText(
            f"{len(self._entries):,} entries shown"
            + (f", {reported:,} reported by the receiver." if reported is not None else ".")
        )

    def _redraw_log(self) -> None:
        needle = self._filter.text().strip().lower()
        shown = [entry for entry in self._entries if not needle or needle in entry.message.lower()]

        self._log.setRowCount(len(shown))
        for row, entry in enumerate(shown):
            severity = _severity_of(entry)
            # §10.9 as amended by #225: severity is shape **and** colour, never colour alone. The
            # amber-and-red pair is the one §9.4.3 singles out — they converge under protanopia and
            # deuteranopia, and under high contrast both resolve to the same token.
            pill = SeverityPill(severity, "", self._palette)
            self._log.setCellWidget(row, 0, pill)
            self._log.setItem(row, 1, QTableWidgetItem(_index_text(entry)))
            self._log.setItem(row, 2, QTableWidgetItem(_when_text(entry)))
            self._log.setItem(row, 3, QTableWidgetItem(entry.message or entry.raw_text))

    def _read_error_queue(self) -> None:
        runner = self._runner
        if runner is None:
            return
        runner.run([(catalog.ERROR_QUEUE, None)], self._absorb_errors)

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
        if not ask(catalog.RUN_SELF_TEST, subsystem, self._palette, self):
            return

        self._test_result.set_state(Severity.NEUTRAL, "Running…")
        self._test_detail.setText(
            "The receiver drops out of lock for this and re-acquires over several minutes."
        )
        runner.run([(catalog.RUN_SELF_TEST, subsystem)], self._absorb_test)

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
        if not ask(catalog.CLEAR_DIAGNOSTIC_LOG, None, self._palette, self):
            return
        runner.run([(catalog.CLEAR_DIAGNOSTIC_LOG, None)], lambda _o: self.refresh())

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
    def test_detail_text(self) -> str:
        return self._test_detail.text()

    @property
    def filter_box(self) -> QLineEdit:
        return self._filter

    @property
    def subsystem_box(self) -> QComboBox:
        return self._subsystem


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
