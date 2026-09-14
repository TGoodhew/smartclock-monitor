"""What the interface **says**, checked against what the receiver **sent** (#99, part 3).

Every other test in this suite checks one layer. The parser tests assert that bytes become a model;
the page tests assert that a model becomes text. **Neither catches a page that reads the wrong
field of a correct model**, and that is the defect class this port has actually had: a value right
in the model and wrong on the surface, or a dash where a figure was available.

So these drive the **real pages** with a status built by the **real driver** from bytes a **real
receiver sent**, and assert the text a user would read — not "the page has a field called
Horizontal error" but "the page reads 2.4 m from a capture whose `GST` says so".

The expected answers are derivable from the captures themselves, which is what makes this cheap:
`form8n-gst-gbs` carries 301 `GST` sentences with a horizontal error near 3.9 m, `vk162-cold-start`
walks the fix ladder, and the bench Z3805A's own screen is in `tests/fixtures/captured/`.
"""

from __future__ import annotations

import os
from typing import Final

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
qt = pytest.importorskip("PySide6.QtWidgets", reason="Qt is not available on this machine")

from PySide6.QtWidgets import QApplication  # noqa: E402

from conftest import NOW  # noqa: E402
from smartclock_device.clock import FixedClock  # noqa: E402
from smartclock_device.models.receiver_status import (  # noqa: E402
    ReceiverStatus,
    SmartClockMode,
)
from smartclock_device.parsing.status_screen import StatusScreenParser  # noqa: E402
from smartclock_monitor.services.polling import Reading  # noqa: E402
from smartclock_monitor.views.pages import (  # noqa: E402
    DASH,
    OverviewPage,
    PositionPage,
    SatellitesPage,
)
from smartclock_monitor.views.wording import mode_words  # noqa: E402
from test_nmea_captures import CAPTURES, _replay  # noqa: E402

SCREENS: Final = CAPTURES.parent / "captured"


@pytest.fixture(scope="module")
def application() -> QApplication:
    existing = QApplication.instance()
    if isinstance(existing, QApplication):
        return existing
    try:
        return QApplication([])
    except Exception as error:  # pragma: no cover - depends on the machine, not the code
        pytest.skip(f"Qt could not start a platform plugin: {error}")


def from_capture(name: str, index: int = -1) -> ReceiverStatus:
    """One status, parsed by the real driver from one capture's bytes."""
    return _replay(name)[index]


def from_uccm_screen() -> ReceiverStatus:
    """One status, parsed by the real parser from the Mt Warrigal module's own screen.

    Lifted from `transitions-13sep2026.replies.txt` **with its bytes intact** — every line of a UCCM
    screen arrives with a NUL prefix, which the parser strips and which a tidied copy would hide.
    """
    from smartclock_device.parsing.uccm_screen import UccmScreenParser

    text = (
        (CAPTURES.parent / "uccm" / "transitions-13sep2026.replies.txt")
        .read_bytes()
        .decode("latin-1")
    )
    start = text.index("---- SYST:STAT?")
    body = text[text.index("\n", start) + 1 : text.index("\n---- ", start + 10)]
    return UccmScreenParser(FixedClock(NOW)).parse(body.strip("\r\n"))


def from_screen(name: str) -> ReceiverStatus:
    """One status, parsed by the real parser from a captured SmartClock screen."""
    text = (SCREENS / f"{name}.txt").read_bytes().decode("latin-1")
    return StatusScreenParser(FixedClock(NOW)).parse(text)


def shown(page: object, status: ReceiverStatus) -> object:
    page.show_reading(Reading(status=status, captured_at=NOW))  # type: ignore[attr-defined]
    return page


# ---- A talker's position, end to end -------------------------------------------------------------


def test_the_position_page_reads_the_error_the_gst_sentences_carry(
    application: QApplication,
) -> None:
    """Not "there is a field" — the number on screen, from the bytes that produced it."""
    del application
    status = from_capture("form8n-gst-gbs-wsl-bench")
    assert status.uncertainty is not None
    expected = status.uncertainty.horizontal_metres
    assert expected is not None

    page = shown(PositionPage(), status)

    assert page.fields.value_of("Horizontal error") == f"{expected:.1f} m"  # type: ignore[attr-defined]
    assert 3.6 < expected < 4.2, "this sitting's own figure, so a wrong capture fails here too"


