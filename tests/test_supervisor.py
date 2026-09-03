"""§7.2's reconnect policy.

The session already reported ``LOST`` — on a fault immediately, and on three consecutive timeouts —
and nothing acted on it. An unplugged adapter stopped the poll loop and left the last reading on
screen looking current, which is the worst of the three things it could have done.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.transport.fake import FakeTransport
from smartclock_monitor.services.session import ConnectionState, DeviceSession
from smartclock_monitor.services.supervisor import (
    FIRST_BACKOFF,
    MAXIMUM_BACKOFF,
    Supervisor,
    backoff_seconds,
)

PROBE = timedelta(milliseconds=5)
IDENTITY = "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"


def clock() -> FixedClock:
    return FixedClock(NOW)


async def a_session(*, answering: bool = True) -> DeviceSession:
    responses = {"*CLS": "", "*IDN?": IDENTITY} if answering else {"*CLS": ""}
    session = DeviceSession(
        FakeTransport(responses, default_response=""), SmartClockDriver(clock=clock()), clock()
    )
    await session.open(probe=PROBE)
    return session


# ---- The backoff -------------------------------------------------------------------------------


def test_the_backoff_is_the_one_section_7_2_gives() -> None:
    """*"retry with exponential backoff (2 s, 4 s, 8 s, capped 30 s)"*, verbatim."""
    assert [backoff_seconds(attempt) for attempt in range(1, 7)] == [2, 4, 8, 16, 30, 30]


def test_the_backoff_is_capped() -> None:
    """Without the cap the fourteenth attempt waits four and a half hours, which is
    indistinguishable from having given up."""
    assert backoff_seconds(20) == MAXIMUM_BACKOFF
    assert backoff_seconds(1) == FIRST_BACKOFF


async def _stops_promptly(task: asyncio.Task[None]) -> None:
    """Cancel a supervisor and assert it actually stops.

    **Bounded, because the failure this guards against is a hang.** A cleanup path that swallows
    the task's own ``CancelledError`` — ``suppress(CancelledError)`` around an ``await`` cannot
    tell whose error it caught — leaves the supervisor going round its ``while True`` for ever,
    since a task is only cancelled once. Written as a bare ``await task`` this suite then hung
    rather than failed: two CI jobs sat at sixteen minutes against their own two-minute twins, and
    a hang says nothing about which test caused it.

    Two seconds is enormous for a loop whose backoff the tests set to zero.
    """
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2.0)


# ---- The cycle ---------------------------------------------------------------------------------


def test_it_reconnects_after_the_link_is_lost() -> None:
    """The whole point. A supervisor that connected once would be what was there before."""
    opened: list[DeviceSession] = []

    async def run() -> None:
        async def connect() -> DeviceSession | None:
            session = await a_session()
            opened.append(session)
            # Drop it as soon as the supervisor starts polling.
            session._state = ConnectionState.LOST
            return session

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            # The cycle is under test, not §7.2's delays. Testing the two together would mean
            # either a slow suite or a flaky one.
            backoff=lambda _attempt: 0,
        )

        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.4)
        await _stops_promptly(task)

    asyncio.run(run())

    assert len(opened) >= 2, "it connected once and gave up"


def test_a_failed_connection_is_retried_too() -> None:
    """A receiver that is not there yet is the ordinary case on launch — the adapter is plugged in
    a moment later, and the application should find it without being restarted."""
    attempts = 0

    async def run() -> None:
        nonlocal attempts

        async def connect() -> DeviceSession | None:
            nonlocal attempts
            attempts += 1
            return None

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            backoff=lambda _attempt: 0,
        )

        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.3)
        await _stops_promptly(task)

    asyncio.run(run())

    assert attempts >= 2


def test_the_session_is_announced_and_withdrawn() -> None:
    """The window clears its command runner when the link drops, so pages disable their controls
    rather than offering buttons that would send into a closed port."""
    seen: list[str] = []

    async def run() -> None:
        async def connect() -> DeviceSession | None:
            session = await a_session()
            session._state = ConnectionState.LOST
            return session

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            on_session=lambda session: seen.append("open" if session is not None else "closed"),
            backoff=lambda _attempt: 0,
        )

        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.3)
        await _stops_promptly(task)

    asyncio.run(run())

    assert "open" in seen and "closed" in seen
    assert seen.index("open") < seen.index("closed")


def test_the_countdown_is_reported() -> None:
    """§9.11: thirty seconds of silence from an application is indistinguishable from a crash."""
    said: list[str] = []

    async def run() -> None:
        async def connect() -> DeviceSession | None:
            return None

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            on_status=said.append,
        )

        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(1.2)
        await _stops_promptly(task)

    asyncio.run(run())

    assert any("Retrying in" in line for line in said)
    assert any("second" in line for line in said)


def test_retry_now_cuts_the_countdown_short() -> None:
    attempts = 0

    async def run() -> None:
        nonlocal attempts

        async def connect() -> DeviceSession | None:
            nonlocal attempts
            attempts += 1
            return None

        supervisor = Supervisor(
            connect=connect, driver=SmartClockDriver(clock=clock()), clock=clock()
        )
        task = asyncio.ensure_future(supervisor.run())

        await asyncio.sleep(0.05)
        before = attempts
        for _ in range(3):
            supervisor.retry_now()
            await asyncio.sleep(0.05)

        await _stops_promptly(task)

        # Without retry_now the first backoff is two seconds, so nothing would have happened.
        assert attempts > before

    asyncio.run(run())


def test_not_staying_connected_waits_to_be_asked() -> None:
    """§10.12's "Reconnect automatically", off. A lost link is reported and left — but the task
    stays alive, because ending it would mean a Connect button with nothing behind it."""
    attempts = 0
    said: list[str] = []

    async def run() -> None:
        nonlocal attempts

        async def connect() -> DeviceSession | None:
            nonlocal attempts
            attempts += 1
            return None

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            on_status=said.append,
            stay_connected=False,
        )
        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.2)

        assert attempts == 1, "it must not keep trying"
        assert task.done() is False, "the task must stay alive to be asked again"

        supervisor.retry_now()
        await asyncio.sleep(0.1)
        assert attempts == 2, "asking must work"

        await _stops_promptly(task)

    asyncio.run(run())

    assert any("Not reconnecting" in line for line in said)


def test_stop_retrying_ends_the_cycle() -> None:
    async def run() -> None:
        async def connect() -> DeviceSession | None:
            return None

        supervisor = Supervisor(
            connect=connect, driver=SmartClockDriver(clock=clock()), clock=clock()
        )
        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.05)

        supervisor.stop_retrying()
        await asyncio.sleep(0.2)

        assert task.done() is True

    asyncio.run(run())


# ---- A deliberate disconnect (§9.7.5's other half of Connect) ------------------------------------


def test_a_deliberate_disconnect_does_not_reconnect_itself() -> None:
    """The gate #28 asks for, and the one a naive implementation fails.

    `stay_connected` defaults to on, so closing the session without stopping the cycle brings the
    port back within a backoff interval — a second or two after the user asked for it to go. That
    reads as a bug, and it is the reason `disconnect` is `stop_retrying` and a closed session
    together rather than just the close.
    """
    attempts = 0

    async def run() -> None:
        nonlocal attempts

        async def connect() -> DeviceSession | None:
            nonlocal attempts
            attempts += 1
            return await a_session()

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            backoff=lambda _: 0,
        )
        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.05)
        assert attempts == 1, "it must connect once to have something to disconnect from"

        supervisor.disconnect()
        await asyncio.sleep(0.2)

        assert attempts == 1, (
            f"it reconnected on its own after a deliberate disconnect ({attempts})"
        )
        assert supervisor.session is None, "the session is still open"
        assert supervisor.stopped_by_user is True

        await _stops_promptly(task)

    asyncio.run(run())


def test_a_deliberate_disconnect_does_not_read_as_a_fault() -> None:
    """§9.11: *"an intentional disconnect is not a fault"*. The sentence a lost link gets —
    "Not reconnecting" — is a report of failure, and it is the wrong one for an instruction the
    user gave."""
    said: list[str] = []

    async def run() -> None:
        async def connect() -> DeviceSession | None:
            return await a_session()

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            backoff=lambda _: 0,
        )
        supervisor.on_status = said.append
        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.05)

        supervisor.disconnect()
        await asyncio.sleep(0.2)
        await _stops_promptly(task)

    asyncio.run(run())

    assert any("Disconnected" in line for line in said), said
    assert not any("Not reconnecting" in line for line in said), said
    assert not any("Lost the connection" in line for line in said), said


def test_connecting_again_after_a_deliberate_disconnect_comes_back() -> None:
    """A disconnect that could not be undone would be a quit with extra steps."""
    attempts = 0

    async def run() -> None:
        nonlocal attempts

        async def connect() -> DeviceSession | None:
            nonlocal attempts
            attempts += 1
            return await a_session()

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            backoff=lambda _: 0,
        )
        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.05)

        supervisor.disconnect()
        await asyncio.sleep(0.1)
        # Read into locals rather than asserted twice on the property: mypy narrows the second
        # read to the first's result and calls everything after it unreachable.
        parked = supervisor.stopped_by_user
        assert parked, "the disconnect did not park the cycle"

        supervisor.reconnect()
        await asyncio.sleep(0.15)

        assert attempts == 2, f"it did not come back ({attempts})"
        resumed = supervisor.stopped_by_user
        assert not resumed, "it came back but still believes it is disconnected"

        await _stops_promptly(task)

    asyncio.run(run())


# ---- A deliberate reconnect (§10.12's Connect button) --------------------------------------------


def test_reconnecting_skips_the_countdown() -> None:
    """Asked for, so no penalty: the next attempt is the first one. A user who has just picked a
    port should not wait out a backoff earned by a previous failure."""
    attempts = 0
    said: list[str] = []

    async def run() -> None:
        nonlocal attempts

        async def connect() -> DeviceSession | None:
            nonlocal attempts
            attempts += 1
            session = await a_session()
            session._state = ConnectionState.LOST
            return session

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            on_status=said.append,
            # A punishing backoff, so anything that waits it out fails this test.
            backoff=lambda _attempt: 30,
        )
        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.2)

        before = attempts
        supervisor.reconnect()
        await asyncio.sleep(0.3)

        assert attempts > before, "it waited out a backoff it had been told to skip"

        await _stops_promptly(task)

    asyncio.run(run())


def test_a_deliberate_reconnect_is_not_reported_as_a_fault() -> None:
    """Closing the transport under a live poll is exactly the case the transport reports as a
    removal. Telling a user who has just pressed Connect that their adapter "was disconnected"
    would be the application misreading its own instruction."""
    said: list[str] = []

    async def run() -> None:
        async def connect() -> DeviceSession | None:
            return await a_session()

        supervisor = Supervisor(
            connect=connect,
            driver=SmartClockDriver(clock=clock()),
            clock=clock(),
            on_status=said.append,
            backoff=lambda _attempt: 0,
        )
        task = asyncio.ensure_future(supervisor.run())
        await asyncio.sleep(0.2)

        supervisor.reconnect()
        await asyncio.sleep(0.3)

        await _stops_promptly(task)

    asyncio.run(run())

    assert any("Reconnecting" in line for line in said)
    assert not any("disconnected" in line for line in said)
    assert not any("Lost the connection" in line for line in said)


def test_reconnecting_clears_a_stop() -> None:
    """Pressing Connect after Stop retrying must work. The two controls are not modes."""
    supervisor = Supervisor(
        connect=lambda: _none(), driver=SmartClockDriver(clock=clock()), clock=clock()
    )
    supervisor.stop_retrying()
    supervisor.reconnect()

    assert supervisor._stopped is False


async def _none() -> DeviceSession | None:
    return None
