"""§10.5's Manage dialog, the exclusion list, and the elevation mask editor."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from conftest import NOW
from smartclock_device.commands import catalog
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.views.manage_satellites import ManageSatellitesDialog, parse_exclusions
from smartclock_monitor.views.pages import SatellitesPage
from test_operational_pages import DEAF, FakeRunner


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def reading(mask: int | None = 10) -> Reading:
    return Reading(
        status=ReceiverStatus(
            captured_at=NOW, mode=SmartClockMode.LOCKED, elevation_mask_degrees=mask
        ),
        captured_at=NOW,
    )


# ---- Reading the exclusion list ----------------------------------------------------------------


def test_an_unreadable_answer_is_not_an_empty_list() -> None:
    """§11.1: what could not be read says nothing. A satellite wrongly marked excluded sends
    someone looking for a setting they never made — and applying an empty list read from a failed
    query would *create* that setting."""
    assert parse_exclusions(None) == (frozenset(), False)
    assert parse_exclusions("") == (frozenset(), False)


def test_a_list_is_read() -> None:
    prns, known = parse_exclusions("+4,+17,+31")

    assert prns == frozenset({4, 17, 31})
    assert known is True


def test_a_token_this_build_cannot_read_does_not_discard_the_rest() -> None:
    """One odd field turning into "nothing is excluded" would be the same defect as an unreadable
    answer being taken as an empty list."""
    prns, known = parse_exclusions("+4,rubbish,+17")

    assert prns == frozenset({4, 17})
    assert known is True


def test_a_prn_outside_the_constellation_is_dropped() -> None:
    prns, _ = parse_exclusions("+4,+99,+0")

    assert prns == frozenset({4})


# ---- What the dialog would send ----------------------------------------------------------------


def test_changing_nothing_sends_nothing() -> None:
    """A dialog that sent the whole list every time would put a tier C command on the wire for a
    user who opened it, looked, and closed it."""
    dialog = ManageSatellitesDialog(frozenset({4, 17}))

    assert dialog.commands() == []


def test_excluding_one_more_clears_then_sets() -> None:
    """The receiver holds a list, so sending only the additions would leave a satellite excluded
    that the user has just un-ticked."""
    dialog = ManageSatellitesDialog(frozenset({4}))
    box = dialog.box_for(17)
    assert box is not None
    box.setChecked(True)

    commands = dialog.commands()

    assert [command.mnemonic for command, _ in commands] == [
        ":GPS:SAT:TRAC:IGN:NONE",
        ":GPS:SAT:TRAC:IGN",
    ]
    assert commands[-1][1] == [4, 17]


def test_clearing_every_box_uses_the_command_with_its_own_sentence() -> None:
    """§8.3's amendment, at the surface it was made for. :IGN:NONE shared the PRN form's sentence
    — "Exclude the selected satellites from tracking?" — for a command that *clears* the exclusion
    list, so a user confirming it would reasonably believe they were excluding satellites."""
    dialog = ManageSatellitesDialog(frozenset({4, 17}))
    for prn in (4, 17):
        box = dialog.box_for(prn)
        assert box is not None
        box.setChecked(False)

    commands = dialog.commands()

    assert len(commands) == 1
    assert commands[0][0] is catalog.CLEAR_EXCLUSIONS
    assert "Clear the exclusion list" in (catalog.CLEAR_EXCLUSIONS.confirmation or "")
    assert "Exclude the selected" not in (catalog.CLEAR_EXCLUSIONS.confirmation or "")


def test_excluding_everything_uses_the_strong_variant() -> None:
    dialog = ManageSatellitesDialog(frozenset())
    dialog._choose_bulk(True)

    commands = dialog.commands()

    assert len(commands) == 1
    assert commands[0][0] is catalog.EXCLUDE_ALL_SATELLITES
    assert catalog.EXCLUDE_ALL_SATELLITES.requires_acknowledgement is True
    assert "lose lock" in (catalog.EXCLUDE_ALL_SATELLITES.confirmation or "")


def test_the_bulk_buttons_only_set_the_boxes() -> None:
    """So the dialog has one send path and one confirmation, and a user who presses *Exclude all*
    and then thinks better of it can press Cancel — which they could not if the button sent."""
    dialog = ManageSatellitesDialog(frozenset())
    dialog._choose_bulk(True)

    assert dialog.excluded == frozenset(range(catalog.FIRST_PRN, catalog.LAST_PRN + 1))
    # Nothing has been sent: `commands()` describes what Apply *would* do.
    assert dialog.result() == 0


def test_an_unread_list_disables_everything_and_says_why() -> None:
    """Applying from a list that could not be read would set a list rather than change one."""
    dialog = ManageSatellitesDialog(frozenset(), known=False)

    assert dialog.apply_button.isEnabled() is False
    assert dialog.commands() == []
    box = dialog.box_for(4)
    assert box is not None and box.isEnabled() is False


def test_every_prn_has_a_box() -> None:
    dialog = ManageSatellitesDialog(frozenset())

    assert all(dialog.box_for(prn) is not None for prn in range(1, 33))
    assert dialog.box_for(33) is None


def test_a_prn_list_renders_comma_joined() -> None:
    """§10.11: *"the values comma-joined"*, the form the 58503A programming guide gives."""
    assert catalog.EXCLUDE_SATELLITES.rendered([4, 17, 31]) == ":GPS:SAT:TRAC:IGN 4,17,31"


def test_a_list_with_one_bad_element_is_refused_entirely() -> None:
    """Any element, not most of them: a partially-valid list sent with the bad entries dropped
    would do something the user did not ask for, and that something would be a subset of a
    destructive operation."""
    assert catalog.EXCLUDE_SATELLITES.rendered([4, 99]) is None
    assert catalog.EXCLUDE_SATELLITES.rendered([]) is None
    assert catalog.EXCLUDE_SATELLITES.rendered("4,17") is None


# ---- The mask editor ---------------------------------------------------------------------------


def test_the_mask_opens_on_the_receiver_s_own_value() -> None:
    """§10.5: it costs no wire time — the status screen already carries it. It was a hard-coded 10
    until #320, and that it happened to match the unit it was developed against made it worse
    rather than better: a default that is right by luck is a default nobody checks."""
    page = SatellitesPage()
    page.show_reading(reading(mask=25))

    assert page._mask.value() == 25


def test_a_sweep_does_not_undo_what_the_user_typed() -> None:
    """One lands every second. Decided by comparing against the last value the page wrote, for the
    same reason the holdover limit does it that way."""
    page = SatellitesPage()
    page.show_reading(reading(mask=10))

    page._mask.setValue(25)
    page.show_reading(reading(mask=10))

    assert page._mask.value() == 25


def test_a_missing_mask_leaves_the_editor_alone() -> None:
    page = SatellitesPage()
    page.show_reading(reading(mask=15))
    page.show_reading(reading(mask=None))

    assert page._mask.value() == 15


def test_the_exclusion_list_is_not_read_on_the_sweep() -> None:
    """§10.5: *"read on navigation, on reconnect, and after the Manage dialog — never on the
    sweep."* A second query on the 1 s cadence to catch an event that happens twice a year would
    be paying wire time for nothing."""
    runner = FakeRunner({catalog.EXCLUDED_SATELLITES.mnemonic: "+4,+17"})
    page = SatellitesPage()
    page.set_command_runner(runner)
    assert page.excluded == frozenset({4, 17})

    runner.sent.clear()
    for _ in range(10):
        page.show_reading(reading())

    assert runner.sent == []


def test_a_failed_read_leaves_nothing_marked_excluded() -> None:
    runner = FakeRunner({catalog.EXCLUDED_SATELLITES.mnemonic: DEAF})
    page = SatellitesPage()
    page.set_command_runner(runner)

    assert page.excluded == frozenset()
    assert page._exclusions_known is False


def test_the_controls_are_disabled_while_disconnected() -> None:
    page = SatellitesPage()
    page.set_command_runner(FakeRunner({}, connected=False))

    assert page._apply_mask.isEnabled() is False
    assert page._manage.isEnabled() is False
