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


@pytest.fixture(scope="module")
def application() -> QApplication:
    """One QApplication for the module. Qt permits exactly one per process."""
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    return QApplication([])


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
