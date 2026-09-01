"""§9.7.4's export and copy layer, and §9.7.5's accelerators.

The rule these are all about is that **a copied value is data leaving the application, not a
readout**. §9.5.3's minus sign and hair space are right on screen and make a spreadsheet cell
*text* — silently, with every formula over the column then returning zero.
"""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication, QLabel

from conftest import NOW
from smartclock_device.models.receiver_status import (
    ReceiverStatus,
    SignalStrengthKind,
    SmartClockMode,
)
from smartclock_device.models.satellite import TrackedSatellite
from smartclock_monitor.services.export import (
    EM_DASH,
    machine_rows,
    suggested_filename,
    to_csv,
    to_machine_text,
)
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.themes.tokens import Theme
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.views.pages import DASH
from smartclock_monitor.widgets.copy_menu import value_menu_text

MINUS = "\N{MINUS SIGN}"
HAIR = "\N{HAIR SPACE}"


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def reading(**kwargs: object) -> Reading:
    defaults: dict[str, object] = {
        "captured_at": NOW,
        "mode": SmartClockMode.LOCKED,
        "one_pps_ti_nanoseconds": -2.9,
        "signal_strength_kind": SignalStrengthKind.CARRIER_TO_NOISE,
        "tracked": (
            TrackedSatellite(prn=4, elevation_degrees=71, azimuth_degrees=93, signal_strength=30),
            TrackedSatellite(prn=7, elevation_degrees=44, azimuth_degrees=250, signal_strength=37),
        ),
    }
    defaults.update(kwargs)
    return Reading(status=ReceiverStatus(**defaults), captured_at=NOW, efc_percent=-16.5989)  # type: ignore[arg-type]


# ---- The machine-text rule ---------------------------------------------------------------------


def test_the_minus_sign_becomes_a_hyphen() -> None:
    """§9.5.3 rule 4 puts U+2212 in a readout because a hyphen is optically too short beside
    lining figures. A spreadsheet handed U+2212 gets text, and every formula over the column then
    returns zero — which is the failure that does not announce itself."""
    assert to_machine_text(f"{MINUS}2.9") == "-2.9"
    assert MINUS not in to_machine_text(f"{MINUS}33.1 ns")


def test_the_unit_and_hair_space_are_dropped() -> None:
    """§9.5.3 rule 3 makes the unit a separate element on screen. It is a separate column in a
    sheet, so carrying it into the cell would make the cell text."""
    assert to_machine_text(f"{MINUS}33.1{HAIR}ns") == "-33.1"
    assert to_machine_text("1,247 h") == "1247"
    # The sign survives: it is what the receiver said, and a spreadsheet reads "+18" as 18.
    assert to_machine_text("+18 s accumulated") == "+18"


def test_a_missing_value_copies_as_nothing() -> None:
    """§11.1's em dash is the *absence* of data. A dash pasted into a sheet looks like a reading
    that happened to be a dash."""
    assert to_machine_text(EM_DASH) == ""
    assert to_machine_text(DASH) == ""
    assert to_machine_text("   ") == ""


def test_text_that_is_not_a_number_survives_intact() -> None:
    """The rule is about typesetting, not about discarding. A mode name is a value too."""
    assert to_machine_text("Locked to GPS") == "Locked to GPS"
    assert to_machine_text("SYMMETRICOM,Z3805A,3625A02931,1.01.03-A") == (
        "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"
    )


def test_scientific_notation_survives() -> None:
    """A spreadsheet reads 6.0E-08 as a number. Truncating the exponent would not be a
    typesetting fix, it would be losing eight orders of magnitude."""
    assert to_machine_text("6.00000E-008") == "6.00000E-008"


def test_device_literal_text_is_exempt() -> None:
    """§9.5.3 rule 4 says so in as many words: raw SCPI text is reproduced verbatim. "Correcting"
    the sign would make the copy disagree with the transcript it came from."""
    literal = QLabel(f"{MINUS}5.4E-009")

    assert value_menu_text(literal, device_literal=True) == f"{MINUS}5.4E-009"
    assert value_menu_text(literal, device_literal=False) == "-5.4E-009"


# ---- CSV ---------------------------------------------------------------------------------------


def test_rows_are_written_with_rfc_4180_endings() -> None:
    """Which every spreadsheet on every platform reads without being asked."""
    text = to_csv([["a", "b"], ["1", "2"]])

    assert text == "a,b\r\n1,2\r\n"


def test_a_cell_containing_a_comma_is_quoted() -> None:
    """ "Holdover started, not tracking GPS" is one log entry the Z3805A emits constantly, and it
    is the reason the log parser splits on the entry prefix rather than on commas."""
    text = to_csv([["Entry"], ["Holdover started, not tracking GPS"]])

    assert '"Holdover started, not tracking GPS"' in text


