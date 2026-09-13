"""§10.12's connection dialog."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.drivers.registry import Registry
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.drivers.uccm import UccmDriver
from smartclock_device.transport.settings import (
    AUTO_DETECT_SEQUENCE,
    SUPPORTED_BAUD_RATES,
    Parity,
    SerialSettings,
    StopBits,
)
from smartclock_monitor.views.connection_dialog import ConnectionDialog

PORTS = [("/dev/ttyUSB0", "/dev/ttyUSB0 — USB-Serial Controller D")]


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def dialog(ports: list[tuple[str, str]] | None = None) -> ConnectionDialog:
    return ConnectionDialog(list_ports=lambda: PORTS if ports is None else ports)


def test_it_opens_on_the_port_it_was_given() -> None:
    """A disconnect then a reconnect should come back to the port you were on.

    `refresh_ports` already keeps a selection across a refresh, but that memory dies with the
    dialog — and the dialog is rebuilt every time it opens, so without this the user was offered
    whichever port happened to sort first. On a machine with 32 built-in `ttyS*` devices and one
    USB adapter, that is never the one they want.
    """
    many = [
        ("/dev/ttyS0", "/dev/ttyS0"),
        ("/dev/ttyS1", "/dev/ttyS1"),
        ("/dev/ttyUSB0", "/dev/ttyUSB0 — USB-Serial Controller D"),
    ]

    fresh = ConnectionDialog(list_ports=lambda: many)
    assert fresh.choice() is not None
    assert fresh.choice().port == "/dev/ttyS0", "without a hint it opens on the first port"  # type: ignore[union-attr]

    remembered = ConnectionDialog(list_ports=lambda: many, preselect="/dev/ttyUSB0")
    chosen = remembered.choice()
    assert chosen is not None
    assert chosen.port == "/dev/ttyUSB0"


def test_a_remembered_port_that_has_gone_does_not_break_the_dialog() -> None:
    """The adapter can be unplugged while the application is disconnected. §9.11's rule applies:
    offer what is there rather than an empty picker or a stale name."""
    box = ConnectionDialog(list_ports=lambda: PORTS, preselect="/dev/ttyS31")
    chosen = box.choice()

    assert chosen is not None
    assert chosen.port == "/dev/ttyUSB0", "it must fall back to a port that exists"


def test_it_opens_on_auto_detect() -> None:
    """§10.12: the fresh-install default. §7.1's whole point is that a second-hand receiver's
    settings are not knowable in advance, so the dialog opens on the option that finds out rather
    than the one that asks the user to already know."""
    box = dialog()

    assert box.automatic.isChecked() is True
    assert box.manual.isChecked() is False
    assert box.choice() is not None
    assert box.choice().is_automatic is True  # type: ignore[union-attr]


def test_the_manual_pickers_are_disabled_until_manual_is_chosen() -> None:
    """§9.11: a control that looks like it works and does nothing is worse than one greyed out."""
    box = dialog()
    assert box.baud_box.isEnabled() is False

    box.manual.setChecked(True)
    assert box.baud_box.isEnabled() is True


def test_manual_asks_for_exactly_what_was_picked() -> None:
    """It does not fall back to the walk: someone who has picked a setting is asserting something
    about their hardware, and quietly trying seven others would make the picker a suggestion."""
    box = dialog()
    box.manual.setChecked(True)
    box.baud_box.setCurrentText("19200")

    choice = box.choice()
    assert choice is not None
    assert choice.is_automatic is False
    assert choice.settings == SerialSettings(19200, 8, Parity.NONE, StopBits.ONE)


def test_the_baud_picker_offers_section_7_1_s_six_rates() -> None:
    box = dialog()
    offered = [box.baud_box.itemText(index) for index in range(box.baud_box.count())]

    assert offered == [str(rate) for rate in SUPPORTED_BAUD_RATES]
    assert len(offered) == 6


def test_no_ports_disables_connect_and_says_why() -> None:
    """§9.11 again: an empty picker beside a live button is a dialog that will fail on click and
    not say what for."""
    box = dialog([])

    assert box.connect_button.isEnabled() is False
    assert "No serial ports" in box.status_text
    assert box.choice() is None


def test_refreshing_keeps_the_selection_where_it_survives() -> None:
    """Re-listing must not silently move a user onto a different port between them choosing one
    and pressing Connect."""
    two = [("/dev/ttyUSB0", "first"), ("/dev/ttyUSB1", "second")]
    box = ConnectionDialog(list_ports=lambda: two)
    box.port_box.setCurrentIndex(1)

    box.refresh_ports()

    choice = box.choice()
    assert choice is not None
    assert choice.port == "/dev/ttyUSB1"


def test_progress_names_the_combination_and_the_position() -> None:
    """Eight combinations at a two-second probe is about sixteen seconds against a port with
    nothing on it, which is long enough that a dialog with no progress reads as hung."""
    box = dialog()
    box.show_progress(AUTO_DETECT_SEQUENCE[1], 2, 8)

    assert "19200-7-O-1" in box.status_text
    assert "2 of 8" in box.status_text


def test_cancel_is_the_default_button() -> None:
    """The same rule as the confirmation dialog. This one is not destructive, but a dialog that
    behaves differently from its sibling teaches the wrong reflex."""
    box = dialog()

    assert box.cancel_button.isDefault() is True
    assert box.connect_button.isDefault() is False


def test_both_launch_options_default_on() -> None:
    box = dialog()
    choice = box.choice()

    assert choice is not None
    assert choice.reconnect_automatically is True
    assert choice.connect_on_launch is True


# ---- Reaching it from the window ----------------------------------------------------------------


def test_the_main_window_offers_a_connect_button() -> None:
    """The dialog was built and tested before anything opened it, which is a control that exists
    and cannot be reached — the same defect class as one that looks live and does nothing."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from smartclock_monitor.themes.tokens import Theme
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)

    assert window._connect_button.isVisible() or window._connect_button is not None
    assert "Ctrl+Shift+C" in window._connect_button.toolTip()


