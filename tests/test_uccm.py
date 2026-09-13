"""The UCCM family, against the only evidence there is (D7, #63).

**Nobody here has a UCCM.** Every assertion below traces to a line in `tests/fixtures/uccm/` —
seven sittings with a Trimble UCCM-P captured in WinZ3805A — and D7's rule is that an assertion
which does not is not made. Where this file asserts something the corpus does not establish, it
says so in as many words.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.capability import ALL_READINGS, ReceiverReading
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.drivers.registry import Registry
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.drivers.uccm import UccmDriver
from smartclock_device.drivers.uccm.profile import UccmVariant, UccmVendor
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.receiver_status import ReceiverStatus
from smartclock_device.transport.response_buffer import match_prompt

CAPTURES: Final = Path(__file__).parent / "fixtures" / "uccm"

#: What the bench module answered `*IDN?`, verbatim from the corpus.
BENCH_IDENTITY: Final = "TRIMBLE,57964-80,40896646,V2.0.1.6-01"


def driver() -> UccmDriver:
    return UccmDriver(clock=FixedClock(NOW))


def test_it_is_a_driver() -> None:
    """If this fails the seam is a suggestion."""
    assert isinstance(driver(), ReceiverDriver)


# ---- What the corpus establishes ----------------------------------------------------------------


def test_the_identity_in_the_corpus_is_the_one_asserted_here() -> None:
    """Guarding the guard: every assertion below rests on this string being what was captured."""
    found = any(
        BENCH_IDENTITY in path.read_text(encoding="latin-1") for path in CAPTURES.glob("*.txt")
    )

    assert found, "the identity these tests are written against is not in the corpus"


def test_the_prompt_in_the_corpus_is_the_one_the_driver_declares() -> None:
    """`UCCM-P >`, 162 times across the sittings."""
    text = "".join(path.read_text(encoding="latin-1") for path in CAPTURES.glob("*.txt"))

    assert "UCCM-P >" in text
    assert "UCCM-P" in driver().prompt_words


def test_the_line_settings_are_the_ones_every_capture_was_taken_at() -> None:
    headers = [
        line
        for path in CAPTURES.glob("*.txt")
        for line in path.read_text(encoding="latin-1").splitlines()
        if "57600-8-N-1" in line
    ]

    assert headers, "the corpus should record the line settings in its headers"
    assert str(driver().auto_detect_sequence[0]) == "57600-8-N-1"


# ---- Recognition ---------------------------------------------------------------------------------


def test_it_recognises_the_vendor_and_not_the_part_number() -> None:
    """Keying on the part number would make this driver serve precisely the one unit nobody owns."""
    subject = driver()

    assert subject.recognises(DeviceIdentity.parse(BENCH_IDENTITY)) is True
    assert subject.recognises(DeviceIdentity.parse("TRIMBLE,99999-11,1,V1")) is True


def test_it_does_not_recognise_a_receiver_that_named_nobody_it_knows() -> None:
    subject = driver()

    assert subject.recognises(None) is False
    assert subject.recognises(DeviceIdentity.parse("ACME,WIDGET-9,1,1")) is False


def test_the_smartclock_is_asked_first_so_a_shared_vendor_token_cannot_take_it() -> None:
    """`SYMMETRICOM` is a token both families answer with, and only one has met hardware.

    Registration order is priority order, and the UCCM is registered last for exactly this reason.
    """
    clock = FixedClock(NOW)
    registry = Registry(
        [SmartClockDriver(clock=clock), NmeaDriver(clock=clock), UccmDriver(clock=clock)]
    )

    selection = registry.select(DeviceIdentity.parse("SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"))

    assert isinstance(selection.driver, SmartClockDriver)


def test_the_variant_comes_from_the_prompt_because_asking_does_not_work() -> None:
    """The identity gives a part number, which says nothing about the variant; the prompt says it.

    That is the sibling's finding rather than a preference — `08c62c1`.
    """
    subject = driver()
    subject.adopt(DeviceIdentity.parse(BENCH_IDENTITY), "UCCM-P >")

    assert subject.profile.vendor is UccmVendor.TRIMBLE
    assert subject.profile.variant is UccmVariant.UCCM_P
    assert subject.name == "Trimble UCCM-P"


def test_a_link_that_established_only_half_says_only_half() -> None:
    """Named for what was established and never for what was assumed."""
    subject = driver()
    subject.adopt(DeviceIdentity.parse(BENCH_IDENTITY), None)

    assert subject.profile.variant is UccmVariant.UNKNOWN
    assert subject.name == "Trimble UCCM"

    fresh = driver()
    assert fresh.name == "UCCM", "and before anything is established, the bare family"


# ---- The prompt grammar --------------------------------------------------------------------------


def test_the_prompt_grammar_matches_this_family_and_not_the_smartclock_s() -> None:
    """§7.2's prompt is a grammar rather than a constant (#470).

    The two families differ in the word **and** the spacing, so no single literal matches both —
    which is why a constant had to become a grammar before this driver could connect at all.
    """
    assert match_prompt("UCCM-P >", ("UCCM-P",)) is not None
    assert match_prompt("UCCM-P >", ("scpi",)) is None, "the SmartClock's grammar must not match it"
    assert match_prompt("scpi > ", ("UCCM-P",)) is None


# ---- D7's label ----------------------------------------------------------------------------------


def test_it_says_it_is_unverified() -> None:
    """**D7's whole condition.** Not a docstring — a property a surface reads.

    A driver written entirely from somebody else's captures is a different thing from one that has
    met the receiver it claims to drive, and only the person in front of it can decide what to do
    about that.
    """
    assert driver().is_verified is False


@pytest.mark.parametrize("other", ["smartclock", "nmea"])
def test_the_families_that_have_met_hardware_say_so(other: str) -> None:
    """The label is only worth anything if it distinguishes."""
    clock = FixedClock(NOW)
    subject = SmartClockDriver(clock=clock) if other == "smartclock" else NmeaDriver(clock=clock)

    assert getattr(subject, "is_verified", True) is True


def test_it_offers_no_capability_it_has_never_sent() -> None:
    """§9.11 greys the control and names the family, which is the right answer for a driver that
    has never met its receiver. Offering a control that has never been sent is a claim D7 forbids.
    """
    from smartclock_device.drivers.capability import Capability

    subject = driver()

    assert all(subject.command(capability) is None for capability in Capability)


def test_what_it_declines_is_read_off_the_captured_screen() -> None:
    """The screen carries TFOM, FFOM, an antenna delay, an elevation mask and a position mode, and
    carries no diagnostic log, error queue or status registers. Both halves are asserted, because
    an over-eager decline is as wrong as a missing one."""
    subject = driver()

    for absent in (
        ReceiverReading.DIAGNOSTIC_LOG,
        ReceiverReading.ERROR_QUEUE,
        ReceiverReading.STATUS_REGISTERS,
    ):
        assert subject.reports(absent) is False

    for present in (
        ReceiverReading.TFOM,
        ReceiverReading.FFOM,
        ReceiverReading.ANTENNA_DELAY,
        ReceiverReading.ELEVATION_MASK,
        ReceiverReading.POSITION_HOLD,
    ):
        assert subject.reports(present) is True, f"the captured screen shows {present.value}"


def test_it_answers_every_reading_one_way_or_the_other() -> None:
    subject = driver()

    assert all(isinstance(subject.reports(r), bool) for r in ALL_READINGS)


def test_it_parses_nothing_yet_and_says_so_with_dashes() -> None:
    """A driver that connects and shows dashes is honest; one that shows a guess is not."""
    from smartclock_device.transport.transaction import Transaction, TransactionOutcome

    status = driver().parse_full(
        Transaction(command="SYST:STAT?", outcome=TransactionOutcome.COMPLETED, lines=("x",)), None
    )

    assert status.captured_at == NOW
    assert status.position is None
    assert status.tfom is None


# ---- §10.12's eleventh combination ------------------------------------------------------------


def test_the_union_is_eleven_with_this_family_registered() -> None:
    """The last of the three gaps #52 recorded between the specification and this port."""
    clock = FixedClock(NOW)
    registry = Registry(
        [SmartClockDriver(clock=clock), NmeaDriver(clock=clock), UccmDriver(clock=clock)]
    )

    assert len(registry.auto_detect_sequence) == 11
    assert str(registry.auto_detect_sequence[-1]) == "57600-8-N-1"


