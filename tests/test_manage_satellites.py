"""§10.5's Manage dialog, the exclusion list, and the elevation mask editor."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from conftest import NOW
from smartclock_device.commands import catalog
from smartclock_device.commands.position_argument import PositionArgument
from smartclock_device.commands.scpi_command import SafetyTier
from smartclock_device.drivers.capability import Capability
from smartclock_device.models.position import SurveySuspendedReason
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_device.models.satellite import FIRST_PRN, LAST_PRN
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.views.manage_satellites import ManageSatellitesDialog, parse_exclusions
from smartclock_monitor.views.pages import PositionPage, SatellitesPage
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

    # Capabilities, not mnemonics: the dialog says what it wants done and the runner asks the
    # connected family how to spell it (#13).
    assert [wanted for wanted, _ in commands] == [
        Capability.CLEAR_EXCLUSIONS,
        Capability.EXCLUDE_SATELLITES,
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
    assert commands[0][0] is Capability.CLEAR_EXCLUSIONS
    assert "Clear the exclusion list" in (catalog.CLEAR_EXCLUSIONS.confirmation or "")
    assert "Exclude the selected" not in (catalog.CLEAR_EXCLUSIONS.confirmation or "")


def test_excluding_everything_uses_the_strong_variant() -> None:
    dialog = ManageSatellitesDialog(frozenset())
    dialog._choose_bulk(True)

    commands = dialog.commands()

    assert len(commands) == 1
    assert commands[0][0] is Capability.EXCLUDE_ALL_SATELLITES
    assert catalog.EXCLUDE_ALL_SATELLITES.requires_acknowledgement is True
    assert "lose lock" in (catalog.EXCLUDE_ALL_SATELLITES.confirmation or "")


def test_the_bulk_buttons_only_set_the_boxes() -> None:
    """So the dialog has one send path and one confirmation, and a user who presses *Exclude all*
    and then thinks better of it can press Cancel — which they could not if the button sent."""
    dialog = ManageSatellitesDialog(frozenset())
    dialog._choose_bulk(True)

    assert dialog.excluded == frozenset(range(FIRST_PRN, LAST_PRN + 1))
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


# ---- §10.6's survey controls -------------------------------------------------------------------


def _position_page(**answers: object) -> PositionPage:
    page = PositionPage()
    page.set_command_runner(FakeRunner(dict(answers)))
    return page


def survey_reading(percent: float | None = None, suspended: str = "NONE") -> Reading:

    return Reading(
        status=ReceiverStatus(
            captured_at=NOW,
            mode=SmartClockMode.LOCKED,
            survey_percent_complete=percent,
            survey_suspended_reason=SurveySuspendedReason[suspended],
        ),
        captured_at=NOW,
    )


def test_no_remaining_time_is_ever_shown() -> None:
    """§10.6 as amended by #316, and confirmed 30 Aug: the receiver reports a percentage and
    nothing else — there is no rate on the wire — so a remaining time computed from a single
    percentage would be a guess presented as a measurement."""
    page = _position_page()
    page.show_reading(survey_reading(percent=57.3))

    text = page._survey_note.text().lower()
    assert "remaining" not in text
    assert "min" not in text
    assert "57.3" in text


def test_the_suspension_reason_is_the_receiver_s_own() -> None:
    """What the line carries instead — which the receiver does report (§11.3)."""
    page = _position_page()
    page.show_reading(survey_reading(percent=12.0, suspended="TOO_FEW_SATELLITES"))

    assert "Suspended" in page._survey_note.text()
    assert "satellites" in page._survey_note.text()


def test_the_progress_bar_hides_when_nothing_is_surveying() -> None:
    page = _position_page()
    page.show_reading(survey_reading(percent=None))

    assert page._progress.isVisible() is False


def test_a_minus_300_carries_the_reason_and_the_route() -> None:
    """#229: a receiver already holding a position refuses Start survey with −300, and no command
    in §8.2 or in any of the three family manuals releases the hold. The route is
    survey-on-power-up, which is the checkbox on this card."""
    from smartclock_monitor.services.session import CommandOutcome

    page = _position_page()
    page._report(
        (
            CommandOutcome(
                command=catalog.START_SURVEY,
                transaction=None,
                error='-300,"Device-specific error"',
            ),
        )
    )

    text = page._survey_note.text()
    assert "-300" in text
    assert "already holding a position" in text
    assert "power-up" in text


def test_any_other_error_gets_the_receiver_s_own_words_and_nothing_added() -> None:
    """§10.6 attaches the advice to −300 **only**: it is device-specific by definition and the
    receiver has not said why, so offering this explanation for the wrong failure would send
    someone to power-cycle an instrument over a loose cable."""
    from smartclock_monitor.services.session import CommandOutcome

    page = _position_page()
    page._report(
        (
            CommandOutcome(
                command=catalog.START_SURVEY,
                transaction=None,
                error='-113,"Undefined header"',
            ),
        )
    )

    text = page._survey_note.text()
    assert text == '-113,"Undefined header"'
    assert "power-up" not in text


def test_manual_position_entry_sends_the_format_the_receiver_wants() -> None:
    """§10.6, issue #12. Held out of the catalog until the wire format was **looked up** rather
    than guessed — a tier C command that changes what every timing solution is computed from.

    The format is the sibling implementation's, which built and tested it: nine parts joined with
    commas. Pinned as an exact string, because that is the whole of what was uncertain.
    """
    argument = PositionArgument("N", 47, 31, 18.822, "W", 122, 12, 22.152, 38.0)

    assert catalog.is_allowed(":GPS:POSition") is True
    assert catalog.SET_POSITION.rendered(argument) == (
        ":GPS:POSition N,47,31,18.822,W,122,12,22.152,38.00"
    )


def test_the_numbers_are_written_in_the_c_locale() -> None:
    """A comma decimal separator would split a field in a comma-separated argument, turning one
    position into ten of nonsense. Python's format mini-language is locale-independent, which is
    what makes this safe — the C# original has to say InvariantCulture at every call site."""
    rendered = PositionArgument("S", 33, 51, 35.9, "E", 151, 12, 40.0, 19.5).rendered()

    assert rendered == "S,33,51,35.9,E,151,12,40,19.50"
    assert rendered.count(",") == 8, "a decimal comma would add a field"


