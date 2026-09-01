"""§10.14's Time & Leap Seconds page, and the query-ordering rule behind its leap card."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from conftest import NOW
from smartclock_device.commands import catalog, leap
from smartclock_device.models.receiver_status import (
    ReceiverStatus,
    SmartClockMode,
    TimeScale,
)
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.themes.severity import Severity
from smartclock_monitor.views.pages import DASH
from smartclock_monitor.views.time_page import DisplayZone, TimePage
from test_operational_pages import DEAF, FakeRunner


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


#: The bench receiver's own numbers: it reports 2007 and the parser corrects to 2026.
REPORTED = datetime(2007, 1, 16, 0, 30, 43, tzinfo=UTC)
CORRECTED = REPORTED + timedelta(weeks=1024)


def reading(**kwargs: object) -> Reading:
    defaults: dict[str, object] = {
        "captured_at": NOW,
        "mode": SmartClockMode.LOCKED,
        "device_date_time": REPORTED,
        "corrected_date_time": CORRECTED,
        "week_rollover_epochs": 1,
        "time_scale": TimeScale.UTC,
    }
    defaults.update(kwargs)
    return Reading(status=ReceiverStatus(**defaults), captured_at=NOW)  # type: ignore[arg-type]


# ---- The ordering rule -------------------------------------------------------------------------


def test_the_state_is_read_before_the_date_and_direction() -> None:
    """§10.14: with ``STAT? = 0`` there is no announced leap second to have a date, and the
    receiver **rejects** the question rather than returning a null — both answer ``E-230``. A page
    that asked all four on arrival would put two errors in the error queue every time it opened."""
    assert catalog.LEAP_STATE in leap.FIRST
    assert catalog.LEAP_DATE not in leap.FIRST
    assert catalog.LEAP_DURATION not in leap.FIRST


def test_nothing_follows_when_no_leap_is_announced() -> None:
    assert leap.follow_up(False) == ()


def test_the_date_and_direction_follow_an_announcement() -> None:
    assert leap.follow_up(True) == (catalog.LEAP_DATE, catalog.LEAP_DURATION)


def test_an_unreadable_state_asks_nothing() -> None:
    """An unreadable state is not permission to guess: the two follow-ups are precisely the
    queries that fail when the guess is wrong."""
    assert leap.follow_up(None) == ()


def test_the_page_does_not_ask_for_a_date_that_cannot_exist() -> None:
    """The rule, end to end. This is the assertion that would catch someone "simplifying" the page
    by reading all four at once."""
    runner = FakeRunner(
        {
            catalog.LEAP_ACCUMULATED.mnemonic: "+18",
            catalog.LEAP_STATE.mnemonic: "0",
            catalog.TIME_CODE_FORMAT.mnemonic: "F2",
        }
    )
    page = TimePage()
    page.set_command_runner(runner)

    asked = {mnemonic for mnemonic, _ in runner.sent}
    assert catalog.LEAP_STATE.mnemonic in asked
    assert catalog.LEAP_DATE.mnemonic not in asked
    assert catalog.LEAP_DURATION.mnemonic not in asked


def test_the_page_does_ask_when_one_is_announced() -> None:
    runner = FakeRunner(
        {
            catalog.LEAP_ACCUMULATED.mnemonic: "+18",
            catalog.LEAP_STATE.mnemonic: "1",
            catalog.LEAP_DATE.mnemonic: "+2026,+12,+31",
            catalog.LEAP_DURATION.mnemonic: "+1",
            catalog.TIME_CODE_FORMAT.mnemonic: "F2",
        }
    )
    page = TimePage()
    page.set_command_runner(runner)

    asked = {mnemonic for mnemonic, _ in runner.sent}
    assert catalog.LEAP_DATE.mnemonic in asked
    assert page.leap_pill.severity is Severity.INFO
    assert page.leap_fields.value_of("Direction") == "Adds a second"


# ---- The clock ---------------------------------------------------------------------------------


def test_the_receiver_s_own_date_is_shown_beside_the_corrected_one() -> None:
    """§7.4: reported and explained, never silently substituted. A user who sees a date two
    decades out with no explanation reasonably concludes the hardware has failed — and one who
    never sees it cannot tell a corrected receiver from a correct one."""
    page = TimePage()
    page.show_reading(reading())

    assert "2007" in page.clock_fields.value_of("Reported by receiver")
    assert "2026" in page.zone_text


def test_the_zone_is_always_named() -> None:
    """§11.2 and #95: an unlabelled wall-clock time cannot be compared to anything."""
    page = TimePage()
    page.show_reading(reading())

    assert page.zone_text.strip()
    page.zone_box.setCurrentIndex(1)  # UTC
    assert "UTC" in page.zone_text


