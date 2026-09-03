"""§9.6.2's compact mode and §9.7.5's F1 guide."""

from __future__ import annotations

import os
from importlib import metadata
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import Theme, palette_for
from smartclock_monitor.views.help_window import (
    HelpWindow,
    guide_markdown,
    guide_path,
    version,
)
from smartclock_monitor.views.main_window import (
    COMPACT_MINIMUM,
    MAIN_MINIMUM,
    MainWindow,
    version_label,
)


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
    # Measured rather than pinned, as the ordinary layout's floors are (#20, #21, #30): §9.6.2's
    # 144 is where the compact layout fits inside it, and it needed 217 with the header still in.
    assert window.minimumHeight() >= COMPACT_MINIMUM[1]
    window.close()


def test_the_readouts_collapse_when_the_window_is_too_short_for_them() -> None:
    """§9.6.2's *collapsed, not clipped*, driven by size rather than by a keystroke (#21).

    `set_compact` did every collapse the section asks for and was reachable only from
    `Ctrl+Shift+M` — no `resizeEvent`, nothing consulting the window's height — so the ordinary
    layout was never collapsed at any size. Forced below what it needed, Qt squeezed instead: the
    three state pills drew over each other and the medallion lost the shape and the count G1
    measures this window on.
    """
    window = MainWindow(Theme.DARK)
    window.show()
    QApplication.processEvents()
    assert window.readouts_card.isVisible() is True, "the readouts belong on a tall window"

    window.resize(window.width(), window.minimumHeight())
    QApplication.processEvents()

    assert window.readouts_card.isVisible() is False, (
        "the readout card is still in the layout at the minimum height, so something is being "
        "squeezed rather than collapsed"
    )
    window.close()


def test_the_count_and_the_lock_state_survive_the_smallest_draggable_window() -> None:
    """The two things §9.6.2 keeps, and the two G1 is measured on: *mode and tracked-satellite
    count legible at 2 m*. They are the first things lost when a layout is squeezed, and they must
    be the last.

    The floor is what makes this hold rather than the collapse alone — below it there is nothing
    further §9.6.2 permits to collapse, so a window that could still be dragged smaller would be
    back to overlapping text.
    """
    window = MainWindow(Theme.DARK)
    window.show()
    QApplication.processEvents()

    assert window.medallion.isVisible() is True, "the satellite count's home"
    assert window.mode_pill.isVisible() is True, "the lock state"

    # **Measured against the layout the floor actually holds, not by resizing to it.** A resize is
    # a request, and the offscreen platform this runs under does not honour it — asking the window
    # its height after one gives the height before. So the collapsed layout is put on screen
    # directly, which is the state the floor exists to accommodate, and asked what it needs.
    central = window.centralWidget()
    assert central is not None
    layout = central.layout()
    assert layout is not None

    window.readouts_card.setVisible(False)
    layout.invalidate()
    layout.activate()
    QApplication.processEvents()
    needed = central.minimumSizeHint().height() + window.statusBar().sizeHint().height()

    assert window.minimumHeight() >= needed, (
        f"the window may be dragged to {window.minimumHeight()} px tall but the collapsed layout "
        f"needs {needed} px — the difference comes out of whatever will compress"
    )
    window.close()


def test_no_header_control_is_clipped_at_the_minimum_width() -> None:
    """§9.6.2's *collapsed, not clipped* applied to the row §10.3 actually has.

    That section's rule names the **footer**, because in WinZ3805A these buttons live in one and it
    collapses at the minimum. This port has no footer and the buttons are in the header, where
    nothing collapses them — so at §9.6.2's literal 380 px the row was 35 px over its space and Qt
    clipped it: `Connect…` lost its first character, `Retry now` its last, and the theme picker
    rendered as `Dar` (#20). A clipped button is still focusable and still hit-testable while
    unreadable, which is what A11Y-1 and A11Y-6 forbid.

    The floor is measured rather than pinned, so this asserts the property and not a number.

    **Asserted as arithmetic rather than by resizing and reading widths back.** Qt reports a
    minimum for the row that is *below* the sum of its controls' preferred sizes — 367 px against
    the 415 they need — which is precisely why it clips rather than refusing to shrink. So a test
    that resized to the minimum and compared `width()` to `sizeHint()` passed while the row was
    visibly cut off, which is worse than no test. The check is therefore that the enforced floor is
    at least the width at which every control gets its preferred size, computed here from the row
    itself so a control added to it is counted.
    """
    window = MainWindow(Theme.DARK)
    window.show()
    QApplication.processEvents()

    controls = window.header_controls
    for control in controls:
        control.ensurePolished()
    needed = (
        sum(control.sizeHint().width() for control in controls)
        + Spacing.SMALL * (len(controls) - 1)
        + Spacing.CARD_PADDING * 2
    )

    assert window.minimumWidth() >= needed, (
        f"The window may be {window.minimumWidth()} px wide, but the button row needs {needed} px "
        f"— it will be clipped: "
        + ", ".join(f"{c.accessibleName()!r} {c.sizeHint().width()}px" for c in controls)
    )
    window.close()