def test_the_position_page_names_the_kind_of_fix_the_capture_holds(
    application: QApplication,
) -> None:
    del application
    page = shown(PositionPage(), from_capture("vk162-steady-state"))

    assert page.fields.value_of("Fix quality") == "Differential"  # type: ignore[attr-defined]

    page = shown(PositionPage(), from_capture("vk162-wsl-bench"))

    assert page.fields.value_of("Fix quality") == "Autonomous", (  # type: ignore[attr-defined]
        "the same module five days later, and the page has to say the difference"
    )


def test_a_talker_with_no_error_statistics_dashes_rather_than_inventing(
    application: QApplication,
) -> None:
    """`vk162-steady-state` carries no `GST` at all, so the row is §11.1's dash."""
    del application
    page = shown(PositionPage(), from_capture("vk162-steady-state"))

    assert page.fields.value_of("Horizontal error") == DASH  # type: ignore[attr-defined]
    assert page.fields.value_of("Integrity") == DASH  # type: ignore[attr-defined]


# ---- The satellites a receiver actually reported ------------------------------------------------


def test_the_satellites_table_shows_what_the_cycle_tracked(application: QApplication) -> None:
    """Row count and designations, from the cycle's own sentences."""
    del application
    status = from_capture("form8n-wsl-bench")
    page = shown(SatellitesPage(), status)

    rows = page.table.rowCount()  # type: ignore[attr-defined]

    assert rows == len(status.tracked) + len(status.not_tracked)
    assert rows > 0, "this capture holds satellites, so a zero here is the parser or the page"


def test_two_constellations_are_told_apart_on_the_surface(application: QApplication) -> None:
    """#57 end to end: the collision is in the bytes, and the table must not collapse it.

    `form8n-wsl-bench` has a number reported by both the `GP` and `GB` talker in **every** cycle,
    so a table keyed on the number alone would show fewer rows than the receiver reported.
    """
    del application
    status = from_capture("form8n-wsl-bench")
    page = shown(SatellitesPage(), status)

    designations = {
        page.table.item(row, 0).text()  # type: ignore[attr-defined]
        for row in range(page.table.rowCount())  # type: ignore[attr-defined]
    }

    assert len(designations) == page.table.rowCount(), "two rows share a label"  # type: ignore[attr-defined]
    assert any(d.startswith("C") for d in designations), "BeiDou, by its RINEX letter"
    assert any(d.startswith("G") for d in designations), "and GPS"


# ---- The SmartClock's own screen -----------------------------------------------------------------


def test_the_overview_reads_the_mode_the_captured_screen_reports(
    application: QApplication,
) -> None:
    """A real Z3805A screen, through the real parser, onto the real page."""
    del application
    status = from_screen("locked-to-gps")
    page = shown(OverviewPage(), status)

    assert page.fields.value_of("Mode") == "Locked to GPS"  # type: ignore[attr-defined]
    assert page.fields.value_of("Warnings") == "None", "this screen parses clean"  # type: ignore[attr-defined]


def test_a_holdover_screen_says_holdover_on_the_page(application: QApplication) -> None:
    """The state a timing user most needs to be told about, from the capture that holds it."""
    del application
    page = shown(OverviewPage(), from_screen("holdover-gps-1pps-invalid"))

    assert "Holdover" in page.fields.value_of("Mode")  # type: ignore[attr-defined]


def test_the_smartclock_position_page_reads_the_screen_s_own_coordinates(
    application: QApplication,
) -> None:
    """Degrees-minutes-seconds, formatted by the model, checked against the screen's own text."""
    del application
    status = from_screen("locked-to-gps")
    assert status.position is not None
    page = shown(PositionPage(), status)

    latitude = page.fields.value_of("Latitude")  # type: ignore[attr-defined]

    assert latitude != DASH
    assert latitude.split()[0] in {"N", "S"}, "hemisphere first, as the receiver prints it"