def test_the_time_scale_is_stated() -> None:
    """UTC and GPS differ by the accumulated leap seconds, so a reading that does not say which it
    is on cannot be compared to anything either."""
    page = TimePage()
    page.show_reading(reading())

    assert page.clock_fields.value_of("Time scale") == "UTC"


def test_switching_zone_changes_the_rendered_time_but_not_the_instant() -> None:
    page = TimePage()
    page.show_reading(reading())

    page.zone_box.setCurrentIndex(1)
    in_utc = page.clock_text
    page.zone_box.setCurrentIndex(0)
    local = page.clock_text

    assert in_utc == CORRECTED.strftime("%H:%M:%S")
    assert local == CORRECTED.astimezone().strftime("%H:%M:%S")


def test_a_missing_corrected_time_renders_a_dash() -> None:
    """§11.1. Not the reported one in its place — that would be presenting an uncorrected date as
    though it were the answer."""
    page = TimePage()
    page.show_reading(reading(corrected_date_time=None))

    assert page.clock_text == DASH


# ---- The rollover and power-up cards -----------------------------------------------------------


def test_the_rollover_card_names_the_correction() -> None:
    page = TimePage()
    page.show_reading(reading(week_rollover_epochs=1))

    assert "1 epoch" in page.rollover_pill.accessibleName()


def test_an_uncorrected_receiver_says_so() -> None:
    page = TimePage()
    page.show_reading(reading(week_rollover_epochs=0, device_date_time=CORRECTED))

    assert page.rollover_pill.severity is Severity.SUCCESS


def test_the_power_up_card_appears_only_while_the_time_is_provisional() -> None:
    """#245, §11.2: shown only while the clock row carries the provisional marker."""
    page = TimePage()

    page.show_reading(reading(device_time_is_provisional=True))
    assert page.power_up_card_is_visible is True

    page.show_reading(reading(device_time_is_provisional=False))
    assert page.power_up_card_is_visible is False


# ---- The leap card -----------------------------------------------------------------------------


def test_the_accumulated_offset_is_shown_unconditionally() -> None:
    """§10.14: it is what anyone comparing GPS time to UTC needs, it is always available, and it is
    the one figure that earns the section title on a day when nothing is announced."""
    runner = FakeRunner(
        {
            catalog.LEAP_ACCUMULATED.mnemonic: "+18",
            catalog.LEAP_STATE.mnemonic: "0",
            catalog.TIME_CODE_FORMAT.mnemonic: "F2",
        }
    )
    page = TimePage()
    page.set_command_runner(runner)

    assert page.leap_fields.value_of("GPS − UTC") == "+18 s accumulated"
    assert page.leap_pill.severity is Severity.SUCCESS


def test_an_unread_leap_card_is_not_reported_as_none_announced() -> None:
    """ "None announced" is an answer. Before the read there is no answer, and saying there is
    would be the same defect as reporting an unread register bit as clear."""
    page = TimePage()

    assert page.leap_pill.severity is Severity.NEUTRAL


# ---- The time code -----------------------------------------------------------------------------


