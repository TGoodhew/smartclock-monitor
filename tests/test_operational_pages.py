"""§10.8's Holdover, §10.9's Diagnostics and §10.10's Status Registers.

Driven by a runner that answers immediately. Half of what these pages do is decide what to show
when a read **fails**, and a test that had to stand up an event loop to reach that path would not
be written — which is why the seam is a Protocol rather than the concrete session runner.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.capability import Capability
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.models import status_register_map as registers
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_device.transport.transaction import Transaction, TransactionOutcome
from smartclock_monitor.services.commands import Then
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.session import CommandOutcome, Refusal
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.views.diagnostics_page import DiagnosticsPage
from smartclock_monitor.views.holdover_page import HoldoverPage
from smartclock_monitor.views.pages import DASH, TimingPage
from smartclock_monitor.views.registers_page import StatusRegistersPage

DEAF = object()
"""Marker for "the receiver did not answer this one at all"."""


def _answered(command: str, text: str) -> Transaction:
    """A completed transaction carrying ``text``, split the way the line protocol splits it."""
    return Transaction(
        command=command,
        outcome=TransactionOutcome.COMPLETED,
        lines=tuple(text.replace("\r\n", "\n").rstrip("\n").split("\n")) if text else (),
    )


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@dataclass
class FakeRunner:
    """Answers from a dict, synchronously, on the calling thread."""

    answers: dict[str, object] = field(default_factory=dict)
    connected: bool = True
    sent: list[tuple[str, object]] = field(default_factory=list)

    #: Which family is on the other end. Defaults to the SmartClock, because that is what almost
    #: every test is about; a test for §12's capability gating supplies one that supports less.
    driver_for: ReceiverDriver | None = None

    @property
    def is_connected(self) -> bool:
        return self.connected

    @property
    def driver(self) -> ReceiverDriver | None:
        if self.driver_for is not None:
            return self.driver_for
        return SmartClockDriver(clock=FixedClock(NOW)) if self.connected else None

    def run(
        self,
        commands: Sequence[tuple[Capability | ScpiCommand, object]],
        then: Then | None = None,
    ) -> None:
        """Resolve capabilities the way the real runner does, then answer from the dict.

        The resolution has to be here rather than in the tests, because it is what the real one
        does: a page names a capability and the *runner* asks the connected family for its command.
        A double that took mnemonics would let a test pass against a page that had bypassed the
        seam entirely.
        """
        outcomes = []
        for wanted, argument in commands:
            command = self._resolve(wanted)
            capability = wanted if isinstance(wanted, Capability) else None
            if command is None:
                self.sent.append((str(wanted), argument))
                outcomes.append(
                    CommandOutcome(
                        command=None,
                        capability=capability,
                        refusal=Refusal(str(wanted), "no command for this"),
                    )
                )
                continue

            self.sent.append((command.mnemonic, argument))
            answer = self.answers.get(command.mnemonic, DEAF)
            if answer is DEAF:
                outcomes.append(
                    CommandOutcome(command=command, capability=capability, transaction=None)
                )
                continue
            outcomes.append(
                CommandOutcome(
                    command=command,
                    capability=capability,
                    sent=command.rendered(argument),
                    transaction=_answered(command.mnemonic, str(answer)),
                )
            )
        if then is not None:
            then(tuple(outcomes))

    def _resolve(self, wanted: Capability | ScpiCommand) -> ScpiCommand | None:
        if isinstance(wanted, Capability):
            driver = self.driver
            return None if driver is None else driver.command(wanted)
        return wanted


def reading(
    *,
    mode: SmartClockMode = SmartClockMode.LOCKED,
    offset: float = 0.0,
    **kwargs: object,
) -> Reading:
    at = NOW + timedelta(seconds=offset)
    return Reading(
        status=ReceiverStatus(captured_at=at, mode=mode, **kwargs),  # type: ignore[arg-type]
        captured_at=at,
    )


# ---- §10.10 Status Registers -------------------------------------------------------------------


def _register_answers(**fields: str) -> dict[str, object]:
    root = f":STAT:{registers.ALL[0].node}"
    return {f"{root}:{field}?": value for field, value in fields.items()}


def test_the_page_reads_all_five_fields_of_the_selected_register() -> None:
    """§10.10's table has a column each for condition, event, enable, PTr and NTr."""
    runner = FakeRunner(_register_answers(COND="+13", EVEN="+4", ENAB="+7", PTR="+7", NTR="+4"))
    page = StatusRegistersPage()
    page.set_command_runner(runner)

    assert page.reading.condition == 13
    assert page.reading.events == 4
    assert page.reading.enable == 7
    assert page.reading.positive_transition == 7
    assert page.reading.negative_transition == 4


