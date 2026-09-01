"""§10.11's Advanced Console, §10.13's Settings, and the preferences behind them.

The claim worth testing hardest is §10.13's: **opting in changes what is reachable, never what is
permitted.** The console is a picker over the same §8.1 allowlist every other page uses, so enabling
it can add no command the application could not already send.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.commands.blocked import is_blocked
from smartclock_device.commands.scpi_command import ArgumentKind, SafetyTier
from smartclock_device.drivers.nmea import NmeaDriver
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_monitor.services.preferences import DEFAULTS, Preferences, load, save
from smartclock_monitor.themes.tokens import Theme
from smartclock_monitor.views.console_page import ConsolePage
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.views.settings_page import SettingsPage
from test_operational_pages import FakeRunner


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


# ---- Preferences -------------------------------------------------------------------------------


def test_the_advanced_defaults_are_off() -> None:
    """§10.13: an advanced surface is one a user has to go looking for."""
    assert DEFAULTS.advanced_console is False
    assert DEFAULTS.undocumented_queries is False


def test_the_only_preference_defaulting_on_is_gone_with_its_channel() -> None:
    """P1-9's lock alert and §10.3.1's keep-running were the two that defaulted *on*, and both
    needed a notification area to mean anything. D5 (issue #6) removed it, so they went with it —
    a switch that cannot do what it says is worse than an absent one, because the user sets it and
    then believes it."""
    import dataclasses

    on_by_default = {
        field.name for field in dataclasses.fields(Preferences) if field.default is True
    }

    assert on_by_default == set(), f"{on_by_default} default on and nothing drives them"


def test_a_missing_file_reads_as_the_defaults(tmp_path: Path) -> None:
    assert load(tmp_path / "nothing.json") == DEFAULTS


@pytest.mark.parametrize(
    "content",
    ["", "{", "null", "[]", '"a string"', '{"advanced_console": "yes"}', "123"],
)
def test_an_unreadable_file_fails_safe_rather_than_open(tmp_path: Path, content: str) -> None:
    """§10.13: **the default for anything advanced is off**, so a store that failed *open* would
    enable an advanced surface because a disk went wrong. Every failure takes the same branch —
    distinguishing them would produce a diagnostic nobody can act on for a file whose entire
    contents are re-settable from the Settings page."""
    path = tmp_path / "preferences.json"
    path.write_text(content)

    assert load(path).advanced_console is False


def test_a_directory_where_a_file_should_be_reads_as_the_defaults(tmp_path: Path) -> None:
    (tmp_path / "preferences.json").mkdir()

    assert load(tmp_path / "preferences.json") == DEFAULTS


def test_an_unknown_key_does_not_cost_the_known_ones(tmp_path: Path) -> None:
    """A file written by a later build should not cost this one every preference in it."""
    path = tmp_path / "preferences.json"
    path.write_text(json.dumps({"advanced_console": True, "invented_later": True}))

    assert load(path).advanced_console is True


def test_preferences_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "preferences.json"
    wanted = Preferences(advanced_console=True, undocumented_queries=True)

    assert save(wanted, path) is True
    assert load(path) == wanted


def test_a_failed_write_is_reported_only_to_its_caller(tmp_path: Path) -> None:
    """§10.13: a failed write is not reported to the user. The bool exists for this test rather
    than for the interface."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")

    assert save(DEFAULTS, blocker / "sub" / "preferences.json") is False


def test_no_preference_can_change_what_is_permitted() -> None:
    """§10.13: *"No setting on this page may ever change that, and none may relax a §8.3
    confirmation."* Asserted structurally — every field is a bool about visibility, and none names
    a command, a tier or a catalog."""
    from dataclasses import fields

    for entry in fields(Preferences):
        assert entry.type in ("bool", bool), f"{entry.name} is not a plain switch"
        assert "command" not in entry.name
        assert "tier" not in entry.name
        assert "confirm" not in entry.name


