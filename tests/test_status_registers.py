"""The §10.10 status registers: the bit tables, and decoding a reading into rows.

The tables answer OQ-1 out of the 58503A/59551A guide's Command Reference 5-36 to 5-39. What is
tested here is not that the guide is right — nothing here can establish that — but that the table
says what the guide says, that a reading decodes into the rows §10.10 draws, and that an
undocumented bit survives to the page instead of vanishing from it.
"""

from __future__ import annotations

import pytest

from smartclock_device.models import status_register_map as maps
from smartclock_device.models.status_register_map import StatusRegisterMap
from smartclock_device.models.status_register_reading import StatusRegisterReading

# ---- The tables ---------------------------------------------------------------------------


def test_the_five_registers_are_the_ones_section_10_10_lists() -> None:
    assert [m.node for m in maps.ALL] == ["OPER", "OPER:HARD", "OPER:HOLD", "OPER:POW", "QUES"]


@pytest.mark.parametrize("node", ["OPER:HARD", "oper:hard", "OpEr:HaRd"])
def test_a_register_is_found_by_node_however_it_is_cased(node: str) -> None:
    assert maps.by_node(node) == maps.HARDWARE


@pytest.mark.parametrize("node", [None, "", "OPER:NOSUCH", "HARD"])
def test_an_unknown_node_is_none(node: str | None) -> None:
    assert maps.by_node(node) is None


def test_every_hardware_bit_is_a_fault() -> None:
    """The register's polarity is the opposite of §10.4's health card, which inverts these."""
    assert all(bit.is_fault for bit in maps.HARDWARE.bits)


def test_hardware_bit_5_is_undocumented() -> None:
    """The guide documents it as not used. §10.10's "(see documentation)" fallback is for exactly
    this, and it is now the exception rather than most of the page."""
    assert maps.HARDWARE.bit_at(5) is None
    assert maps.HARDWARE.bit_at(4) is not None
    assert maps.HARDWARE.bit_at(6) is not None


def test_the_two_hardware_events_are_the_ones_with_no_lasting_condition() -> None:
    """A time-interval measurement failure and a failed EEPROM write are moments, not states."""
    events = {bit.bit for bit in maps.HARDWARE.bits if bit.is_event}

    assert events == {10, 11}


def test_the_power_up_register_records_achievements_rather_than_faults() -> None:
    """Each is something good that has happened since power was applied."""
    assert not any(bit.is_fault for bit in maps.POWER_UP.bits)


def test_operation_marks_only_the_almost_full_log_as_a_fault() -> None:
    """Most of Operation is not a fault; rendering it as one would put a red mark against a locked
    receiver."""
    faults = {bit.bit for bit in maps.OPERATION.bits if bit.is_fault}

    assert faults == {6}


@pytest.mark.parametrize(
    ("register", "highest"),
    [
        (maps.OPERATION, 6),
        (maps.HARDWARE, 12),
        (maps.HOLDOVER, 3),
        (maps.POWER_UP, 2),
        (maps.QUESTIONABLE, 1),
    ],
)
def test_the_highest_documented_bit_is_how_far_a_table_goes(
    register: StatusRegisterMap, highest: int
) -> None:
    assert register.highest_documented_bit == highest


def test_a_register_with_no_documented_bits_has_no_highest() -> None:
    """``-1``, so that a bit count derived from it is zero rather than one."""
    assert StatusRegisterMap(node="X", name="X", summary="X").highest_documented_bit == -1


def test_every_documented_bit_is_reachable_by_its_own_index() -> None:
    for register in maps.ALL:
        for bit in register.bits:
            assert register.bit_at(bit.bit) == bit


# ---- Decoding a reading -------------------------------------------------------------------


def test_a_reading_of_nothing_has_no_values() -> None:
    reading = StatusRegisterReading(register=maps.OPERATION)

    assert reading.has_any_value is False
    assert all(row.condition is None for row in reading.rows)


@pytest.mark.parametrize(
    "reading",
    [
        StatusRegisterReading(register=maps.OPERATION, condition=0),
        StatusRegisterReading(register=maps.OPERATION, events=0),
        StatusRegisterReading(register=maps.OPERATION, enable=0),
        StatusRegisterReading(register=maps.OPERATION, positive_transition=0),
        StatusRegisterReading(register=maps.OPERATION, negative_transition=0),
    ],
)
def test_a_zero_is_a_value_and_not_an_absence(reading: StatusRegisterReading) -> None:
    """Zero is what a healthy register answers. ``None`` means the field was never read, which is a
    different claim and renders differently."""
    assert reading.has_any_value is True