def test_a_field_that_did_not_answer_stays_none_rather_than_zero() -> None:
    """§11.1. Defaulting to zero would draw every bit of that column clear, which is a claim about
    the receiver where a dash is a statement about the read."""
    runner = FakeRunner(_register_answers(COND="+13", ENAB="+7"))
    page = StatusRegistersPage()
    page.set_command_runner(runner)

    assert page.reading.events is None
    assert page.reading.negative_transition is None


def test_an_unread_field_is_never_written_back_as_a_mask_of_zero() -> None:
    """The consequence that matters. Its checkboxes are all clear because there was nothing to
    draw, so applying them would set a mask the user never chose — on a register the application
    could not even read."""
    runner = FakeRunner(_register_answers(COND="+13", ENAB="+7"))
    page = StatusRegistersPage()
    page.set_command_runner(runner)

    assert [field for field, _ in page.pending_changes()] == []


def test_editing_a_mask_marks_exactly_that_field_as_changed() -> None:
    runner = FakeRunner(_register_answers(COND="+13", EVEN="+4", ENAB="+7", PTR="+7", NTR="+4"))
    page = StatusRegistersPage()
    page.set_command_runner(runner)

    box = page.box(3, "ENAB")
    assert box is not None
    box.setChecked(True)  # bit 3 was clear in +7

    assert page.pending_changes() == [("ENAB", 15)]


def test_an_unchanged_mask_is_not_sent() -> None:
    """Every one of these is a tier C command. Sending three where one changed would put two
    unnecessary writes on an instrument for each deliberate one."""
    runner = FakeRunner(_register_answers(COND="+13", EVEN="+4", ENAB="+7", PTR="+7", NTR="+4"))
    page = StatusRegistersPage()
    page.set_command_runner(runner)

    assert page.pending_changes() == []


def test_discarding_puts_the_boxes_back() -> None:
    """It exists because the alternative — a page whose only way out of a half-made edit is to
    navigate away and back — is how someone applies a mask they did not mean to."""
    runner = FakeRunner(_register_answers(COND="+13", EVEN="+4", ENAB="+7", PTR="+7", NTR="+4"))
    page = StatusRegistersPage()
    page.set_command_runner(runner)

    box = page.box(9, "PTR")
    assert box is not None
    box.setChecked(True)
    assert page.pending_changes()

    page._redraw_masks()
    assert page.pending_changes() == []


def test_an_undocumented_bit_says_so_rather_than_inventing_a_label() -> None:
    """§10.10: *"Where a bit meaning is unknown, show the raw state and '(see documentation)'
    rather than inventing a label."*"""
    runner = FakeRunner(_register_answers(COND="+13", EVEN="+4", ENAB="+7", PTR="+7", NTR="+4"))
    page = StatusRegistersPage()
    page.set_command_runner(runner)

    meanings = [
        page.table.item(row, 6).text()  # type: ignore[union-attr]
        for row in range(page.table.rowCount())
    ]
    assert any("(see documentation)" in text for text in meanings)
    assert any("(see documentation)" not in text for text in meanings)


def test_the_raw_line_shows_a_dash_for_a_field_that_did_not_answer() -> None:
    runner = FakeRunner(_register_answers(COND="+13"))
    page = StatusRegistersPage()
    page.set_command_runner(runner)

    assert DASH in page._raw.text()
    assert "+13" in page._raw.text()