def a_console() -> ConsolePage:
    """A console bound to the SmartClock family.

    Bound explicitly, because the picker is **the connected driver's allowlist** rather than the
    catalog: an unbound console shows nothing, which is the honest thing for it to show and is what
    keeps a talker from being offered ninety-eight SCPI mnemonics.
    """
    return ConsolePage(driver=SmartClockDriver(clock=FixedClock(NOW)))


# ---- The console's allowlist -------------------------------------------------------------------


def test_the_picker_offers_the_catalog_and_nothing_else() -> None:
    """§10.11: *"The dropdown is populated from the catalog. Blocked commands are not in the
    catalog and therefore cannot be selected."*"""
    page = a_console()

    offered = {page.command_box.itemData(index) for index in range(page.command_box.count())}
    assert offered == {command.mnemonic for command in catalog.ALL}


def test_nothing_the_picker_offers_is_excluded() -> None:
    """The join between §8.1 and §8.4, asserted at the surface a user actually drives. The catalog
    test asserts it of the data; this asserts it of the control."""
    page = a_console()

    for index in range(page.command_box.count()):
        mnemonic = page.command_box.itemData(index)
        assert is_blocked(mnemonic) is False, f"{mnemonic} is offered and excluded"


def test_enabling_the_console_adds_no_command() -> None:
    """§10.13: *"Opting in changes what is reachable, never what is permitted."* The console's
    universe is the catalog, which is the same set every other page sends from."""
    page = a_console()
    offered = {page.command_box.itemData(index) for index in range(page.command_box.count())}

    assert all(catalog.is_allowed(mnemonic) for mnemonic in offered)


def test_a_tier_c_command_selected_here_still_confirms() -> None:
    """§10.11. A console that skipped the dialog because the user had opted into an advanced
    surface would be treating "I want to see the commands" as "I have read the consequence of
    this one"."""
    page = a_console()
    assert page.select(catalog.CLEAR_DIAGNOSTIC_LOG.mnemonic) is True

    command = page.selected()
    assert command is not None
    assert command.tier is SafetyTier.CONFIRM
    assert command.confirmation


# ---- The console's parameter editors -----------------------------------------------------------


def test_the_preview_shows_exactly_what_will_be_sent() -> None:
    """§10.11's "Will send:" line, so a user can check it against the manual before committing."""
    page = a_console()
    page.select(catalog.SET_HOLDOVER_DURATION_THRESHOLD.mnemonic)
    page._integer.setValue(600)

    assert page.preview_text == ":SYNC:HOLD:DUR:THR 600"


def test_a_parameterless_command_previews_bare() -> None:
    page = a_console()
    page.select(catalog.STATUS_SCREEN.mnemonic)

    assert page.preview_text == ":SYST:STAT?"


def test_the_editor_is_range_bounded_by_the_catalog_entry() -> None:
    """§10.11: parameter entry is typed and range-validated per the command's own spec, so the
    console cannot accept what another page would reject."""
    page = a_console()
    page.select(catalog.SET_ELEVATION_MASK.mnemonic)

    assert page._integer.minimum() == 0
    assert page._integer.maximum() == 90  # the mask's range is 0-90, not 0-89


def test_a_keyword_command_offers_its_keywords_and_nothing_else() -> None:
    page = a_console()
    page.select(catalog.RUN_SELF_TEST.mnemonic)

    offered = [page._keyword.itemText(index) for index in range(page._keyword.count())]
    assert offered == list(catalog.SELF_TEST_SUBSYSTEMS)
    assert page.selected() is not None
    assert page.selected().argument is ArgumentKind.KEYWORD  # type: ignore[union-attr]


def test_the_filter_narrows_the_picker() -> None:
    page = a_console()
    page.filter_box.setText("holdover")

    assert page.command_box.count() < len(catalog.ALL)
    assert page.command_box.count() > 0


