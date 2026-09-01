"""§10.3.1: closing the window.

**Close means close.** §10.3.1's design hides the window on close so the trend keeps filling while
it is out of the way, and both halves of that rested on a notification icon to come back to. D5
(issue #6) settled that this port ships none, and §10.3.1's own argument then decides the rest: a
hidden window with no icon "cannot be reached by any means the user has", so hiding would not be an
inconvenience but a loss of the application.

So the window closes, the poll stops, and the Settings *Exit* button stays — §10.3.1 wants the
application quittable from its own surface, and that argument survives the removal of the surface
it was written against.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from smartclock_monitor.services.preferences import Preferences
from smartclock_monitor.themes.tokens import Theme
from smartclock_monitor.views.main_window import MainWindow
from smartclock_monitor.views.settings_page import SettingsPage


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


# ---- Closing ------------------------------------------------------------------------------------


def test_closing_the_window_exits() -> None:
    """The whole of §10.3.1 for this port. There is nowhere to hide to, and a window that vanished
    with no icon behind it would be the worst available outcome — which is the case §10.3.1 named
    and the one D5 made permanent."""
    window = MainWindow(Theme.DARK)

    event = QCloseEvent()
    window.closeEvent(event)

    assert event.isAccepted() is True, "the close was swallowed; the window would have hidden"


def test_no_preference_can_turn_that_into_hiding() -> None:
    """The switch is gone, not defaulted off. A preference that could re-enable hiding would be a
    preference that strands the user, since the icon it hid to does not exist."""
    import dataclasses

    names = {field.name for field in dataclasses.fields(Preferences)}

    assert "keep_running_when_closed" not in names
    assert "start_in_notification_area" not in names
    assert "alert_on_lock_loss" not in names, "P1-9's switch outlived the channel it drove"


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


# ---- Always on top (P1-6) ----------------------------------------------------------------------


def test_always_on_top_is_off_by_default() -> None:
    """A window that outranks everything else is a decision about the *desktop* rather than about
    this application, and §9.1's user has a spectrum analyser to look at too."""
    assert Preferences().always_on_top is False
    assert MainWindow(Theme.DARK).is_always_on_top is False


def test_the_preference_raises_and_lowers_the_window() -> None:
    window = MainWindow(Theme.DARK)

    window.set_always_on_top(True)
    assert window.is_always_on_top is True

    window.set_always_on_top(False)
    assert window.is_always_on_top is False


def test_a_visible_window_stays_visible_across_the_change() -> None:
    """Changing this flag makes Qt drop a visible window — it vanishes and does not come back on
    its own, which reads as a crash."""
    window = MainWindow(Theme.DARK)
    window.show()

    window.set_always_on_top(True)

    assert window.isVisible() is True
    window.close()


def test_a_hidden_window_is_not_brought_back() -> None:
    """§10.3.1 hides it on close deliberately, and a preference change is not a request to bring
    it back — which re-showing unconditionally would make it."""
    window = MainWindow(Theme.DARK)
    window.hide()

    window.set_always_on_top(True)

    assert window.isVisible() is False


def test_setting_it_to_what_it_already_is_does_nothing() -> None:
    """Qt drops the window on a flag change, so a no-op change would still flicker it."""
    window = MainWindow(Theme.DARK)
    window.show()
    window.set_always_on_top(False)

    assert window.isVisible() is True
    window.close()


def test_the_settings_switch_drives_it() -> None:
    page = SettingsPage()
    page.on_top_switch.setChecked(True)

    assert page.preferences.always_on_top is True