def test_the_header_row_keeps_its_words() -> None:
    """The header is words and stays words; the body is numbers and stops being typeset."""
    rows = machine_rows([["1 PPS TI (ns)"], [f"{MINUS}2.9{HAIR}ns"]])

    assert rows == [["1 PPS TI (ns)"], ["-2.9"]]


def test_the_filename_names_the_view() -> None:
    """§9.7.4 scopes Export to the current page, and a folder of files called export.csv is a
    folder nobody can use a week later."""
    assert suggested_filename("Status Registers", "20260831-231726") == (
        "smartclock-status-registers-20260831-231726.csv"
    )


# ---- What the pages export ---------------------------------------------------------------------


def _window() -> DetailsWindow:
    window = DetailsWindow(Theme.DARK)
    window.show_reading(reading())
    return window


def test_every_page_answers_the_export_question_without_raising() -> None:
    """``csv_rows`` is on the base class returning empty, so a page that has nothing to give says
    so rather than being a special case at the call site."""
    window = _window()

    for page in window.pages:
        rows = page.csv_rows()
        assert isinstance(rows, (list, tuple))


def test_the_satellites_page_exports_its_table() -> None:
    window = _window()
    page = window.page_named("Satellites")

    rows = page.csv_rows()
    assert len(rows) >= 3  # header plus two tracked
    assert "PRN" in rows[0]


def test_the_overview_page_exports_its_fields() -> None:
    window = _window()
    rows = window.page_named("Overview").csv_rows()

    assert rows[0] == ["Card", "Field", "Value"]
    assert any("Mode" in row for row in rows[1:])


def test_a_page_with_nothing_to_show_exports_nothing() -> None:
    """Not a header with no rows: §9.11's rule about controls that look like they work applies to
    Export, and the title bar disables it when the page answers with nothing."""
    from smartclock_monitor.views.registers_page import StatusRegistersPage

    assert StatusRegistersPage().csv_rows() == ()


def test_the_export_command_is_disabled_when_there_is_nothing_to_export() -> None:
    window = DetailsWindow(Theme.DARK)
    window._navigation.setCurrentRow(
        [page.title for page in window.pages].index("Status Registers")
    )
    window._retune_commands()

    assert window._export_action.isEnabled() is False


def test_the_export_command_is_enabled_where_there_is() -> None:
    window = _window()
    window._navigation.setCurrentRow([page.title for page in window.pages].index("Satellites"))
    window._retune_commands()

    assert window._export_action.isEnabled() is True


def test_exporting_writes_machine_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End to end: the file a user gets has hyphens and no units."""
    from PySide6.QtWidgets import QFileDialog

    target = tmp_path / "out.csv"
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(target), ""))
    )

    window = _window()
    window._navigation.setCurrentRow([page.title for page in window.pages].index("Overview"))

    assert window.export_current() == str(target)

    # Bytes, not text: read_text translates CRLF on the way in, so a test reading it the ordinary
    # way cannot tell what was written — and read_text(newline=...) is 3.13, which this is not.
    written = target.read_bytes().decode("utf-8")
    assert MINUS not in written
    assert written.endswith("\r\n"), "RFC 4180, which every spreadsheet reads unprompted"
    # The card name is §10.4's, which is "Synchronization" in the specification's own US spelling.
    assert "Synchronization,Detail," in written, (
        "a missing value exports as an empty cell, not a dash"
    )


def test_cancelling_the_dialog_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    window = _window()

    assert window.export_current() is None
    assert list(tmp_path.iterdir()) == []


def test_the_timing_page_exports_the_raw_series_not_the_decimated_one() -> None:
    """§9.10.2's min/max reduction is right for drawing a shape and wrong for a document, where it
    would silently halve the row count and put two readings a pixel apart in one row."""
    from smartclock_device.clock import FixedClock
    from smartclock_monitor.services.trend_store import TrendStore

    clock = FixedClock(NOW)
    store = TrendStore.in_memory(clock)
    for index in range(500):
        at = NOW - timedelta(seconds=index)
        store.append(
            Reading(
                status=ReceiverStatus(
                    captured_at=at, mode=SmartClockMode.LOCKED, one_pps_ti_nanoseconds=float(index)
                ),
                captured_at=at,
                efc_percent=-16.83,
            )
        )

    window = _window()
    page = window.page_named("Timing")
    page.set_trend_store(store)  # type: ignore[attr-defined]

    rows = page.csv_rows()
    assert len(rows) == 501, "one row per stored reading, plus the header"
    assert rows[0][0].startswith("Time")


# ---- §9.7.5's accelerators ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attribute", "keys"),
    [("_refresh_action", "F5"), ("_export_action", "Ctrl+E"), ("_settings_action", "Ctrl+,")],
)
def test_the_title_bar_commands_carry_their_accelerators(attribute: str, keys: str) -> None:
    """§9.7.5's table. Attached to the *window*, because a control in a collapsible area takes its
    accelerator with it when it collapses — precisely the state a keyboard-only user needs it."""
    window = DetailsWindow(Theme.DARK)
    action = getattr(window, attribute)

    assert action.shortcut() == QKeySequence(keys)
    assert action in window.actions()


def test_the_accelerator_is_in_the_tooltip() -> None:
    """§9.7.5: icon-only buttons must show accelerator text in their tooltip, and the mechanism
    that would have rendered it automatically does not exist here."""
    window = DetailsWindow(Theme.DARK)

    assert "F5" in window._refresh_action.toolTip()
    assert "Ctrl+E" in window._export_action.toolTip()


def test_there_are_nine_destination_accelerators_and_no_tenth() -> None:
    """§9.7.5: *"There is no Ctrl+10"* — §10.2's cap is twelve destinations but only the first
    nine can carry an accelerator, so the pane's order decides which are one keystroke away."""
    window = DetailsWindow(Theme.DARK)

    assert len(window._jumps) == 9
    assert window._jumps[-1].shortcut() == QKeySequence("Ctrl+9")