def test_nothing_is_sent_while_disconnected() -> None:
    """An Apply button that looks live and silently does nothing is worse than one greyed out."""
    runner = FakeRunner({}, connected=False)
    page = StatusRegistersPage()
    page.set_command_runner(runner)

    assert runner.sent == []
    assert page._refresh.isEnabled() is False


def test_every_register_in_the_map_can_be_read() -> None:
    """The catalog and the register map are two lists of the same five registers. A node in one
    and not the other is a page that reads nothing and says nothing about why."""
    for register in registers.ALL:
        root = f":STAT:{register.node}"
        for name, _ in catalog.REGISTER_FIELDS:
            assert catalog.register_query(root, name) is not None, f"{root}:{name}?"


# ---- §10.9 Diagnostics ---------------------------------------------------------------------------

#: The receiver's own shape, from the fixtures: a ``Log NNN:`` prefix, a packed timestamp, and a
#: message that may itself contain commas — "Holdover started, not tracking GPS" is one entry the
#: Z3805A emits constantly, and splitting on commas cut it in half.
LOG = (
    "Log 001: 20060101.05:10:04: Power on\r\n"
    "Log 002: 20060101.05:11:57: Survey mode started\r\n"
    "Log 003: 20060101.07:15:03: Holdover started, not tracking GPS\r\n"
    "Log 004: 20060101.09:02:14: GPS lock started\r\n"
)


def _diagnostics(**overrides: object) -> tuple[DiagnosticsPage, FakeRunner]:
    answers: dict[str, object] = {
        catalog.DIAGNOSTIC_LOG.mnemonic: LOG,
        catalog.LOG_COUNT.mnemonic: "+4",
        catalog.LIFETIME_HOURS.mnemonic: "+1247",
    }
    answers.update(overrides)
    runner = FakeRunner(answers)
    page = DiagnosticsPage()
    page.set_command_runner(runner)
    return page, runner


def test_the_log_is_read_and_shown() -> None:
    page, _ = _diagnostics()

    assert len(page.entries) == 4
    assert page.log_table.rowCount() == 4


def test_the_lifetime_is_hours_and_a_dash_when_unread() -> None:
    """§10.9: an unread or unparseable answer renders a dash rather than "0 h" — a zero being a
    claim about the hardware where a dash is a statement about the read. And the receiver reports
    **hours**, not a count, whatever the mnemonic says."""
    page, _ = _diagnostics()
    assert page.lifetime_text == "1,247 h"

    deaf, _ = _diagnostics(**{catalog.LIFETIME_HOURS.mnemonic: DEAF})
    assert deaf.lifetime_text == DASH
    assert "0 h" not in deaf.lifetime_text


def test_the_filter_narrows_the_log_without_re_reading() -> None:
    page, runner = _diagnostics()
    before = len(runner.sent)

    page.filter_box.setText("holdover")

    assert page.log_table.rowCount() == 1
    assert len(runner.sent) == before, "filtering is local; it must not cost a round trip"


def test_the_filter_is_case_insensitive() -> None:
    page, _ = _diagnostics()
    page.filter_box.setText("GPS LOCK")

    assert page.log_table.rowCount() == 1


def test_a_sweep_that_passes_credits_the_set() -> None:
    """§10.9 as corrected by #345: ``:DIAG:TEST?`` has its own reply, a single value where the
    manual says "0 indicates test passed", and of ALL the manual says it *"returns test
    information for all of the tests"*. The old reading took ``:DIAG:TEST:RES?`` instead and so
    ran every test and then showed twelve dashes — which looks like the run failed."""
    page, _ = _diagnostics(**{catalog.RUN_SELF_TEST.mnemonic: "+0"})
    page._absorb_test(
        (
            CommandOutcome(
                command=catalog.RUN_SELF_TEST,
                transaction=_answered(":DIAG:TEST? ALL", "+0"),
            ),
        )
    )

    assert page.test_result.severity is Severity.SUCCESS
    assert "Every subsystem passed" in page.test_detail_text


