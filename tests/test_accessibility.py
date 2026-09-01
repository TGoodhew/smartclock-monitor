"""§9.12's criteria, for the three that a machine can check.

P0-16 requires each by its stated verification method and says six gate CI. Most of §9.12 is a
manual pass by construction — nothing automated can tell whether a tab order follows *visual
reading* order, or whether a greyscale screenshot is unambiguous. These are the three that can be
decided by walking the real widget tree, which is worth more than a checklist item precisely
because §9.12's own note about A11Y-5 records what happens otherwise: a rule "enforced" by review
was untrue by 8 px for weeks.

The windows here are the real ones. A test that built its own widgets would be checking widgets
nobody sees.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSpinBox,
    QApplication,
    QComboBox,
    QLineEdit,
    QSpinBox,
    QWidget,
)

from smartclock_monitor.services.preferences import Preferences
from smartclock_monitor.themes.tokens import Theme
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.views.main_window import MainWindow

#: §9.12's A11Y-5: pointer targets are at least this, at all times.
POINTER_FLOOR = 32

#: The one recorded exception, and §9.10.2 names the compliant path rather than waiving the rule:
#: a sky-plot marker's *position is the data* and cannot be moved to make room, so the disc is
#: inset inside a 24 px transparent hit area and the tables carry the same data at ≥ 40 px.
SKY_PLOT_HIT_AREA = 24


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def windows() -> list[QWidget]:
    """Both real windows, with every destination present."""
    main = MainWindow(Theme.DARK)
    details = DetailsWindow(Theme.DARK)
    details.apply_preferences(Preferences(advanced_console=True, undocumented_queries=True))
    return [main, details]


def interactive(root: QWidget) -> list[QWidget]:
    """Every control a pointer or a screen reader can reach.

    One ``findChildren`` per type: PySide's overload takes a single type, not a tuple, and passing
    one silently becomes a TypeError rather than a filter that matches nothing.
    """
    found: list[QWidget] = []
    for kind in (QAbstractButton, QComboBox, QLineEdit, QSpinBox):
        for child in root.findChildren(kind):
            if child.isHidden() or _is_internal_editor(child):
                continue
            found.append(child)
    return found


def _is_internal_editor(widget: QWidget) -> bool:
    """A spin box and an editable combo each contain a ``QLineEdit`` of their own.

    That editor is not an independent control: it has no name because the control around it does,
    and its size is the control's. Counting it would report every spin box twice and demand a name
    for something a screen reader reaches through its parent.
    """
    parent = widget.parentWidget()
    return isinstance(widget, QLineEdit) and isinstance(parent, QAbstractSpinBox | QComboBox)


def describe(widget: QWidget) -> str:
    text = getattr(widget, "text", lambda: "")()
    return f"{type(widget).__name__}({text or widget.accessibleName() or 'unnamed'})"


# ---- A11Y-3: nothing icon-only is nameless ------------------------------------------------------


def test_every_control_without_visible_text_is_named_or_tipped() -> None:
    """§9.12's A11Y-3, as corrected: **either** an accessible name or a tooltip — the gate the
    specification describes does not require both, and this is that gate.

    A control whose label is its icon is invisible to a screen reader without one of the two, and
    §9.9's own requirement is that icon-only buttons carry both.
    """
    offenders: list[str] = []

    for window in windows():
        for control in interactive(window):
            visible_text = getattr(control, "text", lambda: "")()
            if visible_text:
                continue
            if control.accessibleName() or control.toolTip():
                continue
            offenders.append(f"{type(window).__name__}: {describe(control)}")

    assert not offenders, "Icon-only controls with no name and no tooltip: " + ", ".join(offenders)


def test_the_gate_catches_a_control_with_neither() -> None:
    """CLAUDE.md: a rule that matches nothing enforces nothing, and it fails silently."""
    from PySide6.QtWidgets import QPushButton

    nameless = QPushButton("")
    assert not nameless.text()
    assert not nameless.accessibleName()
    assert not nameless.toolTip()


# ---- A11Y-5: pointer targets ---------------------------------------------------------------------


def test_every_interactive_control_meets_the_pointer_floor() -> None:
    """§9.12's A11Y-5, and §9.4.5's note on it is why this is a gate rather than a review item:
    ``WzDenseListItemStyle`` set a list row's minimum height to 0 to escape the stock 40, the rows
    measured 26–28 px, and the sky plot's documented exception therefore *rested on an alternate
    that was no more compliant than the thing it was excusing*. It was untrue by 8 px for weeks
    because nothing measured it.
    """
    offenders: list[str] = []

    for window in windows():
        window.resize(1200, 900)
        for control in interactive(window):
            height = max(control.minimumHeight(), control.sizeHint().height())
            if height < POINTER_FLOOR:
                offenders.append(f"{describe(control)} is {height} px")

    assert not offenders, "Pointer targets under 32 px: " + ", ".join(sorted(set(offenders)))


def test_the_sky_plot_marker_keeps_its_documented_hit_area() -> None:
    """A11Y-5's one recorded exception, and §9.10.2 does not waive the rule — it names the
    compliant path. The visible disc is 8–18 px and *its position is the data*; growing the target
    past a point stops helping and starts silently selecting the wrong satellite."""
    from smartclock_monitor.themes.spacing import (
        MINIMUM_POINTER_TARGET,
        SKY_PLOT_POINTER_TARGET,
    )

    # The two are different numbers on purpose, and the assertion is exact rather than an
    # inequality: ">= 24" passed while markers had the full 32, which was the state this test was
    # written in and the state §9.10.2 warns against.
    assert MINIMUM_POINTER_TARGET == POINTER_FLOOR
    assert SKY_PLOT_POINTER_TARGET == SKY_PLOT_HIT_AREA
    assert SKY_PLOT_POINTER_TARGET < MINIMUM_POINTER_TARGET


# ---- A11Y-12 / P0-19: severity never renders as colour alone -------------------------------------


def test_only_the_sanctioned_renderers_resolve_a_severity_to_a_colour() -> None:
    """P0-19: *"Every severity indication in the app renders through SeverityPill"* — and §9.13
    item 10 requires it stay that way, which is why ``ReadoutTile``'s own severity property was
    struck rather than kept.

    Checked as **who may call ``colour_for``**. A page that resolved a severity to a colour itself
    would be one bare coloured shape away from conveying meaning by colour alone, and that is the
    defect A11Y-12 exists to prevent — greyscale review would catch it only after it shipped.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "smartclock_monitor"
    allowed = {
        "themes/severity.py",  # defines it
        "widgets/severity_pill.py",  # §9.13's one renderer
        "widgets/medallion.py",  # §9.10.2's ring, which carries the word beneath it
        "platform/tray.py",  # §9.4.3.1's shell surface, from the same rasteriser
    }

    offenders = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative in allowed:
            continue
        if "colour_for" in path.read_text(encoding="utf-8"):
            offenders.append(relative)

    assert not offenders, (
        "These resolve a severity to a colour outside the sanctioned renderers: "
        + ", ".join(offenders)
    )


