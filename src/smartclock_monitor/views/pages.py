"""The details window's pages (§10.4 – §10.10).

Each page takes a :class:`Reading` and renders it. None of them holds state of its own: the poll
loop is the single source, and a page that cached would drift from it the moment a field stopped
being reported.

**A missing value renders as an em dash, never as a zero** (§11.1). That rule is why every readout
here goes through :func:`~smartclock_monitor.views.main_window._number` and its neighbours rather
than formatting inline — a timing instrument showing ``0.0 ns`` for a reading it never received is
lying, and it is the kind of lie that is impossible to spot afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.commands import catalog
from smartclock_device.models import coordinates
from smartclock_device.models.receiver_status import ReceiverStatus, SignalStrengthKind
from smartclock_device.parsing.scalars import parse_integer
from smartclock_monitor.services.allan import allan_deviation, summarise
from smartclock_monitor.services.commands import CommandRunner
from smartclock_monitor.services.drift import FIT_MARGIN, advise
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.session import CommandOutcome
from smartclock_monitor.services.statistics import deviation
from smartclock_monitor.services.trend_store import (
    SETTLING,
    Series,
    TrendStore,
    TrendStoreError,
    empty_series,
)
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.widgets.copy_menu import attach_table_menu, attach_value_menu
from smartclock_monitor.widgets.severity_pill import SeverityPill
from smartclock_monitor.widgets.sky_plot import SkyPlot
from smartclock_monitor.widgets.trend_chart import AxisMode, TrendChart

DASH = "—"


def label(text: str, role: str = "body", parent: QWidget | None = None) -> QLabel:
    widget = QLabel(text, parent)
    widget.setProperty("role", role)
    return widget


def card(title: str) -> tuple[QFrame, QVBoxLayout]:
    """An L2 card with a heading, and the layout to put things in.

    The vertical size policy is ``Minimum``, meaning "never smaller than the sizeHint". Without it
    a column of cards shares the height between them, every row inside gets squeezed below its
    natural height, and the text clips — half a line of a timestamp reads as a rendering fault
    rather than as a layout that ran out of room. Cards keep their height and the page scrolls
    instead.
    """
    frame = QFrame()
    frame.setProperty("card", "true")
    frame.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(
        Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING, Spacing.CARD_PADDING
    )
    layout.setSpacing(Spacing.SMALL)
    if title:
        layout.addWidget(label(title, "subtitle"))
    return frame, layout


class Page(QWidget):
    """Base for every details page."""

    #: What the navigation list calls it.
    title = "Page"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self.setAccessibleName(self.title)

    def set_palette_tokens(self, palette: Palette) -> None:
        self._palette = palette

    def csv_rows(self) -> Sequence[Sequence[str]]:
        """What ``Ctrl+E`` writes for this page. Empty means there is nothing to export.

        Empty rather than raising, and empty rather than a header with no rows: §9.11's rule about
        controls that look like they work applies to Export too, and the title bar disables it when
        the current page answers with nothing.
        """
        return ()

    def show_reading(self, reading: Reading) -> None:
        """Render one sweep."""
        raise NotImplementedError


class FieldGrid(QWidget):
    """A two-column grid of labelled values, which is most of what these pages are."""

    def __init__(self, fields: tuple[str, ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._values: dict[str, QLabel] = {}

        grid = QGridLayout(self)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(Spacing.LARGE)
        grid.setVerticalSpacing(Spacing.SMALL)

        for row, name in enumerate(fields):
            caption = label(name, "caption")
            value = label(DASH, "body")
            # §9.7.4's *Copy value*. Text selection is left off on these: a label that carries its
            # own selection flyout shadows the context menu, and the original measured the same
            # collision. The menu is the affordance here; selection is the one on the transcript.
            attach_value_menu(value)
            grid.addWidget(caption, row, 0, Qt.AlignmentFlag.AlignTop)
            grid.addWidget(value, row, 1, Qt.AlignmentFlag.AlignTop)
            grid.setColumnStretch(1, 1)
            self._values[name] = value

    def set(self, name: str, text: str, *, device_literal: bool = False) -> None:
        """Set one field. ``device_literal`` puts it in the monospace face (§9.5's split)."""
        widget = self._values[name]
        widget.setText(text)
        widget.setProperty("role", "device" if device_literal else "body")
        widget.setAccessibleName(f"{name}: {text}")
        # A property change after the stylesheet is applied needs an explicit repolish.
        style = widget.style()
        if style is not None:
            style.unpolish(widget)
            style.polish(widget)

    def value_of(self, name: str) -> str:
        return self._values[name].text()

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(self._values)

    def rows(self) -> list[list[str]]:
        """Every field as a Field/Value pair, for §9.7.4's Export and copy layer."""
        return [[name, widget.text()] for name, widget in self._values.items()]

    def is_device_literal(self, name: str) -> bool:
        """Whether this field is reproducing what the receiver emitted.

        §9.5.3 rule 4 exempts raw device text from the typesetting rules, and the copy layer has to
        honour that exemption: "correcting" the sign in a value the receiver printed would make the
        copy disagree with the transcript it came from.
        """
        return bool(self._values[name].property("role") == "device")


class _FieldsExport:
    """Mixin: export whichever FieldGrids a page declares in ``_exported``.

    A page lists its grids rather than this walking the widget tree, because the order of the
    document is a decision — the rows come out in the order someone reads them — and a tree walk
    would make it an accident of layout.
    """

    _exported: tuple[tuple[str, FieldGrid], ...] = ()

    def csv_rows(self) -> Sequence[Sequence[str]]:
        rows: list[Sequence[str]] = [["Card", "Field", "Value"]]
        for card_name, grid in self._exported:
            rows.extend([card_name, name, value] for name, value in grid.rows())
        return rows if len(rows) > 1 else ()


# ---- §10.4 Overview -----------------------------------------------------------------------------


class OverviewPage(_FieldsExport, Page):
    """§10.4: the health monitor, and what the receiver is doing."""

    title = "Overview"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)

        summary, summary_layout = card("Receiver")
        self._fields = FieldGrid(
            ("Mode", "Detail", "Outputs", "Time scale", "Captured", "Warnings")
        )
        summary_layout.addWidget(self._fields)
        layout.addWidget(summary)

        health, self._health_layout = card("Health monitor")
        self._health_pills: list[SeverityPill] = []
        layout.addWidget(health)

        layout.addStretch(1)
        self._exported = (("Receiver", self._fields),)

    def show_reading(self, reading: Reading) -> None:
        status = reading.status
        self._fields.set("Mode", status.mode.name.replace("_", " ").title())
        self._fields.set("Detail", status.mode_detail or DASH, device_literal=True)
        self._fields.set("Outputs", status.outputs.name.title())
        self._fields.set("Time scale", status.time_scale.name)
        self._fields.set("Captured", status.captured_at.strftime("%Y-%m-%d %H:%M:%S"))
        self._fields.set(
            "Warnings", "; ".join(status.parse_warnings) if status.parse_warnings else "None"
        )
        self._rebuild_health(status)

    def _rebuild_health(self, status: ReceiverStatus) -> None:
        """One pill per monitored item.

        **The card inverts the register's polarity.** Every bit in the Hardware register is a fault
        — set means the bad thing is true — while this card draws ticks. Rendering them the same
        way round would put a red mark against a healthy receiver.
        """
        for pill in self._health_pills:
            pill.setParent(None)
            pill.deleteLater()
        self._health_pills = []

        if not status.health_items:
            pill = SeverityPill(Severity.NEUTRAL, "Not reported", self._palette)
            self._health_layout.addWidget(pill)
            self._health_pills.append(pill)
            return

        for name, ok in status.health_items.items():
            pill = SeverityPill(
                Severity.SUCCESS if ok else Severity.CRITICAL,
                f"{name}: {'OK' if ok else 'Failed'}",
                self._palette,
            )
            self._health_layout.addWidget(pill)
            self._health_pills.append(pill)

    def set_palette_tokens(self, palette: Palette) -> None:
        super().set_palette_tokens(palette)
        for pill in self._health_pills:
            pill.set_palette_tokens(palette)