def test_a_failing_sweep_does_not_claim_attribution() -> None:
    """§10.9: *"A non-zero sweep says something in the set did not pass and does not say which."*
    The number is never presentable as eleven separate findings."""
    page, _ = _diagnostics()
    page._absorb_test(
        (
            CommandOutcome(
                command=catalog.RUN_SELF_TEST,
                transaction=_answered(":DIAG:TEST? ALL", "+3"),
            ),
        )
    )

    assert page.test_result.severity is Severity.CRITICAL
    assert "does not say which" in page.test_detail_text


def test_a_single_subsystem_credits_its_own() -> None:
    page, _ = _diagnostics()
    page.subsystem_box.setCurrentText("GPS")
    page._absorb_test(
        (
            CommandOutcome(
                command=catalog.RUN_SELF_TEST,
                transaction=_answered(":DIAG:TEST? GPS", "+0"),
            ),
        )
    )

    assert page.test_result.severity is Severity.SUCCESS
    assert "GPS passed" in page.test_detail_text


def test_all_is_the_default_subsystem() -> None:
    """§10.9's reason, from the manual: one sweep is one disruption, measured at 12.4 s; eleven
    separate runs would be eleven disruptions of a disciplined oscillator."""
    page, _ = _diagnostics()

    assert page.subsystem_box.currentText() == "ALL"


def test_no_error_in_the_queue_reads_as_no_errors() -> None:
    page, _ = _diagnostics()
    page._absorb_errors(
        (
            CommandOutcome(
                command=catalog.ERROR_QUEUE,
                transaction=_answered(":SYST:ERR?", '+0,"No error"'),
            ),
        )
    )

    assert page.queue_text == "No errors."


def test_an_error_in_the_queue_is_shown_verbatim() -> None:
    """§9.5.1: what the machine said, unedited. Someone matching it against the guide's error
    table needs the receiver's own text."""
    page, _ = _diagnostics()
    page._absorb_errors(
        (
            CommandOutcome(
                command=catalog.ERROR_QUEUE,
                transaction=_answered(":SYST:ERR?", '-221,"Settings conflict"'),
            ),
        )
    )

    assert page.queue_text == '-221,"Settings conflict"'


def test_the_log_card_is_bounded_rather_than_grown() -> None:
    """#345: the receiver holds up to 222 entries and the card was as tall as all of them, so the
    filter box and the buttons scrolled away with it — which are exactly the controls someone
    reading the log wants."""
    page, _ = _diagnostics()

    assert page.log_table.maximumHeight() <= 400


# ---- §10.8 Holdover ------------------------------------------------------------------------------


def test_the_two_thresholds_are_not_the_same_one() -> None:
    """#320: the card described one threshold and the page offered two, labelled as though they
    were the same. A user could adjust the editor, watch the reading above it never move, and be
    right to be confused."""
    runner = FakeRunner({catalog.HOLDOVER_DURATION_THRESHOLD.mnemonic: "+86400"})
    page = HoldoverPage()
    page.set_command_runner(runner)
    page.show_reading(reading(hold_threshold_seconds=1e-06))

    assert page.thresholds.value_of("Uncertainty threshold") == "1.000 µs"
    assert page.limit_box.value() == 86_400


def test_an_unread_limit_leaves_apply_disabled() -> None:
    """§10.8: *"The hard-coded 1 was worse than an empty box."* It read as the receiver's answer
    and was not one — on the unit this was verified against the limit is 86 400 seconds, so a user
    adjusting from "1" was working from a number wrong by nearly five orders of magnitude."""
    page = HoldoverPage()
    page.set_command_runner(FakeRunner({}))

    assert page.limit_is_known is False
    assert page.apply_button.isEnabled() is False


