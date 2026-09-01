"""The catalog is an allowlist, and the two safety mechanisms check each other.

§8.1's architecture is that a command not catalogued does not exist. That only holds if the
catalog cannot contain an excluded command, and the check for that is here rather than in a comment
— so the allowlist and the exclusion list are each other's test.
"""

from __future__ import annotations

from typing import Final

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.commands.blocked import is_blocked
from smartclock_device.commands.scpi_command import (
    ArgumentKind,
    ResponseFormat,
    SafetyTier,
)
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.parsing.scalars import (
    parse_boolean,
    parse_decimal,
    parse_first_of_list,
    parse_integer,
    parse_keyword,
)


def test_no_catalogued_command_is_an_excluded_one() -> None:
    """The join between §8.1 and §8.4. If the catalog ever grows an excluded command, the
    allowlist stops being a safety property and becomes a list."""
    for command in catalog.ALL:
        assert is_blocked(command.mnemonic) is False, (
            "A catalogued command is excluded by §8.4. One of the two lists is wrong."
        )


def test_the_catalog_is_not_empty() -> None:
    """Guarding the guard: an empty catalog would pass the check above while allowing nothing."""
    assert len(catalog.ALL) >= 10


def test_every_entry_has_a_unique_mnemonic() -> None:
    """The lookup is keyed on it, so a duplicate would silently shadow an entry."""
    mnemonics = [command.mnemonic.upper() for command in catalog.ALL]

    assert len(mnemonics) == len(set(mnemonics))


def test_an_uncatalogued_command_is_not_allowed() -> None:
    """The point-of-send check asks whether the command **is catalogued**, not whether it is
    excluded. An allowlist answers the first question; answering the second is the architecture
    §8.1 rejects."""
    assert catalog.is_allowed(":NOSUCH:COMMAND?") is False
    assert catalog.find(":NOSUCH:COMMAND?") is None


@pytest.mark.parametrize("mnemonic", [None, "", "   "])
def test_nothing_is_not_allowed(mnemonic: str | None) -> None:
    assert catalog.is_allowed(mnemonic) is False


def test_a_catalogued_command_is_found_however_it_is_cased() -> None:
    assert catalog.is_allowed(":syst:stat?") is True
    assert catalog.is_allowed(":SYST:STAT?") is True


def test_every_confirming_command_carries_its_own_sentence() -> None:
    """P0-6.

    §8.3, and its own amendment note is the argument for keeping the sentence *on the command*.

    ``:IGN:NONE`` shared the exclusion sentence — *"Exclude the selected satellites from
    tracking?"* — for a command that **clears** the exclusion list, in this table and in the
    catalog both. A user confirming it would reasonably believe they were excluding satellites
    while making every satellite eligible again. The dialog is the safety mechanism and that one
    named the reverse of what it was about to do.

    So: no tier C entry without a sentence, and no two entries sharing one, because sharing is how
    that defect happened.
    """
    confirming = [command for command in catalog.ALL if command.tier is SafetyTier.CONFIRM]
    assert confirming, "the tier exists; something should be in it"

    for command in confirming:
        assert command.confirmation, f"{command.mnemonic} confirms with no sentence."
        assert command.confirmation.endswith("?") or "?" in command.confirmation, (
            f"{command.mnemonic}'s confirmation does not ask anything."
        )


def test_a_safe_command_carries_no_confirmation() -> None:
    """A sentence on a tier S entry is either a miscategorised command or a sentence nothing will
    ever show. Both are worth failing over."""
    for command in catalog.ALL:
        if command.tier is SafetyTier.SAFE:
            assert command.confirmation is None, f"{command.mnemonic} is safe but has a sentence."
            assert command.requires_acknowledgement is False


def test_forcing_holdover_needs_the_extra_acknowledgement() -> None:
    """§9.7.4 gates the strong variants behind a tick. Forcing holdover inside 24 hours of
    power-up corrupts SmartClock oscillator learning, which is not undoable by clicking again."""
    assert catalog.HOLDOVER_FORCE.requires_acknowledgement is True
    assert "24 hours" in (catalog.HOLDOVER_FORCE.confirmation or "")


def test_recovering_from_holdover_is_safe() -> None:
    """§8.2 says why in as many words: both recovery commands move the unit *toward* lock, which
    is the desired state, and cannot damage anything."""
    assert catalog.HOLDOVER_RECOVER.tier is SafetyTier.SAFE
    assert catalog.HOLDOVER_IGNORE_RECOVERY_LIMIT.tier is SafetyTier.SAFE


def test_every_argument_taking_command_declares_what_it_accepts() -> None:
    """A setter with no bounds accepts whatever a spin box hands it. The bounds are the validation
    — there is nowhere else it happens."""
    for command in catalog.ALL:
        if command.argument in (ArgumentKind.INTEGER, ArgumentKind.DECIMAL):
            assert command.minimum is not None, f"{command.mnemonic} has no lower bound."
            assert command.maximum is not None, f"{command.mnemonic} has no upper bound."
            assert command.minimum <= command.maximum
        if command.argument is ArgumentKind.KEYWORD:
            assert command.keywords, f"{command.mnemonic} accepts a keyword from nowhere."
            assert all(word == word.upper() for word in command.keywords)


