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
from pathlib import Path
from typing import Final

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.commands.position_argument import (
    HEIGHT_METRES,
    MINUTES,
    SECONDS,
    PositionArgument,
)
from smartclock_device.drivers.capability import Capability
from smartclock_device.models import antenna_cable, coordinates
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.position import GeoPosition
from smartclock_device.models.receiver_status import (
    OutputValidity,
    ReceiverStatus,
    SignalStrengthKind,
)
from smartclock_device.parsing.scalars import parse_decimal, parse_integer, parse_keyword
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
from smartclock_monitor.themes.spacing import TABLE_ROW_TARGET, Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.views.capability import command_for, gate
from smartclock_monitor.views.confirm_dialog import ask
from smartclock_monitor.views.manage_satellites import ask_to_manage, parse_exclusions
from smartclock_monitor.views.wording import humanise
from smartclock_monitor.widgets import sky_image
from smartclock_monitor.widgets.copy_menu import attach_table_menu, attach_value_menu
from smartclock_monitor.widgets.severity_pill import SeverityPill
from smartclock_monitor.widgets.sky_plot import SkyPlot
from smartclock_monitor.widgets.trend_chart import AxisMode, TrendChart

DASH = "—"


#: The roles that carry **prose** rather than a value, and therefore wrap.
#:
#: Wrapping is a property of the text, not of the call site, so it belongs here: it was being set
#: by hand and five of the ten pages had none at all, which made them scroll *horizontally* — the
#: Position page wanted 1358 px of a 692 px viewport. A sentence that runs off the right of a card
#: is a sentence nobody reads, and §9.11's whole argument is that the explanation is the part that
#: has to arrive.
#:
#: Values do not wrap. A monospace device literal, a readout and a heading are each meant to be one
#: line; wrapping them would let the layout squeeze a timestamp onto two, which reads as a
#: rendering fault rather than as a narrow window.
WRAPPING_ROLES: Final[frozenset[str]] = frozenset({"body", "caption", "tertiary"})


def _floor_row_height(table: QTableWidget) -> None:
    """Give a table's rows §9.10.2's floor, so a selectable row is a reachable target.

    Set on the vertical header rather than in QSS: a stylesheet ``min-height`` on
    ``QTableWidget::item`` does not drive Qt's row sizing, and a rule that looks applied and is not
    is how this went wrong in the first place — the rows measured 30 px while §9.10.2 required 40.
    """
    header = table.verticalHeader()
    if header is not None:
        header.setMinimumSectionSize(TABLE_ROW_TARGET)
        header.setDefaultSectionSize(TABLE_ROW_TARGET)


def label(text: str, role: str = "body", parent: QWidget | None = None) -> QLabel:
    widget = QLabel(text, parent)
    widget.setProperty("role", role)
    widget.setWordWrap(role in WRAPPING_ROLES)
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


#: §10.4's *Outputs* row, in words rather than in enum spelling.
#:
#: ``VALID_REDUCED.name.title()`` rendered as **"Valid_Reduced"** — an identifier on screen, on the
#: row §11.1 calls "the single most important thing the main window has to convey". The wording for
#: the middle state follows §9.4.1's caution row, which already says *reduced accuracy*.
OUTPUT_VALIDITY_TEXT: Final[dict[OutputValidity, str]] = {
    OutputValidity.UNKNOWN: "Unknown",
    OutputValidity.INVALID: "Invalid",
    OutputValidity.VALID_REDUCED: "Valid, reduced accuracy",
    OutputValidity.VALID: "Valid",
}


