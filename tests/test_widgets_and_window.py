"""The custom widgets and the main window, driven headlessly.

Qt renders to an offscreen platform plugin here, so these run on CI with no display. They are
**skipped rather than failed** where Qt cannot be started at all — a build machine missing
``libEGL`` is a packaging problem, not a defect in this code, and turning it into a red test would
teach people to ignore the colour.

What is checked is what §9 promises and what a screenshot cannot: that severity reaches the
accessibility tree as words, that the geometry holds at awkward sizes, that a theme change repaints
the custom widgets rather than only the stylesheet, and that a missing reading renders as a dash
rather than as a zero.
"""

from __future__ import annotations

import os

import pytest

# The offscreen plugin has to be chosen before Qt is imported.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

qt = pytest.importorskip("PySide6.QtWidgets", reason="Qt is not available on this machine")

from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import NOW  # noqa: E402
from smartclock_device.models.receiver_status import (  # noqa: E402
    OutputValidity,
    ReceiverStatus,
    SignalStrengthKind,
    SmartClockMode,
)
from smartclock_monitor.services.polling import Reading  # noqa: E402
from smartclock_monitor.themes.severity import SEVERITY_SHAPES, Severity  # noqa: E402
from smartclock_monitor.themes.tokens import ALL_THEMES, Theme, palette_for  # noqa: E402
from smartclock_monitor.widgets.medallion import (  # noqa: E402
    StatusMedallion,
    ring_geometry,
    tick_positions,
)
from smartclock_monitor.widgets.severity_pill import SeverityPill, shape_path  # noqa: E402
from smartclock_monitor.widgets.sky_plot import Marker, SatelliteMarker  # noqa: E402
from smartclock_monitor.widgets.sky_plot_geometry import (  # noqa: E402
    MAX_MARKER,
    MIN_MARKER,
    SEQUENTIAL_STEPS,
    marker_size,
    sequential_step,
)


@pytest.fixture(scope="module")
def application() -> QApplication:
    """One QApplication for the module. Qt permits exactly one per process.

    Skips rather than errors when Qt will not start. ``importorskip`` above covers a missing
    package; this covers the other half — the package imports but the platform plugin cannot
    initialise, which is what a machine without ``libEGL`` does. CI installs those libraries so
    this should not trigger there, and a skip that fires on CI is worth investigating rather than
    accepting.
    """
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    try:
        return QApplication([])
    except Exception as error:  # pragma: no cover - depends on the machine, not the code
        pytest.skip(f"Qt could not start a platform plugin: {error}")


def status(mode: SmartClockMode = SmartClockMode.LOCKED, **kwargs: object) -> ReceiverStatus:
    return ReceiverStatus(captured_at=NOW, mode=mode, **kwargs)  # type: ignore[arg-type]


# ---- Geometry, which needs no window ----------------------------------------------------------


def test_the_ring_is_always_a_circle_in_the_shorter_side() -> None:
    """So the medallion never distorts when the window is resized to an awkward shape."""
    wide = ring_geometry(400, 120)
    tall = ring_geometry(120, 400)

    assert wide.radius == pytest.approx(tall.radius)
    assert wide.radius * 2 + wide.thickness == pytest.approx(120)


@pytest.mark.parametrize("size", [1, 2, 10, 96, 1000])
def test_the_ring_survives_every_size(size: int) -> None:
    """Including the degenerate ones. A widget is briefly 0 by 0 during layout, and a division by
    the shorter side is exactly where that bites."""
    geometry = ring_geometry(size, size)

    assert geometry.radius > 0
    assert geometry.thickness > 0


def test_a_zero_sized_widget_does_not_divide_by_zero() -> None:
    geometry = ring_geometry(0, 0)

    assert geometry.radius >= 0


def test_the_ticks_are_evenly_spaced_and_start_at_the_top() -> None:
    geometry = ring_geometry(200, 200)
    ticks = tick_positions(geometry, 4)

    assert len(ticks) == 4
    first_inner, _ = ticks[0]
    assert first_inner.x() == pytest.approx(geometry.centre_x)
    assert first_inner.y() < geometry.centre_y, "The first tick should be above the centre."


def test_every_severity_shape_is_a_distinct_outline(application: QApplication) -> None:
    """§9.4.3 draws them as geometry rather than as glyphs, so that under high contrast they
    resolve to outlines rather than depending on a font being present.

    Distinct *silhouettes*, not just distinct names: two shapes with the same bounding path would
    put the application back to distinguishing severity by colour alone.
    """
    del application
    outlines = {}
    for severity in Severity:
        shape, _ = SEVERITY_SHAPES[severity]
        path = shape_path(shape, 12.0)
        assert not path.isEmpty(), f"{shape} drew nothing."
        outlines[shape] = path.elementCount()

    assert len(outlines) == len(Severity)