def test_a_re_read_does_not_overwrite_what_the_user_is_typing() -> None:
    """§10.8. Whether the value on screen is theirs is decided by comparing against the last value
    the page itself wrote, rather than by a flag around the assignment — when ``valueChanged``
    arrives relative to the setter is the control's business, and a comparison does not depend on
    the answer."""
    runner = FakeRunner({catalog.HOLDOVER_DURATION_THRESHOLD.mnemonic: "+86400"})
    page = HoldoverPage()
    page.set_command_runner(runner)
    assert page.limit_box.value() == 86_400

    page.limit_box.setValue(600)  # the user types
    page.refresh()  # a reconnect re-reads

    assert page.limit_box.value() == 600, "the receiver's answer must not steal the caret"


def test_a_re_read_does_update_a_value_the_page_itself_wrote() -> None:
    """The other half: the limit has one-second resolution, so what the receiver took need not be
    what was sent, and this editor is the only place that figure appears."""
    runner = FakeRunner({catalog.HOLDOVER_DURATION_THRESHOLD.mnemonic: "+86400"})
    page = HoldoverPage()
    page.set_command_runner(runner)

    runner.answers[catalog.HOLDOVER_DURATION_THRESHOLD.mnemonic] = "+3600"
    page.refresh()

    assert page.limit_box.value() == 3600


def test_the_state_pill_distinguishes_holdover_from_lock() -> None:
    page = HoldoverPage()
    # Read into locals before asserting: mypy narrows a property's type at the first identity
    # check and then calls the second one unreachable, which is a false positive that would have
    # to be silenced rather than fixed.
    page.show_reading(reading(mode=SmartClockMode.LOCKED))
    locked = page.state_pill.severity

    page.show_reading(reading(mode=SmartClockMode.HOLDOVER))
    in_holdover = page.state_pill.severity

    assert locked is Severity.SUCCESS
    assert in_holdover is Severity.CRITICAL


def test_the_waiting_reason_is_the_screen_s_own_mode_detail() -> None:
    """§10.8: *"not an answer to :SYNC:HOLD:WAIT?, which nothing sends."*"""
    page = HoldoverPage()
    page.show_reading(reading(mode_detail="Waiting for position hold"))

    assert page.fields.value_of("Waiting reason") == "Waiting for position hold"


def test_exceeded_is_a_dash_when_either_figure_is_missing() -> None:
    """ "No" would be an answer, and one that says the receiver is inside a limit nobody read."""
    page = HoldoverPage()
    page.show_reading(reading(holdover_predicted_seconds=2.5e-06))

    assert page.thresholds.value_of("Currently exceeded") == DASH


def test_exceeded_compares_the_prediction_against_the_threshold() -> None:
    page = HoldoverPage()
    page.show_reading(reading(holdover_predicted_seconds=2.5e-06, hold_threshold_seconds=1e-06))
    assert page.thresholds.value_of("Currently exceeded") == "Yes"

    page.show_reading(reading(holdover_predicted_seconds=0.5e-06, hold_threshold_seconds=1e-06))
    assert page.thresholds.value_of("Currently exceeded") == "No"


def test_the_power_up_guard_never_reports_a_clearance() -> None:
    """§10.8's guard needs a captured power-on log entry that does not exist, so it degrades to
    *unknown* — which is what §10.8 specifies for exactly this case.

    Observed uptime is a **lower bound and never a clearance**: this application having watched
    for two hours says nothing about whether the receiver was powered up two hours ago or two
    months. Reporting it as "safe" would be the guard inventing the fact it exists to check.
    """
    page = HoldoverPage()
    page.show_reading(reading(offset=0))
    page.show_reading(reading(offset=3 * 24 * 3600))

    assert page.observed_uptime() == timedelta(days=3)
    assert page.guard_pill.severity is not Severity.SUCCESS
    assert "unknown" in page.guard_pill.accessibleName().lower()