def test_height_always_carries_two_decimals_and_seconds_at_most_three() -> None:
    """The sibling's "0.00" and "0.###". Three on seconds because §10.6's range stops at 59.999
    and a fourth would be precision the field cannot express."""
    argument = PositionArgument("N", 0, 0, 1.23456, "E", 0, 0, 0.0, 7.0)

    assert argument.rendered() == "N,0,0,1.235,E,0,0,0,7.00"


@pytest.mark.parametrize(
    "argument",
    [
        PositionArgument("X", 0, 0, 0.0, "E", 0, 0, 0.0, 0.0),
        PositionArgument("N", 0, 0, 0.0, "N", 0, 0, 0.0, 0.0),
        PositionArgument("N", 91, 0, 0.0, "E", 0, 0, 0.0, 0.0),
        PositionArgument("N", 0, 60, 0.0, "E", 0, 0, 0.0, 0.0),
        PositionArgument("N", 0, 0, 60.0, "E", 0, 0, 0.0, 0.0),
        PositionArgument("N", 0, 0, 0.0, "E", 181, 0, 0.0, 0.0),
        PositionArgument("N", 0, 0, 0.0, "E", 0, 0, 0.0, 18001.0),
        PositionArgument("N", 0, 0, 0.0, "E", 0, 0, 0.0, -1001.0),
    ],
)
def test_a_part_outside_the_receivers_own_table_is_refused(argument: PositionArgument) -> None:
    """§10.6's ranges are the 58503A manual's own. Refused rather than raised, for the reason
    §11.1 gives on the way in: a value out of range is somebody typing one."""
    assert argument.rendered() is None
    assert argument.is_valid() is False
    assert catalog.SET_POSITION.rendered(argument) is None


def test_the_command_refuses_anything_that_is_not_a_position() -> None:
    """The argument is a type, not a string. A caller handing over a number would otherwise have
    it formatted as a decimal and sent."""
    for wrong in (None, 47.5, "N,47,31,18.822,W,122,12,22.152,38.00", (47, 31)):
        assert catalog.SET_POSITION.rendered(wrong) is None


def test_it_confirms_and_is_acknowledged() -> None:
    """§8.3. It cancels a survey and changes every timing solution afterwards, and the sibling's
    own confirmation says an incorrect position degrades timing accuracy."""
    assert catalog.SET_POSITION.tier is SafetyTier.CONFIRM
    assert catalog.SET_POSITION.requires_acknowledgement is True
    assert "degrades timing accuracy" in (catalog.SET_POSITION.confirmation or "")


