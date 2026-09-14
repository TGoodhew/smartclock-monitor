"""§10.9 reads the two condition registers and says what they mean (#110, #112).

Both registers were already documented bit by bit in `status_register_map.py` and already had a
page that shows them raw (§10.10). What was missing was anything that **read** them — so the bench
receiver could report *diagnostic log almost full* for as long as it liked, and the application
would draw a log card with a count on it and no verdict.

The audit against Lady Heather (#98) found the first, `tests/test_registers_against_screen.py`
pinned it against the capture, and this drives the page.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.models import status_register_map as registers
from smartclock_device.models.status_register_map import faults_with_no_health_label
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.themes.tokens import DARK
from smartclock_monitor.views.diagnostics_page import DiagnosticsPage
from test_operational_pages import FakeRunner


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def page_reading(**answers: str) -> DiagnosticsPage:
    """A Diagnostics page that has refreshed against the answers given."""
    page = DiagnosticsPage()
    page.set_command_runner(FakeRunner(answers=dict(answers)))
    page.refresh()
    return page


# ---- The map ----------------------------------------------------------------------------------


def test_two_hardware_faults_have_no_health_label() -> None:
    """#112, stated as data. Twelve bits, six labels, and the two that fall through are the whole
    of the issue: *time interval measurement failed* and *EEPROM write failed*."""
    unlabelled = [bit.bit for bit in registers.HARDWARE.bits if bit.health_label is None]

    assert unlabelled == [10, 11]


def test_every_health_label_the_screen_prints_is_one_a_bit_claims() -> None:
    """The pairing runs both ways or it is not a pairing.

    The six are the labels the corpus has, in the order the receiver prints them
    (`tests/fixtures/smartclock/locked-log-almost-full-13sep2026`). A label here that no bit names
    would mean the map had drifted from the screen — which is the failure this direction catches
    and the other cannot.
    """
    claimed = {bit.health_label for bit in registers.HARDWARE.bits if bit.health_label}

    assert claimed == {"Self Test", "Int Pwr", "Oven Pwr", "OCXO", "EFC", "GPS Rcv"}


def test_a_healthy_register_reports_nothing() -> None:
    assert faults_with_no_health_label(0) == ()


def test_a_fault_the_health_monitor_covers_is_left_to_it() -> None:
    """Bits 6 and 7 are the EFC pair, and the health block has an `EFC` label. Reporting them here
    as well would say the same thing twice in two places, which is how a user learns to read one
    of them and ignore the other."""
    assert faults_with_no_health_label((1 << 6) | (1 << 7)) == ()


def test_the_two_with_nowhere_to_go_are_reported() -> None:
    reported = faults_with_no_health_label((1 << 10) | (1 << 11))

    assert [bit.bit for bit in reported] == [10, 11]
    assert "EEPROM" in reported[1].meaning


def test_a_bit_the_map_cannot_name_is_reported_rather_than_dropped() -> None:
    """A firmware setting bit 13 is saying something this port has no word for. *That* is the
    report — an unnameable fault is still a fault, and silence would be the one answer that is
    certainly wrong."""
    reported = faults_with_no_health_label(1 << 13)

    assert len(reported) == 1
    assert "13" in reported[0].meaning
    assert reported[0].is_fault is True


# ---- The page ----------------------------------------------------------------------------------


def test_the_log_card_says_the_log_is_almost_full() -> None:
    """#110, as the bench receiver actually answers: `+90` and 222 entries."""
    page = page_reading(
        **{
            catalog.OPERATION_CONDITION.mnemonic: "+90",
            catalog.LOG_COUNT.mnemonic: "+222",
            catalog.HARDWARE_CONDITION.mnemonic: "+0",
        }
    )

    severity, text = page.log_condition
    assert severity is Severity.CAUTION
    assert "almost full" in text.lower()
    assert "clear" in text.lower()


def test_the_log_card_says_so_when_there_is_room() -> None:
    """The other half, and the reason the pill is always present: *not read* and *read and fine*
    are different claims about the receiver, and a pill that appeared only on the fault would make
    them the same one."""
    page = page_reading(
        **{
            catalog.OPERATION_CONDITION.mnemonic: "+26",
            catalog.HARDWARE_CONDITION.mnemonic: "+0",
        }
    )

    severity, text = page.log_condition
    assert severity is Severity.SUCCESS
    assert text == "Log has room"


def test_an_unread_register_is_not_a_healthy_one() -> None:
    page = page_reading()

    assert page.log_condition == (Severity.NEUTRAL, "Log condition not read")
    assert [text for _severity, text in page.hardware_conditions] == ["Not read"]