# ---- §10.5 Satellites ---------------------------------------------------------------------------


class SatellitesPage(Page):
    """§10.5: the sky plot, and the table beside it.

    The table is **not** hidden behind a toggle. §9.10.2 requires a list alternate view for users
    who cannot use the spatial form, and a mode switch would make it a second-class view of the
    same data — where side by side it is useful to everyone, and the two agree by construction
    because they render the same tuple.
    """

    title = "Satellites"

    _COLUMNS = ("PRN", "Elevation", "Azimuth", "Signal", "State")

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)

        layout = QHBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)

        plot_card, plot_layout = card("Sky")
        self._plot = SkyPlot(palette)
        plot_layout.addWidget(self._plot, 0, Qt.AlignmentFlag.AlignCenter)
        self._counts = label("", "caption")
        plot_layout.addWidget(self._counts)
        plot_layout.addStretch(1)
        layout.addWidget(plot_card, 0)

        table_card, table_layout = card("Tracked and predicted")
        self._table = QTableWidget(0, len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(list(self._COLUMNS))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAccessibleName("Satellite table")
        header = self._table.horizontalHeader()
        if header is not None:
            # The numeric columns take the width their heading needs and no more; the state column
            # takes the rest. Stretching all five clipped "Elevation" to "Elevatior", which is the
            # kind of defect that survives review because it still looks like a word.
            for column in range(len(self._COLUMNS) - 1):
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            header.setSectionResizeMode(len(self._COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        table_layout.addWidget(self._table)
        self._attach_table_menu()
        layout.addWidget(table_card, 1)

    def show_reading(self, reading: Reading) -> None:
        status = reading.status
        self._plot.set_satellites(
            status.tracked,
            status.not_tracked,
            status.signal_strength_kind,
            status.elevation_mask_degrees,
        )

        mask = (
            f", mask {status.elevation_mask_degrees}°"
            if status.elevation_mask_degrees is not None
            else ""
        )
        self._counts.setText(
            f"{len(status.tracked)} tracked, {len(status.not_tracked)} predicted{mask}"
        )

        rows = [
            (s.prn, s.elevation_degrees, s.azimuth_degrees, s.signal_strength, "Tracked")
            for s in status.tracked
        ] + [
            (s.prn, s.elevation_degrees, s.azimuth_degrees, None, "Predicted")
            for s in status.not_tracked
        ]
        rows.sort(key=lambda row: row[0])

        self._table.setRowCount(len(rows))
        for index, (prn, elevation, azimuth, strength, state) in enumerate(rows):
            for column, text in enumerate(
                (
                    str(prn),
                    _degrees(elevation),
                    _degrees(azimuth),
                    _signal(strength, status.signal_strength_kind),
                    state,
                )
            ):
                self._table.setItem(index, column, QTableWidgetItem(text))

    def set_palette_tokens(self, palette: Palette) -> None:
        super().set_palette_tokens(palette)
        self._plot.set_palette_tokens(palette)

    @property
    def plot(self) -> SkyPlot:
        return self._plot

    def _attach_table_menu(self) -> None:
        attach_table_menu(self._table, self.csv_rows)

    def csv_rows(self) -> Sequence[Sequence[str]]:
        """The satellite table as it stands, header included.

        §9.7.4 puts *Copy table as CSV* on the card and Export on the title bar, and both hand over
        the same document — which is what makes the copy layer safe to have: it offers nothing the
        keyboard path does not.
        """
        table = self._table
        if table.rowCount() == 0:
            return ()

        header: list[str] = []
        for column in range(table.columnCount()):
            item = table.horizontalHeaderItem(column)
            header.append(item.text() if item is not None else "")

        rows: list[Sequence[str]] = [header]
        for row in range(table.rowCount()):
            cells = []
            for column in range(table.columnCount()):
                item = table.item(row, column)
                cells.append(item.text() if item is not None else "")
            rows.append(cells)
        return rows

    @property
    def table(self) -> QTableWidget:
        return self._table


# ---- §10.6 Position -----------------------------------------------------------------------------


class PositionPage(_FieldsExport, Page):
    """§10.6: where the receiver thinks it is, and how it decided."""

    title = "Position"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)

        frame, frame_layout = card("Position")
        self._fields = FieldGrid(
            ("Latitude", "Longitude", "Height", "Datum", "Mode", "Qualifier", "Survey", "Suspended")
        )
        frame_layout.addWidget(self._fields)
        layout.addWidget(frame)
        layout.addStretch(1)
        self._exported = (("Position", self._fields),)

    def show_reading(self, reading: Reading) -> None:
        status = reading.status
        position = status.position

        if position is None:
            for name in ("Latitude", "Longitude", "Height"):
                self._fields.set(name, DASH)
        else:
            # Degrees-minutes-seconds, formatted by the model rather than here. The minute mark is
            # a PRIME and not an apostrophe, which is most of why that module exists.
            self._fields.set(
                "Latitude",
                coordinates.latitude(position.latitude_degrees) or DASH,
                device_literal=True,
            )
            self._fields.set(
                "Longitude",
                coordinates.longitude(position.longitude_degrees) or DASH,
                device_literal=True,
            )
            self._fields.set(
                "Height",
                DASH if position.height_metres is None else f"{position.height_metres:.2f} m",
            )

        self._fields.set("Datum", status.height_datum.name.replace("_", " ").title())
        self._fields.set("Mode", status.position_mode.name.replace("_", " ").title())
        self._fields.set("Qualifier", status.position_qualifier.name.replace("_", " ").title())
        self._fields.set(
            "Survey",
            DASH
            if status.survey_percent_complete is None
            else f"{status.survey_percent_complete:.1f} %",
        )
        self._fields.set("Suspended", status.survey_suspended_reason.name.replace("_", " ").title())


# ---- §10.7 Timing -------------------------------------------------------------------------------

#: §10.7's four ranges, in the order the wireframe draws them.
TREND_RANGES: Final[tuple[tuple[str, timedelta], ...]] = (
    ("1 h", timedelta(hours=1)),
    ("6 h", timedelta(hours=6)),
    ("24 h", timedelta(hours=24)),
    ("7 d", timedelta(days=7)),
)

#: What σ is always measured over, whatever range is selected. §10.7 puts it beside *Current* as a
#: property of the receiver now rather than of the window being drawn.
SIGMA_WINDOW: Final = timedelta(hours=1)

#: Used only where a reading has arrived with no timestamp at all and the window is empty too —
#: the advisory needs an instant to project from, and refusing to draw the card over it would be
#: a worse answer than dating a projection nobody is going to get.
NOW_FALLBACK: Final = datetime.min.replace(tzinfo=UTC)


class TimingPage(Page):
    """§10.7 and §10.8: the figures of merit, the clock, and holdover."""

    title = "Timing"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._store: TrendStore | None = None
        self._runner: CommandRunner | None = None
        #: The hardware condition register, or ``None`` where it has not been read.
        self._register_bits: tuple[bool, ...] | None = None
        self._range: timedelta = TREND_RANGES[0][1]
        self._last_captured: datetime | None = None
        self._last_refresh: datetime | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)

        merit, merit_layout = card("Figures of merit")
        self._merit = FieldGrid(
            (
                "Time figure of merit",
                "Frequency figure of merit",
                "1 PPS interval",
                "Oscillator EFC",
            )
        )
        merit_layout.addWidget(self._merit)
        layout.addWidget(merit)

        clock, clock_layout = card("Clock")
        self._clock = FieldGrid(
            ("Receiver time", "Time scale", "Provisional", "Rollover epochs", "Corrected", "Leap")
        )
        clock_layout.addWidget(self._clock)
        layout.addWidget(clock)

        holdover, holdover_layout = card("Holdover")
        self._holdover = FieldGrid(
            ("Duration", "Predicted", "Present", "Threshold", "Antenna delay")
        )
        holdover_layout.addWidget(self._holdover)
        layout.addWidget(holdover)

        layout.addWidget(self._build_trends())
        layout.addStretch(1)

    # -- §10.7's trends ------------------------------------------------------------------------

    def _build_trends(self) -> QFrame:
        trends, trends_layout = card("1 PPS time interval")

        heading = QHBoxLayout()
        self._sigma = label("", "readout-small")
        heading.addWidget(self._sigma)
        heading.addStretch(1)
        heading.addWidget(self._build_ranges())
        trends_layout.addLayout(heading)

        self._evidence = label("", "caption")
        self._evidence.setWordWrap(True)
        trends_layout.addWidget(self._evidence)

        self._ti_chart = TrendChart(
            "1 PPS time interval", AxisMode.ZERO_ANCHORED, "ns", self._palette
        )
        trends_layout.addWidget(self._ti_chart)

        trends_layout.addWidget(label("Oscillator control (EFC)", "subtitle"))
        self._efc_chart = TrendChart("Oscillator control", AxisMode.FRAMED, "%", self._palette)
        trends_layout.addWidget(self._efc_chart)

        trends_layout.addWidget(label("Oscillator drift", "subtitle"))
        self._drift_pill = SeverityPill(Severity.NEUTRAL, "No history yet", self._palette)
        trends_layout.addWidget(self._drift_pill)
        self._drift_evidence = label("", "caption")
        self._drift_evidence.setWordWrap(True)
        trends_layout.addWidget(self._drift_evidence)

        trends_layout.addWidget(label("Stability (Allan deviation)", "subtitle"))
        self._stability = QTableWidget(0, 3)
        self._stability.setHorizontalHeaderLabels(
            # §10.7.2's own column headings. The symbols are the notation of the measurement —
            # "sigma sub y" in a column heading is a different claim from σy — and both characters
            # are on pyproject.toml's allowed-confusables list for exactly this.
            ["Averaging time τ", "σy(τ)", "Differences averaged"]
        )
        self._stability.verticalHeader().setVisible(False)
        self._stability.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._stability.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._stability.setAccessibleName("Allan deviation by averaging time")
        header = self._stability.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        trends_layout.addWidget(self._stability)

        self._stability_summary = label("", "caption")
        self._stability_summary.setWordWrap(True)
        trends_layout.addWidget(self._stability_summary)

        return trends

    def _build_ranges(self) -> QWidget:
        """§10.7.1: **one** range selector, shared by both charts.

        A selector per chart would let the two disagree about what window is being looked at, and
        the whole reason the EFC chart sits under the TI one is that they are read together.
        """
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(Spacing.TIGHT)

        self._range_buttons = QButtonGroup(holder)
        self._range_buttons.setExclusive(True)

        for index, (text, span) in enumerate(TREND_RANGES):
            button = QPushButton(text)
            button.setCheckable(True)
            button.setChecked(span == self._range)
            button.setAccessibleName(f"Show the last {text}")
            self._range_buttons.addButton(button, index)
            row.addWidget(button)

        self._range_buttons.idClicked.connect(self._choose_range)
        return holder

    def _choose_range(self, index: int) -> None:
        self._range = TREND_RANGES[index][1]
        # Redraw at once rather than at the next poll: the click *is* the request, and waiting a
        # second to honour it reads as the button not having worked.
        self._refresh_trends(force=True)

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        """§10.7.1's hardware bits 6 and 7 are *read from the receiver rather than recomputed*.

        They are the alarm and the slope is the gauge, so an inference drawn from the same EFC data
        would not do: the bit is the hardware reporting a state. Until this page had a runner the
        card could only say they had not been read, which was honest and useless.
        """
        self._runner = runner
        if runner is not None and runner.is_connected:
            runner.run([(catalog.HARDWARE_CONDITION, None)], self._absorb_register)

    def _absorb_register(self, outcomes: Sequence[CommandOutcome]) -> None:
        """Fold the hardware condition register in as a bit list.

        A read that failed leaves ``None``, and the advisory then says the bits have not been read
        rather than reporting them clear — an unread bit and a clear bit are different facts, and
        reporting the first as the second is how an alarm gets missed.
        """
        if not outcomes or outcomes[0].transaction is None:
            self._register_bits = None
            return

        value = parse_integer(outcomes[0].transaction.first_line)
        self._register_bits = (
            None if value is None else tuple(bool(value >> bit & 1) for bit in range(16))
        )
        self._refresh_trends(force=True)

    def set_trend_store(self, store: TrendStore | None) -> None:
        """Give the page its history, or take it away.

        ``None`` is an ordinary state, not an error: §10.7 has to work on a run whose store could
        not be opened, and the charts then show their empty state while every other card on the
        page carries on."""
        self._store = store
        self._refresh_trends(force=True)

    def _refresh_interval(self) -> timedelta:
        """How often to re-read the store.

        One pixel column's worth of time, bounded. Re-reading a 7-day window every second would
        redraw 604 800 rows to move the trace by less than a pixel; re-reading an hour window once
        a minute would make a live chart look frozen."""
        per_column = self._range / 360
        return max(timedelta(seconds=5), min(per_column, timedelta(minutes=5)))

    def _refresh_trends(self, *, force: bool = False) -> None:
        store = self._store
        if store is None:
            self._ti_chart.show_series(empty_series(self._range))
            self._efc_chart.show_series(empty_series(self._range))
            self._sigma.setText(DASH)
            self._evidence.setText("No trend history is being kept this run.")
            self._stability.setRowCount(0)
            self._stability.setVisible(False)
            self._stability_summary.setText("Stability needs stored readings.")
            self._drift_pill.set_state(Severity.NEUTRAL, "No history")
            self._drift_evidence.setText("")
            return

        now = self._last_captured
        due = (
            force
            or now is None
            or self._last_refresh is None
            or now - self._last_refresh >= self._refresh_interval()
        )
        if not due:
            return
        self._last_refresh = now

        try:
            window = store.window(self._range, ending=now)
            # §10.7: the deviation is over an hour whatever range is selected, because it sits
            # beside *Current* as a property of the receiver now rather than of the window drawn.
            # A σ that changed when the user pressed 7 d would be a different statistic wearing
            # the same label.
            hour = window if self._range == SIGMA_WINDOW else store.window(SIGMA_WINDOW, ending=now)
        except TrendStoreError:
            # The store went away underneath us — a removed drive, a file deleted. The page keeps
            # working without it, which is the same contract as never having had one.
            self._store = None
            self._refresh_trends(force=True)
            return

        self._ti_chart.show_series(window)
        self._efc_chart.show_series(window)
        self._describe_deviation(hour)
        self._advise_drift(store, now)
        self._show_stability(window)

    def _show_stability(self, window: Series) -> None:
        """§10.7.2's table, over **the raw window rather than the decimated one**.

        §9.10.2's decimation keeps each pixel column's extremes, which is right for drawing a
        shape and wrong for a statistic: a second difference taken across a bucket's extremes
        measures the decimation (#63). The chart is handed the same series and reduces it itself.
        """
        points = allan_deviation(window)

        self._stability.setRowCount(len(points))
        for row, point in enumerate(points):
            # Seconds throughout, never switching to minutes down the column — §9.5.3 rule 6.
            self._stability.setItem(row, 0, QTableWidgetItem(f"{point.tau_seconds:,.0f} s"))
            self._stability.setItem(row, 1, QTableWidgetItem(point.formatted()))
            self._stability.setItem(row, 2, QTableWidgetItem(f"{point.differences:,}"))

        # A τ the series cannot support is dropped rather than dashed, so an empty table is an
        # ordinary state and the sentence below is what explains it.
        self._stability.setVisible(bool(points))
        self._stability_summary.setText(summarise(points, window))

    def _advise_drift(self, store: TrendStore, now: datetime | None) -> None:
        """§10.7.1's advisory, over a window slightly wider than the one drawn.

        A window of exactly *n* hours holds a span slightly under *n* hours, so the 24 h range
        could never satisfy the day-long separability rule and the range named for a day could not
        reach the day-based analysis. The charts are unaffected: they are what the user is looking
        at, and the fit is what is being said about it.
        """
        try:
            wider = store.window(self._range + FIT_MARGIN, ending=now)
            settling = self._settling_boundary(store, wider)
        except TrendStoreError:
            self._store = None
            self._refresh_trends(force=True)
            return

        moment = now if now is not None else (wider.end or NOW_FALLBACK)
        advisory = advise(
            wider, now=moment, settling_until=settling, register_bits=self._register_bits
        )

        self._drift_pill.set_state(advisory.severity, advisory.headline)
        self._drift_evidence.setText("\n".join(advisory.lines))

    def _settling_boundary(self, store: TrendStore, window: Series) -> datetime | None:
        """When the last power-up's settling period ends, or ``None`` if none is known.

        Asked of the store rather than read off the window: the exclusion reaches back 24 h and
        the window may be an hour, so a warm-up that finished before the window opened leaves no
        trace in it at all.
        """
        start = window.start
        if start is None:
            return None

        power_up = store.last_power_up(start)
        if power_up is None:
            return None

        boundary = power_up + SETTLING
        return boundary if boundary > start else None

    def _describe_deviation(self, hour: Series) -> None:
        """§10.7's σ caption, which **names what it found rather than what it asked for**.

        The application is not always running, so an hour of wall clock routinely holds four
        minutes of readings — and a deviation over 3,000 readings and one over 12 are not the same
        figure. Both the span and the count go beside the value.
        """
        spread = deviation(hour.ti_nanoseconds)

        if spread.value is None:
            self._sigma.setText(f"σ {DASH}")
            self._evidence.setText(
                "Not enough stored readings yet for a deviation — it needs two."
                if spread.count < 2
                else "No 1 PPS readings in the last hour."
            )
            return

        self._sigma.setText(f"σ {spread.value:.1f} ns")
        minutes = hour.span.total_seconds() / 60.0
        self._evidence.setText(
            f"Over {minutes:.0f} min of stored readings ({spread.count:,} samples). "
            f"σ is always the last hour, whichever range is drawn."
        )

    def csv_rows(self) -> Sequence[Sequence[str]]:
        """§10.7: *"TimingPage implements it for the trend series."*

        The **drawn window**, not the whole store, and the **raw** samples rather than the chart's
        decimated columns — §9.10.2's min/max reduction is right for drawing a shape and wrong for
        a document, where it would silently halve the row count and put two readings a pixel apart
        in one row.
        """
        series = self._ti_chart.series
        if not series:
            return ()

        rows: list[Sequence[str]] = [["Time (UTC)", "1 PPS TI (ns)", "EFC (%)", "Mode"]]
        for index in range(len(series)):
            ti = series.ti_at(index)
            efc = series.efc_at(index)
            rows.append(
                [
                    series.moment_at(index).strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "" if ti is None else f"{ti:.3f}",
                    "" if efc is None else f"{efc:.6f}",
                    series.mode[index].name,
                ]
            )
        return rows

    def set_palette_tokens(self, palette: Palette) -> None:
        super().set_palette_tokens(palette)
        self._ti_chart.set_palette_tokens(palette)
        self._efc_chart.set_palette_tokens(palette)

    def show_reading(self, reading: Reading) -> None:
        status = reading.status
        self._last_captured = reading.captured_at or status.captured_at
        self._refresh_trends()

        self._merit.set("Time figure of merit", _int(status.tfom))
        self._merit.set("Frequency figure of merit", _int(status.ffom))
        self._merit.set("1 PPS interval", _fixed(status.one_pps_ti_nanoseconds, 1, "ns"))
        self._merit.set("Oscillator EFC", _fixed(reading.efc_percent, 2, "%"))

        self._clock.set(
            "Receiver time",
            DASH
            if status.device_date_time is None
            else status.device_date_time.strftime("%Y-%m-%d %H:%M:%S"),
            device_literal=True,
        )
        self._clock.set("Time scale", status.time_scale.name)
        self._clock.set("Provisional", "Yes" if status.device_time_is_provisional else "No")
        self._clock.set("Rollover epochs", str(status.week_rollover_epochs))
        self._clock.set(
            "Corrected",
            DASH
            if status.corrected_date_time is None
            else status.corrected_date_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._clock.set("Leap", status.leap_pending.name.replace("_", " ").title())

        self._holdover.set(
            "Duration", DASH if status.holdover_duration is None else str(status.holdover_duration)
        )
        self._holdover.set("Predicted", _fixed(status.holdover_predicted_seconds, 1, "s"))
        self._holdover.set("Present", _fixed(status.holdover_present_seconds, 1, "s"))
        self._holdover.set("Threshold", _fixed(status.hold_threshold_seconds, 1, "s"))
        self._holdover.set("Antenna delay", _fixed(status.antenna_delay_nanoseconds, 1, "ns"))


# ---- Formatting ---------------------------------------------------------------------------------


def _int(value: int | None) -> str:
    return DASH if value is None else str(value)


def _fixed(value: float | None, decimals: int, unit: str) -> str:
    """§9.5.3's rule: **fixed decimal places per quantity, never variable.**

    A column that changes its precision row to row is unreadable, and where a figure is too small
    to survive its quantity's precision the answer is to change the unit rather than the number of
    decimals.
    """
    return DASH if value is None else f"{value:.{decimals}f} {unit}"


def _degrees(value: int | None) -> str:
    return DASH if value is None else f"{value}°"


def _signal(value: int | None, kind: SignalStrengthKind) -> str:
    """The reading, with the scale it is on.

    §11.1 warns the two scales are not interchangeable — 26–55 with ≥ 35 good on one, 0–255 with
    20–30 weak on the other — so the number is never shown without saying which it is.
    """
    if value is None:
        return DASH
    match kind:
        case SignalStrengthKind.CARRIER_TO_NOISE:
            return f"{value} C/N"
        case SignalStrengthKind.SIGNAL_STRENGTH:
            return f"{value} SS"
        case _:
            return str(value)