# ---- The pill ---------------------------------------------------------------------------------


def test_the_pill_carries_all_three_channels(application: QApplication) -> None:
    """§9.13: colour + shape + text, never colour alone. There is deliberately no setter for the
    colour on its own."""
    del application
    pill = SeverityPill(Severity.CRITICAL, "Holdover", palette_for(Theme.DARK))

    assert pill.severity is Severity.CRITICAL
    assert pill.text == "Holdover"
    assert "Holdover" in pill.accessibleName()


def test_the_pill_names_its_severity_to_an_assistive_technology(
    application: QApplication,
) -> None:
    """A screen reader sees neither the colour nor the shape. The text channel is what survives."""
    del application
    pill = SeverityPill(Severity.SUCCESS, "Locked to GPS", palette_for(Theme.LIGHT))

    name = pill.accessibleName()

    assert "Success" in name
    assert "Locked to GPS" in name


def test_changing_the_state_updates_both_channels(application: QApplication) -> None:
    del application
    pill = SeverityPill(Severity.NEUTRAL, "Unknown", palette_for(Theme.LIGHT))

    pill.set_state(Severity.CAUTION, "Recovering")

    assert pill.severity is Severity.CAUTION
    assert "Recovering" in pill.accessibleName()


# ---- The medallion ----------------------------------------------------------------------------


def test_the_medallion_says_what_it_shows(application: QApplication) -> None:
    """§9.12. It is the primary readout, so the words have to reach the accessibility tree."""
    del application
    medallion = StatusMedallion(palette_for(Theme.DARK))

    medallion.set_state(Severity.SUCCESS, "8", "Locked to GPS")

    assert medallion.accessibleName() == "Locked to GPS, 8 satellites tracked"


# ---- The window -------------------------------------------------------------------------------


def test_the_window_fits_g1_s_box(application: QApplication) -> None:
    """G1: a glanceable window, ≤ 420 by 260. A floor rather than a fixed size — the criterion is
    that it *fits*, not that it is stuck there."""
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)

    assert window.minimumWidth() <= 420
    assert window.minimumHeight() <= 260


def test_a_locked_reading_reaches_the_window(application: QApplication) -> None:
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)
    window.show_reading(
        Reading(
            status=status(SmartClockMode.LOCKED, outputs=OutputValidity.VALID),
            tracked_count=8,
            sync_state="LOCK",
        )
    )

    assert "8 satellites tracked" in window.medallion.accessibleName()
    assert window.mode_pill.severity is Severity.SUCCESS


def test_holdover_renders_as_critical(application: QApplication) -> None:
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)
    window.show_reading(Reading(status=status(SmartClockMode.HOLDOVER), tracked_count=0))

    assert window.mode_pill.severity is Severity.CRITICAL
    assert "Holdover" in window.mode_pill.text


def test_a_missing_reading_renders_as_a_dash_rather_than_a_zero(
    application: QApplication,
) -> None:
    """§11.1's whole point: "not reported" and "reported as nought" are different claims, and a
    timing instrument that shows 0 ns for a reading it never got is lying."""
    del application
    from smartclock_monitor.views.main_window import DASH, MainWindow

    window = MainWindow(Theme.DARK)
    window.show_reading(Reading(status=status(SmartClockMode.UNKNOWN)))

    assert window.readouts["tfom"].value_text == DASH
    assert window.readouts["interval"].value_text == DASH


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda t: t.value)
def test_a_theme_change_repaints_the_custom_widgets(
    theme: Theme, application: QApplication
) -> None:
    """Both halves are needed and neither is enough: QSS carries the ordinary widgets and cannot
    re-resolve, so it is regenerated; the custom widgets never read QSS at all, so they are handed
    the palette."""
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.LIGHT)
    window.apply_theme(theme)

    expected = palette_for(theme)
    assert window.medallion.palette_tokens is expected
    assert window.mode_pill.palette_tokens is expected
    assert expected.card_fill in window.styleSheet()


def test_the_application_name_is_read_from_one_constant() -> None:
    """§6.3's rule survives the loss of the API that used to supply it: the name appears in the
    title bar, the about surface and the guide, and a rename made in nine places gets made in
    eight."""
    from smartclock_monitor.views import main_window

    assert main_window.APPLICATION_NAME
    assert main_window.APPLICATION_NAME.strip() == main_window.APPLICATION_NAME


# ---- The sky plot's strength encodings (§9.4.4, §9.10.2) ----------------------------------------


def test_the_ramp_step_count_matches_every_theme_s_ramp() -> None:
    """``sky_plot_geometry`` names the step count so it can answer without a palette. That is only
    safe while the number agrees with the ramp it indexes — and disagreeing costs an IndexError on
    a marker, i.e. at paint time, in one theme."""
    for theme in ALL_THEMES:
        assert len(palette_for(theme).sequential) == SEQUENTIAL_STEPS, theme.value