def test_send_is_disabled_while_disconnected() -> None:
    page = a_console()
    page.select(catalog.STATUS_SCREEN.mnemonic)
    page.set_command_runner(FakeRunner({}, connected=False))

    assert page.send_button.isEnabled() is False


def test_the_transcript_records_both_directions() -> None:
    page = a_console()
    page.set_command_runner(FakeRunner({catalog.STATUS_SCREEN.mnemonic: "LOCK"}))
    page.select(catalog.STATUS_SCREEN.mnemonic)
    page._send_selected()

    assert "> :SYST:STAT?" in page.transcript
    assert "< LOCK" in page.transcript


def test_the_transcript_can_be_cleared() -> None:
    page = a_console()
    page.set_command_runner(FakeRunner({catalog.STATUS_SCREEN.mnemonic: "LOCK"}))
    page.select(catalog.STATUS_SCREEN.mnemonic)
    page._send_selected()
    page.clear_transcript()

    assert page.transcript == ""


# ---- The Settings page and the destination it adds ---------------------------------------------


def test_the_console_is_absent_until_it_is_switched_on() -> None:
    """§10.13: the switch **adds and removes the destination**; it does not merely hide it, so a
    disabled console is not an item a keyboard user can still reach."""
    window = DetailsWindow(Theme.DARK)

    titles = [page.title for page in window.pages]
    assert ConsolePage.title not in titles
    assert window.navigation.count() == len(titles)

    # And still absent after the defaults are *applied*, not merely before anything has been.
    # Written the first way, this passed against a mutant that added the console unconditionally,
    # because the constructor never calls apply_preferences at all.
    window.apply_preferences(Preferences())

    titles = [page.title for page in window.pages]
    assert ConsolePage.title not in titles
    assert window.navigation.count() == len(titles)


def test_switching_it_on_adds_the_destination() -> None:
    window = DetailsWindow(Theme.DARK)
    window.apply_preferences(Preferences(advanced_console=True))

    titles = [page.title for page in window.pages]
    assert ConsolePage.title in titles
    assert window.navigation.count() == len(titles)


def test_switching_it_off_removes_it_again() -> None:
    window = DetailsWindow(Theme.DARK)
    window.apply_preferences(Preferences(advanced_console=True))
    window.apply_preferences(Preferences(advanced_console=False))

    titles = [page.title for page in window.pages]
    assert ConsolePage.title not in titles
    assert window.navigation.count() == len(titles)


def test_switching_it_off_while_it_is_showing_falls_back_to_the_first_page() -> None:
    """§10.13: *"the pane falls back to the first destination rather than leaving the frame on a
    page it no longer lists."*"""
    window = DetailsWindow(Theme.DARK)
    window.apply_preferences(Preferences(advanced_console=True))
    window.navigation.setCurrentRow(len(window.pages) - 1)

    window.apply_preferences(Preferences(advanced_console=False))

    assert window.navigation.currentRow() == 0


def test_the_settings_switch_drives_it() -> None:
    """End to end: the control the user actually touches."""
    window = DetailsWindow(Theme.DARK)
    settings = window.page_named(SettingsPage.title)
    assert isinstance(settings, SettingsPage)

    settings.console_switch.setChecked(True)
    assert ConsolePage.title in [page.title for page in window.pages]

    settings.console_switch.setChecked(False)
    assert ConsolePage.title not in [page.title for page in window.pages]


def test_a_preference_change_reaches_whoever_is_saving() -> None:
    saved: list[Preferences] = []
    window = DetailsWindow(Theme.DARK)
    window.settings_changed = saved.append

    settings = window.page_named(SettingsPage.title)
    assert isinstance(settings, SettingsPage)
    settings.on_top_switch.setChecked(True)

    assert saved and saved[-1].always_on_top is True


def test_setting_preferences_does_not_report_a_change_nobody_made() -> None:
    """``setChecked`` emits ``toggled``, so a redraw would otherwise report a change and — worse —
    write the defaults over a file that was being read at the time."""
    saved: list[Preferences] = []
    window = DetailsWindow(Theme.DARK)
    window.settings_changed = saved.append

    window.apply_preferences(Preferences(advanced_console=True, always_on_top=True))

    assert saved == []