def test_the_format_is_read_rather_than_assumed() -> None:
    """§10.14: ``z3801.pdf`` states T1 is the default and the bench Z3805A answers F2. Anything
    written against the documented default would mis-parse every message this receiver sends."""
    runner = FakeRunner(
        {
            catalog.LEAP_ACCUMULATED.mnemonic: "+18",
            catalog.LEAP_STATE.mnemonic: "0",
            catalog.TIME_CODE_FORMAT.mnemonic: "F2",
        }
    )
    page = TimePage()
    page.set_command_runner(runner)

    assert "T2" in page.time_code.value_of("Format")
    assert "23 characters" in page.time_code.value_of("Message length")


def test_the_card_names_both_spellings() -> None:
    """The command's parameter is F1/F2 while the header the message carries is T1/T2, and a user
    comparing this page against a raw time code has to recognise those as the same thing."""
    runner = FakeRunner(
        {
            catalog.LEAP_ACCUMULATED.mnemonic: "+18",
            catalog.LEAP_STATE.mnemonic: "0",
            catalog.TIME_CODE_FORMAT.mnemonic: "F1",
        }
    )
    page = TimePage()
    page.set_command_runner(runner)

    text = page.time_code.value_of("Format")
    assert "F1" in text and "T1" in text


def test_an_unread_format_is_a_dash_rather_than_the_documented_default() -> None:
    """The whole reason the format is read. Falling back to T1 would be writing against exactly
    the assumption that mis-parses this receiver."""
    runner = FakeRunner(
        {
            catalog.LEAP_ACCUMULATED.mnemonic: "+18",
            catalog.LEAP_STATE.mnemonic: "0",
            catalog.TIME_CODE_FORMAT.mnemonic: DEAF,
        }
    )
    page = TimePage()
    page.set_command_runner(runner)

    assert page.time_code.value_of("Format") == DASH


def test_the_page_never_asks_for_the_time_code_itself() -> None:
    """§10.14: ``:PTIM:TCOD?`` answers on the receiver's own 1 Hz cadence, so a request lands in
    the next emission slot and blocks for up to a second — a cost a read-only page has no reason
    to pay, charged again on every refresh."""
    runner = FakeRunner(
        {
            catalog.LEAP_ACCUMULATED.mnemonic: "+18",
            catalog.LEAP_STATE.mnemonic: "0",
            catalog.TIME_CODE_FORMAT.mnemonic: "F2",
        }
    )
    page = TimePage()
    page.set_command_runner(runner)

    assert ":PTIM:TCOD?" not in {mnemonic for mnemonic, _ in runner.sent}


def test_the_page_sends_nothing_that_changes_the_receiver() -> None:
    """§10.14.1's question 2: the page is read-only, the time code card included. ``:PTIM:TZONe``
    would set the offset the *receiver* reports in, which is a different thing from the zone this
    application displays in — and it is tier C."""
    runner = FakeRunner(
        {
            catalog.LEAP_ACCUMULATED.mnemonic: "+18",
            catalog.LEAP_STATE.mnemonic: "1",
            catalog.LEAP_DATE.mnemonic: "+2026,+12,+31",
            catalog.LEAP_DURATION.mnemonic: "+1",
            catalog.TIME_CODE_FORMAT.mnemonic: "F2",
        }
    )
    page = TimePage()
    page.set_command_runner(runner)
    page.show_reading(reading())
    page.zone_box.setCurrentIndex(1)

    for mnemonic, _ in runner.sent:
        command = catalog.find(mnemonic)
        assert command is not None
        assert command.is_query, f"{mnemonic} is not a query"
        assert command.needs_confirmation is False


def test_the_display_zone_is_a_preference_not_a_device_setting() -> None:
    """§10.14.1's question 3. One preference, two places to set it — a duplicated control, not
    duplicated state."""
    assert set(DisplayZone) == {DisplayZone.LOCAL, DisplayZone.UTC}
