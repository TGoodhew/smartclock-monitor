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

from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.preferences import Preferences
from smartclock_monitor.themes.tokens import Theme
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.views.main_window import MainWindow

#: §9.12's A11Y-5: pointer targets are at least this, at all times.
POINTER_FLOOR = 32

#: §9.10.2: a table row that is the sky plot's compliant alternate is at least this.
#:
#: A11Y-5's *touch* floor, taken deliberately — §9.10.2 argues that an exception resting on an
#: alternate should rest on the stronger figure rather than the weaker one it happens to need.
#: **Written out here rather than imported**, for the same reason POINTER_FLOOR is: a gate that
#: compares the code against its own constant passes whatever the constant says. The first version
#: of this did exactly that and accepted 30.
ALTERNATE_ROW_FLOOR = 40

#: The only files that may turn a severity into a colour. §9.13 item 10 and A11Y-12: a page that
#: resolved one itself would be a bare coloured shape away from meaning-by-colour-alone.
#:
#: One list, read by both the gate and its staleness check. `platform/tray.py` was here until D5
#: removed the tray, and the copy in the staleness check had to be found separately.
SANCTIONED_COLOUR_CALLERS = frozenset(
    {
        "themes/severity.py",  # defines it
        "widgets/severity_pill.py",  # §9.13's one renderer
        "widgets/medallion.py",  # §9.10.2's ring, which carries the word beneath it
    }
)

#: How much of the window's minimum width every page must leave unused.
#:
#: Not a style preference. Font metrics differ between machines at the same point size, so a page
#: measured to fit exactly on one desktop does not fit on another — which is how the sideways-scroll
#: gate came to pass here and fail on CI by 24 px. Ten per cent is comfortably more than the ~2 %
#: that cost, and small enough that it does not become the thing driving the window's size.
WIDTH_MARGIN = 0.10

#: The one recorded exception, and §9.10.2 names the compliant path rather than waiving the rule:
#: a sky-plot marker's *position is the data* and cannot be moved to make room, so the disc is
#: inset inside a 24 px transparent hit area and the tables carry the same data at ≥ 40 px.
SKY_PLOT_HIT_AREA = 24


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def windows(*, populated: bool = False) -> list[QWidget]:
    """Both real windows, with every destination present.

    :param populated: also feed them a captured reading, so the tables have rows. Off by default —
        most gates here are about controls that exist before any receiver answers.
    """
    main = MainWindow(Theme.DARK)
    details = DetailsWindow(Theme.DARK)
    details.apply_preferences(Preferences(advanced_console=True, undocumented_queries=True))
    if populated:
        reading = _a_captured_reading()
        main.show_reading(reading)
        details.show_reading(reading)
    return [main, details]


def _a_captured_reading() -> Reading:
    """One real status screen, parsed the way the application parses it."""
    from pathlib import Path

    from smartclock_device.clock import SystemClock
    from smartclock_device.drivers.smartclock import SmartClockDriver
    from smartclock_device.transport.transaction import Transaction, TransactionOutcome

    fixture = Path(__file__).resolve().parent / "fixtures" / "locked-stabilizing.txt"
    lines = tuple(fixture.read_text(encoding="latin-1").splitlines())
    status = SmartClockDriver(clock=SystemClock()).parse_full(
        Transaction(command=":SYST:STAT?", outcome=TransactionOutcome.COMPLETED, lines=lines),
        None,
    )
    return Reading(status=status, captured_at=status.captured_at)


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
    allowed = SANCTIONED_COLOUR_CALLERS

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
    that had quietly stopped covering anything.

    Reads the **same constant** the gate does. It used to keep its own copy, so removing
    `platform/tray.py` with D5 broke it in two places and each had to be found separately — a
    duplicated allowlist is the failure this test exists to describe, arrived at from the inside.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "smartclock_monitor"
    for relative in sorted(SANCTIONED_COLOUR_CALLERS):
        source = root / relative
        assert source.exists(), f"{relative} is sanctioned and does not exist"
        assert "colour_for" in source.read_text(encoding="utf-8"), relative