def test_forcing_holdover_is_the_only_manual_control_that_confirms() -> None:
    """§8.2 classes both recovery commands Safe: they move the unit *toward* lock, which is the
    desired state, and cannot damage anything. Forcing holdover away from it does not."""
    assert catalog.HOLDOVER_FORCE.needs_confirmation is True
    assert catalog.HOLDOVER_RECOVER.needs_confirmation is False
    assert catalog.HOLDOVER_IGNORE_RECOVERY_LIMIT.needs_confirmation is False


def test_a_recovery_command_goes_straight_out() -> None:
    runner = FakeRunner({catalog.HOLDOVER_DURATION_THRESHOLD.mnemonic: "+600"})
    page = HoldoverPage()
    page.set_command_runner(runner)
    runner.sent.clear()

    page._send_safe(catalog.HOLDOVER_RECOVER)

    assert runner.sent == [(":SYNC:HOLD:REC:INIT", None)]


# ---- §10.7.1's hardware bits, now that the registers can be read ---------------------------------


def _timing_with(condition: object) -> TimingPage:
    """A Timing page with enough stored history to have a drift card at all."""
    from smartclock_device.clock import FixedClock
    from smartclock_monitor.services.trend_store import TrendStore

    clock = FixedClock(NOW)
    store = TrendStore.in_memory(clock)
    for index in range(600):
        store.append(
            Reading(
                status=ReceiverStatus(
                    captured_at=NOW - timedelta(seconds=index),
                    mode=SmartClockMode.LOCKED,
                    one_pps_ti_nanoseconds=-2.0,
                ),
                captured_at=NOW - timedelta(seconds=index),
                efc_percent=-16.83,
            )
        )

    page = TimingPage()
    page.show_reading(reading())
    page.set_trend_store(store)
    page.set_command_runner(FakeRunner({catalog.HARDWARE_CONDITION.mnemonic: condition}))
    return page


def test_the_drift_card_reports_the_hardware_bits_once_they_are_read() -> None:
    """§10.7.1: bits 6 and 7 are *read from the receiver rather than recomputed* — they are the
    alarm and the slope is the gauge. Until the Timing page had a runner the card could only say
    they had not been read, which was honest and useless."""
    page = _timing_with("+0")

    assert "both clear" in page._drift_evidence.text()


def test_a_set_bit_7_reaches_the_card_as_critical() -> None:
    """Bit 7 is "EFC voltage at full scale". It outranks the fit however flat the trend looks: the
    hardware is reporting a state and the fit is inferring one."""
    page = _timing_with(f"+{1 << 7}")

    assert page._drift_pill.severity is Severity.CRITICAL
    assert "bit 7 is set" in page._drift_evidence.text()


def test_a_set_bit_6_reaches_the_card_as_caution() -> None:
    page = _timing_with(f"+{1 << 6}")

    assert page._drift_pill.severity is Severity.CAUTION
    assert "near full scale" in page._drift_evidence.text()


def test_a_register_read_that_fails_is_not_reported_as_clear() -> None:
    """An unread bit and a clear bit are different facts, and reporting the first as the second is
    how an alarm gets missed."""
    page = _timing_with(DEAF)

    assert "have not been read" in page._drift_evidence.text()
    assert "both clear" not in page._drift_evidence.text()


def test_the_hardware_condition_query_is_the_catalogued_one() -> None:
    """Named in the catalog rather than assembled from a string the page would have to keep in
    step with the register roots."""
    assert catalog.HARDWARE_CONDITION.mnemonic == ":STAT:OPER:HARD:COND?"
    assert catalog.is_allowed(catalog.HARDWARE_CONDITION.mnemonic) is True


# ---- §10.7's antenna cable delay card ----------------------------------------------------------


def _timing_page(**answers: object) -> TimingPage:
    page = TimingPage()
    page.show_reading(reading())
    page.set_command_runner(FakeRunner(dict(answers)))
    return page