def test_the_minimum_width_stays_inside_g1s_box() -> None:
    """G1 accepts the main window at **420 by 260 px or smaller** — it is a glanceable window
    meant to be left open on a second monitor, so its box is an upper bound rather than a target.

    The floor above is derived from font metrics, which is the only honest way to size it, and the
    risk that buys is a face wide enough to push the row past G1's width on some desktop. The two
    typefaces are bundled precisely so metrics are pinned rather than inherited, so this should
    hold everywhere; if it ever fails it is a real G1 regression and not a flaky measurement.
    """
    window = MainWindow(Theme.DARK)
    window.show()
    assert window.minimumWidth() <= 420, (
        f"The header needs {window.minimumWidth()} px, which puts the window outside G1's box."
    )
    window.close()


def test_compact_takes_the_button_row_out_of_the_layout() -> None:
    """§9.6.2's compact row hides *the footer*, and in WinZ3805A the buttons are in one.

    This port has no footer and they are in the header, so the header is what that instruction
    means here. Left visible the row needed 415 px in a 380 px window and clipped `Connect…` to
    "onnect…" — #20's defect returning through a door #20 did not close (#30).
    """
    window = MainWindow(Theme.DARK)
    window.show()
    assert window.connect_button.isVisible() is True

    window.set_compact(True)

    for control in window.header_controls:
        assert control.isVisible() is False, (
            f"{control.accessibleName()!r} is still in the compact layout, which has no room for it"
        )

    window.set_compact(False)
    assert window.connect_button.isVisible() is True, "leaving compact must put the row back"
    window.close()


def test_compact_fits_what_it_still_shows() -> None:
    """The window `Ctrl+Shift+M` produces must not be smaller than its own contents.

    `set_compact` asserted §9.6.2's literals — `setMinimumSize(380, 144)` — against a layout that
    needed 217 px, so the state pills drew over each other and the medallion flattened out of
    shape, exactly as the ordinary layout did before #21. It also *lowered* the width floor
    `_size_minimum_width` had raised, discarding #20's fix on a keystroke.
    """
    window = MainWindow(Theme.DARK)
    window.show()
    QApplication.processEvents()

    window.set_compact(True)
    QApplication.processEvents()

    central = window.centralWidget()
    assert central is not None
    layout = central.layout()
    assert layout is not None
    layout.invalidate()
    layout.activate()
    needed = central.minimumSizeHint().height() + window.statusBar().sizeHint().height()

    assert window.minimumHeight() >= needed, (
        f"compact may be {window.minimumHeight()} px tall and its layout needs {needed} px"
    )
    assert window.minimumWidth() >= COMPACT_MINIMUM[0]
    window.close()


def test_the_medallion_shrinks_to_64() -> None:
    """§9.6.2's compact row: a 64 px medallion **with the satellite count in its centre**. §9.10.2
    draws the ring uniform at that size rather than as a sparkline, because sixty marks of
    differing length make a circle that small read as misshapen."""
    window = MainWindow(Theme.DARK)
    window.set_compact(True)

    assert window.medallion.maximumHeight() == 64
    assert window.medallion.minimumHeight() == 64