def test_the_hardware_card_reports_a_fault_the_health_monitor_cannot(
    request: pytest.FixtureRequest,
) -> None:
    """#112's whole point: this receiver prints `HEALTH MONITOR ... [ OK ]` and §10.4 draws six
    green ticks, because the screen has no label for a failed EEPROM write."""
    page = page_reading(
        **{
            catalog.HARDWARE_CONDITION.mnemonic: str(1 << 11),
            catalog.OPERATION_CONDITION.mnemonic: "+26",
        }
    )

    conditions = page.hardware_conditions
    assert len(conditions) == 1
    severity, text = conditions[0]
    assert severity is Severity.CRITICAL
    assert "EEPROM" in text


def test_the_hardware_card_says_so_when_there_is_nothing_to_add() -> None:
    page = page_reading(
        **{
            catalog.HARDWARE_CONDITION.mnemonic: "+0",
            catalog.OPERATION_CONDITION.mnemonic: "+26",
        }
    )

    assert page.hardware_conditions == [
        (Severity.SUCCESS, "Nothing the health monitor cannot show")
    ]


def test_a_family_with_no_registers_is_told_so_rather_than_left_blank() -> None:
    """§9.11. A talker has no status registers and never will, which is a different sentence from
    "not read yet" and has to stay a different sentence."""
    page = DiagnosticsPage()
    page.set_command_runner(FakeRunner(driver_for=NmeaDriver(clock=FixedClock(NOW))))

    _severity, text = page.log_condition
    assert "no command for this" in text
    assert [t for _s, t in page.hardware_conditions] == [text]


def test_the_pills_follow_a_theme_change() -> None:
    """Custom widgets take their colours from a palette object rather than from QSS, so a theme
    change has to reach each one. This page had no override at all."""
    page = page_reading(
        **{
            catalog.HARDWARE_CONDITION.mnemonic: "+0",
            catalog.OPERATION_CONDITION.mnemonic: "+26",
        }
    )

    page.set_palette_tokens(DARK)

    assert page.palette_of_condition_pills() == [DARK] * 2


# ---- §10.9's Front panel card (#118) -------------------------------------------------------------


def test_the_lamp_switch_shows_what_the_receiver_says() -> None:
    page = page_reading(
        **{
            catalog.ACTIVE_LAMP.mnemonic: "1",
            catalog.HARDWARE_CONDITION.mnemonic: "+0",
            catalog.OPERATION_CONDITION.mnemonic: "+26",
        }
    )

    assert page.lamp_switch.isChecked() is True


def test_clicking_the_switch_writes_the_lamp() -> None:
    """Tier S, so no confirmation: §8.2's ruling is that the command changes no receiver behaviour
    and a confirmation would be asking permission to change nothing."""
    page = DiagnosticsPage()
    runner = FakeRunner(
        answers={catalog.ACTIVE_LAMP.mnemonic: "0", catalog.SET_ACTIVE_LAMP.mnemonic: ""}
    )
    page.set_command_runner(runner)

    page.lamp_switch.click()

    assert (catalog.SET_ACTIVE_LAMP.mnemonic, "ON") in runner.sent
    assert page.lamp_switch.isChecked() is True


def test_a_write_the_receiver_refuses_puts_the_switch_back() -> None:
    """§9.11: a Safe setter gets no success bar, so the switch's own position is the feedback — and
    a switch that stayed where a user put it while the lamp did not move would be the one lie this
    card can tell."""
    page = DiagnosticsPage()
    page.set_command_runner(FakeRunner(driver_for=SmartClockDriver(clock=FixedClock(NOW))))

    page.lamp_switch.click()

    assert page.lamp_switch.isChecked() is False
    assert "back as it was" in page.lamp_note_text


def test_a_refresh_does_not_write_the_lamp_back_at_itself() -> None:
    """The click handler must not fire when the page sets the switch from a reading. Unguarded, a
    page open on a locked receiver writes the lamp once a second for ever — and each write takes
    the receiver about a second."""
    page = DiagnosticsPage()
    runner = FakeRunner(answers={catalog.ACTIVE_LAMP.mnemonic: "1"})
    page.set_command_runner(runner)
    page.refresh()

    assert not [
        mnemonic for mnemonic, _ in runner.sent if mnemonic == catalog.SET_ACTIVE_LAMP.mnemonic
    ]


def test_a_family_with_no_lamp_keeps_the_switch_and_explains() -> None:
    page = DiagnosticsPage()
    page.set_command_runner(FakeRunner(driver_for=NmeaDriver(clock=FixedClock(NOW))))

    assert page.lamp_switch.isEnabled() is False
    assert "no command for this" in page.lamp_note_text
