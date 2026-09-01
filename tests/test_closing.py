"""§10.3.1: closing the window, and staying alive.

**Hiding a window is only safe if there is a way back to it.** §10.3.1 makes hiding the default so
the trend keeps filling while the window is out of the way — but its own argument for the Settings
*Exit* button is that an application whose only exit is an invisible icon is quittable in principle
and by Task Manager in practice. On a desktop with **no tray at all** that goes further: a hidden
window with no icon cannot be reached by any means the user has.

This session has no tray (WSLg reports none), so the fallback is the path these run against — which
is the one that matters, because it is the one that could lose somebody their application.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QLabel

from smartclock_monitor.platform import tray
from smartclock_monitor.services.preferences import Preferences
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.tokens import Theme, palette_for
from smartclock_monitor.views.main_window import MainWindow
from smartclock_monitor.views.settings_page import SettingsPage


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


# ---- With no notification area -----------------------------------------------------------------


def test_no_tray_here_which_is_the_case_worth_testing() -> None:
    """Asked at the moment it matters rather than inferred from the platform: WSLg reports no tray
    on a system that calls itself Linux, and a check on ``sys.platform`` would have got it wrong."""
    assert tray.is_available() is False


def test_attaching_a_tray_says_whether_it_worked() -> None:
    window = MainWindow(Theme.DARK)

    assert window.attach_tray() is False
    assert window.tray is None
    assert window.can_keep_running is False


def test_closing_exits_when_there_is_nowhere_to_hide_to() -> None:
    """The preference is on by default, and honouring it here would leave the user with a running
    process, no window, and no icon — a loss of the application rather than an inconvenience."""
    window = MainWindow(Theme.DARK)
    window.attach_tray()
    assert window.preferences.keep_running_when_closed is True

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted() is True, "it must close"


def test_the_settings_switch_says_why_it_cannot_work() -> None:
    """§9.11's rule about a control that looks like it works, applied to a switch. The reason is on
    screen rather than left for the user to discover by closing the window."""
    page = SettingsPage()
    page.set_can_keep_running(False)

    assert page.keep_running_switch.isEnabled() is False

    text = " ".join(child.text() for child in page.findChildren(QLabel))
    assert "no notification area" in text
    assert "no way to get it back" in text


def test_the_switch_is_live_where_a_tray_exists() -> None:
    page = SettingsPage()
    page.set_can_keep_running(True)

    assert page.keep_running_switch.isEnabled() is True


# ---- The exit route ----------------------------------------------------------------------------


def test_the_application_is_quittable_from_its_own_surface() -> None:
    """§10.3.1: *"not only from the notification area."* There the argument is that Windows does
    not promote a newly registered icon; here it is stronger, because a desktop may have none."""
    quit_calls: list[int] = []
    page = SettingsPage()
    page.on_exit = lambda: quit_calls.append(1)

    page.exit_button.click()

    assert quit_calls == [1]


def test_exit_is_marked_destructive() -> None:
    assert SettingsPage().exit_button.property("role") == "destructive"


def test_a_page_does_not_decide_to_quit() -> None:
    """Quitting is not something a page decides. With nobody listening it does nothing, rather
    than reaching for the application object itself."""
    page = SettingsPage()
    page.on_exit = None

    page.exit_button.click()  # must not raise, must not quit


# ---- Turning the preference off ----------------------------------------------------------------


def test_switching_keep_running_off_makes_close_exit() -> None:
    window = MainWindow(Theme.DARK)
    window.apply_theme(Theme.DARK)
    window._preferences = Preferences(keep_running_when_closed=False)

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted() is True


# ---- The icon's vocabulary ---------------------------------------------------------------------


@pytest.mark.parametrize("severity", list(Severity))
def test_the_icon_draws_the_same_shapes_as_everything_else(severity: Severity) -> None:
    """§9.4.3.1: both shell surfaces draw from one rasteriser, so a hexagon cannot come to mean
    different things in two places. The shape comes from what SeverityPill draws with."""
    icon = tray.render_icon(severity, palette_for(Theme.DARK))

    assert not icon.isNull()
    assert icon.availableSizes() != []

    # Drawn, not blank: a null-coloured brush would have produced an icon that exists and shows
    # nothing, which is what the type: ignore in this function was hiding.
    drawn = icon.pixmap(32, 32).toImage()
    assert any(drawn.pixelColor(x, y).alpha() > 0 for x in range(0, 32, 4) for y in range(0, 32, 4))
