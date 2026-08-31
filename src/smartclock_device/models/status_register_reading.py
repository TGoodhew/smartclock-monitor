"""The five readable fields of one status register, as the receiver last answered them.

**Reading the event field clears it.** That is SCPI's rule and the 58503A guide restates it: an
event bit is cleared when the event register is read. So a page that polled this on a timer would
consume the very latches a user opened it to see, which is why §10.10 gives the page a Refresh
button rather than a cadence.
"""

from __future__ import annotations

from dataclasses import dataclass

from smartclock_device.models.status_register_map import StatusBit, StatusRegisterMap

#: The widest register the receiver reports, and the width the C# original's ``int`` fixed. Bits
#: above this are not scanned for, because there is nothing that could set them.
_REGISTER_WIDTH = 32


def _test(register: int | None, bit: int) -> bool | None:
    """Whether one bit is set, or ``None`` when the field was never read."""
    return None if register is None else (register & (1 << bit)) != 0


@dataclass(frozen=True, slots=True)
class StatusBitReading:
    """One row of the §10.10 register table."""

    #: Which bit this is.
    bit: int

    #: What it means, or ``None`` when this register does not document it.
    definition: StatusBit | None = None

    #: Whether the condition is present.
    condition: bool | None = None

    #: Whether an event is latched.
    event: bool | None = None

    #: Whether the bit is enabled to reach the summary.
    enable: bool | None = None

    #: Whether a false-to-true transition latches an event.
    positive_transition: bool | None = None

    #: Whether a true-to-false transition latches an event.
    negative_transition: bool | None = None

    @property
    def meaning_text(self) -> str:
        """What the meaning column shows.

        §10.10: where a bit meaning is unknown, show the raw state and "(see documentation)" rather
        than inventing a label. With OQ-1 answered this is now the exception — Hardware bit 5 is
        documented as unused, and anything past a register's table is unmapped.
        """
        return self.definition.meaning if self.definition is not None else "(see documentation)"

    @property
    def is_documented(self) -> bool:
        """Whether this bit's meaning is known."""
        return self.definition is not None

    @property
    def is_fault(self) -> bool:
        """Whether this bit being set is bad news."""
        return self.definition is not None and self.definition.is_fault

    @property
    def is_event(self) -> bool:
        """Whether it is a latched event rather than a live condition."""
        return self.definition is not None and self.definition.is_event

    @property
    def is_raised(self) -> bool:
        """Whether this bit is currently reporting a fault.

        A fault bit counts as raised by its condition, or — for the two Hardware entries that are
        events rather than conditions — by its latched event, since a time-interval measurement
        failure has no lasting condition to read.
        """
        return self.is_fault and (self.condition is True or (self.is_event and self.event is True))


@dataclass(frozen=True, slots=True)
class StatusRegisterReading:
    """One register's five fields, any of which may not have been read."""

    #: Which register this is.
    register: StatusRegisterMap

    #: Live conditions.
    condition: int | None = None

    #: Latched events, cleared by the read that returned them.
    events: int | None = None

    #: Which bits are enabled to reach the summary bit.
    enable: int | None = None

    #: Which false-to-true transitions latch an event.
    positive_transition: int | None = None

    #: Which true-to-false transitions latch an event.
    negative_transition: int | None = None

    @property
    def _fields(self) -> tuple[int | None, ...]:
        return (
            self.condition,
            self.events,
            self.enable,
            self.positive_transition,
            self.negative_transition,
        )

    @property
    def has_any_value(self) -> bool:
        """Whether anything at all was read."""
        return any(value is not None for value in self._fields)

    @property
    def bit_count(self) -> int:
        """How many bits the table should show.

        The documented bits, extended to cover anything actually set that the table does not
        document. §10.10 requires an undocumented bit to be shown with its raw state rather than
        hidden, and a firmware revision that sets bit 14 must not simply vanish from the page.
        """
        highest = self.register.highest_documented_bit

        for value in self._fields:
            if value is None:
                continue
            for bit in range(_REGISTER_WIDTH - 1, highest, -1):
                if value & (1 << bit):
                    highest = bit
                    break

        return highest + 1

    @property
    def rows(self) -> tuple[StatusBitReading, ...]:
        """The decoded rows, one per bit."""
        return tuple(
            StatusBitReading(
                bit=bit,
                definition=self.register.bit_at(bit),
                condition=_test(self.condition, bit),
                event=_test(self.events, bit),
                enable=_test(self.enable, bit),
                positive_transition=_test(self.positive_transition, bit),
                negative_transition=_test(self.negative_transition, bit),
            )
            for bit in range(self.bit_count)
        )