def test_the_page_says_what_is_not_there() -> None:
    """§9.11's rule against a control that looks like it works and does nothing applies to a
    settings page more than to most. Poll cadences are a *refusal* rather than a gap: §7.3 fixes
    them and §12 gives the poller sole ownership."""
    from PySide6.QtWidgets import QLabel

    settings = SettingsPage()
    text = " ".join(child.text() for child in settings.findChildren(QLabel))

    assert "Poll cadences" in text
    assert "§7.3" in text and "§12" in text
    assert "notification area" in text


# ---- The picker follows the connected family ---------------------------------------------------


def test_an_unbound_console_offers_nothing() -> None:
    """§12's #304 item 2. A console with no receiver has no allowlist to show, and defaulting to
    one family's would be the staleness this closes, arranged in advance."""
    page = ConsolePage()

    assert page.command_box.count() == 0
    assert page.selected() is None


def test_the_picker_is_rebound_when_a_talker_connects() -> None:
    """The bug, made reachable the day a second family was registered: the picker *is* the
    allowlist made visible, so a stale one offers a family ninety-eight commands it has never
    heard of — on a device that would read every one of them as noise in its own stream."""
    page = a_console()
    assert page.command_box.count() == len(catalog.ALL)

    page.set_command_runner(FakeRunner(driver_for=NmeaDriver(clock=FixedClock(NOW))))

    assert page.command_box.count() == 0, "a talker has no allowlist to be on"
    assert page.selected() is None


def test_the_picker_comes_back_when_the_smartclock_returns() -> None:
    """The other direction, which is the half a one-way rebind would leave broken."""
    page = ConsolePage(driver=NmeaDriver(clock=FixedClock(NOW)))
    assert page.command_box.count() == 0

    page.set_command_runner(FakeRunner())

    assert page.command_box.count() == len(catalog.ALL)
    assert page.select(catalog.STATUS_SCREEN.mnemonic) is True


def test_a_disconnected_runner_leaves_the_picker_alone() -> None:
    """Disconnection is not a family change. Emptying the picker every time the link dropped would
    make §7.2's ordinary reconnect look like a receiver swap."""
    page = a_console()

    page.set_command_runner(FakeRunner(connected=False))

    assert page.command_box.count() == len(catalog.ALL)


def test_an_empty_picker_says_why_it_is_empty() -> None:
    """§9.11: **absent means disabled and explained, never hidden.** An empty picker with no words
    is neither — it reads as a page that failed to load."""
    page = ConsolePage()

    assert page.command_box.count() == 0
    assert page._why_empty.isVisible() or page._why_empty.text()
    assert "Not connected" in page._why_empty.text()


def test_a_talker_s_empty_picker_names_the_family() -> None:
    """Two different facts, and a user can act on the difference: nothing is connected, or the
    connected family has no command parser. Naming the family is what §12's capability gate does
    everywhere else, for the same reason."""
    page = ConsolePage(driver=NmeaDriver(clock=FixedClock(NOW)))

    text = page._why_empty.text()
    assert "NMEA 0183 talker" in text
    assert "read only" in text


def test_the_explanation_goes_away_when_a_receiver_arrives() -> None:
    """A control that says why it is empty while being full is worse than one that says nothing.

    Written first as "a console built with a driver explains nothing", which asserted nothing at
    all: that console never had an explanation to clear, so it passed against a version that only
    ever *set* the text and never unset it. It has to be the transition.
    """
    page = ConsolePage()
    assert page._why_empty.text(), "the unbound console should be explaining itself"

    page.set_command_runner(FakeRunner())

    assert page.command_box.count() == len(catalog.ALL)
    assert page._why_empty.text() == "", "the explanation outlived the reason for it"
