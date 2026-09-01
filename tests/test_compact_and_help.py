"""§9.6.2's compact mode and §9.7.5's F1 guide."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from smartclock_monitor.themes.tokens import Theme, palette_for
from smartclock_monitor.views.help_window import (
    HelpWindow,
    guide_markdown,
    guide_path,
    version,
)
from smartclock_monitor.views.main_window import COMPACT_MINIMUM, MAIN_MINIMUM, MainWindow


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


# ---- §9.6.2's compact mode ---------------------------------------------------------------------


def test_the_minimums_are_the_figures_section_9_6_2_gives() -> None:
    """Content sizes in effective pixels — which on Qt are also what setMinimumSize takes, because
    logical pixels already have the device ratio applied. §9.6.2's conversion, its recomputation
    on a scaling change and its work-area cap are Windows arithmetic that does not arise here."""
    assert MAIN_MINIMUM == (380, 240)
    assert COMPACT_MINIMUM == (380, 144)


def test_compact_collapses_rather_than_clips() -> None:
    """§9.6.2: *"collapsed — not clipped, not scrolled: they are removed from the layout, so
    nothing is focusable or hit-testable off-screen"* (A11Y-1, A11Y-6). A hidden widget in Qt is
    out of the layout and out of the tab order, which is exactly what that rule wants."""
    window = MainWindow(Theme.DARK)
    window.show()
    assert window.readouts_card.isVisible() is True

    window.set_compact(True)

    assert window.is_compact is True
    assert window.readouts_card.isVisible() is False
    assert window.minimumHeight() == COMPACT_MINIMUM[1]
    window.close()


def test_the_medallion_shrinks_to_64() -> None:
    """§9.6.2's compact row: a 64 px medallion **with the satellite count in its centre**. §9.10.2
    draws the ring uniform at that size rather than as a sparkline, because sixty marks of
    differing length make a circle that small read as misshapen."""
    window = MainWindow(Theme.DARK)
    window.set_compact(True)

    assert window.medallion.maximumHeight() == 64
    assert window.medallion.minimumHeight() == 64


def test_leaving_compact_puts_everything_back() -> None:
    window = MainWindow(Theme.DARK)
    window.show()
    window.set_compact(True)
    window.set_compact(False)

    assert window.is_compact is False
    assert window.readouts_card.isVisible() is True
    assert window.minimumHeight() == MAIN_MINIMUM[1]
    assert window.medallion.maximumHeight() == 180
    window.close()


def test_escape_leaves_compact_and_otherwise_does_nothing() -> None:
    """§9.7.5 gives Escape three jobs — cancel a dialog, close a flyout, exit compact mode. Not
    closing the window: Escape closing a *window* would be surprising in a way the other two are
    not."""
    window = MainWindow(Theme.DARK)
    window.show()

    window.leave_compact()
    assert window.isVisible() is True, "it must not close"

    window.set_compact(True)
    window.leave_compact()
    assert window.is_compact is False
    window.close()


def test_the_accelerators_section_9_7_5_gives_are_bound() -> None:
    """Attached to the window, which is also how §9.7.5's own amendment says the original does it:
    a control in a collapsible area takes its accelerator with it when it collapses — and compact
    mode is exactly a collapse."""
    from PySide6.QtGui import QShortcut

    window = MainWindow(Theme.DARK)
    bound = {shortcut.key().toString() for shortcut in window.findChildren(QShortcut)}

    for keys in ("Ctrl+Shift+M", "F1", "Ctrl+D", "Ctrl+Shift+C", "Esc"):
        assert QKeySequence(keys).toString() in bound, keys


# ---- §9.7.5's F1 -------------------------------------------------------------------------------


def test_the_guide_is_found_in_a_checkout() -> None:
    """It ships inside the package for an installed copy and sits in docs/ in a checkout, and a
    run from either has to work — the second is how it is read while being written."""
    found = guide_path()

    assert found is not None
    assert found.name == "how-to-use.md"


def test_the_guide_carries_a_version_line_at_its_foot() -> None:
    """§9.7.5's amendment: the row said *About*, nothing registered it, and there was no About
    surface — what a person pressing F1 wants is the guide, and the version line an About would
    have carried sits at its foot."""
    text = guide_markdown()

    assert text.rstrip().endswith(version())
    assert "SmartClock Monitor" in text.rsplit("---", 1)[-1]


def test_an_uninstalled_package_says_so_rather_than_guessing() -> None:
    """A guess would be worse than an admission: this line exists so somebody reporting a problem
    can quote it."""
    assert version()  # never empty, never raises


def test_the_window_renders_the_guide_natively() -> None:
    """Markdown into the same text engine every other surface uses, so the window inherits the
    application's theme and fonts. A browser would put the one document explaining this
    application outside it."""
    window = HelpWindow(palette_for(Theme.DARK))

    assert "SmartClock" in window.text
    assert len(window.text) > 200


def test_f1_opens_one_window_and_keeps_it() -> None:
    """Kept rather than rebuilt, so a reader keeps their scroll position when they go back to the
    application and press it again."""
    window = MainWindow(Theme.DARK)
    window.open_help()
    first = window.help_window
    window.open_help()

    assert first is not None
    assert window.help_window is first
    if first is not None:
        first.close()


def test_closing_the_help_does_not_stop_the_receiver_being_polled() -> None:
    """The main window's close is §10.3.1's hide-or-exit decision. An ordinary window must not
    inherit it, or dismissing the help would stop the poll loop."""
    from PySide6.QtGui import QCloseEvent

    help_window = HelpWindow(palette_for(Theme.LIGHT))
    event = QCloseEvent()
    help_window.closeEvent(event)

    assert event.isAccepted() is True