# ---- The label a user actually sees --------------------------------------------------------------


def test_the_identity_card_says_the_family_has_never_been_connected_to(
    application: object,
) -> None:
    """**D7's condition, on the surface rather than in a docstring.**

    The wording names the family and says what it means — that everything on the page comes from a
    driver written against captures taken elsewhere. "Unverified" alone would be a word nobody can
    act on.
    """
    del application
    from smartclock_monitor.views.pages import OverviewPage

    page = OverviewPage()
    page.show()

    page.set_driver(driver())
    assert page.unverified_note.isVisible()
    assert "never been connected" in page.unverified_note.text()
    assert "UCCM" in page.unverified_note.text(), "it must name the family"

    page.set_driver(SmartClockDriver(clock=FixedClock(NOW)))
    assert not page.unverified_note.isVisible(), "a family that has met hardware says nothing"


def test_disconnecting_takes_the_label_away(application: object) -> None:
    del application
    from smartclock_monitor.views.pages import OverviewPage

    page = OverviewPage()
    page.show()
    page.set_driver(driver())

    page.set_driver(None)

    assert not page.unverified_note.isVisible()


@pytest.fixture(scope="module")
def application() -> object:
    """One QApplication for the module, skipped where Qt cannot start a platform plugin."""
    qt = pytest.importorskip("PySide6.QtWidgets", reason="Qt is not available on this machine")
    existing = qt.QApplication.instance()
    if existing is not None:
        return existing
    try:
        return qt.QApplication([])
    except Exception as error:  # pragma: no cover - depends on the machine, not the code
        pytest.skip(f"Qt could not start a platform plugin: {error}")


