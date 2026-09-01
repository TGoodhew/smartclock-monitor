"""§10.14's Time & Leap Seconds page. **Read-only, deliberately** — see §10.14.1's question 2.

``:PTIM:TCOD:FORMat`` has a setter and it is not catalogued. ``:PTIM:TZONe`` would set the offset
the *receiver* reports in, which is a different thing from the zone this application displays in,
and it is tier C: changing it would move every reported time including the timecode output, for a
cosmetic gain the display-zone picker already provides without touching the device.

**The receiver's own date is shown beside the corrected one, never instead of it** (§7.4). The
correction is reported and explained. A user who sees a date two decades out with no explanation
reasonably concludes the hardware has failed, and one who never sees it cannot tell a corrected
receiver from a correct one.

**The zone is always named.** Never an unlabelled wall-clock time (§11.2, #95): a reading that does
not say which zone it is in cannot be compared to anything, and neither can one that does not say
which *time scale* the receiver is on — UTC and GPS differ by the accumulated leap seconds.

**The time code itself is not shown, and that is a decision rather than an omission.**
``:PTIM:TCOD?`` does not answer when asked: it answers on the receiver's own 1 Hz cadence, about
509 ms before the 1 PPS it names. A request lands in the next emission slot and blocks for up to a
second — a cost a read-only page has no reason to pay, and one charged again on every refresh. The
format is the part that does not change and the part without which the message cannot be read at
all.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from enum import Enum

from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QVBoxLayout, QWidget

from smartclock_device.commands import catalog, leap
from smartclock_device.models import time_code_format
from smartclock_device.models.receiver_status import LeapSecondPending, ReceiverStatus
from smartclock_device.parsing.scalars import parse_boolean, parse_first_of_list, parse_integer
from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.session import CommandOutcome
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.views.pages import DASH, FieldGrid, Page, card, label
from smartclock_monitor.views.wording import humanise
from smartclock_monitor.widgets.severity_pill import SeverityPill


class DisplayZone(Enum):
    """Which zone the clock card renders in.

    Two, not a full zone list. §10.14 wants the zone *named* rather than chosen from a thousand,
    and the two that matter are the one the user is sitting in and the one the receiver is on.
    """

    LOCAL = "local"
    UTC = "utc"


class TimePage(Page):
    """§10.14."""

    title = "Time"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._runner: CommandRunner | None = None
        self._zone = DisplayZone.LOCAL
        self._status: ReceiverStatus | None = None
        self._accumulated: int | None = None
        self._announced: bool | None = None
        self._leap_date: str | None = None
        self._leap_direction: int | None = None
        self._format: time_code_format.TimeCodeFormat | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)
        layout.addWidget(self._build_clock())
        layout.addWidget(self._build_power_up())
        layout.addWidget(self._build_rollover())
        layout.addWidget(self._build_leap())
        layout.addWidget(self._build_time_code())
        layout.addStretch(1)

    # -- The cards -------------------------------------------------------------------------------

    def _build_clock(self) -> QFrame:
        holder, holder_layout = card("Receiver clock")

        self._clock = label(DASH, "readout")
        self._clock.setAccessibleName("The receiver's time, corrected")
        holder_layout.addWidget(self._clock)

        self._zone_name = label("", "caption")
        holder_layout.addWidget(self._zone_name)

        row = QHBoxLayout()
        row.addWidget(label("Show times in", "caption"))
        self._zone_box = QComboBox()
        self._zone_box.setAccessibleName("Which time zone to show times in")
        self._zone_box.addItem("This computer", DisplayZone.LOCAL.value)
        self._zone_box.addItem("UTC", DisplayZone.UTC.value)
        self._zone_box.currentIndexChanged.connect(self._choose_zone)
        row.addWidget(self._zone_box)
        row.addStretch(1)
        holder_layout.addLayout(row)

        self._clock_fields = FieldGrid(("Time scale", "Reported by receiver"))
        holder_layout.addWidget(self._clock_fields)
        return holder

    def _build_power_up(self) -> QFrame:
        holder, holder_layout = card("Power-up time")
        self._provisional = SeverityPill(
            Severity.CAUTION,
            "Provisional — the receiver has not yet corrected this from GPS",
            self._palette,
        )
        holder_layout.addWidget(self._provisional)
        # Shown only while the clock row carries the provisional marker (#245, §11.2).
        holder.setVisible(False)
        self._power_up_card = holder
        return holder

    def _build_rollover(self) -> QFrame:
        holder, holder_layout = card("Week rollover correction")
        self._rollover = SeverityPill(Severity.NEUTRAL, "Not determined", self._palette)
        holder_layout.addWidget(self._rollover)
        holder_layout.addWidget(
            label(
                "GPS transmits the week number in ten bits, so it wraps about every 19.6 years "
                "and a receiver of this age reports a date that far in the past. The time of day "
                "and the 1 PPS output are unaffected.",
                "tertiary",
            )
        )
        return holder

    def _build_leap(self) -> QFrame:
        holder, holder_layout = card("Leap second")
        self._leap_pill = SeverityPill(Severity.NEUTRAL, "Not read", self._palette)
        holder_layout.addWidget(self._leap_pill)
        self._leap_fields = FieldGrid(("GPS − UTC", "Announced for", "Direction"))
        holder_layout.addWidget(self._leap_fields)
        holder_layout.addWidget(
            label(
                "The date and direction are asked only while an announcement stands — the "
                "receiver rejects those questions otherwise.",
                "tertiary",
            )
        )
        return holder

    def _build_time_code(self) -> QFrame:
        holder, holder_layout = card("Time code output")
        self._time_code = FieldGrid(("Format", "Message length"))
        holder_layout.addWidget(self._time_code)
        holder_layout.addWidget(
            label(
                "The time code itself is emitted on the receiver's own 1 Hz cadence, about 509 ms "
                "before the 1 PPS it names, so it is not requested here.",
                "tertiary",
            )
        )
        return holder

    # -- Wiring ----------------------------------------------------------------------------------

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        self._runner = runner
        if runner is not None and runner.is_connected:
            self.refresh()

    def refresh(self) -> None:
        """§10.14: read ``ACC?`` and ``STAT?`` on arrival and on reconnect, and the code format."""
        runner = self._runner
        if runner is None or not runner.is_connected:
            return

        first: list[tuple[object, object]] = [(command, None) for command in leap.FIRST]
        first.append((catalog.TIME_CODE_FORMAT, None))
        runner.run(first, self._absorb_first)  # type: ignore[arg-type]

    def _absorb_first(self, outcomes: Sequence[CommandOutcome]) -> None:
        by_mnemonic = {outcome.command.mnemonic: outcome for outcome in outcomes}

        self._accumulated = _integer(by_mnemonic.get(catalog.LEAP_ACCUMULATED.mnemonic))
        self._announced = _boolean(by_mnemonic.get(catalog.LEAP_STATE.mnemonic))

        code = by_mnemonic.get(catalog.TIME_CODE_FORMAT.mnemonic)
        if code is not None and code.transaction is not None and code.transaction.succeeded:
            self._format = time_code_format.parse(code.transaction.first_line)

        self._redraw_leap()
        self._redraw_time_code()

        # Only now, and only if there is an announcement to have a date.
        follow_up = leap.follow_up(self._announced)
        runner = self._runner
        if follow_up and runner is not None:
            runner.run([(command, None) for command in follow_up], self._absorb_announcement)

    def _absorb_announcement(self, outcomes: Sequence[CommandOutcome]) -> None:
        by_mnemonic = {outcome.command.mnemonic: outcome for outcome in outcomes}

        date = by_mnemonic.get(catalog.LEAP_DATE.mnemonic)
        if date is not None and date.transaction is not None and date.transaction.succeeded:
            self._leap_date = date.transaction.first_line

        duration = by_mnemonic.get(catalog.LEAP_DURATION.mnemonic)
        if duration is not None and duration.transaction is not None:
            value = parse_first_of_list(duration.transaction.first_line)
            self._leap_direction = None if value is None else int(value)

        self._redraw_leap()

    # -- Drawing ---------------------------------------------------------------------------------

    def _choose_zone(self, index: int) -> None:
        self._zone = DisplayZone.LOCAL if index == 0 else DisplayZone.UTC
        self._redraw_clock()

    def show_reading(self, reading: Reading) -> None:
        self._status = reading.status
        self._redraw_clock()
        self._redraw_rollover()
        self._redraw_leap()

    def _redraw_clock(self) -> None:
        status = self._status
        if status is None:
            return

        corrected = status.corrected_date_time
        if corrected is None:
            self._clock.setText(DASH)
            self._zone_name.setText("")
        else:
            shown = corrected if self._zone is DisplayZone.UTC else corrected.astimezone()
            self._clock.setText(shown.strftime("%H:%M:%S"))
            # The zone is always named — never an unlabelled wall-clock time (§11.2, #95).
            self._zone_name.setText(f"{_zone_name(shown)} · {shown:%d %b %Y}")

        self._clock_fields.set("Time scale", humanise(status.time_scale))
        # §7.4: the receiver's own date beside the corrected one, never instead of it.
        self._clock_fields.set(
            "Reported by receiver",
            DASH
            if status.device_date_time is None
            else status.device_date_time.strftime("%d %b %Y %H:%M:%S"),
            device_literal=True,
        )
        self._power_up_card.setVisible(status.device_time_is_provisional)

    def _redraw_rollover(self) -> None:
        status = self._status
        if status is None:
            return

        epochs = status.week_rollover_epochs
        if epochs == 0:
            self._rollover.set_state(Severity.SUCCESS, "No correction needed")
        else:
            self._rollover.set_state(
                Severity.INFO,
                f"Corrected by {epochs} epoch{'s' if epochs != 1 else ''} of 1024 weeks",
            )

    def _redraw_leap(self) -> None:
        self._leap_fields.set(
            "GPS − UTC",
            DASH if self._accumulated is None else f"{self._accumulated:+d} s accumulated",
        )

        pending = self._status.leap_pending if self._status is not None else None
        announced = self._announced or (
            pending is not None and pending is not LeapSecondPending.NONE
        )

        if self._announced is None and pending is None:
            self._leap_pill.set_state(Severity.NEUTRAL, "Not read")
        elif announced:
            self._leap_pill.set_state(Severity.INFO, "A leap second is announced")
        else:
            self._leap_pill.set_state(Severity.SUCCESS, "None announced")

        self._leap_fields.set("Announced for", self._leap_date or DASH)
        self._leap_fields.set("Direction", _direction(self._leap_direction, pending))

    def _redraw_time_code(self) -> None:
        if self._format is None:
            self._time_code.set("Format", DASH)
            self._time_code.set("Message length", DASH)
            return

        # Both spellings, because the command's parameter is F1/F2 while the header the message
        # carries is T1/T2, and a user comparing this page against a raw time code has to
        # recognise those as the same thing.
        name = self._format.name
        self._time_code.set("Format", f"F{name[-1]} — messages begin {name}")
        length = time_code_format.message_length(self._format)
        self._time_code.set("Message length", DASH if length is None else f"{length} characters")

    def csv_rows(self) -> Sequence[Sequence[str]]:
        rows: list[Sequence[str]] = [["Card", "Field", "Value"]]
        rows.append(["Receiver clock", "Time", self._clock.text()])
        rows.append(["Receiver clock", "Zone", self._zone_name.text()])
        for name, grid in (
            ("Receiver clock", self._clock_fields),
            ("Leap second", self._leap_fields),
            ("Time code output", self._time_code),
        ):
            rows.extend([name, field, value] for field, value in grid.rows())
        return rows

    # -- What a test may read --------------------------------------------------------------------

    @property
    def clock_text(self) -> str:
        return self._clock.text()

    @property
    def zone_text(self) -> str:
        return self._zone_name.text()

    @property
    def clock_fields(self) -> FieldGrid:
        return self._clock_fields

    @property
    def leap_fields(self) -> FieldGrid:
        return self._leap_fields

    @property
    def leap_pill(self) -> SeverityPill:
        return self._leap_pill

    @property
    def rollover_pill(self) -> SeverityPill:
        return self._rollover

    @property
    def time_code(self) -> FieldGrid:
        return self._time_code

    @property
    def power_up_card_is_visible(self) -> bool:
        return not self._power_up_card.isHidden()

    @property
    def zone_box(self) -> QComboBox:
        return self._zone_box


def _integer(outcome: CommandOutcome | None) -> int | None:
    if outcome is None or outcome.transaction is None or not outcome.transaction.succeeded:
        return None
    return parse_integer(outcome.transaction.first_line)


def _boolean(outcome: CommandOutcome | None) -> bool | None:
    if outcome is None or outcome.transaction is None or not outcome.transaction.succeeded:
        return None
    return parse_boolean(outcome.transaction.first_line)


def _zone_name(moment: datetime) -> str:
    """The zone's own name, or its offset where it has none.

    Never blank: an unlabelled wall-clock time is the defect #95 records, and a zone that will not
    name itself still has an offset that says the same thing less readably.
    """
    name = moment.tzname()
    if name:
        return name
    offset = moment.utcoffset()
    return "UTC" if offset is None else f"UTC{offset}"


def _direction(seconds: int | None, pending: LeapSecondPending | None) -> str:
    """Which way the announced leap second goes.

    Prefers the receiver's own ``:PTIM:LEAP:DUR?`` where it answered, and falls back to the status
    screen's pending field — which says the same thing and is read every poll.
    """
    if seconds is not None:
        return "Adds a second" if seconds > 0 else "Removes a second"
    if pending is None or pending is LeapSecondPending.NONE:
        return DASH
    return humanise(pending)