def test_the_current_delay_and_mask_are_read_back() -> None:
    """§10.7's card leads with what the receiver is compensating for, and the elevation mask beside
    it — both read rather than assumed. The bench receiver answers 6.00000E-008 and +10."""
    page = _timing_page(
        **{
            catalog.ANTENNA_DELAY.mnemonic: "+6.00000E-008",
            catalog.ELEVATION_MASK.mnemonic: "+10",
        }
    )

    assert page._antenna_current.value_of("Current") == "60.0 ns"
    assert page._antenna_current.value_of("Elevation mask") == "10°"


def test_an_unread_delay_is_a_dash_not_a_zero() -> None:
    """§11.1 again, and it matters here more than most: a delay of 0 ns is a *setting* someone
    might act on, where a dash says the read did not happen."""
    page = _timing_page()

    assert page._antenna_current.value_of("Current") == DASH


def test_the_two_entry_modes_produce_one_number() -> None:
    """Two ways to the same value, not two settings. The computed figure is shown before it is
    applied so the arithmetic is visible rather than implied."""
    page = _timing_page()

    page._direct_mode.setChecked(True)
    page._delay_ns.setValue(77)
    assert page.intended_delay_ns() == 77.0

    page._cable_mode.setChecked(True)
    page._cable.setCurrentIndex(1)  # LMR-400, 3.93 ns/m
    page._length.setValue(20)

    assert page.intended_delay_ns() == pytest.approx(78.6, abs=0.05)
    assert "Computed delay" in page._computed.text()


def test_the_cable_presets_are_the_three_the_spec_lists() -> None:
    """§10.7's table: RG-213 at 5.05 ns/m from the 58503A guide, Belden 9913 at 3.94, and LMR-400
    at 3.93 — that last one this section's own substitution for a modern installation."""
    from smartclock_device.models import antenna_cable

    page = _timing_page()
    offered = [page._cable.itemText(index) for index in range(page._cable.count())]

    assert offered == [preset.name for preset in antenna_cable.PRESETS]
    assert len(offered) == 3


def test_the_delay_is_sent_in_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The receiver takes seconds and the card is in nanoseconds. Getting that wrong by 1e9 is the
    kind of defect that reaches hardware and is not visible anywhere on screen."""
    # The confirmation is tested in test_confirm_and_commands; here it would only block.
    monkeypatch.setattr("smartclock_monitor.views.pages.ask", lambda *a, **k: True)

    runner = FakeRunner({catalog.SET_ANTENNA_DELAY.mnemonic: ""})
    page = TimingPage()
    page.show_reading(reading())
    page.set_command_runner(runner)
    page._direct_mode.setChecked(True)
    page._delay_ns.setValue(60)

    runner.sent.clear()
    page._send_delay()

    sent = [pair for pair in runner.sent if "ADEL" in pair[0]]
    assert sent, "the page sent nothing"
    assert sent[0][1] == pytest.approx(60e-9), "60 ns is 6e-08 s, not 60"
    assert catalog.SET_ANTENNA_DELAY.rendered(sent[0][1]) == ":GPS:REF:ADEL 0.00000006"


def test_the_confirmation_is_not_skipped_for_the_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    """§8.3 classes it tier C: changing the delay while locked can push the receiver into
    holdover. Declining must send nothing."""
    monkeypatch.setattr("smartclock_monitor.views.pages.ask", lambda *a, **k: False)

    runner = FakeRunner({catalog.SET_ANTENNA_DELAY.mnemonic: ""})
    page = TimingPage()
    page.show_reading(reading())
    page.set_command_runner(runner)
    page._delay_ns.setValue(60)

    runner.sent.clear()
    page._send_delay()

    assert [pair for pair in runner.sent if "ADEL" in pair[0]] == []


def test_a_delay_the_model_will_not_accept_is_not_sent() -> None:
    """The model already knows what the receiver takes. Refusing here costs a message; sending it
    costs a round trip and an error the user has to interpret."""
    from smartclock_device.models import antenna_cable

    assert antenna_cable.is_acceptable_delay(1e9) is False
    assert catalog.SET_ANTENNA_DELAY.rendered(1.0) is None, "and the bound refuses it too"