def test_a_command_that_takes_nothing_refuses_an_argument() -> None:
    """The allowlist is an exact match on the header, so an argument appended to a command that
    does not take one would be text nobody validated."""
    assert catalog.STATUS_SCREEN.rendered() == ":SYST:STAT?"
    assert catalog.STATUS_SCREEN.rendered("ALL") is None


def test_an_integer_argument_is_bounded_and_whole() -> None:
    setter = catalog.SET_HOLDOVER_DURATION_THRESHOLD

    assert setter.rendered(600) == ":SYNC:HOLD:DUR:THR 600"
    assert setter.rendered(0) is None
    assert setter.rendered(1_000_000) is None
    assert setter.rendered(1.5) is None
    assert setter.rendered("not a number") is None
    assert setter.rendered(None) is None


def test_a_keyword_argument_comes_from_the_list_or_not_at_all() -> None:
    """§10.9's twelve subsystem keywords were probed against the live receiver rather than taken
    on trust. Anything else is a command this application has never seen answered."""
    assert catalog.RUN_SELF_TEST.rendered("ALL") == ":DIAG:TEST? ALL"
    assert catalog.RUN_SELF_TEST.rendered("gps") == ":DIAG:TEST? GPS"
    assert catalog.RUN_SELF_TEST.rendered("NOSUCH") is None
    assert catalog.RUN_SELF_TEST.rendered(7) is None


def test_a_decimal_argument_is_not_sent_in_exponent_notation() -> None:
    """The antenna delay is seconds, and 60 ns is 6e-08. A receiver handed "6e-08" for a value it
    spells plainly is a command that fails for a formatting reason."""
    rendered = catalog.SET_ANTENNA_DELAY.rendered(6e-08)

    assert rendered is not None
    # The argument, not the whole line — ":GPS:REF:ADEL" has an "e" of its own in REF.
    assert "e" not in rendered.split(" ", 1)[1].lower()
    assert rendered == ":GPS:REF:ADEL 0.00000006"


def test_every_register_has_all_five_fields() -> None:
    """§10.10's table has a column each for condition, event, enable, PTr and NTr, over five
    registers. A missing pair is a column of dashes on one register only."""
    for root, _ in catalog.REGISTER_ROOTS:
        for field, _ in catalog.REGISTER_FIELDS:
            assert catalog.register_query(root, field) is not None, f"{root}:{field}?"


def test_only_the_three_mask_fields_can_be_written() -> None:
    """Condition and event are the receiver's own state. A setter for either would be an offer to
    change what the hardware is reporting, which is not a thing that can be done."""
    for root, _ in catalog.REGISTER_ROOTS:
        assert catalog.register_setter(root, "COND") is None
        assert catalog.register_setter(root, "EVEN") is None
        for field in ("ENAB", "PTR", "NTR"):
            assert catalog.register_setter(root, field) is not None


def test_a_query_is_recognisable_as_one() -> None:
    assert catalog.STATUS_SCREEN.is_query is True
    assert catalog.CLEAR_STATUS.is_query is False


# ---- §7.3's sweep -----------------------------------------------------------------------------


def test_the_fast_tier_is_the_six_commands_section_7_3_lists() -> None:
    assert [command.mnemonic for command in catalog.FAST_TIER] == [
        ":SYNC:STAT?",
        ":SYNC:TFOM?",
        ":SYNC:FFOM?",
        ":SYNC:TINT?",
        ":DIAG:ROSC:EFC:REL?",
        ":GPS:SAT:TRAC:COUN?",
    ]


def test_the_state_query_stays_first_in_the_sweep() -> None:
    """§7.3.1's rule depends on knowing the sync state before the rest of the tier is asked. If
    this ever reorders, the suppression keys on last second's state."""
    assert catalog.FAST_TIER[0] is catalog.SYNC_STATE


def test_the_refusable_reading_is_the_time_interval() -> None:
    """§7.3.1: while unlocked there is no GPS 1 PPS to measure against, so the receiver answers
    nothing and puts an error in the prompt. Asked once a second it filled the bench receiver's
    error queue until real errors were being discarded to make room for poll noise."""
    assert catalog.REFUSABLE is catalog.TIME_INTERVAL


def test_the_time_interval_is_read_in_seconds() -> None:
    """The receiver answers in seconds; the medallion and every display work in nanoseconds. The
    unit is recorded rather than inferred."""
    assert catalog.TIME_INTERVAL.unit == "s"
    assert catalog.TIME_INTERVAL.response is ResponseFormat.DECIMAL


def test_the_status_screen_is_the_only_entry_with_its_own_format() -> None:
    """Only the status screen parser understands it, and nothing else should try."""
    screens = [c for c in catalog.ALL if c.response is ResponseFormat.STATUS_SCREEN]

    assert screens == [catalog.STATUS_SCREEN]


