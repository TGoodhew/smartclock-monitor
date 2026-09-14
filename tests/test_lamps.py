"""§10.9's two front-panel lamps, and the rules for borrowing them (#123).

`z3801.pdf`'s *Front Panel at a Glance*: *"User-definable indicators labeled Enabled and Active."*
Two lamps belong to the host software and four belong to the receiver — and until WinZ3805A's #462
both of ours said the same thing, which wasted one. **Enabled is the application's** (steady while
connected) and **Active is the receiver's** (lit while locked), which separates *"software is
attached to this one"* from *"this one is locked"* in front of a rack.

**The receiver owns them; these classes borrow them.** Every assertion below is about the borrow:
read the baseline first, put it back verbatim, never write from a remembered value, and never hold
a disconnect open for a lamp.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from smartclock_device.clock import FixedClock
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_device.transport.fake import FakeTransport
from smartclock_monitor.services.lamps import ActivityLamp, Lamps, LockLamp
from smartclock_monitor.services.session import DeviceSession

NOW: Final = datetime(2026, 9, 14, tzinfo=UTC)
PROBE: Final = timedelta(milliseconds=20)

ENABLED: Final = ":LED:ENAB?"
SET_ENABLED: Final = ":LED:ENABled ON"
ACTIVE: Final = ":LED:ACT?"


async def connected(**answers: str) -> tuple[DeviceSession, FakeTransport]:
    clock = FixedClock(NOW)
    # `default_response=""` is the prompt alone, which is what a receiver answers a setter with —
    # and what the fake needs, because it keys on the **whole written line** and a lamp write
    # carries its argument.
    transport = FakeTransport({"*IDN?": "SYMMETRICOM,Z3805A,1,1", **answers}, default_response="")
    session = DeviceSession(transport, SmartClockDriver(clock=clock), clock)
    await session.open(probe=PROBE)
    return session, transport


# ---- The borrow ---------------------------------------------------------------------------------


async def test_a_lamp_is_read_before_it_is_lit() -> None:
    """The baseline is what is owed back. Lighting first would lose it."""
    session, transport = await connected(**{ENABLED: "0", ":LED:ENABled": ""})
    lamp = ActivityLamp(session)

    assert await lamp.arm() is True

    sent = [line for line in transport.written if line.startswith(":LED:")]
    assert sent[0] == ENABLED
    assert sent[1] == SET_ENABLED


async def test_a_lamp_is_put_back_exactly_as_it_was_found() -> None:
    """A user who left it **on** gets it back on — which is why the baseline is read rather than
    assumed to be off."""
    session, transport = await connected(**{ENABLED: "1", ":LED:ENABled": ""})
    lamp = ActivityLamp(session)
    await lamp.arm()

    assert await lamp.restore() is True
    assert transport.written[-1] == ":LED:ENABled ON"
    assert lamp.is_lit is False


async def test_a_lamp_that_cannot_be_read_is_left_alone() -> None:
    """§11.1's rule seen from the write side: never act on a value nobody has. Lighting it anyway
    would leave nothing to put back."""
    session, transport = await connected(**{":LED:ENABled": ""})

    assert await ActivityLamp(session).arm() is False
    assert SET_ENABLED not in transport.written


async def test_arming_twice_does_not_overwrite_the_borrowed_value() -> None:
    """How *"the user left it on"* becomes *"the application decided it was off"*."""
    session, _ = await connected(**{ENABLED: "1", ":LED:ENABled": ""})
    lamp = ActivityLamp(session)
    await lamp.arm()

    assert await lamp.arm() is False
    assert lamp.is_lit is True


async def test_a_family_with_no_lamp_is_not_asked() -> None:
    """A talker has no lamp and no command channel to drive one, and the UCCM's `LED:GPSL?` is a
    query in another dialect and is not this. Asked of the driver, not decided here."""
    clock = FixedClock(NOW)
    transport = FakeTransport({})
    session = DeviceSession(transport, NmeaDriver(clock=clock), clock)

    lamp = ActivityLamp(session)
    assert lamp.is_supported is False
    assert await lamp.arm() is False
    assert transport.written == []


# ---- The lock lamp ------------------------------------------------------------------------------


async def test_the_lock_lamp_writes_only_when_the_state_changes() -> None:
    """**What makes a second-a-write affordable.** A flash per sweep was measured at 194% of the
    whole poll budget; a lock state changes a few times a day."""
    session, transport = await connected(**{ACTIVE: "0", ":LED:ACTive": ""})
    lamp = LockLamp(session)
    await lamp.arm()
    before = len(transport.written)

    assert await lamp.follow(SmartClockMode.LOCKED) is True
    assert await lamp.follow(SmartClockMode.LOCKED) is False
    assert await lamp.follow(SmartClockMode.HOLDOVER) is True
    assert await lamp.follow(SmartClockMode.HOLDOVER) is False

    writes = [line for line in transport.written[before:] if line.startswith(":LED:ACTive")]
    assert writes == [":LED:ACTive ON", ":LED:ACTive OFF"]


async def test_an_unarmed_lock_lamp_writes_nothing() -> None:
    """Following without borrowing would be writing to a lamp nobody asked for."""
    session, transport = await connected(**{ACTIVE: "0", ":LED:ACTive": ""})
    before = len(transport.written)

    assert await LockLamp(session).follow(SmartClockMode.LOCKED) is False
    assert transport.written[before:] == []


# ---- Both at once -------------------------------------------------------------------------------


async def test_both_lamps_are_armed_and_both_are_restored() -> None:
    session, transport = await connected(
        **{ENABLED: "0", ":LED:ENABled": "", ACTIVE: "1", ":LED:ACTive": ""}
    )
    lamps = Lamps()
    lamps.adopt(session)

    await lamps.arm()
    await lamps.restore()

    writes = [line for line in transport.written if line.startswith(":LED:") and " " in line]
    assert writes == [
        ":LED:ENABled ON",  # lit for this application
        ":LED:ACTive OFF",  # armed out, to be driven by the lock state
        ":LED:ACTive ON",  # put back as found
        ":LED:ENABled OFF",  # likewise
    ]


async def test_forgetting_a_session_writes_nothing() -> None:
    """A reconnect must not put a **previous** receiver's baseline onto a new one, and by the time
    a link has gone there is no wire to write over anyway."""
    session, transport = await connected(**{ENABLED: "0", ":LED:ENABled": ""})
    lamps = Lamps()
    lamps.adopt(session)
    await lamps.arm()
    before = len(transport.written)

    lamps.forget()
    await lamps.restore()

    assert transport.written[before:] == []


async def test_a_reading_only_schedules_a_write_when_the_lamp_is_borrowed() -> None:
    """`follow` is called from the poll loop's publish, which is synchronous and must not block on
    a lamp. With nothing borrowed it must not even schedule."""
    lamps = Lamps()

    lamps.follow(SmartClockMode.LOCKED)  # no session adopted: nothing to do, and nothing raised

    assert lamps.lock is None


@pytest.mark.parametrize("mode", [SmartClockMode.LOCKED, SmartClockMode.HOLDOVER])
async def test_the_preference_is_off_by_default(mode: SmartClockMode) -> None:
    """§10.9: *the only setting that makes the application change something on the receiver by
    itself*. A default of on would make that sentence a surprise rather than a promise."""
    del mode
    from smartclock_monitor.services.preferences import DEFAULTS

    assert DEFAULTS.drive_the_lamps is False
