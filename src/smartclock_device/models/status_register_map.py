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
        StatusBit(0, "Self-test failure", is_fault=True),
        StatusBit(1, "+15 V supply out of tolerance", is_fault=True),
        StatusBit(2, "−15 V supply out of tolerance", is_fault=True),
        StatusBit(3, "+5 V supply out of tolerance", is_fault=True),
        StatusBit(4, "Oven supply out of tolerance", is_fault=True),
        StatusBit(6, "EFC voltage near full scale", is_fault=True),
        StatusBit(7, "EFC voltage at full scale", is_fault=True),
        StatusBit(8, "GPS 1 PPS failure", is_fault=True),
        StatusBit(9, "GPS failure", is_fault=True),
        StatusBit(10, "Time interval measurement failed", is_event=True, is_fault=True),
        StatusBit(11, "EEPROM write failed", is_event=True, is_fault=True),
        StatusBit(12, "Internal reference failure", is_fault=True),
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