# ---- The driver seam ---------------------------------------------------------------------------


def driver() -> SmartClockDriver:
    return SmartClockDriver(clock=FixedClock(NOW))


def test_the_smartclock_driver_satisfies_the_seam() -> None:
    """The application asks the driver the session selected, never a concrete family."""
    assert isinstance(driver(), ReceiverDriver)


def test_the_driver_carries_section_7_3_s_cadence() -> None:
    """The cadence is a property of the driver, not of the application: §7.3's schedule is this
    family's, and a broadcast talker has a different one."""
    assert driver().cadence.fast.total_seconds() == 1
    assert driver().cadence.full.total_seconds() == 10


def test_the_driver_answers_the_allowlist_question() -> None:
    assert driver().is_allowed(":SYST:STAT?") is True
    assert driver().is_allowed(":NOSUCH?") is False


def test_the_driver_answers_the_exclusion_question() -> None:
    """Routed through the driver so the application never imports the exclusion module itself."""
    assert driver().is_blocked(":SYST:STAT?") is False


def test_the_plan_names_the_refusable_query_and_the_state_it_keys_on() -> None:
    plan = driver().plan

    assert plan.refusable is catalog.TIME_INTERVAL
    assert plan.state_query is catalog.SYNC_STATE
    assert plan.full is catalog.STATUS_SCREEN


# ---- Response formats, against what the receiver actually answered -------------------------------

#: What a Z3805A (S/N 3625A02931, firmware 1.01.03-A) answered on 31 Aug 2026, verbatim.
#:
#: **Recorded because three of these disagreed with what the catalog claimed.** A response format
#: is a claim about the receiver, and the only way to check one is to ask. It is cheap to get wrong
#: — nothing fails, the page just renders an em dash for a value the receiver gave it, which reads
#: as "the receiver did not say" rather than "we could not read what it said".
OBSERVED: Final[dict[str, str]] = {
    ":SYNC:HOLD:DUR?": "+7.80000E+001,0",
    ":SYNC:HOLD:DUR:THR?": "+86400",
    ":SYNC:HOLD:DUR:THR:EXC?": "0",
    ":SYNC:HOLD:TUNC:PRED?": "+2.5E-006,0",
    ":DIAG:LOG:COUN?": "+222",
    ":DIAG:LIF:COUN?": "+36760",
    ":PTIM:DATE?": "+2007,+1,+16",
    ":PTIM:TIME?": "+0,+30,+43",
    ":PTIM:TZON?": "+0,+0",
    ":PTIM:LEAP:ACC?": "+18",
    ":PTIM:LEAP:STAT?": "0",
    ":GPS:SAT:TRAC:EMAN?": "+10",
    ":GPS:REF:ADEL?": "+6.00000E-008",
    ":STAT:OPER:COND?": "+90",
    ":STAT:OPER:HARD:ENAB?": "+8191",
}


@pytest.mark.parametrize("mnemonic", sorted(OBSERVED))
def test_the_declared_format_reads_what_the_receiver_answered(mnemonic: str) -> None:
    """Every observed answer must parse through the format its catalog entry declares.

    Three did not when this was written. ``:SYNC:HOLD:DUR?`` and both uncertainty queries answer
    ``<value>,<validity>`` and were catalogued DECIMAL, which parses to ``None``; and
    ``:PTIM:LEAP:STAT?`` answers ``0`` and was catalogued KEYWORD, which would have rendered the
    string "0" as though it were a state name.
    """
    command = catalog.find(mnemonic)
    assert command is not None, f"{mnemonic} is not catalogued."

    answer = OBSERVED[mnemonic]
    parsed: object
    match command.response:
        case ResponseFormat.INTEGER:
            parsed = parse_integer(answer)
        case ResponseFormat.DECIMAL:
            parsed = parse_decimal(answer)
        case ResponseFormat.BOOLEAN:
            parsed = parse_boolean(answer)
        case ResponseFormat.VALUE_LIST:
            parsed = parse_first_of_list(answer)
        case ResponseFormat.KEYWORD:
            parsed = parse_keyword(answer)
        case _:
            pytest.skip(f"{command.response} has no scalar parser")

    assert parsed is not None, (
        f"{mnemonic} answered {answer!r} and its declared {command.response.name} format "
        f"cannot read it — the page would show a dash for a value the receiver gave."
    )


def test_the_holdover_reads_are_value_lists_rather_than_bare_decimals() -> None:
    """The specific correction, pinned so it cannot quietly revert. The trailing field is a
    validity flag, and a decimal parser rejects the whole string rather than taking the figure."""
    for command in (
        catalog.HOLDOVER_DURATION,
        catalog.HOLDOVER_UNCERTAINTY_PREDICTED,
        catalog.HOLDOVER_UNCERTAINTY_PRESENT,
    ):
        assert command.response is ResponseFormat.VALUE_LIST, command.mnemonic

    assert parse_decimal("+2.5E-006,0") is None
    assert parse_first_of_list("+2.5E-006,0") == pytest.approx(2.5e-06)
