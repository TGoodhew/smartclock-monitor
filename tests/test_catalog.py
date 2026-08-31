"""The catalog is an allowlist, and the two safety mechanisms check each other.

§8.1's architecture is that a command not catalogued does not exist. That only holds if the
catalog cannot contain an excluded command, and the check for that is here rather than in a comment
— so the allowlist and the exclusion list are each other's test.
"""

from __future__ import annotations

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.commands.blocked import is_blocked
from smartclock_device.commands.scpi_command import ResponseFormat, SafetyTier
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.smartclock import SmartClockDriver


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


def test_every_entry_is_safe_until_a_setter_is_added() -> None:
    """This subset is reads and the status clear. When the first tier C setter lands, §8.3's
    confirmation flow lands with it — this assertion is what will notice."""
    assert all(command.tier is SafetyTier.SAFE for command in catalog.ALL)


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
