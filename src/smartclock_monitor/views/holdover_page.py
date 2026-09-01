"""§10.8's Holdover page: the state, the two thresholds, and the manual controls.

**There are two thresholds and only one of them can be set.** #316 recorded this as a unit
disagreement — the wireframe in microseconds, the editor in seconds — which was the symptom rather
than the fault:

- the **uncertainty threshold** is the status screen's ``HOLD THR``, what the predicted 24 h
  uncertainty is compared against, and **read only**: the guide lists exactly one threshold command
  and this is not it;
- the **holdover duration limit** is ``:SYNC:HOLD:DUR:THR``, *"the duration in seconds which
  represents a limit against which the elapsed time of holdover is compared"*.

A user could otherwise adjust the editor, watch the reading above it never move, and be right to be
confused.

**An unread limit is an empty box, and Apply is disabled while it is.** The hard-coded 1 was worse
than an empty box: it read as the receiver's answer and was not one, and on the unit this was
verified against the limit is 86 400 seconds — so a user adjusting from "1" was working from a
number wrong by nearly five orders of magnitude.

**A re-read never overwrites a number the user is part way through typing.** Whether the value is
theirs is decided by comparing against the last value this page itself wrote, rather than by a flag
around the assignment: when ``valueChanged`` arrives relative to the setter is the control's
business, and a comparison does not depend on the answer.

**The power-up guard degrades to "unknown", and that is the specified behaviour rather than a gap.**
§10.8 computes it from app-observed uptime plus the log's power-on entries; the log half needs a
captured power-on entry that does not exist, so keying a safety decision on a string nobody has seen
the receiver print would be inventing the guard rather than implementing it. Unknown requires the
extra tick, which §10.8 specifies for exactly this case.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.commands import catalog
from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_device.parsing.scalars import parse_decimal
from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.session import CommandOutcome
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.views.confirm_dialog import ask
from smartclock_monitor.views.pages import DASH, FieldGrid, Page, card, label
from smartclock_monitor.widgets.severity_pill import SeverityPill

#: §10.8: do not force holdover within 24 hours of power-up — it corrupts SmartClock oscillator
#: learning. The same figure §10.7.1 excludes from the drift fit, and named once for that reason.
POWER_UP_GUARD = timedelta(hours=24)

#: The spin steps §10.8 gives, which are right for a limit with one-second resolution.
_STEP = 1
_PAGE_STEP = 60


class HoldoverPage(Page):
    """§10.8."""

    title = "Holdover"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._runner: CommandRunner | None = None
        self._mode: SmartClockMode = SmartClockMode.UNKNOWN
        self._connected_at: datetime | None = None
        self._now: datetime | None = None

        #: The last value this page wrote into the editor. A re-read compares against it to decide
        #: whether the number on screen is the user's — see the module docstring.
        self._written: int | None = None
        self._limit_known = False

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)
        layout.addWidget(self._build_state())
        layout.addWidget(self._build_thresholds())
        layout.addWidget(self._build_manual())
        layout.addStretch(1)

        self._retune()

    # -- The cards -------------------------------------------------------------------------------

    def _build_state(self) -> QWidget:
        holder, holder_layout = card("Current state")
        self._state = SeverityPill(Severity.NEUTRAL, "Unknown", self._palette)
        holder_layout.addWidget(self._state)
        self._fields = FieldGrid(
            (
                "Predicted 24 h uncertainty",
                "Present time error",
                "Duration",
                "Waiting reason",
            )
        )
        holder_layout.addWidget(self._fields)
        return holder

    def _build_thresholds(self) -> QWidget:
        holder, holder_layout = card("Thresholds")

        self._uncertainty = FieldGrid(("Uncertainty threshold", "Currently exceeded"))
        holder_layout.addWidget(self._uncertainty)
        holder_layout.addWidget(
            label(
                "The uncertainty threshold is read only — the guide lists exactly one threshold "
                "command and this is not it.",
                "tertiary",
            )
        )

        row = QHBoxLayout()
        row.addWidget(label("Holdover duration limit", "caption"))
        self._limit = QSpinBox()
        self._limit.setRange(1, 999_999)
        self._limit.setSingleStep(_STEP)
        self._limit.setSuffix(" s")
        self._limit.setAccessibleName("Holdover duration limit, in seconds")
        self._limit.setSpecialValueText("")
        self._limit.setKeyboardTracking(False)
        self._limit.valueChanged.connect(lambda _v: self._retune())
        row.addWidget(self._limit)

        self._apply = QPushButton("Apply")
        self._apply.setProperty("role", "destructive")
        self._apply.setAccessibleName("Send the holdover duration limit to the receiver")
        self._apply.clicked.connect(self._apply_limit)
        row.addWidget(self._apply)
        row.addStretch(1)
        holder_layout.addLayout(row)
        return holder

    def _build_manual(self) -> QWidget:
        holder, holder_layout = card("Manual control")
        holder_layout.addWidget(
            label(
                "Do not force holdover within 24 hours of power-up. Doing so corrupts the "
                "SmartClock oscillator learning process.",
                "body",
            )
        )
        self._guard = SeverityPill(Severity.NEUTRAL, "Time since power-up: unknown", self._palette)
        holder_layout.addWidget(self._guard)

        row = QHBoxLayout()
        self._force = QPushButton("Force holdover")
        self._force.setProperty("role", "destructive")
        self._force.clicked.connect(self._force_holdover)
        self._recover = QPushButton("Recover now")
        self._recover.clicked.connect(lambda: self._send_safe(catalog.HOLDOVER_RECOVER))
        self._ignore = QPushButton("Ignore recovery limit")
        self._ignore.clicked.connect(
            lambda: self._send_safe(catalog.HOLDOVER_IGNORE_RECOVERY_LIMIT)
        )
        for button in (self._force, self._recover, self._ignore):
            row.addWidget(button)
        row.addStretch(1)
        holder_layout.addLayout(row)
        return holder

    # -- Wiring ----------------------------------------------------------------------------------

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        self._runner = runner
        self._retune()
        if runner is not None:
            self.refresh()

    def show_reading(self, reading: Reading) -> None:
        """Most of this card is on the status screen already, so it comes from the poll loop.

        Only the duration limit needs its own read, and §10.8 says when: on navigation, on every
        reconnect, and again after a successful Apply.
        """
        status = reading.status
        self._mode = status.mode
        self._now = reading.captured_at or status.captured_at
        if self._connected_at is None:
            self._connected_at = self._now

        self._state.set_state(*_state_of(status.mode))
        self._fields.set("Predicted 24 h uncertainty", _micro(status.holdover_predicted_seconds))
        self._fields.set("Present time error", _micro(status.holdover_present_seconds))
        self._fields.set(
            "Duration", DASH if status.holdover_duration is None else str(status.holdover_duration)
        )
        # §10.8: the *Waiting reason* row shows the status screen's own mode detail, not an answer
        # to :SYNC:HOLD:WAIT?, which nothing sends.
        self._fields.set("Waiting reason", status.mode_detail or DASH)

        self._uncertainty.set("Uncertainty threshold", _micro(status.hold_threshold_seconds))
        exceeded = _exceeded(status.holdover_predicted_seconds, status.hold_threshold_seconds)
        self._uncertainty.set("Currently exceeded", exceeded)

        self._redraw_guard()
        self._retune()

    def _retune(self) -> None:
        live = self._runner is not None and self._runner.is_connected
        for button in (self._force, self._recover, self._ignore):
            button.setEnabled(live)
        # Apply stays disabled while the limit is unread — there being nothing to apply.
        self._apply.setEnabled(live and self._limit_known)

    # -- Reading ---------------------------------------------------------------------------------

    def refresh(self) -> None:
        runner = self._runner
        if runner is None or not runner.is_connected:
            return
        runner.run([(catalog.HOLDOVER_DURATION_THRESHOLD, None)], self._absorb_limit)

    def _absorb_limit(self, outcomes: Sequence[CommandOutcome]) -> None:
        if not outcomes or outcomes[0].transaction is None:
            return

        seconds = parse_decimal(outcomes[0].transaction.first_line)
        if seconds is None:
            # An unread field stays empty — on a read that fails, on a driver whose catalog has no
            # such query, and before the first read.
            self._limit_known = False
            self._retune()
            return

        value = int(seconds)
        # A re-read never overwrites a number the user is part way through typing. Whether the
        # value on screen is theirs is decided by comparing it against the last value this page
        # wrote, not by a flag around the setter.
        if self._written is None or self._limit.value() == self._written:
            self._limit.setValue(value)
            self._written = value

        self._limit_known = True
        self._retune()

    # -- Writing ---------------------------------------------------------------------------------

    def _apply_limit(self) -> None:
        runner = self._runner
        if runner is None or not self._limit_known:
            return

        value = self._limit.value()
        if not ask(catalog.SET_HOLDOVER_DURATION_THRESHOLD, value, self._palette, self):
            return

        # Re-read after applying: the limit has one-second resolution, so what the receiver took
        # need not be what was sent, and this editor is the only place that figure appears.
        runner.run([(catalog.SET_HOLDOVER_DURATION_THRESHOLD, value)], lambda _o: self.refresh())

    def _force_holdover(self) -> None:
        runner = self._runner
        if runner is None:
            return
        if not ask(catalog.HOLDOVER_FORCE, None, self._palette, self):
            return
        runner.run([(catalog.HOLDOVER_FORCE, None)])

    def _send_safe(self, command: object) -> None:
        """§8.2 classes both recovery commands Safe, so they go on click with no dialog."""
        runner = self._runner
        if runner is None:
            return
        runner.run([(command, None)])  # type: ignore[list-item]

    # -- The power-up guard ------------------------------------------------------------------------

    def _redraw_guard(self) -> None:
        """§10.8's guard, degraded to *unknown* — which is what §10.8 specifies for this case.

        The app-observed half is real: this session knows when it connected. The log half needs a
        captured power-on entry, and none exists, so the guard would otherwise be keying a safety
        decision on a string nobody has seen the receiver print.

        Observed uptime is therefore reported as a **lower bound** and never as a clearance: this
        application has been watching for two hours, which says nothing about whether the receiver
        was powered up two hours ago or two months.
        """
        observed = self.observed_uptime()
        if observed is None:
            self._guard.set_state(Severity.CAUTION, "Time since power-up: unknown")
            return

        self._guard.set_state(
            Severity.CAUTION,
            f"Watched for {_duration(observed)} — time since power-up unknown",
        )

    def observed_uptime(self) -> timedelta | None:
        """How long this application has been watching. Not how long the receiver has been up."""
        if self._connected_at is None or self._now is None:
            return None
        return self._now - self._connected_at

    def csv_rows(self) -> Sequence[Sequence[str]]:
        """Both cards, plus the duration limit — which lives in a spin box rather than a grid and
        would otherwise be the one figure on the page the export omitted."""
        rows: list[Sequence[str]] = [["Card", "Field", "Value"]]
        for name, grid in (("Current state", self._fields), ("Thresholds", self._uncertainty)):
            rows.extend([name, field, value] for field, value in grid.rows())
        if self._limit_known:
            rows.append(["Thresholds", "Holdover duration limit", str(self._limit.value())])
        return rows

    # -- What a test may read --------------------------------------------------------------------

    @property
    def limit_box(self) -> QSpinBox:
        return self._limit

    @property
    def limit_is_known(self) -> bool:
        return self._limit_known

    @property
    def apply_button(self) -> QPushButton:
        return self._apply

    @property
    def state_pill(self) -> SeverityPill:
        return self._state

    @property
    def guard_pill(self) -> SeverityPill:
        return self._guard

    @property
    def fields(self) -> FieldGrid:
        return self._fields

    @property
    def thresholds(self) -> FieldGrid:
        return self._uncertainty


def _state_of(mode: SmartClockMode) -> tuple[Severity, str]:
    match mode:
        case SmartClockMode.LOCKED:
            return Severity.SUCCESS, "Locked to GPS — not in holdover"
        case SmartClockMode.HOLDOVER:
            return Severity.CRITICAL, "In holdover — running on the oscillator alone"
        case SmartClockMode.RECOVERY:
            return Severity.CAUTION, "Recovering — reacquiring GPS"
        case SmartClockMode.POWER_UP:
            return Severity.CAUTION, "Warming up after power was applied"
        case _:
            return Severity.NEUTRAL, "Unknown"


def _micro(seconds: float | None) -> str:
    """§10.8's wireframe is in microseconds, and these values are seconds on the wire."""
    return DASH if seconds is None else f"{seconds * 1e6:.3f} µs"


def _exceeded(predicted: float | None, threshold: float | None) -> str:
    """Whether the predicted uncertainty is over the threshold.

    ``—`` where either is missing: "No" would be an answer, and one that says the receiver is
    inside a limit nobody read.
    """
    if predicted is None or threshold is None:
        return DASH
    return "Yes" if predicted > threshold else "No"


def _duration(span: timedelta) -> str:
    days, rest = divmod(int(span.total_seconds()), 86_400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days} d {hours} h"
    if hours:
        return f"{hours} h {minutes} min"
    return f"{minutes} min"