@pytest.mark.parametrize(
    "name",
    [
        "locked-to-gps",
        "holdover-gps-1pps-invalid",
        "power-up-gps-acquisition",
        "recovery-fine-freq-adj",
        "surveying-locked-to-gps-stabilizing-frequency",
    ],
)
def test_no_captured_screen_puts_a_page_into_a_state_it_cannot_draw(
    name: str, application: QApplication
) -> None:
    """Every captured state, through every page that takes one. §11.1 is not scoped to one page.

    This is the crash-on-navigation class §12's #304 was about, asked of real device output rather
    than of a status built by hand.
    """
    del application
    status = from_screen(name)

    for page in (OverviewPage(), PositionPage(), SatellitesPage()):
        shown(page, status)


# ---- The vocabulary this file found two of -------------------------------------------------------


def test_every_surface_words_a_mode_the_same_way(application: QApplication) -> None:
    """**Found on this file's first run**, which is the argument for it existing.

    The main window's pill said *Locked to GPS*; §10.4's Overview card said *Locked*. The card used
    `humanise`, which renders the enum's **own name** — and the enum is named for the protocol
    rather than for a reader.
    """
    del application
    from smartclock_monitor.views.main_window import MainWindow

    status = from_screen("locked-to-gps")
    window = MainWindow()
    window.show_reading(Reading(status=status, captured_at=NOW))
    page = shown(OverviewPage(), status)

    assert window.mode_pill.text == page.fields.value_of("Mode")  # type: ignore[attr-defined]


@pytest.mark.parametrize("mode", list(SmartClockMode))
def test_the_words_a_mode_is_given_are_the_guide_s(mode: SmartClockMode) -> None:
    """**The guide decides the vocabulary, not the code.**

    `how-to-use.md` is the `F1` help. It uses *Locked to GPS* six times, *Powering up* twice and
    *Recovering* once — and none of `humanise`'s renderings of the same members (*Locked*,
    *Power up*, *Recovery*) appears in it anywhere. A user who read the help and then looked at the
    page had to guess the two were the same state.
    """
    guide = (CAPTURES.parent.parent.parent / "docs" / "how-to-use.md").read_text(encoding="utf-8")
    word = mode_words(mode)

    if mode is SmartClockMode.UNKNOWN:
        return  # the guide has no occasion to name it
    assert word in guide, f"{word} is shown to users and the guide never uses it"


# ---- The third family, whose pages no person here will ever see ----------------------------------
#
# D7: nobody in this repository has a UCCM, so the captures are the whole of the evidence — and a
# page that drew this family's screen wrongly would be wrong in front of the one person who does
# have one. Which makes the assertions below the only review those pages will get.


def test_the_uccm_position_page_reads_the_module_s_own_survey(
    application: QApplication,
) -> None:
    """Mt Warrigal, from the module's own screen: S 34:32:39.019, E 150:50:25.107, 49.72 m.

    The sidecar records the same figures from the sitting's own notes, so this crosses the seam
    twice — bytes to model to text, against a number written down by the person who was there.
    """
    del application
    page = PositionPage()
    shown(page, from_uccm_screen())
    rows = dict(page.fields.rows())

    assert rows["Latitude"].startswith("S 34")
    assert rows["Longitude"].startswith("E 150")
    assert "49.72" in rows["Height"]


def test_the_uccm_overview_says_what_the_module_was_doing(application: QApplication) -> None:
    """`OCXO WARMUP`, TFOM 2, FFOM 3 — a module two seconds past a power cycle with no antenna.

    The **mode** is unknown and the **detail** is not, which is the honest reading of a screen whose
    own state line says something this port has no enumeration for. A page that resolved the
    unknown mode to a confident word would be inventing one.
    """
    del application
    status = from_uccm_screen()
    page = OverviewPage()
    shown(page, status)
    rows = dict(page.fields.rows())

    assert status.mode is SmartClockMode.UNKNOWN
    assert rows["Mode"] == mode_words(SmartClockMode.UNKNOWN)
    assert rows["Detail"] == "OCXO WARMUP"


def test_the_uccm_satellite_table_is_empty_and_says_so(application: QApplication) -> None:
    """Nothing tracked, because the antenna was off — and an empty table rather than a page that
    cannot be drawn. §11.1's dash means *did not parse*; nought satellites is a reading."""
    del application
    status = from_uccm_screen()
    page = SatellitesPage()
    shown(page, status)

    assert status.tracked == ()
    assert page.table.rowCount() == 0
