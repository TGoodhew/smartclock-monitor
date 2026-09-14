"""The five condition registers and every documented bit in them.

**From the 58503A/59551A Operating and Programming Guide, Command Reference 5-36 to 5-39**
("Status Reporting System", Figure 5-1). This is the answer to OQ-1, which §10.10 defers to for
exactly this table and which was open until the guide reached the manual library.

§10.10 says that where a bit meaning is unknown, the page shows the raw state and "(see
documentation)" rather than inventing a label. That fallback stays — Hardware bit 5 is documented
as not used, and a firmware revision may set something no table here covers — but it is now the
exception rather than most of the page.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class StatusBit:
    """What one bit of a status register means."""

    #: Its position, zero-based.
    bit: int

    #: What the receiver is saying when it is set.
    meaning: str

    #: Whether it is a latched event rather than a live condition.
    #:
    #: An event bit is set when the thing happens and cleared at power-up or when the event
    #: register is read; a condition bit tracks the state and clears itself when the state ends.
    is_event: bool = False

    #: Whether "set" is bad news.
    #:
    #: Most of the Hardware register is faults, most of Operation is not, and rendering them the
    #: same way would put a red mark against a locked receiver.
    is_fault: bool = False

    #: Which label on §10.4's health monitor covers this bit, or ``None`` when none does.
    #:
    #: The health block prints six labels and the Hardware register has twelve bits, so the card
    #: cannot be a bit-for-bit rendering of the register and never was. What this records is the
    #: **other direction**: given a bit the receiver has set, is there a label on the card that
    #: would already be showing it as failed? Two bits answer no, and a receiver with either
    #: reports `HEALTH MONITOR ... [ OK ]` while the fault is real (#112).
    #:
    #: **A hypothesis, and marked as one.** No capture in the corpus has ever carried a failing
    #: health monitor — a bench receiver in good health is the only kind there is — so the pairing
    #: is read off the label names and the manual's bit meanings, corroborated by Lady Heather
    #: grouping the same bits the same way (#98). The consequence of a wrong pairing is a duplicate
    #: line about a fault, in a state no unit here has ever reached.
    health_label: str | None = None


@dataclass(frozen=True, slots=True)
class StatusRegisterMap:
    """One status register: its SCPI node, its name, and what its bits mean."""

    #: The SCPI node under ``:STAT:`` — ``OPER``, ``OPER:HARD``, and so on.
    node: str

    #: What the register is called.
    name: str

    #: One line on what the register is for.
    summary: str

    #: The documented bits, in order.
    bits: tuple[StatusBit, ...] = ()

    def bit_at(self, bit: int) -> StatusBit | None:
        """The meaning of a bit, or ``None`` when this register does not document one."""
        return next((candidate for candidate in self.bits if candidate.bit == bit), None)

    @property
    def highest_documented_bit(self) -> int:
        """The highest documented bit, which is how far a table needs to go.

        ``-1`` for a register with no documented bits, so that a bit count derived from it is zero.
        """
        return max((b.bit for b in self.bits), default=-1)


#: The Operation register: what the receiver is doing.
OPERATION: Final = StatusRegisterMap(
    node="OPER",
    name="Operation",
    summary="What the receiver is doing, and summaries of the three subgroups below it.",
    bits=(
        StatusBit(0, "Power-up summary"),
        StatusBit(1, "Locked to GPS"),
        StatusBit(2, "Holdover summary"),
        StatusBit(3, "Position hold (clear = surveying)"),
        StatusBit(4, "1 PPS reference valid"),
        StatusBit(5, "Hardware summary"),
        StatusBit(6, "Diagnostic log almost full", is_fault=True),
    ),
)

#: The Hardware register: continuously monitored health.
#:
#: **Every bit here is a fault.** Set means the named bad thing is true, which is the opposite
#: polarity to the ticks §10.4's health monitor draws — that card inverts these, and its six labels
#: each cover more than one bit.
HARDWARE: Final = StatusRegisterMap(
    node="OPER:HARD",
    name="Hardware",
    summary=(
        "Continuously monitored hardware health. Every bit is a fault: set means the fault is "
        "present."
    ),
    bits=(
        StatusBit(0, "Self-test failure", is_fault=True, health_label="Self Test"),
        StatusBit(1, "+15 V supply out of tolerance", is_fault=True, health_label="Int Pwr"),
        StatusBit(2, "−15 V supply out of tolerance", is_fault=True, health_label="Int Pwr"),
        StatusBit(3, "+5 V supply out of tolerance", is_fault=True, health_label="Int Pwr"),
        StatusBit(4, "Oven supply out of tolerance", is_fault=True, health_label="Oven Pwr"),
        StatusBit(6, "EFC voltage near full scale", is_fault=True, health_label="EFC"),
        StatusBit(7, "EFC voltage at full scale", is_fault=True, health_label="EFC"),
        StatusBit(8, "GPS 1 PPS failure", is_fault=True, health_label="GPS Rcv"),
        StatusBit(9, "GPS failure", is_fault=True, health_label="GPS Rcv"),
        StatusBit(10, "Time interval measurement failed", is_event=True, is_fault=True),
        StatusBit(11, "EEPROM write failed", is_event=True, is_fault=True),
        StatusBit(12, "Internal reference failure", is_fault=True, health_label="OCXO"),
    ),
)

#: The Holdover register: which holdover state, and whether it is over threshold.
HOLDOVER: Final = StatusRegisterMap(
    node="OPER:HOLD",
    name="Holdover",
    summary=(
        "Which holdover state the receiver is in, and whether it has passed the user threshold."
    ),
    bits=(
        StatusBit(0, "Holding", is_fault=True),
        StatusBit(1, "Waiting to recover"),
        StatusBit(2, "Recovering"),
        StatusBit(3, "Exceeding user threshold", is_fault=True),
    ),
)

#: The Power-up register: what has been achieved since power was applied.
#:
#: These are the opposite of faults — each is something good that has happened since power-up,
#: cleared at power-up and set when it occurs.
POWER_UP: Final = StatusRegisterMap(
    node="OPER:POW",
    name="Power-up",
    summary=(
        "What the receiver has achieved since power was applied. Cleared at power-up, set as each "
        "happens."
    ),
    bits=(
        StatusBit(0, "First satellite tracked"),
        StatusBit(1, "Oscillator oven warm"),
        StatusBit(2, "Date and time valid", is_event=True),
    ),
)

#: The Questionable register.
QUESTIONABLE: Final = StatusRegisterMap(
    node="QUES",
    name="Questionable",
    summary="Conditions that call the receiver's own output into question.",
    bits=(
        StatusBit(0, "Time reset against the satellites", is_event=True, is_fault=True),
        StatusBit(1, "User-reported"),
    ),
)


def faults_with_no_health_label(condition: int) -> tuple[StatusBit, ...]:
    """The Hardware faults a set register reports that §10.4's health block cannot show.

    Bits 10 and 11 — *time interval measurement failed* and *EEPROM write failed* — have no label
    on the health monitor, so a receiver with either prints `[ OK ]` across all six and this
    application draws six green ticks. #112, and #98's audit against Lady Heather is what found it:
    she surfaces the EEPROM bit as an alarm of its own, which is what drew attention to a bit with
    nowhere to go.

    **Undocumented bits count too.** A bit the map has no entry for is by definition a bit no label
    covers, and a firmware that sets one is saying something this port cannot name — which is worth
    reporting as exactly that rather than dropping. `test_registers_against_screen.py` asserts the
    bench receiver sets none.
    """
    named = []
    for bit in range(16):
        if not condition & (1 << bit):
            continue
        meaning = HARDWARE.bit_at(bit)
        if meaning is None:
            named.append(StatusBit(bit, f"Hardware bit {bit} (see documentation)", is_fault=True))
        elif meaning.health_label is None:
            named.append(meaning)
    return tuple(named)


#: Every register, in the order §10.10's picker lists them.
ALL: Final[tuple[StatusRegisterMap, ...]] = (
    OPERATION,
    HARDWARE,
    HOLDOVER,
    POWER_UP,
    QUESTIONABLE,
)


def by_node(node: str | None) -> StatusRegisterMap | None:
    """Find a register by its SCPI node, case-insensitively, or ``None``."""
    if node is None:
        return None

    wanted = node.upper()
    return next((m for m in ALL if m.node.upper() == wanted), None)