#: How narrow §10.5's table may get before it scrolls inside itself instead.
#:
#: Enough for PRN, elevation and azimuth to stay readable; the state column is what goes first,
#: and it is the one the sky plot also shows by filling or outlining the marker.
_TABLE_MINIMUM: Final = 320


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

        # §10.4 names this card *Synchronization*, in the specification's own US spelling. It read
        # "Receiver" and so did the identity card below it, which put two cards with one title on
        # the first page anyone opens.
        summary, summary_layout = card("Synchronization")
        self._fields = FieldGrid(
            ("Mode", "Detail", "Outputs", "Time scale", "Captured", "Warnings")
        )
        summary_layout.addWidget(self._fields)
        layout.addWidget(summary)

        health, self._health_layout = card("Health monitor")
        self._health_pills: list[SeverityPill] = []
        layout.addWidget(health)

        layout.addWidget(self._build_receiver())
        layout.addStretch(1)
        self._exported = (("Synchronization", self._fields), ("Receiver", self._identity))

    def show_reading(self, reading: Reading) -> None:
        status = reading.status
        self._fields.set("Mode", humanise(status.mode))
        self._fields.set("Detail", status.mode_detail or DASH, device_literal=True)
        self._fields.set("Outputs", OUTPUT_VALIDITY_TEXT[status.outputs])
        self._fields.set("Time scale", humanise(status.time_scale))
        self._fields.set("Captured", status.captured_at.strftime("%Y-%m-%d %H:%M:%S"))
        self._fields.set(
            "Warnings", "; ".join(status.parse_warnings) if status.parse_warnings else "None"
        )
        self._rebuild_health(status)

    def _build_receiver(self) -> QFrame:
        """§10.4's *Receiver* card: the four ``*IDN?`` fields.

        **P0-1 is not met by a string that reaches only the log** — the specification says so in as
        many words, having found exactly that defect in the original (#319 item 14). The identity
        is how a user knows they are talking to the instrument they think they are, and it was
        reaching the status bar and the log and nowhere they would look twice.
        """
        holder, holder_layout = card("Receiver")
        self._identity = FieldGrid(("Manufacturer", "Model", "Serial number", "Firmware"))
        holder_layout.addWidget(self._identity)

        # Shown *instead* where the answer is not four comma-separated fields. Four dashes would
        # say "nothing is connected", which is a different statement from "a model this build has
        # not seen" — and §11.1's rule is that what could not be parsed keeps its evidence.
        self._identity_raw = label("", "device")
        self._identity_raw.setWordWrap(True)
        self._identity_raw.setAccessibleName("What the receiver answered")
        self._identity_raw.setVisible(False)
        holder_layout.addWidget(self._identity_raw)
        return holder

    def set_identity(self, identity: DeviceIdentity | None, raw: str | None) -> None:
        """§10.4: re-read on every connection change, because a reconnect can find a different
        receiver on the port — the same reason §12 re-selects the driver."""
        parsed = identity is not None and identity.manufacturer is not None

        self._identity.setVisible(parsed or raw is None)
        self._identity_raw.setVisible(not parsed and raw is not None)

        if not parsed:
            self._identity_raw.setText(raw or "")
            for name in self._identity.names:
                self._identity.set(name, DASH)
            return

        assert identity is not None
        self._identity.set("Manufacturer", identity.manufacturer or DASH, device_literal=True)
        self._identity.set("Model", identity.model or DASH, device_literal=True)
        self._identity.set("Serial number", identity.serial_number or DASH, device_literal=True)
        self._identity.set("Firmware", identity.firmware_revision or DASH, device_literal=True)

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
        self._runner: CommandRunner | None = None
        self._captured_at: datetime | None = None
        self._tracked: tuple[object, ...] = ()
        self._predicted: tuple[object, ...] = ()
        self._mask_reported: int | None = None
        self._excluded: frozenset[int] = frozenset()
        self._exclusions_known = False
        self._mask_written: int | None = None
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
        # The table may shrink below the width its columns want, and scroll inside itself when it
        # does. Without this its size hint became the page's, and §10.5 was the one page that
        # scrolled *horizontally* at the window's own 900 px opening size — which is worse than a
        # narrow table, because the sky plot goes off the side with it.
        _floor_row_height(self._table)
        self._table.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Expanding)
        self._table.setMinimumWidth(_TABLE_MINIMUM)
        table_layout.addWidget(self._table)
        self._attach_table_menu()

        # **Two rows, not one.** All five controls in a single row needed 450 px, which made this
        # card — and so the page, and so the window — as wide as the longest button caption in
        # whatever font the desktop happens to have. It failed on CI for exactly that reason after
        # passing here: the runner's fonts are wider than this machine's, and a minimum measured on
        # one machine's metrics is not a minimum.
        controls = QHBoxLayout()
        controls.addWidget(label("Elevation mask", "caption"))
        self._mask = QSpinBox()
        self._mask.setRange(0, 90)
        self._mask.setSuffix("°")
        self._mask.setAccessibleName("Elevation mask in degrees")
        self._mask.setKeyboardTracking(False)
        controls.addWidget(self._mask)
        self._apply_mask = QPushButton("Apply")
        self._apply_mask.setProperty("role", "destructive")
        self._apply_mask.clicked.connect(self._send_mask)
        controls.addWidget(self._apply_mask)
        controls.addStretch(1)
        table_layout.addLayout(controls)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self._save_image = QPushButton("Save image…")
        self._save_image.setAccessibleName("Save the sky plot as a picture")
        self._save_image.setToolTip("Save the plot, with a caption naming the mask and the time")
        self._save_image.clicked.connect(self.save_image)
        actions.addWidget(self._save_image)

        self._manage = QPushButton("Manage…")
        self._manage.setAccessibleName("Choose which satellites the receiver may track")
        self._manage.clicked.connect(self._manage_satellites)
        actions.addWidget(self._manage)
        table_layout.addLayout(actions)
        layout.addWidget(table_card, 1)

    def show_reading(self, reading: Reading) -> None:
        status = reading.status
        self._captured_at = reading.captured_at or status.captured_at
        self._tracked = status.tracked
        self._predicted = status.not_tracked
        self._mask_reported = status.elevation_mask_degrees
        self._save_image.setEnabled(self.caption().is_worth_saving)
        self._sync_mask(status.elevation_mask_degrees)
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

    # -- §10.5's mask editor and exclusion list --------------------------------------------------

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        self._runner = runner
        live = runner is not None and runner.is_connected
        driver = runner.driver if live and runner is not None else None

        gate(self._apply_mask, driver, Capability.SET_ELEVATION_MASK)
        # §12's #304 keeps the manage dialog's own five lookups as assertions, gated by the same
        # five on the button: the dialog may assume what the button already checked.
        gate(
            self._manage,
            driver,
            Capability.EXCLUDED_SATELLITES,
            Capability.EXCLUDE_SATELLITES,
            Capability.EXCLUDE_ALL_SATELLITES,
            Capability.CLEAR_EXCLUSIONS,
        )
        if live:
            self.refresh_exclusions()

    def refresh_exclusions(self) -> None:
        """§10.5: read **on navigation, on reconnect, and after the Manage dialog — never on the
        sweep.** It changes only when someone changes it, and a second query on the 1 s cadence to
        catch an event that happens twice a year would be paying wire time for nothing (§7.3).
        """
        runner = self._runner
        if runner is None or not runner.is_connected:
            return
        runner.run([(Capability.EXCLUDED_SATELLITES, None)], self._absorb_exclusions)

    def _absorb_exclusions(self, outcomes: Sequence[CommandOutcome]) -> None:
        line = None
        if outcomes and outcomes[0].transaction is not None:
            line = outcomes[0].transaction.first_line
        self._excluded, self._exclusions_known = parse_exclusions(line)

    @property
    def excluded(self) -> frozenset[int]:
        return self._excluded

    def _manage_satellites(self) -> None:
        runner = self._runner
        if runner is None:
            return

        commands = ask_to_manage(
            self._excluded, known=self._exclusions_known, palette=self._palette, parent=self
        )
        if not commands:
            # None means cancelled and [] means nothing changed. Neither sends anything, and
            # neither is worth telling the user about.
            return

        # Resolved here, because the dialog names capabilities and the confirmation shows exactly
        # what will go on the wire — which only the connected family can spell.
        resolved = [
            (command_for(self._runner, wanted) if isinstance(wanted, Capability) else wanted, value)
            for wanted, value in commands
        ]
        if any(command is None for command, _ in resolved):
            return

        # One confirmation for one action, naming every command it will send.
        rendered = [
            text
            for text in (
                command.rendered(argument) for command, argument in resolved if command is not None
            )
            if text is not None
        ]
        if not ask(resolved[0][0], resolved[0][1], self._palette, self, detail=rendered):
            return

        runner.run(commands, lambda _o: self.refresh_exclusions())

    def caption(self) -> sky_image.Caption:
        """What the exported image says that the screen does not (§10.5)."""
        return sky_image.Caption(
            captured_at=self._captured_at,
            tracked=len(self._tracked),
            predicted=len(self._predicted),
            elevation_mask_degrees=self._mask_reported,
        )

    def save_image(self, path: str | None = None) -> str | None:
        """§10.5's *Save image*. Returns where it was written, or ``None``.

        Offered only while the plot has satellites on it: an empty export is a picture of three
        rings, which reads as a working antenna seeing nothing rather than as a receiver that is
        not connected.
        """
        caption = self.caption()
        if not caption.is_worth_saving:
            return None

        chosen = path
        if chosen is None:
            suggested = str(Path.home() / sky_image.suggested_name(self._captured_at))
            chosen, _filter = QFileDialog.getSaveFileName(
                self, "Save sky plot", suggested, "PNG images (*.png)"
            )
        if not chosen:
            return None

        # The palette the card is already drawn in — passed rather than chosen, so the caption
        # cannot end up in a different theme from the plot above it. §10.5: no theme substitution.
        # An extension is added where the user did not give one: Qt infers the format from it and
        # fails without one, which would look like the save silently not happening.
        if not chosen.lower().endswith(".png"):
            chosen = f"{chosen}.png"

        image = sky_image.render(self._plot, caption, self._palette)
        return chosen if image.save(chosen) else None

    def _sync_mask(self, degrees: int | None) -> None:
        """§10.5: the editor **opens on the receiver's own mask**, which the status screen already
        carries — so unlike §10.8's duration limit this costs no wire time.

        It was a hard-coded 10 in the original until #320, and that it happened to match the unit
        it was developed against made it worse rather than better: *a default that is right by
        luck is a default nobody checks.*

        Not overwritten once the user has typed. A sweep lands every second and would otherwise
        undo them mid-edit — decided by comparing against the last value this page wrote, for the
        same reason the holdover limit does.
        """
        if degrees is None:
            return
        if self._mask_written is None or self._mask.value() == self._mask_written:
            self._mask.setValue(degrees)
            self._mask_written = degrees

    def _send_mask(self) -> None:
        runner = self._runner
        if runner is None:
            return
        degrees = self._mask.value()
        if not ask(
            command_for(self._runner, Capability.SET_ELEVATION_MASK), degrees, self._palette, self
        ):
            return
        self._mask_written = degrees
        runner.run([(Capability.SET_ELEVATION_MASK, degrees)])

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


