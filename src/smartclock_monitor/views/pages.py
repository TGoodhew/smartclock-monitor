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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.models import coordinates
from smartclock_device.models.receiver_status import ReceiverStatus, SignalStrengthKind
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.widgets.severity_pill import SeverityPill
from smartclock_monitor.widgets.sky_plot import SkyPlot

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
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
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


# ---- §10.4 Overview -----------------------------------------------------------------------------


class OverviewPage(Page):
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

    @property
    def table(self) -> QTableWidget:
        return self._table


# ---- §10.6 Position -----------------------------------------------------------------------------


class PositionPage(Page):
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


class TimingPage(Page):
    """§10.7 and §10.8: the figures of merit, the clock, and holdover."""

    title = "Timing"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
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

        layout.addStretch(1)

    def show_reading(self, reading: Reading) -> None:
        status = reading.status

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