def test_a_destination_accelerator_jumps() -> None:
    window = _window()
    window._jump_to(2)

    assert window.navigation.currentRow() == 2


def test_an_accelerator_past_the_end_does_nothing() -> None:
    """Nine accelerators exist; a window with fewer destinations must not crash on Ctrl+9."""
    window = _window()
    before = window.navigation.currentRow()
    window._jump_to(50)

    assert window.navigation.currentRow() == before


def test_settings_is_one_keystroke_away() -> None:
    window = _window()
    window.show_settings()

    page = window.current_page()
    assert page is not None and page.title == "Settings"


# ---- P0-1: the identity has to be somewhere a user looks ---------------------------------------


def test_the_overview_shows_the_four_identity_fields() -> None:
    """P0-1, whose acceptance the specification states twice: *"A P0 is not met by a string that
    reaches only the log."* The original had exactly this defect (#319 item 14) — the connection
    was made inside the window and no view displayed the identity."""
    from smartclock_device.models.device_identity import DeviceIdentity

    window = _window()
    page = window.page_named("Overview")
    page.set_identity(  # type: ignore[attr-defined]
        DeviceIdentity.parse("SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"),
        "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A",
    )

    shown = {str(row[1]): str(row[2]) for row in page.csv_rows()[1:]}
    assert shown["Manufacturer"] == "SYMMETRICOM"
    assert shown["Model"] == "Z3805A"
    assert shown["Serial number"] == "3625A02931"
    assert shown["Firmware"] == "1.01.03-A"


def test_an_answer_that_is_not_four_fields_shows_the_raw_answer() -> None:
    """§10.4: *"shows the raw answer instead, rather than four dashes: four dashes say 'nothing is
    connected', which is a different statement from 'a model this build has not seen'."* §11.1
    keeps the evidence."""
    from smartclock_device.models.device_identity import DeviceIdentity

    window = _window()
    page = window.page_named("Overview")
    page.set_identity(  # type: ignore[attr-defined]
        DeviceIdentity.parse("SOMETHING ELSE ENTIRELY"), "SOMETHING ELSE ENTIRELY"
    )

    assert page._identity_raw.text() == "SOMETHING ELSE ENTIRELY"  # type: ignore[attr-defined]
    assert page._identity_raw.isHidden() is False  # type: ignore[attr-defined]


def test_nothing_answering_is_dashes_rather_than_an_empty_card() -> None:
    """Not connected is the one case where four dashes *are* the right answer."""
    window = _window()
    page = window.page_named("Overview")
    page.set_identity(None, None)  # type: ignore[attr-defined]

    shown = {str(row[1]): str(row[2]) for row in page.csv_rows()[1:]}
    assert shown["Model"] == DASH
    assert page._identity_raw.isHidden() is True  # type: ignore[attr-defined]


def test_the_identity_is_device_literal_text() -> None:
    """§9.5: what the receiver itself emitted is monospace, and the copy layer reproduces it
    verbatim rather than putting it through the typesetting rules."""
    from smartclock_device.models.device_identity import DeviceIdentity

    window = _window()
    page = window.page_named("Overview")
    page.set_identity(  # type: ignore[attr-defined]
        DeviceIdentity.parse("SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"), None
    )

    assert page._identity.is_device_literal("Model") is True  # type: ignore[attr-defined]