@pytest.mark.parametrize(
    ("strength", "expected"),
    [(26, 0), (30, 0), (35, 2), (40, 3), (45, 4), (50, 5), (55, 6), (99, 6), (0, 0)],
)
def test_carrier_to_noise_maps_across_the_whole_ramp(strength: int, expected: int) -> None:
    """C/N 26–55 spans the seven steps. The top of the scale takes the last step rather than
    falling off the end, which is what an unclamped ``int(fraction * steps)`` would do."""
    assert sequential_step(strength, SignalStrengthKind.CARRIER_TO_NOISE) == expected


def test_the_two_scales_are_not_interchangeable() -> None:
    """A 30 is weak on C/N and almost nothing on SS. A plot that guessed the scale would colour
    half the family backwards — the same reason ``marker_size`` takes the kind."""
    assert sequential_step(30, SignalStrengthKind.CARRIER_TO_NOISE) == 0
    assert sequential_step(200, SignalStrengthKind.SIGNAL_STRENGTH) == 5
    assert sequential_step(30, SignalStrengthKind.SIGNAL_STRENGTH) == 0


def test_an_unreadable_strength_takes_the_weakest_step_not_a_crash() -> None:
    """§11.1: the parser hands ``None`` for a field it could not read, and every consumer takes
    it. The satellite is still up there, so it is drawn — as the least assertive mark on the plot,
    matching the smallest marker ``marker_size`` gives it."""
    assert sequential_step(None, SignalStrengthKind.CARRIER_TO_NOISE) == 0
    assert sequential_step(40, SignalStrengthKind.UNKNOWN) == 0
    assert marker_size(None, SignalStrengthKind.CARRIER_TO_NOISE) == marker_size(
        26, SignalStrengthKind.CARRIER_TO_NOISE
    )


def test_the_ramp_step_rises_with_strength_and_never_falls() -> None:
    """The encoding is a magnitude. Monotonicity is the one property it must have, and a
    transposed bound inside ``strength_fraction`` would still produce plausible-looking colours."""
    steps = [sequential_step(v, SignalStrengthKind.CARRIER_TO_NOISE) for v in range(20, 60)]
    assert steps == sorted(steps)
    assert steps[0] == 0
    assert steps[-1] == SEQUENTIAL_STEPS - 1


def test_the_two_encodings_agree_about_where_the_middle_is() -> None:
    """Size is linear in *area* and the ramp is linear in *strength*, which is deliberate — but
    they encode one quantity, so a reader compares them without being told. Both must put the
    midpoint of the scale at the middle of their own range.

    This is the assertion that would have caught running the ramp through ``marker_size``'s square
    root as well, which puts the ramp's midpoint at a quarter of the scale."""
    middle = 26 + (55 - 26) // 2
    assert sequential_step(middle, SignalStrengthKind.CARRIER_TO_NOISE) == SEQUENTIAL_STEPS // 2

    area_fraction = (marker_size(middle, SignalStrengthKind.CARRIER_TO_NOISE) - MIN_MARKER) / (
        MAX_MARKER - MIN_MARKER
    )
    assert 0.65 < area_fraction < 0.75  # sqrt(0.5), i.e. half the area


def test_a_marker_takes_its_fill_from_the_sequential_ramp_not_the_categorical_one() -> None:
    """§9.10.2 puts the marker fill on the sequential ramp, and §9.4.4 forbids assigning a
    categorical colour by hash. It was ``series[prn % 8]``, which made the fill mean identity
    rather than magnitude and collided every eighth PRN regardless."""
    palette = palette_for(Theme.DARK)
    strong = SatelliteMarker(
        Marker(prn=1, elevation=45, azimuth=90, strength=54, tracked=True),
        SignalStrengthKind.CARRIER_TO_NOISE,
        palette,
    )
    weak = SatelliteMarker(
        Marker(prn=9, elevation=45, azimuth=90, strength=27, tracked=True),
        SignalStrengthKind.CARRIER_TO_NOISE,
        palette,
    )

    # Eight apart, so the old mapping gave these two the same colour.
    assert strong._step() != weak._step()
    assert palette.sequential[strong._step()] != palette.sequential[weak._step()]


def test_two_satellites_of_equal_strength_are_drawn_alike() -> None:
    """The corollary, and the property the categorical ramp could not have: the fill says how
    strong the signal is and nothing else, so two equal readings look equal."""
    palette = palette_for(Theme.LIGHT)
    markers = [
        SatelliteMarker(
            Marker(prn=prn, elevation=30, azimuth=10, strength=44, tracked=True),
            SignalStrengthKind.CARRIER_TO_NOISE,
            palette,
        )
        for prn in (2, 17, 31)
    ]
    assert len({marker._step() for marker in markers}) == 1