class _DegreesMinutesSeconds:
    """One coordinate as hemisphere, degrees, minutes and seconds — the receiver's own four parts.

    Degrees–minutes–seconds rather than a decimal box, because that is what the receiver prints on
    its status screen and what §10.6's table bounds. Asking for decimal degrees would mean the user
    converting what the screen shows in order to correct it, and the conversion is the part people
    get wrong.
    """

    def __init__(self, name: str, hemispheres: tuple[str, str], degree_maximum: int) -> None:
        self.row = QHBoxLayout()
        self.row.addWidget(label(name, "caption"))

        self._hemisphere = QComboBox()
        self._hemisphere.addItems(list(hemispheres))
        self._hemisphere.setAccessibleName(f"{name} hemisphere")
        self.row.addWidget(self._hemisphere)

        self._degrees = _whole_field(f"{name} degrees", degree_maximum, "°")
        self._minutes = _whole_field(f"{name} minutes", MINUTES[1], "′")
        self._seconds = QDoubleSpinBox()
        self._seconds.setRange(*SECONDS)
        self._seconds.setDecimals(3)
        self._seconds.setSuffix("″")
        self._seconds.setAccessibleName(f"{name} seconds")
        self._seconds.setKeyboardTracking(False)

        for widget in (self._degrees, self._minutes, self._seconds):
            self.row.addWidget(widget)
        self.row.addStretch(1)

    def hemisphere(self) -> str:
        return str(self._hemisphere.currentText())

    def degrees(self) -> int:
        return int(self._degrees.value())

    def minutes(self) -> int:
        return int(self._minutes.value())

    def seconds(self) -> float:
        return float(self._seconds.value())

    def set_decimal(self, degrees: float | None) -> None:
        """Fill the four parts from signed decimal degrees, the form the status screen is parsed to.

        **What keeps the result sendable is the seconds box's own range**, which is §10.6's
        0 – 59.999 and clamps anything above it. Not the rounding here, and not a carry.

        Both were written first, and neither was doing the job. A carry for the 60-second case is
        unreachable: rounding the whole angle before the split makes the seconds a multiple of a
        thousandth, and over 290 271 latitudes the largest the split produces is 59.999. Removing
        the pre-rounding as well changed nothing either, because the box still clamps. Dead code
        that appears to handle a case implies the case can occur, so it is gone; the rounding stays
        only because it puts a clean value in the box rather than leaving the clamp to tidy up.

        The test asserts the invariant — a position the receiver reported comes back sendable —
        rather than any of the three mechanisms, since it is the invariant that matters and two of
        the three turned out not to be why it holds.
        """
        if degrees is None:
            return

        self._hemisphere.setCurrentIndex(0 if degrees >= 0 else 1)
        total_seconds = round(abs(degrees) * 3600.0, 3)
        whole_degrees, remainder = divmod(total_seconds, 3600.0)
        whole_minutes, seconds = divmod(remainder, 60.0)

        self._degrees.setValue(int(whole_degrees))
        self._minutes.setValue(int(whole_minutes))
        self._seconds.setValue(seconds)