def test_a_condition_decodes_bit_by_bit() -> None:
    """Bit 1 is "Locked to GPS", bit 4 is "1 PPS reference valid"."""
    reading = StatusRegisterReading(register=maps.OPERATION, condition=0b0001_0010)

    states = {row.bit: row.condition for row in reading.rows}

    assert states[1] is True
    assert states[4] is True
    assert states[0] is False
    assert states[2] is False


def test_an_unread_field_stays_none_across_every_row() -> None:
    """§11.1: not read is not the same as clear, and the row must be able to say so."""
    reading = StatusRegisterReading(register=maps.OPERATION, condition=0b10)

    for row in reading.rows:
        assert row.event is None
        assert row.enable is None
        assert row.condition is not None


def test_a_table_covers_the_documented_bits_by_default() -> None:
    reading = StatusRegisterReading(register=maps.HARDWARE, condition=0)

    assert reading.bit_count == 13
    assert len(reading.rows) == 13


def test_an_undocumented_set_bit_extends_the_table() -> None:
    """§10.10 requires an undocumented bit to be shown with its raw state rather than hidden: a
    firmware revision that sets bit 14 must not simply vanish from the page."""
    reading = StatusRegisterReading(register=maps.QUESTIONABLE, condition=1 << 14)

    assert reading.bit_count == 15
    assert reading.rows[14].condition is True
    assert reading.rows[14].is_documented is False
    assert reading.rows[14].meaning_text == "(see documentation)"


def test_the_table_extends_for_any_of_the_five_fields() -> None:
    """A latched event in an undocumented bit is as much a thing to show as a live condition."""
    reading = StatusRegisterReading(register=maps.QUESTIONABLE, events=1 << 9)

    assert reading.bit_count == 10


def test_the_highest_set_bit_wins() -> None:
    reading = StatusRegisterReading(
        register=maps.QUESTIONABLE, condition=1 << 5, events=1 << 20, enable=1 << 11
    )

    assert reading.bit_count == 21


def test_the_top_bit_is_reachable() -> None:
    """32 bits is the width the C# original's ``int`` fixed, and bit 31 is inside it."""
    reading = StatusRegisterReading(register=maps.QUESTIONABLE, condition=1 << 31)

    assert reading.bit_count == 32
    assert reading.rows[31].condition is True


def test_a_documented_bit_carries_its_meaning_into_the_row() -> None:
    reading = StatusRegisterReading(register=maps.HARDWARE, condition=0)

    assert reading.rows[9].meaning_text == "GPS failure"
    assert reading.rows[9].is_documented is True
    assert reading.rows[9].is_fault is True


def test_the_negative_rail_keeps_its_minus_sign() -> None:
    """Not a hyphen. It sits directly beneath "+15 V" and "+5 V" in the guide's own table, and the
    string is byte-identical to WinZ3805A's — see the confusables note in ``pyproject.toml``."""
    bit = maps.HARDWARE.bit_at(2)

    assert bit is not None
    assert bit.meaning == "\N{MINUS SIGN}15 V supply out of tolerance"


# ---- Faults -------------------------------------------------------------------------------


def test_a_fault_condition_is_raised() -> None:
    reading = StatusRegisterReading(register=maps.HARDWARE, condition=1 << 9)

    assert reading.rows[9].is_raised is True


def test_a_clear_fault_is_not_raised() -> None:
    reading = StatusRegisterReading(register=maps.HARDWARE, condition=0)

    assert all(row.is_raised is False for row in reading.rows)


def test_an_event_only_fault_is_raised_by_its_latch() -> None:
    """Bit 10 has no lasting condition to read — a time interval measurement either failed or it
    did not — so the latched event is what raises it."""
    reading = StatusRegisterReading(register=maps.HARDWARE, condition=0, events=1 << 10)

    assert reading.rows[10].is_event is True
    assert reading.rows[10].is_raised is True


def test_a_non_fault_bit_is_never_raised_however_it_reads() -> None:
    """Bit 1 of Operation is "Locked to GPS" — set is good news."""
    reading = StatusRegisterReading(register=maps.OPERATION, condition=0b10, events=0b10)

    assert reading.rows[1].is_raised is False


def test_a_latched_event_on_a_condition_fault_does_not_raise_it_alone() -> None:
    """Bit 9 is a live condition, not an event. Its latch is history; the card reports now."""
    reading = StatusRegisterReading(register=maps.HARDWARE, condition=0, events=1 << 9)

    assert reading.rows[9].is_event is False
    assert reading.rows[9].is_raised is False


def test_an_undocumented_bit_is_never_a_fault() -> None:
    """Inventing a severity for a bit whose meaning is unknown is the one thing §10.10 forbids."""
    reading = StatusRegisterReading(register=maps.QUESTIONABLE, condition=1 << 14)

    assert reading.rows[14].is_fault is False
    assert reading.rows[14].is_raised is False
