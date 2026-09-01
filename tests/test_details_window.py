"""The details window, its pages, and the sky plot.

The sky plot's geometry is tested without Qt at all — the polar mapping is the part that can be
wrong in ways a screenshot will not show, and separating it is what makes that possible.

The accessibility assertions are the ones that matter most here. §9.10.2 requires each marker to be
a real focusable object reporting its own name, and the port plan is explicit that painting dots
and bolting on a peer is the wrong answer. A test that only checked pixels would pass on the wrong
implementation.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6.QtWidgets", reason="Qt is not available on this machine")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from conftest import NOW
from smartclock_device.models.receiver_status import (
    ReceiverStatus,
    SignalStrengthKind,
    SmartClockMode,
)
from smartclock_device.models.satellite import PredictedSatellite, TrackedSatellite
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.themes.tokens import ALL_THEMES, Theme, palette_for
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.widgets.sky_plot import markers_from
from smartclock_monitor.widgets.sky_plot_geometry import (
    MAX_MARKER,
    MIN_MARKER,
    describe,
    disc_for,
    elevation_ring,
    marker_size,
    position,
)


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    try:
        return QApplication([])
    except Exception as error:  # pragma: no cover - depends on the machine
        pytest.skip(f"Qt could not start a platform plugin: {error}")


TRACKED = (
    TrackedSatellite(prn=14, elevation_degrees=84, azimuth_degrees=316, signal_strength=38),
    TrackedSatellite(prn=2, elevation_degrees=18, azimuth_degrees=67, signal_strength=33),
)
PREDICTED = (PredictedSatellite(prn=8, elevation_degrees=14, azimuth_degrees=42),)


def reading(**kwargs: object) -> Reading:
    status = ReceiverStatus(
        captured_at=NOW,
        mode=SmartClockMode.LOCKED,
        tracked=TRACKED,
        not_tracked=PREDICTED,
        signal_strength_kind=SignalStrengthKind.CARRIER_TO_NOISE,
        elevation_mask_degrees=10,
        **kwargs,  # type: ignore[arg-type]
    )
    return Reading(status=status, tracked_count=len(TRACKED))


# ---- The polar mapping, with no Qt --------------------------------------------------------------


def test_overhead_is_the_centre_and_the_horizon_is_the_rim() -> None:
    """North up, 0° elevation at the rim, 90° at the centre — the convention every receiver's own
    plot uses. Inverting it would make the display actively misleading to someone who knows the
    instrument."""
    disc = disc_for(200, 200)

    overhead = position(disc, 90, 0)
    horizon = position(disc, 0, 0)

    assert overhead == pytest.approx((disc.centre_x, disc.centre_y))
    assert horizon == pytest.approx((disc.centre_x, disc.centre_y - disc.radius))


@pytest.mark.parametrize(
    ("azimuth", "expected"),
    [(0, "up"), (90, "right"), (180, "down"), (270, "left")],
)
def test_azimuth_runs_clockwise_from_north(azimuth: int, expected: str) -> None:
    disc = disc_for(200, 200)
    x, y = position(disc, 0, azimuth)

    match expected:
        case "up":
            assert y < disc.centre_y and x == pytest.approx(disc.centre_x)
        case "right":
            assert x > disc.centre_x and y == pytest.approx(disc.centre_y)
        case "down":
            assert y > disc.centre_y and x == pytest.approx(disc.centre_x)
        case "left":
            assert x < disc.centre_x and y == pytest.approx(disc.centre_y)


def test_an_elevation_below_the_horizon_lands_on_the_rim_rather_than_outside_it() -> None:
    """A receiver reporting a negative elevation for a satellite it is still tracking is reporting
    one below the horizon. Drawing that outside the disc would be worse than drawing it on the
    rim."""
    disc = disc_for(200, 200)

    assert position(disc, -5, 0) == pytest.approx(position(disc, 0, 0))


def test_the_elevation_mask_ring_sits_where_its_elevation_does() -> None:
    disc = disc_for(200, 200)

    assert elevation_ring(disc, 0) == pytest.approx(disc.radius)
    assert elevation_ring(disc, 90) == pytest.approx(0)
    assert elevation_ring(disc, 45) == pytest.approx(disc.radius / 2)


def test_marker_area_scales_with_strength_so_the_diameter_scales_with_its_root() -> None:
    """P0-9.

    Scaling the diameter directly would make a strong satellite look four times the signal of a
    middling one rather than twice — the classic way a bubble chart lies."""
    kind = SignalStrengthKind.CARRIER_TO_NOISE
    weakest = marker_size(26, kind)
    strongest = marker_size(55, kind)
    middle = marker_size(40, kind)

    assert weakest == pytest.approx(MIN_MARKER)
    assert strongest == pytest.approx(MAX_MARKER)
    # Halfway in value is past halfway in diameter, because area is what is proportional.
    assert middle > (weakest + strongest) / 2


def test_the_two_signal_scales_are_not_interchangeable() -> None:
    """§11.1: 26–55 with ≥ 35 good on one, 0–255 with 20–30 weak on the other. A 30 that means
    "good" on one means "weak" on the other, and a plot that guessed would size its markers
    backwards on half the family."""
    as_carrier = marker_size(30, SignalStrengthKind.CARRIER_TO_NOISE)
    as_strength = marker_size(30, SignalStrengthKind.SIGNAL_STRENGTH)

    assert as_carrier > as_strength


def test_a_satellite_with_no_reading_still_gets_a_marker() -> None:
    """It is still up there, and omitting it would put a hole in the plot that reads as an
    obstruction."""
    assert marker_size(None, SignalStrengthKind.CARRIER_TO_NOISE) == pytest.approx(MIN_MARKER)


def test_the_marker_description_is_the_sentence_the_specification_gives() -> None:
    """§9.10.2 gives the form verbatim."""
    said = describe(19, 65, 52, 49, SignalStrengthKind.CARRIER_TO_NOISE, tracked=True)

    assert said == "PRN 19, elevation 65 degrees, azimuth 52 degrees, carrier to noise 49, tracked."


def test_an_unreported_field_is_omitted_rather_than_read_as_a_dash() -> None:
    """ "Elevation dash degrees" is noise where leaving it out is a fact."""
    said = describe(7, None, 116, None, SignalStrengthKind.UNKNOWN, tracked=False)

    assert "elevation" not in said
    assert said == "PRN 7, azimuth 116 degrees, not tracked."


def test_markers_come_back_in_prn_order() -> None:
    """Which is the order the keyboard walks them in, and it is stable — a spatial traversal
    reorders itself every time a satellite moves."""
    markers = markers_from(TRACKED, PREDICTED)

    assert [marker.prn for marker in markers] == [2, 8, 14]


def test_a_satellite_with_no_position_is_not_placeable() -> None:
    """Putting it at the centre — which a ``None`` treated as zero would do — would claim it is
    directly overhead."""
    markers = markers_from((TrackedSatellite(prn=3),), ())

    assert markers[0].is_placeable is False


# ---- The plot as a widget ----------------------------------------------------------------------


def test_every_marker_is_a_real_focusable_widget(application: QApplication) -> None:
    """§9.10.2, and the port plan's explicit instruction: **do not paint dots and bolt on a
    hand-written peer.** A marker that is a real widget is in the accessibility tree by
    construction and takes focus by construction."""
    del application
    window = DetailsWindow(Theme.DARK)
    page = window.page_named("Satellites")
    page.show_reading(reading())

    markers = page.plot.markers  # type: ignore[attr-defined]

    assert len(markers) == 3
    for marker in markers:
        assert marker.focusPolicy() != Qt.FocusPolicy.NoFocus
        assert marker.accessibleName().startswith("PRN ")


def test_each_marker_reports_its_own_name(application: QApplication) -> None:
    del application
    window = DetailsWindow(Theme.DARK)
    page = window.page_named("Satellites")
    page.show_reading(reading())

    names = [marker.accessibleName() for marker in page.plot.markers]  # type: ignore[attr-defined]

    assert (
        "PRN 14, elevation 84 degrees, azimuth 316 degrees, carrier to noise 38, tracked." in names
    )
    assert "PRN 8, elevation 14 degrees, azimuth 42 degrees, not tracked." in names


def test_a_marker_hit_target_is_declared_at_the_documented_exception(
    application: QApplication,
) -> None:
    """The target is **declared, not inherited** — the ink may be 8 px and the target is not.

    §9.10.2's exception rather than §9.12's floor, and asserted as an equality rather than as
    ``>=``: a marker larger than 24 px is the defect the exception exists to prevent, so a floor
    written the usual way round would pass in exactly the case that matters. At the plot's 240 px
    minimum two satellites in the fixtures sit 27.0 px apart, and 32 px targets overlap there.
    """
    del application
    from smartclock_monitor.themes.spacing import SKY_PLOT_POINTER_TARGET

    window = DetailsWindow(Theme.DARK)
    page = window.page_named("Satellites")
    page.show_reading(reading())

    for marker in page.plot.markers:  # type: ignore[attr-defined]
        assert marker.width() == SKY_PLOT_POINTER_TARGET
        assert marker.height() == SKY_PLOT_POINTER_TARGET


def test_arrow_keys_walk_the_markers_in_prn_order(application: QApplication) -> None:
    del application
    from PySide6.QtGui import QKeyEvent

    window = DetailsWindow(Theme.DARK)
    page = window.page_named("Satellites")
    page.show_reading(reading())
    plot = page.plot  # type: ignore[attr-defined]

    press = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Right, Qt.KeyboardModifier.NoModifier)
    plot.keyPressEvent(press)
    first = plot.selected_prn
    plot.keyPressEvent(press)
    second = plot.selected_prn

    assert [first, second] == [2, 8]


def test_the_table_and_the_plot_agree(application: QApplication) -> None:
    """§9.10.2 requires a list alternate view for users who cannot use the spatial form. Side by
    side rather than behind a toggle, and they agree by construction because they render the same
    tuple."""
    del application
    window = DetailsWindow(Theme.DARK)
    page = window.page_named("Satellites")
    page.show_reading(reading())

    assert page.table.rowCount() == 3  # type: ignore[attr-defined]
    prns = {page.table.item(row, 0).text() for row in range(3)}  # type: ignore[attr-defined]
    assert prns == {"2", "8", "14"}


# ---- The window --------------------------------------------------------------------------------


def test_every_page_is_reachable_from_the_navigation(application: QApplication) -> None:
    """P0-5: gated here."""

    del application
    window = DetailsWindow(Theme.DARK)

    titles = [window.navigation.item(row).text() for row in range(window.navigation.count())]

    assert titles == [page.title for page in window.pages]
    assert len(titles) >= 4


def test_every_page_is_fed_even_when_it_is_not_showing(application: QApplication) -> None:
    """A page that only updated while visible would show a stale value for one poll interval after
    being switched to — which is exactly when someone is looking at it."""
    del application
    window = DetailsWindow(Theme.DARK)
    window.navigation.setCurrentRow(0)

    window.show_reading(reading())

    satellites = window.page_named("Satellites")
    assert satellites.table.rowCount() == 3  # type: ignore[attr-defined]


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda t: t.value)
def test_a_theme_change_reaches_every_page(theme: Theme, application: QApplication) -> None:
    del application
    window = DetailsWindow(Theme.LIGHT)
    window.show_reading(reading())

    window.apply_theme(theme)

    assert palette_for(theme).card_fill in window.styleSheet()


def test_asking_for_a_page_that_does_not_exist_raises(application: QApplication) -> None:
    """Rather than returning ``None``: a caller asking for a page that does not exist has a bug,
    and handing back ``None`` would hide it."""
    del application
    window = DetailsWindow(Theme.DARK)

    with pytest.raises(KeyError):
        window.page_named("Nonexistent")


def test_the_main_window_opens_the_details_window_on_demand(application: QApplication) -> None:
    """Created lazily and kept, because most sessions never open it — and throwing it away on close
    would lose the satellite row a user had selected."""
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)
    before = window.details

    window.open_details()
    first = window.details
    window.open_details()
    second = window.details

    assert before is None, "It should not exist until it is asked for."
    assert first is not None
    assert second is first, "Opening twice must not build a second window."


def test_a_reading_reaches_the_details_window_once_it_is_open(application: QApplication) -> None:
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)
    window.open_details()
    window.show_reading(reading())

    details = window.details
    assert details is not None
    assert details.page_named("Satellites").table.rowCount() == 3  # type: ignore[attr-defined]