def test_the_spoken_form_is_words_rather_than_the_wire_format() -> None:
    """§8.3 wants the consequence in words, and a comma-separated string is not words."""
    spoken = PositionArgument("N", 47, 31, 18.822, "W", 122, 12, 22.152, 38.0).spoken()

    assert spoken == "N 47° 31′ 18.822″, W 122° 12′ 22.152″, 38.00 m"
    assert "," in spoken and ",122," not in spoken


def test_the_survey_commands_all_confirm() -> None:
    """P0-12.

    Each starts, stops or reconfigures a two-hour operation the receiver uses for every timing
    solution afterwards."""
    for command in (
        catalog.START_SURVEY,
        catalog.ADOPT_SURVEYED_POSITION,
        catalog.RESTORE_LAST_POSITION,
        catalog.SET_SURVEY_ON_POWER_UP,
    ):
        assert command.needs_confirmation is True, command.mnemonic
        assert command.confirmation


def test_declining_the_power_up_change_puts_the_box_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A box that stayed moved would show a setting the receiver does not have."""
    monkeypatch.setattr("smartclock_monitor.views.pages.ask", lambda *a, **k: False)

    runner = FakeRunner({catalog.SURVEY_ON_POWER_UP.mnemonic: "OFF"})
    page = PositionPage()
    page.set_command_runner(runner)
    assert page._on_power_up.isChecked() is False

    page._on_power_up.setChecked(True)
    runner.sent.clear()
    page._send_power_up()

    assert page._on_power_up.isChecked() is False
    assert runner.sent == []


def test_an_unreadable_power_up_answer_leaves_the_box_alone() -> None:
    """§11.1. Clearing it would show a setting the user never made."""
    page = _position_page(**{catalog.SURVEY_ON_POWER_UP.mnemonic: DEAF})

    assert page._on_power_up.isChecked() is False  # its initial state, untouched


# ---- §10.5's Save image ------------------------------------------------------------------------


def sky_reading(tracked: int = 2, predicted: int = 3, mask: int | None = 10) -> Reading:
    from smartclock_device.models.satellite import PredictedSatellite, TrackedSatellite

    return Reading(
        status=ReceiverStatus(
            captured_at=NOW,
            mode=SmartClockMode.LOCKED,
            elevation_mask_degrees=mask,
            tracked=tuple(
                TrackedSatellite(
                    prn=prn, elevation_degrees=40, azimuth_degrees=90, signal_strength=40
                )
                for prn in range(1, tracked + 1)
            ),
            not_tracked=tuple(
                PredictedSatellite(
                    prn=prn, elevation_degrees=20, azimuth_degrees=180, attempting_to_track=False
                )
                for prn in range(20, 20 + predicted)
            ),
        ),
        captured_at=NOW,
    )


def test_the_caption_carries_what_the_screen_does_not() -> None:
    """§10.5's second normative property: product name, capture time **in UTC**, the two counts,
    and the elevation mask in force. The mask is not decoration — the same sky under a 10° mask
    and a 25° mask produces two legitimate plots with different satellites missing, so a record
    omitting it cannot be compared with anything."""
    page = SatellitesPage()
    page.show_reading(sky_reading(tracked=2, predicted=3, mask=25))

    title, detail = page.caption().lines()

    assert "SmartClock Monitor" in title
    assert "UTC" in detail
    assert "2 tracked" in detail and "3 predicted" in detail
    assert "25" in detail


def test_an_empty_sky_is_not_offered() -> None:
    """§10.5: an empty export is a picture of three rings, which reads as a working antenna seeing
    nothing rather than as a receiver that is not connected."""
    page = SatellitesPage()
    page.show_reading(sky_reading(tracked=0, predicted=0))

    assert page.caption().is_worth_saving is False
    assert page._save_image.isEnabled() is False
    assert page.save_image("/tmp/never-written.png") is None


def test_a_populated_sky_is() -> None:
    page = SatellitesPage()
    page.show_reading(sky_reading())

    assert page.caption().is_worth_saving is True
    assert page._save_image.isEnabled() is True


def test_an_unreported_mask_says_so_rather_than_guessing() -> None:
    """A record that silently omitted the mask would be one nobody could compare, and one that
    invented a value would be worse."""
    page = SatellitesPage()
    page.show_reading(sky_reading(mask=None))

    _title, detail = page.caption().lines()
    assert "not reported" in detail


def test_the_image_is_written_and_is_taller_than_the_plot(tmp_path: Path) -> None:
    """The caption band is added beneath the grabbed card — the capture is the live element, not a
    second renderer, because a separate drawing path is free to disagree with the one the user
    reviewed."""
    from PySide6.QtGui import QImage

    page = SatellitesPage()
    page.resize(400, 300)
    page.show_reading(sky_reading())

    target = tmp_path / "sky.png"
    assert page.save_image(str(target)) == str(target)

    written = QImage(str(target))
    assert not written.isNull()
    assert written.height() > page._plot.height()


# ---- §10.6's manual entry, on the page ----------------------------------------------------------


def test_filling_from_the_receiver_round_trips_a_position() -> None:
    """A small correction should be a small edit, not nine fields retyped.

    Round-tripped rather than spot-checked: the page holds degrees, minutes and seconds and the
    status screen is parsed to signed decimal degrees, so this is the conversion in both
    directions and it is the part people get wrong.
    """
    from smartclock_device.models.position import GeoPosition

    page = _position_page()
    page.show_reading(
        Reading(
            status=ReceiverStatus(
                captured_at=NOW,
                position=GeoPosition(
                    latitude_degrees=47.521839, longitude_degrees=-122.206153, height_metres=38.0
                ),
            ),
            captured_at=NOW,
        )
    )

    page._fill_from_receiver.click()
    argument = page._position_argument()

    assert argument.latitude_hemisphere == "N"
    assert (argument.latitude_degrees, argument.latitude_minutes) == (47, 31)
    assert argument.latitude_seconds == pytest.approx(18.62, abs=0.01)
    assert argument.longitude_hemisphere == "W", "a negative longitude is West"
    assert (argument.longitude_degrees, argument.longitude_minutes) == (122, 12)
    assert argument.longitude_seconds == pytest.approx(22.15, abs=0.01)
    assert argument.height_metres == pytest.approx(38.0)
    assert argument.is_valid()


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (47.521839, -122.206153),
        (-33.859972, 151.211111),
        (0.0, 0.0),
        (89.999444, -179.999444),
        (12.3456789, 98.7654321),
        (-0.000278, 0.000278),
    ],
)
def test_filling_from_the_receiver_preserves_the_position(
    latitude: float, longitude: float
) -> None:
    """The round trip has to come back where it started.

    Decimal degrees in — the form the status screen is parsed to — and degrees, minutes, seconds
    and a hemisphere out, which is what the receiver prints and what §10.6's table bounds. This
    converts back and compares, because the conversion is the part people get wrong and every way
    of getting it wrong still produces a plausible-looking position: a dropped sign puts you in
    the wrong hemisphere, swapped degrees and minutes puts you sixty times off, and neither is
    visible in the field values themselves.

    Tolerance is a thousandth of a second of arc, the finest the field can express — about 30 mm.
    """
    from smartclock_device.models.position import GeoPosition

    page = _position_page()
    page.show_reading(
        Reading(
            status=ReceiverStatus(
                captured_at=NOW,
                position=GeoPosition(
                    latitude_degrees=latitude, longitude_degrees=longitude, height_metres=38.0
                ),
            ),
            captured_at=NOW,
        )
    )
    page._fill_from_receiver.click()

    argument = page._position_argument()
    assert argument.is_valid(), f"came back as {argument.spoken()}, which is unsendable"

    def decimal(hemisphere: str, degrees: int, minutes: int, seconds: float) -> float:
        size = degrees + minutes / 60.0 + seconds / 3600.0
        return -size if hemisphere in ("S", "W") else size

    back_latitude = decimal(
        argument.latitude_hemisphere,
        argument.latitude_degrees,
        argument.latitude_minutes,
        argument.latitude_seconds,
    )
    back_longitude = decimal(
        argument.longitude_hemisphere,
        argument.longitude_degrees,
        argument.longitude_minutes,
        argument.longitude_seconds,
    )

    arcsecond = 1.0 / 3600.0
    assert back_latitude == pytest.approx(latitude, abs=arcsecond / 1000.0)
    assert back_longitude == pytest.approx(longitude, abs=arcsecond / 1000.0)


def test_filling_says_so_when_nothing_has_been_read() -> None:
    """§9.11: a control that does nothing has to say why. Before the first reading there is no
    position to copy, and silently doing nothing reads as a broken button."""
    page = _position_page()

    page._fill_from_receiver.click()

    assert "No position" in page._position_note.text()


def test_nothing_is_sent_without_a_receiver() -> None:
    page = PositionPage()

    page._send_position()

    assert page._position_note.text() == ""
