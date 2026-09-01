"""§7.2's reconnect policy: connect, poll, and come back when the link goes.

The session already reports :attr:`ConnectionState.LOST` — on a fault immediately, and on three
consecutive timeouts — and until this existed nothing acted on it. An unplugged adapter stopped the
poll loop and left the last reading on screen looking current.

**The backoff is §7.2's:** 2 s, 4 s, 8 s, doubling, capped at 30. It exists because the common
reason a link goes is that somebody is doing something to the receiver — moving it, re-cabling it,
power-cycling it — and a retry every 200 ms during that achieves nothing except making the port
unavailable to whatever they are using instead.

**The countdown is shown, and the wait is interruptible.** §9.11's connection-lost state asks for a
retry countdown with *Retry now* and *Stop retrying*, because thirty seconds of silence from an
application is indistinguishable from a crash.

**Polling stops before the session is closed, not after.** A poll in flight against a transport
that is being closed underneath it is the one ordering that produces an exception nobody can act
on.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Final

from smartclock_device.clock import Clock
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_monitor.services.polling import PollingService, Reading
from smartclock_monitor.services.session import ConnectionState, DeviceSession

#: §7.2, verbatim: "retry with exponential backoff (2 s, 4 s, 8 s, capped 30 s)".
FIRST_BACKOFF: Final = 2
MAXIMUM_BACKOFF: Final = 30

#: How often the poll loop's health is checked. One second is the fast tier's own cadence, so this
#: notices a lost link no later than the next sweep would have.
_WATCH_INTERVAL: Final = 1.0

#: Opens a session, or returns ``None`` having already explained why.
Connect = Callable[[], Awaitable[DeviceSession | None]]


def backoff_seconds(attempt: int) -> int:
    """The delay before attempt number ``attempt`` (1-based), per §7.2."""
    if attempt <= 1:
        return FIRST_BACKOFF
    return int(min(MAXIMUM_BACKOFF, FIRST_BACKOFF * 2 ** (attempt - 1)))


@dataclass
class Supervisor:
    """Owns the connect–poll–reconnect cycle for one receiver."""

    connect: Connect
    driver: ReceiverDriver
    clock: Clock

    #: Called with each session as it opens, and with ``None`` as it closes, so the window can
    #: rewire the command runner rather than holding a session that has gone.
    on_session: Callable[[DeviceSession | None], None] | None = None

    on_reading: Callable[[Reading], None] | None = None

    #: Status text, in §9.11's terms.
    on_status: Callable[[str], None] | None = None

    #: §10.12's "Reconnect automatically". While off, a lost link is reported and left.
    stay_connected: bool = True

    #: How long to wait before attempt *n*. Injected so a test can drive the cycle without racing
    #: a two-second countdown — the delays are §7.2's policy, and the *cycle* is what this class
    #: is. Testing the two together would mean either a slow suite or a flaky one.
    backoff: Callable[[int], int] = backoff_seconds

    _retry_now: asyncio.Event = field(default_factory=asyncio.Event, init=False)
    _stopped: bool = field(default=False, init=False)
    _restarting: bool = field(default=False, init=False)
    _session: DeviceSession | None = field(default=None, init=False)

    # -- What the interface calls ----------------------------------------------------------------

    def retry_now(self) -> None:
        """Cut the countdown short."""
        self._retry_now.set()

    def stop_retrying(self) -> None:
        """Give up until asked again. §9.11 offers this beside the countdown."""
        self._stopped = True
        self._retry_now.set()

    def resume(self) -> None:
        self._stopped = False
        self._retry_now.set()

    def reconnect(self) -> None:
        """Drop the current session and connect again, now.

        **A deliberate restart, not a fault.** Closing the transport under a live poll is exactly
        the case the transport reports as a removal, and telling a user who has just pressed
        Connect that their adapter "was disconnected" would be the application misreading its own
        instruction. So the poll is asked to stop, and the cycle skips the countdown.
        """
        self._stopped = False
        self._restarting = True
        self._retry_now.set()

    @property
    def session(self) -> DeviceSession | None:
        return self._session

    # -- The cycle -------------------------------------------------------------------------------

    async def run(self) -> None:
        """Connect and poll until cancelled."""
        attempt = 0

        while True:
            # **Always yield, even when nothing else in this iteration will.** A connect that
            # fails immediately, with a short backoff, walks the whole cycle without awaiting
            # anything that suspends — so the event loop never runs and the interface freezes.
            # §7.2's two-second backoff hides it; a supervisor that *can* livelock the UI thread
            # is one that eventually will.
            await asyncio.sleep(0)

            # Cleared here rather than before each wait. Clearing immediately before waiting
            # discards a *Retry now* pressed while the countdown was being set up — the press
            # lands between the two statements and the wait then blocks for its full second as
            # though nobody had asked.
            self._retry_now.clear()

            session = await self.connect()

            if session is None:
                attempt += 1
                if not await self._wait_to_retry(attempt):
                    return
                continue

            attempt = 0
            self._adopt(session)
            try:
                await self._poll(session)
            finally:
                self._adopt(None)
                await _quietly_close(session)

            if self._restarting:
                # Asked for, so no countdown and no penalty: the next attempt is the first one.
                self._restarting = False
                self._retry_now.clear()
                attempt = 0
                continue

            attempt += 1
            if not await self._wait_to_retry(attempt):
                return

    def _adopt(self, session: DeviceSession | None) -> None:
        self._session = session
        if self.on_session is not None:
            self.on_session(session)

    async def _poll(self, session: DeviceSession) -> None:
        """Poll until the session reports the link gone.

        The poll task is cancelled and awaited before the caller closes the session — a poll in
        flight against a transport being closed underneath it is the one ordering that produces an
        exception nobody can act on.
        """
        service = PollingService(session=session, driver=self.driver, clock=self.clock)
        service.on_reading = self.on_reading

        polling = asyncio.ensure_future(service.run())
        # Woken by the event as well as by the interval, so a *Connect* press is acted on at once
        # rather than up to a second later. Polling a flag would have been simpler and would have
        # made the button feel broken on the press that mattered.
        woken = asyncio.ensure_future(self._retry_now.wait())
        try:
            while not polling.done():
                if self._restarting:
                    self._say("Reconnecting…")
                    return
                if session.state is ConnectionState.LOST:
                    self._say(session.last_fault or "The connection was lost.")
                    return
                await asyncio.wait(
                    [polling, woken],
                    timeout=_WATCH_INTERVAL,
                    return_when=asyncio.FIRST_COMPLETED,
                )
        finally:
            # Awaited rather than abandoned: a cancelled task that is never awaited leaves its
            # exception unretrieved, which asyncio reports at garbage-collection time and which
            # reads as an unrelated crash minutes later.
            woken.cancel()
            polling.cancel()
            for child in (woken, polling):
                await _absorb(child)

    async def _wait_to_retry(self, attempt: int) -> bool:
        """Count down to the next attempt. Returns whether to make one."""
        if not self.stay_connected or self._stopped:
            self._say("Not reconnecting. Connect again when you are ready.")
            # Wait indefinitely for someone to ask, rather than returning and ending the task:
            # ending it would mean a Connect button with nothing behind it.
            await self._retry_now.wait()
            return not self._stopped

        for remaining in range(self.backoff(attempt), 0, -1):
            self._say(f"Lost the connection. Retrying in {remaining} second{_s(remaining)}…")
            try:
                await asyncio.wait_for(self._retry_now.wait(), timeout=1.0)
            except TimeoutError:
                continue
            # Somebody pressed something. Whether it was *Retry now* or *Stop retrying* is the
            # difference between coming back and staying away.
            return not self._stopped

        return True

    def _say(self, text: str) -> None:
        if self.on_status is not None:
            self.on_status(text)


def _s(count: int) -> str:
    return "" if count == 1 else "s"


async def _absorb(child: asyncio.Task[Any]) -> None:
    """Wait for a cancelled child, keeping its failure and **not** eating our own cancellation.

    ``with suppress(asyncio.CancelledError): await child`` reads correctly and is a trap:
    ``suppress`` cannot tell *whose* ``CancelledError`` it caught. If this task is itself being
    cancelled, the next ``await`` re-delivers **our** cancellation here — and swallowing it leaves
    the supervisor running its ``while True`` for ever, because a task is only cancelled once.

    That is not a test artefact. It is a shutdown that never completes, and it reproduced as an
    intermittent hang of the whole suite on Python 3.12 — two CI jobs sitting at sixteen minutes
    against their own two-minute twins.

    So the child's cancellation is absorbed and ours is re-raised. Anything else the child raised
    is the failure that ended the poll, already reported through the session's own state.
    """
    try:
        await child
    except asyncio.CancelledError:
        current = asyncio.current_task()
        if current is not None and current.cancelling() > 0:
            raise
    except Exception:
        return


async def _quietly_close(session: DeviceSession) -> None:
    """Closing a link that has already gone is best-effort, and never the reason the cycle stops."""
    with suppress(Exception):
        await session.close()