def test_the_oscillator_control_is_dashed_rather_than_declined() -> None:
    """It was declined, and a citation contradicted the decline (#98).

    The decline rested on seven sittings **not showing a field** rather than on a receiver saying
    it has none — the code said as much at the time. Lady Heather 5.00 queries
    `DIAG:ROSC:EFC:DATA?` on this family, so the reading exists; it is simply not on the status
    screen, which is a different fact.

    **A decline is a strictly stronger claim than a dash.** Softening one this port cannot support
    needs no new evidence; asserting it would. Reading it is a separate piece of work and wants a
    capture, per D7.
    """
    subject = driver()

    assert subject.reports(ReceiverReading.OSCILLATOR_CONTROL) is True, (
        "unparsed is 'not yet', which is the dash — not 'never', which is the decline"
    )
    assert subject.reports(ReceiverReading.ONE_PPS_INTERVAL) is True, (
        "same reasoning: the screen carries a phase figure this port does not yet read"
    )


# ---- The catalogue, from the spellings the firmware was actually asked ---------------------------


def _spelling_reply(command: str) -> list[str]:
    """What `catalog-spellings-12sep2026` recorded for one command."""
    text = (CAPTURES / "catalog-spellings-12sep2026.txt").read_text(encoding="latin-1")
    block = text.split(f"==== SENT: {command}")[1].split("---- LINES")[1].split("====")[0]
    return [
        match.group(2)
        for line in block.splitlines()
        if (match := re.match(r"\s*\[(Payload|Complete|Error|Prompt)\]\s?(.*)$", line))
    ]