def _whole_field(name: str, maximum: int, suffix: str) -> QSpinBox:
    box = QSpinBox()
    box.setRange(0, maximum)
    box.setSuffix(suffix)
    box.setAccessibleName(name)
    box.setKeyboardTracking(False)
    return box


class PositionPage(_FieldsExport, Page):
    """§10.6: where the receiver thinks it is, and how it decided."""

    title = "Position"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        self._runner: CommandRunner | None = None
        #: The last position the receiver reported, for "Fill from the receiver".
        self._last_position: GeoPosition | None = None
        super().__init__(palette, parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)

        frame, frame_layout = card("Position")
        self._fields = FieldGrid(
            ("Latitude", "Longitude", "Height", "Datum", "Mode", "Qualifier", "Survey", "Suspended")
        )
        frame_layout.addWidget(self._fields)
        layout.addWidget(frame)
        layout.addWidget(self._build_survey())
        layout.addWidget(self._build_manual_position())
        layout.addStretch(1)
        self._exported = (("Position", self._fields),)

    def _show_survey(self, status: ReceiverStatus) -> None:
        """The progress bar and the receiver's own suspension reason."""
        percent = status.survey_percent_complete
        surveying = percent is not None
        self._progress.setVisible(surveying)
        if percent is not None:
            self._progress.setValue(int(percent))

        reason = status.survey_suspended_reason
        if reason.name != "NONE":
            # The receiver's own reason, not one inferred here (§11.3).
            self._survey_note.setText(f"Suspended: {reason.name.replace('_', ' ').lower()}")
        elif surveying:
            self._survey_note.setText(f"Surveying — {percent:.1f} % complete.")
        elif not self._survey_note.text():
            self._survey_note.setText("Not surveying.")

    def _build_survey(self) -> QFrame:
        holder, holder_layout = card("Survey")

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setAccessibleName("How far through the survey the receiver is")
        holder_layout.addWidget(self._progress)

        # §10.6, amended by #316: **no remaining-time estimate.** The receiver reports a
        # percentage and nothing else — there is no rate on the wire — so a time computed from a
        # single percentage would be a guess presented as a measurement. What the line carries
        # instead is the suspension reason, which the receiver does report (§11.3).
        self._survey_note = label("", "caption")
        self._survey_note.setWordWrap(True)
        holder_layout.addWidget(self._survey_note)

        buttons = QHBoxLayout()
        self._start_survey = QPushButton("Start survey")
        self._start_survey.setProperty("role", "destructive")
        self._start_survey.clicked.connect(self._begin_survey)
        self._adopt = QPushButton("Adopt computed position")
        self._adopt.setProperty("role", "destructive")
        self._adopt.clicked.connect(
            lambda: self._send_survey_command(Capability.ADOPT_SURVEYED_POSITION)
        )
        self._cancel_survey = QPushButton("Cancel")
        self._cancel_survey.setProperty("role", "destructive")
        self._cancel_survey.clicked.connect(
            lambda: self._send_survey_command(Capability.RESTORE_LAST_POSITION)
        )
        for button in (self._start_survey, self._adopt, self._cancel_survey):
            buttons.addWidget(button)
        buttons.addStretch(1)
        holder_layout.addLayout(buttons)

        self._on_power_up = QCheckBox("Survey on power-up")
        self._on_power_up.setAccessibleName("Whether the receiver surveys when powered on")
        self._on_power_up.clicked.connect(self._send_power_up)
        holder_layout.addWidget(self._on_power_up)

        return holder

    def _build_manual_position(self) -> QFrame:
        """§10.6's manual entry. Nine fields, in the order the receiver wants them.

        Held out of the build until issue #12 could settle the argument's wire format — a tier C
        command that changes what every timing solution is computed from is the wrong place for a
        plausible guess. It is built the way the sibling implementation built and tested it; see
        ``commands/position_argument.py`` for the format and for why it is a looked-up fact.
        """
        holder, holder_layout = card("Set position by hand")

        holder_layout.addWidget(
            label(
                "The receiver times from this position. Enter it on the datum the receiver itself "
                "reports, shown above — the manual contradicts itself about whether the height is "
                "above mean sea level or the ellipsoid, and the two differ by tens of metres, so "
                "nothing here converts between them.",
                "tertiary",
            )
        )

        self._latitude = _DegreesMinutesSeconds("Latitude", ("N", "S"), 90)
        self._longitude = _DegreesMinutesSeconds("Longitude", ("E", "W"), 180)
        holder_layout.addLayout(self._latitude.row)
        holder_layout.addLayout(self._longitude.row)

        height_row = QHBoxLayout()
        height_row.addWidget(label("Height", "caption"))
        self._height = QDoubleSpinBox()
        self._height.setRange(*HEIGHT_METRES)
        self._height.setDecimals(2)
        self._height.setSuffix(" m")
        self._height.setAccessibleName("Height, on the datum the receiver reports")
        self._height.setKeyboardTracking(False)
        height_row.addWidget(self._height)
        height_row.addStretch(1)
        holder_layout.addLayout(height_row)

        actions = QHBoxLayout()
        self._fill_from_receiver = QPushButton("Fill from the receiver")
        self._fill_from_receiver.setAccessibleName("Copy the position the receiver is using")
        self._fill_from_receiver.clicked.connect(self._fill_position)
        actions.addWidget(self._fill_from_receiver)
        actions.addStretch(1)
        self._apply_position = QPushButton("Apply position")
        self._apply_position.setProperty("role", "destructive")
        self._apply_position.clicked.connect(self._send_position)
        actions.addWidget(self._apply_position)
        holder_layout.addLayout(actions)

        self._position_note = label("", "caption")
        holder_layout.addWidget(self._position_note)
        return holder

    def _position_argument(self) -> PositionArgument:
        return PositionArgument(
            latitude_hemisphere=self._latitude.hemisphere(),
            latitude_degrees=self._latitude.degrees(),
            latitude_minutes=self._latitude.minutes(),
            latitude_seconds=self._latitude.seconds(),
            longitude_hemisphere=self._longitude.hemisphere(),
            longitude_degrees=self._longitude.degrees(),
            longitude_minutes=self._longitude.minutes(),
            longitude_seconds=self._longitude.seconds(),
            height_metres=self._height.value(),
        )

    def _fill_position(self) -> None:
        """Seed the fields from what the receiver is using, so a small correction is a small edit.

        Not a shortcut for the confirmation: the value still has to be applied deliberately, and
        §8.3's dialog still appears. What it saves is retyping nine fields to change one.
        """
        position = self._last_position
        if position is None:
            self._position_note.setText("No position has been read from the receiver yet.")
            return

        self._latitude.set_decimal(position.latitude_degrees)
        self._longitude.set_decimal(position.longitude_degrees)
        if position.height_metres is not None:
            self._height.setValue(position.height_metres)
        self._position_note.setText("Filled from the receiver. Nothing has been sent.")

    def _send_position(self) -> None:
        runner = self._runner
        if runner is None:
            return

        argument = self._position_argument()
        if not argument.is_valid():
            # Cannot normally happen — the spin boxes carry the same ranges — but the argument owns
            # them and the page asks rather than assumes.
            self._position_note.setText("That is not a position the receiver would accept.")
            return

        if not ask(
            command_for(self._runner, Capability.SET_POSITION), argument, self._palette, self
        ):
            return

        self._position_note.setText(f"Sending {argument.spoken()}…")
        runner.run([(Capability.SET_POSITION, argument)], self._absorb_position)

    def _absorb_position(self, outcomes: Sequence[CommandOutcome]) -> None:
        for outcome in outcomes:
            if outcome.refusal is not None:
                self._position_note.setText(outcome.refusal.reason)
            elif outcome.succeeded:
                self._position_note.setText("The receiver accepted the position.")
            else:
                self._position_note.setText(outcome.error or "The receiver did not answer.")

    # -- Survey -----------------------------------------------------------------------------------

    def set_command_runner(self, runner: CommandRunner | None) -> None:
        self._runner = runner
        live = runner is not None and runner.is_connected
        driver = runner.driver if live and runner is not None else None

        gate(self._start_survey, driver, Capability.START_SURVEY)
        gate(self._adopt, driver, Capability.ADOPT_SURVEYED_POSITION)
        gate(self._cancel_survey, driver, Capability.RESTORE_LAST_POSITION)
        gate(self._on_power_up, driver, Capability.SET_SURVEY_ON_POWER_UP)
        gate(self._apply_position, driver, Capability.SET_POSITION)
        if live:
            self.refresh_survey()

    def refresh_survey(self) -> None:
        runner = self._runner
        if runner is None or not runner.is_connected:
            return
        runner.run([(Capability.SURVEY_ON_POWER_UP, None)], self._absorb_survey)

    def _absorb_survey(self, outcomes: Sequence[CommandOutcome]) -> None:
        if not outcomes or outcomes[0].transaction is None:
            return
        answer = parse_keyword(outcomes[0].transaction.first_line)
        if answer is None:
            return
        # §11.1: only a recognised answer moves the box. An unreadable one leaves it alone rather
        # than clearing it, which would show a setting the user never made.
        self._on_power_up.setChecked(answer in {"ON", "1"})

    def _send_survey_command(self, command: object) -> None:
        runner = self._runner
        if runner is None:
            return
        if not ask(command, None, self._palette, self):  # type: ignore[arg-type]
            return
        runner.run([(command, None)], self._report)  # type: ignore[list-item]

    def _begin_survey(self) -> None:
        self._send_survey_command(Capability.START_SURVEY)

    def _send_power_up(self) -> None:
        runner = self._runner
        if runner is None:
            return
        wanted = "ON" if self._on_power_up.isChecked() else "OFF"
        if not ask(
            command_for(self._runner, Capability.SET_SURVEY_ON_POWER_UP),
            wanted,
            self._palette,
            self,
        ):
            # Put the box back: the user declined, and a box that stayed moved would show a
            # setting the receiver does not have.
            self._on_power_up.setChecked(not self._on_power_up.isChecked())
            return
        runner.run([(Capability.SET_SURVEY_ON_POWER_UP, wanted)], lambda _o: self.refresh_survey())

    def _report(self, outcomes: Sequence[CommandOutcome]) -> None:
        """Say what happened, and attach §10.6's advice to −300 **only**.

        #229: a receiver already holding a position refuses ``:GPS:POS:SURV:STAT ONCE`` with −300,
        and no command in §8.2 or in any of the three family manuals releases the hold — the route
        is survey-on-power-up, which is the checkbox above. A timeout or any other code gets the
        receiver's own words and nothing added: −300 is device-specific by definition and the
        receiver has not said why, so offering this explanation for the wrong failure would send
        someone to power-cycle an instrument over a loose cable.
        """
        if not outcomes:
            return
        outcome = outcomes[0]
        if outcome.succeeded:
            self._survey_note.setText("Sent.")
            return

        error = outcome.error or (outcome.refusal.reason if outcome.refusal else "")
        if error and error.lstrip("+").startswith("-300"):
            self._survey_note.setText(
                f"{error} — a receiver already holding a position refuses this, and nothing "
                f"releases the hold. Tick 'Survey on power-up' and power-cycle the receiver."
            )
        else:
            self._survey_note.setText(error or "The receiver did not answer.")

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

        self._last_position = status.position
        self._fields.set("Datum", humanise(status.height_datum))
        self._fields.set("Mode", humanise(status.position_mode))
        self._fields.set("Qualifier", humanise(status.position_qualifier))
        self._fields.set(
            "Survey",
            DASH
            if status.survey_percent_complete is None
            else f"{status.survey_percent_complete:.1f} %",
        )
        self._fields.set("Suspended", humanise(status.survey_suspended_reason))
        self._show_survey(status)


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

        layout.addWidget(self._build_antenna())

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

    # -- §10.7's antenna cable delay ------------------------------------------------------------

    def _build_antenna(self) -> QFrame:
        """§10.7's first card: the delay the receiver is compensating for, and two ways to set it.

        **Two ways to the same number, not two settings.** Entering the delay directly and
        computing it from a cable produce one value; the computed figure is shown before it is
        applied so the arithmetic is visible rather than implied.
        """
        holder, holder_layout = card("Antenna cable delay")

        self._antenna_current = FieldGrid(("Current", "Elevation mask"))
        holder_layout.addWidget(self._antenna_current)

        direct = QHBoxLayout()
        self._direct_mode = QRadioButton("Enter delay directly")
        self._direct_mode.setChecked(True)
        self._direct_mode.toggled.connect(lambda _on: self._retune_antenna())
        direct.addWidget(self._direct_mode)
        self._delay_ns = QSpinBox()
        self._delay_ns.setRange(0, 999_999)
        self._delay_ns.setSuffix(" ns")
        self._delay_ns.setAccessibleName("Antenna delay in nanoseconds")
        direct.addWidget(self._delay_ns)
        direct.addStretch(1)
        holder_layout.addLayout(direct)

        computed = QHBoxLayout()
        self._cable_mode = QRadioButton("Calculate from cable")
        self._cable_mode.toggled.connect(lambda _on: self._retune_antenna())
        computed.addWidget(self._cable_mode)
        self._cable = QComboBox()
        self._cable.setAccessibleName("Cable type")
        for preset in antenna_cable.PRESETS:
            self._cable.addItem(preset.name, preset.delay_ns_per_metre)
        self._cable.currentIndexChanged.connect(lambda _i: self._recompute_delay())
        computed.addWidget(self._cable)
        self._length = QSpinBox()
        self._length.setRange(0, 9_999)
        self._length.setSuffix(" m")
        self._length.setAccessibleName("Cable length in metres")
        self._length.valueChanged.connect(lambda _v: self._recompute_delay())
        computed.addWidget(self._length)
        computed.addStretch(1)
        holder_layout.addLayout(computed)

        self._computed = label("", "caption")
        holder_layout.addWidget(self._computed)

        holder_layout.addWidget(
            label(
                "Changing this while locked can push the receiver into holdover.",
                "tertiary",
            )
        )

        apply_row = QHBoxLayout()
        apply_row.addStretch(1)
        self._apply_delay = QPushButton("Apply delay")
        self._apply_delay.setProperty("role", "destructive")
        self._apply_delay.clicked.connect(self._send_delay)
        apply_row.addWidget(self._apply_delay)
        holder_layout.addLayout(apply_row)

        self._retune_antenna()
        return holder

    def _retune_antenna(self) -> None:
        from_cable = self._cable_mode.isChecked()
        self._delay_ns.setEnabled(not from_cable)
        self._cable.setEnabled(from_cable)
        self._length.setEnabled(from_cable)
        self._computed.setVisible(from_cable)

        live = self._runner is not None and self._runner.is_connected
        driver = self._runner.driver if live and self._runner is not None else None
        gate(self._apply_delay, driver, Capability.SET_ANTENNA_DELAY)
        self._recompute_delay()

    def _recompute_delay(self) -> None:
        if not self._cable_mode.isChecked():
            self._computed.setText("")
            return
        self._computed.setText(f"Computed delay {self.intended_delay_ns():.1f} ns")

    def intended_delay_ns(self) -> float:
        """The delay the Apply button would send, whichever way it was arrived at."""
        if not self._cable_mode.isChecked():
            return float(self._delay_ns.value())
        per_metre = float(self._cable.currentData() or 0.0)
        return per_metre * float(self._length.value())

    def _send_delay(self) -> None:
        runner = self._runner
        if runner is None:
            return

        nanoseconds = self.intended_delay_ns()
        # §11's own guard: the receiver takes seconds, and the model already knows what it will
        # accept. Refusing here costs a message; sending it costs a round trip and an error.
        if not antenna_cable.is_acceptable_delay(nanoseconds):
            return

        seconds = nanoseconds * 1e-9
        if not ask(
            command_for(self._runner, Capability.SET_ANTENNA_DELAY), seconds, self._palette, self
        ):
            return
        runner.run([(Capability.SET_ANTENNA_DELAY, seconds)], lambda _o: self.refresh_antenna())

    def refresh_antenna(self) -> None:
        """Read back what the receiver took.

        The same rule the holdover limit follows: what the receiver accepted need not be what was
        sent, and this card is the only place the figure appears.
        """
        runner = self._runner
        if runner is None or not runner.is_connected:
            return
        runner.run(
            [(Capability.ANTENNA_DELAY, None), (Capability.ELEVATION_MASK, None)],
            self._absorb_antenna,
        )

    def _absorb_antenna(self, outcomes: Sequence[CommandOutcome]) -> None:
        # Keyed by **capability**, which is what was asked for. Keying by mnemonic meant the page
        # knowing the connected family's spelling of its own question.
        answered = {outcome.capability: outcome for outcome in outcomes if outcome.capability}

        delay = answered.get(Capability.ANTENNA_DELAY)
        seconds = None
        if delay is not None and delay.transaction is not None:
            seconds = parse_decimal(delay.transaction.first_line)
        self._antenna_current.set("Current", DASH if seconds is None else f"{seconds * 1e9:.1f} ns")

        mask = answered.get(Capability.ELEVATION_MASK)
        degrees = None
        if mask is not None and mask.transaction is not None:
            degrees = parse_decimal(mask.transaction.first_line)
        self._antenna_current.set("Elevation mask", DASH if degrees is None else f"{degrees:.0f}°")

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
        self._retune_antenna()
        if runner is not None and runner.is_connected:
            runner.run([(Capability.HARDWARE_CONDITION, None)], self._absorb_register)
            self.refresh_antenna()

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
        self._clock.set("Time scale", humanise(status.time_scale))
        self._clock.set("Provisional", "Yes" if status.device_time_is_provisional else "No")
        self._clock.set("Rollover epochs", str(status.week_rollover_epochs))
        self._clock.set(
            "Corrected",
            DASH
            if status.corrected_date_time is None
            else status.corrected_date_time.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._clock.set("Leap", humanise(status.leap_pending))

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
