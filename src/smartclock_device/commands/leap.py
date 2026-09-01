"""§10.14's leap-second query order, which is a rule about the receiver rather than about a page.

**The date and the direction answer only while an announcement stands.** With ``:PTIM:LEAP:STAT?``
reporting ``0`` there is no announced leap second to have a date or a direction, and the receiver
**rejects** the question rather than returning a null — measured on the bench receiver, where both
answer ``E-230``.

So the state is read first and the other two are asked only if it says yes. A page that asked all
four on arrival would put two errors in the receiver's error queue every time it was opened, and
§7.2's error-queue discipline would then report them against whatever ran next.

This lives here, in the device layer, so it can be asserted without a receiver and without a
window: the ordering is a fact about the instrument, not a detail of how one page happens to be
written.
"""

from __future__ import annotations

from typing import Final

from smartclock_device.drivers.capability import Capability

#: Asked on arrival and on every reconnect. Both always answer.
#:
#: The accumulated offset is the figure worth showing unconditionally: it is what anyone comparing
#: GPS time to UTC needs, it is always available, and it is the one number on the card that earns
#: the section's title on a day when nothing is announced.
FIRST: Final[tuple[Capability, ...]] = (Capability.LEAP_ACCUMULATED, Capability.LEAP_STATE)

#: Asked only when the state reports an announcement.
WHEN_ANNOUNCED: Final[tuple[Capability, ...]] = (
    Capability.LEAP_DATE,
    Capability.LEAP_DURATION,
)


def follow_up(announced: bool | None) -> tuple[Capability, ...]:
    """What to ask after the state, given what the state said.

    ``None`` — the state could not be read — asks nothing. An unreadable state is not permission
    to guess: the two follow-ups are precisely the queries that fail when the guess is wrong.
    """
    return WHEN_ANNOUNCED if announced else ()