def test_the_catalogue_is_what_the_firmware_answered() -> None:
    """Six of the nine spellings sent on 12 Sep. Not a list from a datasheet."""
    catalogued = {command.mnemonic for command in driver().commands}

    assert catalogued == {
        "*IDN?",
        "SYST:STAT?",
        "SYNC:TINT?",
        "DIAG:ROSC:EFC:REL?",
        "DIAG:LOOP?",
        "LED:GPSL?",
    }


@pytest.mark.parametrize(
    ("command", "refusal"),
    [
        (":ROSC:HOLD:DUR?", "Command error"),
        (":GPS:POS:SURV:STAT?", "Undefined header"),
        (":GPS:POS:SURV:PROG?", "Undefined header"),
    ],
)
def test_the_three_that_were_refused_are_not_catalogued(command: str, refusal: str) -> None:
    """**And the way each was refused is why.**

    `Undefined header` is a mnemonic this firmware does not have. `Command error` is one it knows
    and will not answer — `:ROSC:HOLD:DUR?` was refused cold, locked, and through fourteen minutes
    of genuine holdover. That the module distinguishes the two is itself a finding.

    Cataloguing any of them would offer a control that has never once succeeded against the only
    module this port has evidence for.
    """
    assert any(refusal in line for line in _spelling_reply(command)), (
        "the capture should show this refusal, or the reasoning below it is wrong"
    )
    assert not driver().is_allowed(command)


def test_the_oscillator_control_was_in_the_corpus_all_along() -> None:
    """**The audit's finding, closed properly rather than softened.**

    This driver declined `OSCILLATOR_CONTROL` on the grounds that no capture showed one. Lady
    Heather pointed at `DIAG:ROSC:EFC:DATA?` and the decline was softened to a dash (#100). Reading
    the file showed better: `DIAG:ROSC:EFC:REL?` was **asked and answered on 12 September** and
    nobody had looked.

    The lesson is the one #98 exists for — the corpus was ahead of the driver, and a citation only
    prompted somebody to check.
    """
    reply = _spelling_reply("DIAG:ROSC:EFC:REL?")

    assert any("19.70" in line for line in reply), "the captured value"
    assert driver().reports(ReceiverReading.OSCILLATOR_CONTROL) is True
    assert any(c.mnemonic == "DIAG:ROSC:EFC:REL?" for c in driver().commands)


def test_the_fast_tier_carries_what_it_claims() -> None:
    """#61b's rule, for the third family."""
    plan = driver().plan

    assert set(plan.fast_readings) == {
        ReceiverReading.ONE_PPS_INTERVAL,
        ReceiverReading.OSCILLATOR_CONTROL,
    }
    for reading in plan.fast_readings:
        assert driver().reports(reading), "a tier cannot be answerable for a declined reading"


def test_the_time_interval_is_read_in_the_units_the_module_sends() -> None:
    """`1.576293E-09` is **seconds**, and the model holds nanoseconds."""
    from smartclock_device.transport.transaction import Transaction, TransactionOutcome

    reply = _spelling_reply("SYNC:TINT?")
    value = next(line for line in reply if "E-" in line)

    folded = driver().apply_fast(
        ReceiverStatus(captured_at=NOW),
        {
            "SYNC:TINT?": Transaction(
                command="SYNC:TINT?", outcome=TransactionOutcome.COMPLETED, lines=(value,)
            )
        },
    )

    assert folded.one_pps_ti_nanoseconds == pytest.approx(1.576293, abs=1e-6)


def test_a_refused_scalar_does_not_overwrite_a_good_reading() -> None:
    """This module refuses queries it knows, in states it does not like."""
    from smartclock_device.transport.transaction import Transaction, TransactionOutcome

    known = ReceiverStatus(captured_at=NOW, one_pps_ti_nanoseconds=42.0)

    folded = driver().apply_fast(
        known,
        {
            "SYNC:TINT?": Transaction(
                command="SYNC:TINT?", outcome=TransactionOutcome.TIMED_OUT, lines=()
            )
        },
    )

    assert folded.one_pps_ti_nanoseconds == 42.0