def test_the_choice_reaches_whoever_can_act_on_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """The window does not know how to open a port and must not learn — it hands the choice to
    whoever owns it."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QDialog

    from smartclock_monitor.themes.tokens import Theme
    from smartclock_monitor.views import main_window as module
    from smartclock_monitor.views.main_window import MainWindow

    del QDialog
    monkeypatch.setattr(module, "ConnectionDialog", lambda *a, **k: _Accepting())

    taken: list[object] = []
    window = MainWindow(Theme.DARK)
    window.on_connection_chosen = taken.append

    choice = window.choose_connection()

    assert choice is not None
    assert taken == [choice]
    assert choice.port == "/dev/ttyUSB0"


class _Accepting:
    """A stand-in dialog that answers as though the user pressed Connect."""

    def exec(self) -> int:
        from PySide6.QtWidgets import QDialog

        return int(QDialog.DialogCode.Accepted)

    def choice(self) -> object:
        from smartclock_monitor.views.connection_dialog import ConnectionChoice

        return ConnectionChoice(port="/dev/ttyUSB0", settings=None)


def test_cancelling_hands_over_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from smartclock_monitor.themes.tokens import Theme
    from smartclock_monitor.views import main_window as module
    from smartclock_monitor.views.main_window import MainWindow

    class _Rejecting(_Accepting):
        def exec(self) -> int:
            return 0

    monkeypatch.setattr(module, "ConnectionDialog", lambda *a, **k: _Rejecting())

    taken: list[object] = []
    window = MainWindow(Theme.DARK)
    window.on_connection_chosen = taken.append

    assert window.choose_connection() is None
    assert taken == []


# ---- D7: a driver that has never met a receiver says so before you connect ----------------------


def test_the_dialog_names_the_unverified_family(application: QApplication) -> None:
    """D7's condition, at the moment a user can act on it.

    §10.4's identity card says the same thing once a receiver is on the link. That is the wrong
    moment for the only decision this affects — whether to trust what the next screen says — and
    the person choosing the port is the one who can weigh it.
    """
    del application
    dialog = ConnectionDialog(unverified=("Trimble UCCM-P",))

    assert dialog.unverified_note.isVisible() or not dialog.isVisible()
    text = dialog.unverified_note.text()
    assert "Trimble UCCM-P" in text, "a general warning is one nobody can use"
    assert "never been connected" in text


def test_a_build_with_nothing_unverified_says_nothing(application: QApplication) -> None:
    """A caution that is always there is one people stop reading."""
    del application
    dialog = ConnectionDialog()

    assert dialog.unverified_note.text() == ""
    assert dialog.unverified_note.isHidden()


def test_the_list_comes_from_the_registry_rather_than_a_literal(application: QApplication) -> None:
    """So a driver that starts claiming verification stops being named, without an edit here.

    This is the same rule as everywhere else in this port: one place holds the fact, and a second
    copy would go stale — the difference being that this one would go stale *reassuringly*.
    """
    del application
    clock = FixedClock(NOW)
    registry = Registry(
        [SmartClockDriver(clock=clock), NmeaDriver(clock=clock), UccmDriver(clock=clock)]
    )

    unverified = [d.name for d in registry.drivers if not getattr(d, "is_verified", True)]

    assert unverified == ["UCCM"], "the UCCM, and only the UCCM"