def test_the_compact_layout_fits_the_figure_section_9_6_2_sets() -> None:
    """A minimum the content does not fit in is not a minimum.

    §9.6.2 spends its 144 px on a title bar, a page margin, §9.10.2's 64 px medallion and a margin,
    and says the compact layout "is already down to a medallion and one line of text" — so anything
    else still in the layout there is over budget by construction. The button row and the status
    bar were, by 48 px, and `set_compact` puts the window at exactly this size: entering compact
    mode clipped the medallion to an arc and drew the mode text across it, every time.

    Measured rather than eyeballed, because that is the only form of this that fails when somebody
    adds a second row to the header.
    """
    window = MainWindow(Theme.DARK)
    window.show()
    window.set_compact(True)

    content = window.centralWidget()
    assert content is not None
    assert content.sizeHint().height() <= COMPACT_MINIMUM[1]
    assert content.sizeHint().width() <= COMPACT_MINIMUM[0]
    window.close()


def test_leaving_compact_puts_everything_back() -> None:
    window = MainWindow(Theme.DARK)
    window.show()
    window.set_compact(True)
    window.set_compact(False)

    assert window.is_compact is False
    assert window.readouts_card.isVisible() is True
    # The floor is measured, as the width's is (#20, #21): §9.6.2's 240 is where the reduced
    # layout fits inside it, and in this port's layout it does not. Never below the spec figure.
    assert window.minimumHeight() >= MAIN_MINIMUM[1]
    assert window.medallion.maximumHeight() == 180
    # Everything compact collapsed comes back with it, not only the readout row.
    bar = window.statusBar()
    assert bar is not None and bar.isVisible() is True
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


def test_the_connect_button_says_which_half_it_is() -> None:
    """§9.7.5 gives `Ctrl+Shift+C` as *Connect / disconnect*, and only the connect half existed
    (#28). The button said *Connect…* while connected and opened the port picker on a live link.

    **All three strings, not just the label.** A screen-reader user hearing "Choose a port and
    connect" from a button that disconnects is worse off than a sighted one, who at least sees the
    word — so the accessible name is the half that would otherwise rot unnoticed.
    """
    window = MainWindow(Theme.DARK)
    window.show()

    button = window.connect_button
    assert button.text() == "Connect…"
    assert "connect" in button.accessibleName().lower()
    assert "disconnect" not in button.accessibleName().lower()

    window.set_command_runner(object())  # type: ignore[arg-type]  # standing in for a live session

    assert button.text() == "Disconnect"
    assert "disconnect" in button.accessibleName().lower()
    assert "close the link" in button.toolTip().lower(), button.toolTip()

    window.set_command_runner(None)

    assert button.text() == "Connect…"
    assert "disconnect" not in button.accessibleName().lower()
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


def test_the_status_bar_leads_with_the_release() -> None:
    """#23: a screenshot of the window should be enough to say which build produced it.

    Every message carries it, not only the connected one — the states somebody photographs are
    usually the ones that went wrong, so stamping the success line alone would leave the reports
    that matter unlabelled.
    """
    window = MainWindow(Theme.DARK)
    window.show()
    window.set_connection_text("Connected to Z3805A — /dev/ttyUSB0 @ 9600-8-N-1")

    shown = window.statusBar().currentMessage()
    assert shown.startswith(version_label()), shown
    assert "Connected to Z3805A" in shown
    window.close()


def test_the_release_shown_is_the_installed_one_and_not_a_literal() -> None:
    """The gate #23 asks for, and the reason there is no "bump this every build" note anywhere.

    §6.3 forbids hard-coding the application's *name* because "a rename that has to be made in nine
    places gets made in eight". A version is that argument with a number: it changes every release,
    so a copy goes stale silently while still looking authoritative. This asserts the label is the
    metadata rather than a string that happens to match it today — which is what would fail if
    somebody ever pinned it.
    """
    installed = metadata.version("smartclock-monitor")

    assert version() == installed
    assert version_label() == f"v{installed}"


def test_a_frozen_build_can_still_read_its_own_version() -> None:
    """`importlib.metadata` needs the package's `.dist-info`, and PyInstaller does not carry it
    unless asked. Without this the derivation above resolves to NOT_INSTALLED in every bundle —
    the one distribution channel where the user has no other way to find the number, and silently,
    because that answer is legitimate everywhere else.

    Asserted against the spec file rather than by building: a PyInstaller run needs a toolchain
    that is deliberately not in the `dev` extra, and the defect is the missing declaration.
    """
    spec = (
        Path(__file__).resolve().parent.parent / "build" / "smartclock-monitor.spec"
    ).read_text()

    assert "copy_metadata" in spec, "the bundle will report its version as NOT_INSTALLED"
    assert 'copy_metadata("smartclock-monitor")' in spec


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