def test_the_sanctioned_list_is_not_stale() -> None:
    """Guarding the guard: a list naming files that no longer resolve a colour would be a rule
    that had quietly stopped covering anything."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "smartclock_monitor"
    for relative in (
        "themes/severity.py",
        "widgets/severity_pill.py",
        "widgets/medallion.py",
        "platform/tray.py",
    ):
        assert "colour_for" in (root / relative).read_text(encoding="utf-8"), relative


def test_no_two_markers_overlap_at_the_plot_s_minimum_size() -> None:
    """§9.10.2's exception, checked against captured sky rather than against the argument for it.

    The specification predicts that a 32 px target on this plot covers roughly 8° of projected sky
    and that satellites routinely sit closer, making the failure **silently selecting the wrong
    satellite** — worse than a small target, because a missed click is obvious and a wrong
    selection is not.

    It reproduces. At the plot's own 240 px minimum, PRN 5 and PRN 20 in
    ``locked-stabilizing.txt`` sit 27.0 px apart: 32 px targets overlap on real sky and 24 px ones
    do not. That is what moved this from a judgement call to a measurement.
    """
    import itertools
    import math
    from pathlib import Path

    from smartclock_device.clock import SystemClock
    from smartclock_device.drivers.smartclock import SmartClockDriver
    from smartclock_device.transport.transaction import Transaction, TransactionOutcome
    from smartclock_monitor.themes.spacing import SKY_PLOT_POINTER_TARGET
    from smartclock_monitor.widgets.sky_plot import SkyPlot
    from smartclock_monitor.widgets.sky_plot_geometry import disc_for, position

    smallest = float(SkyPlot().minimumWidth())
    driver = SmartClockDriver(clock=SystemClock())
    fixtures = sorted((Path(__file__).resolve().parent / "fixtures").glob("*.txt"))
    assert fixtures, "the fixtures are the oracle; a test that found none would pass vacuously"

    closest = math.inf
    for fixture in fixtures:
        lines = tuple(fixture.read_text(encoding="latin-1").splitlines())
        status = driver.parse_full(
            Transaction(command=":SYST:STAT?", outcome=TransactionOutcome.COMPLETED, lines=lines),
            None,
        )
        disc = disc_for(smallest, smallest)
        # Tracked and not-tracked are different types with no common base, so they are walked
        # separately rather than concatenated — a joined list is list[object] and mypy is right
        # to refuse it.
        placed: list[tuple[float, float]] = []
        for tracked in status.tracked:
            if tracked.elevation_degrees is not None and tracked.azimuth_degrees is not None:
                placed.append(
                    position(disc, float(tracked.elevation_degrees), float(tracked.azimuth_degrees))
                )
        for predicted in status.not_tracked:
            if predicted.elevation_degrees is not None and predicted.azimuth_degrees is not None:
                placed.append(
                    position(
                        disc, float(predicted.elevation_degrees), float(predicted.azimuth_degrees)
                    )
                )
        for one, other in itertools.combinations(placed, 2):
            closest = min(closest, math.hypot(one[0] - other[0], one[1] - other[1]))

    assert closest < math.inf, "no fixture placed two satellites; nothing was compared"
    assert closest >= SKY_PLOT_POINTER_TARGET, (
        f"two markers are {closest:.1f} px apart at a {smallest:.0f} px plot, "
        f"inside the {SKY_PLOT_POINTER_TARGET} px target — one would take the other's clicks"
    )
    assert closest < POINTER_FLOOR, (
        "the fixtures no longer reproduce the overlap this exception exists for, so the exception "
        "is now resting on the argument rather than on the measurement"
    )