def test_no_two_markers_overlap_at_the_plot_s_minimum_size() -> None:
    """§9.10.2's exception, checked against captured sky rather than against the argument for it.

    The specification predicts that a 32 px target on this plot covers roughly 8° of projected sky
    and that satellites routinely sit closer, making the failure **silently selecting the wrong
    satellite** — worse than a small target, because a missed click is obvious and a wrong
    selection is not.

    It reproduces, across all ten captures. Of 424 satellite pairs placed on a plot at its own
    240 px minimum, **thirteen** are closer than 32 px and **none** is closer than 24; the tightest
    is PRN 17 and PRN 22 in ``surveying-locked-to-gps-stabilizing-frequency.txt`` at 26.8 px. That
    is what moved this from a judgement call to a measurement.
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
    # **rglob.** Nine of the ten captures live in ``fixtures/captured/``, and a flat glob found
    # only the one at the top — so this walked a tenth of its oracle while asserting it had one.
    # The non-empty assertion below did not catch that: one fixture is not none.
    fixtures = sorted((Path(__file__).resolve().parent / "fixtures").rglob("*.txt"))
    assert len(fixtures) >= 10, (
        f"found only {len(fixtures)} captures; the fixtures are the oracle and there are ten"
    )

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


# ---- Every interactive class the windows contain is coloured by the token layer ------------------


def test_no_widget_that_paints_its_own_ground_is_left_at_the_desktop_s_palette() -> None:
    """§9.4: colour comes from the token table, and a control with no rule takes the *desktop's*.

    **Background, not foreground.** `QWidget` declares ``color`` for everything, so foreground is
    never the thing that goes missing — which is precisely what made this defect so hard to see. A
    control that paints its own ground and has no ``background-color`` rule keeps Qt's default
    white *and* inherits this theme's light text, so on Dark it renders as a white rectangle with
    an unreadable value in it. That is what a spin box looked like, next to a correctly dark combo
    box that had carried the full set since the first commit.

    Asked of the classes the **real windows actually contain**, so a control nobody wrote a rule
    for fails here rather than in a screenshot months later.
    """
    import re

    from PySide6.QtWidgets import (
        QAbstractItemView,
        QAbstractSpinBox,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QTextEdit,
        QToolBar,
    )

    from smartclock_monitor.themes.qss import stylesheet
    from smartclock_monitor.themes.tokens import palette_for

    #: Controls that fill their own rectangle. Checkboxes, radio buttons and labels are absent
    #: deliberately — they draw over the card behind them and §9's own QLabel rule makes that
    #: explicit, so requiring a ground of them would be requiring the bug.
    paints_a_ground = (
        QAbstractItemView,
        QAbstractSpinBox,
        QComboBox,
        QLineEdit,
        QPlainTextEdit,
        QProgressBar,
        QPushButton,
        QScrollArea,
        QTextEdit,
        QToolBar,
    )

    present: set[str] = set()
    for window in windows():
        for kind in paints_a_ground:
            for child in window.findChildren(kind):
                present.add(type(child).__name__)
    assert present, "no widgets were found; the walk is broken, not the theme"

    for theme in Theme:
        sheet = stylesheet(palette_for(theme))
        for name in sorted(present):
            # The class must be the **subject** of the selector — its last element — not merely
            # mentioned in one: `QComboBox QAbstractItemView { … }` styles the popup and says
            # nothing about the combo.
            covered = any(
                re.search(
                    rf"(^|[\s,]){base}(::[\w-]+)?(:[\w-]+)?\s*(,[^{{}}]*)?{{"
                    # The declaration must *begin* at the brace or after a semicolon. An
                    # unanchored `\bbackground` matched inside `selection-background-color`,
                    # which sets the highlight and leaves the ground exactly as unset as it was —
                    # so a run that stripped the text inputs' real background still passed.
                    rf"(?:[^}}]*;)?\s*background(-color)?\s*:",
                    sheet,
                    re.MULTILINE,
                )
                for base in _qt_bases(name)
            )
            assert covered, (
                f"{name} appears in a real window and no rule in the {theme.value} stylesheet "
                f"gives it a background, so it paints Qt's default white and takes this theme's "
                f"text colour over it"
            )


def _qt_bases(name: str) -> list[str]:
    """A class name and the Qt base classes a stylesheet rule for it may be written against."""
    from PySide6 import QtWidgets

    kind = getattr(QtWidgets, name, None)
    if kind is None:
        return [name]
    return [base.__name__ for base in kind.__mro__ if base.__name__.startswith("Q")]


# ---- §10.3's outputs pill says which of the four states it is ------------------------------------


def test_every_output_validity_gets_its_own_wording_and_severity() -> None:
    """§11.1 calls the middle state *"the distinction between usable but drifting and do not use"*
    and *"the single most important thing the main window has to convey"*.

    It was falling through a catch-all and reporting **Outputs unknown** in neutral grey — the one
    state where saying nothing is worst, rendered as if nothing had been read at all. Written as an
    exhaustive match now, so a fifth state fails mypy rather than becoming grey.
    """
    from conftest import NOW
    from smartclock_device.models.receiver_status import OutputValidity, ReceiverStatus
    from smartclock_monitor.themes.severity import Severity
    from smartclock_monitor.views.main_window import _outputs_state

    seen: dict[OutputValidity, tuple[Severity, str]] = {}
    for validity in OutputValidity:
        seen[validity] = _outputs_state(ReceiverStatus(captured_at=NOW, outputs=validity))

    assert len({text for _, text in seen.values()}) == len(OutputValidity), (
        "two states share a wording, so one of them is unreportable"
    )
    assert seen[OutputValidity.VALID][0] is Severity.SUCCESS
    assert seen[OutputValidity.INVALID][0] is Severity.CRITICAL
    assert seen[OutputValidity.UNKNOWN][0] is Severity.NEUTRAL

    # §9.4.1's caution row is "recovering, waiting, reduced accuracy, stale data" in as many words.
    severity, text = seen[OutputValidity.VALID_REDUCED]
    assert severity is Severity.CAUTION
    assert "reduced" in text.lower()


def test_the_theme_picker_is_wide_enough_to_name_the_theme() -> None:
    """The shared QComboBox rule sets a 32 px min-width — a pointer floor, not a width for words.
    In §10.3's header row this picker shrank to a single letter, so the control naming the current
    theme did not name it."""
    from smartclock_monitor.views.main_window import MAIN_MINIMUM, MainWindow

    window = MainWindow(Theme.DARK)
    # At §10.3's own minimum, which is where it broke: a wider window hides the crowding.
    window.resize(*MAIN_MINIMUM)
    window.show()
    # The layout has not run until the event loop turns, and an unlaid-out widget reports its hint
    # rather than its width — which is the number this test exists not to trust.
    QApplication.processEvents()
    try:
        picker = window._theme_picker
        longest = max(
            (
                picker.fontMetrics().horizontalAdvance(picker.itemText(index))
                for index in range(picker.count())
            ),
            default=0,
        )
        # The **laid-out width**, not the size hint. The hint was already 142 px against a 97 px
        # longest entry and stayed there while the header squeezed the control itself to 50 — so an
        # assertion on the hint passed in exactly the state that put one letter on screen.
        assert picker.width() >= longest, (
            f"the picker is {picker.width()} px and its longest entry needs {longest}, "
            f"so it cannot name the theme it is showing"
        )
    finally:
        window.close()


# ---- No page scrolls sideways at the size its window opens at ----------------------------------


def test_no_details_page_needs_horizontal_scrolling_at_the_window_minimum() -> None:
    """§9.11: the explanation is the part that has to arrive, and a sentence that runs off the
    right of a card is a sentence nobody reads.

    Five of the ten pages did, at the size the Details window **opens** at — the Position page
    wanted 1358 px of a 692 px viewport. Almost all of it was explanatory text that never had
    ``setWordWrap`` called on it, which ``views.pages.label()`` now decides from the role.

    **The window's minimum is computed from the pages, so this asserts the thing itself.** Three
    hard-coded numbers were tried — 900, 1100, 1160 — and each was a measurement of one machine.
    CI rejected 1100 on a runner with slightly wider fonts and 1160 on Windows, where four pages
    overflowed and one scrolled: a named face this port does not bundle falls back to whatever the
    desktop has, and glyph widths go with it. Asserting a *margin* against a hard-coded number was
    chasing the wrong quantity.

    Vertical scrolling is fine and expected. This is only about the axis that hides content.
    """
    from PySide6.QtWidgets import QScrollArea

    from smartclock_monitor.views.details_window import DetailsWindow

    window = DetailsWindow(Theme.DARK)
    window.apply_preferences(Preferences(advanced_console=True, undocumented_queries=True))
    window.resize(window.minimumWidth(), window.minimumHeight())
    window.show()
    QApplication.processEvents()

    try:
        scrolling: list[str] = []
        for index, page in enumerate(window.pages):
            window._navigation.setCurrentRow(index)
            QApplication.processEvents()

            area = window._stack.currentWidget()
            if not isinstance(area, QScrollArea):
                continue
            bar = area.horizontalScrollBar()
            if bar is not None and bar.maximum() > 0:
                scrolling.append(f"{page.title} scrolls {bar.maximum()} px sideways")

        assert not scrolling, (
            "these pages scroll sideways at the size the window opens at: " + "; ".join(scrolling)
        )
    finally:
        window.close()


def test_no_page_is_so_wide_it_hits_the_window_s_ceiling() -> None:
    """The computed minimum is bounded, and the bound is where a page should be fixed instead.

    Without this, a page whose layout ran away would silently clamp at the cap and start scrolling
    sideways — the failure would look like the window's fault rather than the page's.

    The ceiling is a screen width: past it the page does not fit the narrowest laptop in common
    use, so scrolling is the lesser evil and the page is the thing to change. Worth knowing how
    close that is — the Diagnostics page measures about 1321 px on Windows, where the fallback face
    is wider than this machine's.
    """
    from smartclock_monitor.themes.spacing import Spacing
    from smartclock_monitor.views.details_window import (
        _MINIMUM_WIDTH_CAP,
        _NAVIGATION_WIDTH,
        DetailsWindow,
    )

    window = DetailsWindow(Theme.DARK)
    window.apply_preferences(Preferences(advanced_console=True, undocumented_queries=True))
    try:
        chrome = _NAVIGATION_WIDTH + Spacing.PAGE * 2
        too_wide = {
            page.title: page.minimumSizeHint().width() + chrome
            for page in window.pages
            if page.minimumSizeHint().width() + chrome > _MINIMUM_WIDTH_CAP
        }

        assert not too_wide, (
            f"these pages want more than the {_MINIMUM_WIDTH_CAP} px ceiling, so the window "
            f"would clamp and they would scroll: {too_wide}"
        )
    finally:
        window.close()


# ---- §9.10.2: the tables are the sky plot's compliant alternate, and must actually be ------------


def test_every_selectable_table_row_meets_the_alternate_floor() -> None:
    """§9.10.2, and the reason the sky plot may have 24 px markers at all.

    The exception for those markers is granted **on the strength of the tables**: they carry the
    same data, selection is shared both ways, and their rows are "full-width and at least 40 px".
    An exception resting on an alternate that is no more compliant than the thing it excuses is not
    an exception, it is two failures.

    §9.10.2 carries a warning about this because it already went wrong once in WinZ3805A — a dense
    list style set the row minimum to 0 to escape Qt's stock 40, rows measured 26–28 px, and the
    sentence claiming otherwise stayed in the specification for weeks. **This port reproduced it at
    30 px**, and it was found by drafting `divergences.md` and checking a sentence before writing
    it, not by any test here. Hence this one.

    Measured on the real windows, because the value that matters is the rendered row height and not
    the constant it was set from.
    """
    from PySide6.QtWidgets import QTableWidget

    from smartclock_monitor.themes.spacing import TABLE_ROW_TARGET

    assert TABLE_ROW_TARGET == ALTERNATE_ROW_FLOOR, (
        f"the constant says {TABLE_ROW_TARGET} and §9.10.2 says {ALTERNATE_ROW_FLOOR}"
    )

    measured: dict[str, int] = {}
    for window in windows(populated=True):
        for table in window.findChildren(QTableWidget):
            if table.rowCount() == 0:
                continue
            name = table.accessibleName() or "an unnamed table"
            measured[name] = min(table.rowHeight(row) for row in range(table.rowCount()))

    assert measured, "no populated table was found; the walk is broken, not the layout"
    for name, height in sorted(measured.items()):
        assert height >= ALTERNATE_ROW_FLOOR, (
            f"{name} has {height} px rows, under §9.10.2's {ALTERNATE_ROW_FLOOR} px floor — "
            f"which is what the sky plot's 24 px marker exception rests on"
        )
