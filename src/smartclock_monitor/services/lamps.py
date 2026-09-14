"""The receiver's two user-definable front-panel lamps, and the rules for borrowing them.

`z3801.pdf`'s *Front Panel at a Glance*, item 2: *"User-definable indicators labeled Enabled and
Active. These can be turned on through the RS-422 port."* The panel has six lamps and exactly two
belong to the host software; the other four are the receiver's own.

**They say different things, and that is the whole design** (#123, following WinZ3805A's #462).
Giving both the same meaning wastes one:

- **Enabled** is the *application's* lamp — :class:`ActivityLamp` — steady while this application
  holds the link.
- **Active** is the *receiver's* — :class:`LockLamp` — lit while it is locked to GPS.

In front of a rack of four instruments that separates *"software is attached to this one"* from
*"this one is locked"*, which is the pair of questions somebody is actually asking and which one
lamp cannot answer.

**A `:LED:` write costs about a second**, because the receiver services the node on its own 1 Hz
tick — measured upstream at 810 ms and 903 ms against ~30 ms for a query, and re-measured here on
14 Sep 2026 at 0.6 s against 0.036 s. It is not the wire and not the lamp: setting a lamp to the
value it already has costs the same. That arithmetic is why neither of these writes on a timer.
:class:`ActivityLamp` writes twice a session; :class:`LockLamp` writes only when the lock state
actually changes.

**The receiver owns the lamps; these classes borrow them.** The baseline is read before a lamp is
lit and put back verbatim afterwards, so a user who left one on gets it back on. Nothing is cached
between sessions, persisted or carried across a reconnect — a remembered value is wrong the moment
a missed reply, a reconnect or a person changes it, and the front panel is the only truth there is.

**An unexpected disconnect leaves a lamp lit, and that is an accepted cost.** If the cable is pulled
there is no wire left to restore over, and because nothing is retained the next connect reads the
lit lamp and adopts it as the value to put back. The application cannot tell *"the user wanted it
on"* from *"we left it on"* — which is exactly why §10.9 carries a manual control for each, and why
this is not a heuristic.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from smartclock_device.drivers.capability import Capability
from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_device.parsing.scalars import parse_boolean
from smartclock_monitor.services.session import CommandOutcome, DeviceSession


@dataclass
class _Lamp:
    """One borrowed lamp: read it, light it, put it back."""

    session: DeviceSession

    #: Which capability reads this lamp, and which writes it.
    read: Capability
    write: Capability

    #: What the lamp read before this session touched it, held **only while borrowed**.
    #:
    #: The only state here, and it is not a cache: it is the value owed back to the receiver,
    #: dropped the instant it has been returned. ``None`` means the lamp is not ours.
    _borrowed_from: bool | None = field(default=None, init=False)

    @property
    def is_borrowed(self) -> bool:
        return self._borrowed_from is not None

    @property
    def is_supported(self) -> bool:
        """Whether the connected family can drive this lamp at all.

        Asked of the driver rather than answered here (§12's #304): a talker has no lamp and no
        command channel to drive one, and the UCCM's `LED:GPSL?` is a query in another dialect and
        is not this.
        """
        driver = self.session.driver
        return driver.command(self.read) is not None and driver.command(self.write) is not None

    async def arm(self, *, lit: bool = True) -> bool:
        """Read the lamp, remember it, and set it. Returns whether it is now ours.

        Does nothing when the family has no such lamp or when it is **already borrowed** — arming
        twice would overwrite the borrowed value with our own, which is how *"the user left it on"*
        becomes *"the application decided it was off"*.
        """
        if self.is_borrowed or not self.is_supported:
            return False

        baseline = await self._read()
        if baseline is None:
            # Unreadable. Lighting it anyway would leave nothing to put back — §11.1's rule seen
            # from the write side: never act on a value nobody has.
            return False

        if not await self._set(lit):
            return False

        self._borrowed_from = baseline
        return True

    async def restore(self) -> bool:
        """Put the lamp back exactly as it was found, and forget it.

        **Must run before the transport is torn down.** The borrowed value is dropped whether or
        not the write lands: retrying against a link that is going away would hold a disconnect
        open for a lamp.
        """
        baseline, self._borrowed_from = self._borrowed_from, None
        if baseline is None:
            return False
        return await self._set(baseline)

    async def _read(self) -> bool | None:
        command = self.session.driver.command(self.read)
        if command is None:
            return None
        outcome = await self.session.execute_command(command)
        if outcome.transaction is None or not outcome.transaction.succeeded:
            return None
        return parse_boolean(outcome.transaction.first_line)

    async def _set(self, lit: bool) -> bool:
        command = self.session.driver.command(self.write)
        if command is None:
            return False
        outcome: CommandOutcome = await self.session.execute_command(
            command, "ON" if lit else "OFF"
        )
        return outcome.transaction is not None and outcome.transaction.succeeded


@dataclass
class ActivityLamp:
    """**Enabled**: lit while this application holds the link.

    Two writes a session — one to light it, one to put it back — and nothing in between. What it
    buys is weaker than a per-command flicker and is the honest version of the same idea: not
    *"the application is talking right now"* but *"the application is connected to **this** unit"*.
    """

    session: DeviceSession

    def __post_init__(self) -> None:
        self._lamp = _Lamp(self.session, Capability.ENABLED_LAMP, Capability.SET_ENABLED_LAMP)

    @property
    def is_lit(self) -> bool:
        return self._lamp.is_borrowed

    @property
    def is_supported(self) -> bool:
        return self._lamp.is_supported

    async def arm(self) -> bool:
        return await self._lamp.arm(lit=True)

    async def restore(self) -> bool:
        return await self._lamp.restore()


@dataclass
class LockLamp:
    """**Active**: lit while the receiver is locked to GPS.

    **Written only when the state changes, which is what makes it affordable.** A flash per sweep
    was measured at 194% of the whole poll budget and rejected; a lock state changes a few times a
    day, and on the occasions it changes quickly the receiver is doing something a person wants to
    see on the front panel anyway.
    """

    session: DeviceSession

    def __post_init__(self) -> None:
        self._lamp = _Lamp(self.session, Capability.ACTIVE_LAMP, Capability.SET_ACTIVE_LAMP)
        self._shown: bool | None = None

    @property
    def is_borrowed(self) -> bool:
        return self._lamp.is_borrowed

    @property
    def is_supported(self) -> bool:
        return self._lamp.is_supported

    async def arm(self) -> bool:
        armed = await self._lamp.arm(lit=False)
        if armed:
            self._shown = False
        return armed

    async def follow(self, mode: SmartClockMode) -> bool:
        """Track one reading's mode. Returns whether a write was sent.

        **Nothing is written unless the answer changes**, which is the difference between this and
        the per-sweep flash: at a second a write, following a state that changes a few times a day
        costs a few seconds a day.
        """
        if not self._lamp.is_borrowed:
            return False

        wanted = mode is SmartClockMode.LOCKED
        if wanted == self._shown:
            return False

        if not await self._lamp._set(wanted):
            return False
        self._shown = wanted
        return True

    async def restore(self) -> bool:
        self._shown = None
        return await self._lamp.restore()


@dataclass
class Lamps:
    """Both lamps for whichever session is current, and the sync entry points a callback needs.

    **Per session and never across one.** `adopt` binds to a session, `forget` drops the binding
    without writing anything — a reconnect must not put a *previous* receiver's baseline onto a new
    one — and `restore` is the only thing that writes on the way out.

    The writes are scheduled rather than awaited, because the two callers are a connection
    announcement and a poll-loop callback, and a lamp is never worth delaying a reading for.
    """

    activity: ActivityLamp | None = field(default=None, init=False)
    lock: LockLamp | None = field(default=None, init=False)

    #: The arming task, held so it is not garbage-collected mid-write. Nothing awaits it: a lamp
    #: is never worth delaying a connection for, and a lamp that will not light is not a
    #: connection that failed.
    arming: asyncio.Task[None] | None = field(default=None, init=False)

    def adopt(self, session: DeviceSession) -> None:
        self.activity = ActivityLamp(session)
        self.lock = LockLamp(session)

    def forget(self) -> None:
        """Drop the binding **without writing**. For a reconnect, where the wire is already gone."""
        self.activity = None
        self.lock = None

    async def arm(self) -> None:
        """Light both, ignoring a receiver that will not have them.

        A lamp that would not light is not a connection that failed, so nothing here raises into
        the task that calls it.
        """
        if self.activity is not None:
            await self.activity.arm()
        if self.lock is not None:
            await self.lock.arm()

    async def restore(self) -> None:
        if self.lock is not None:
            await self.lock.restore()
        if self.activity is not None:
            await self.activity.restore()

    def follow(self, mode: SmartClockMode) -> None:
        """Track one reading's mode, from a **synchronous** callback.

        The poll loop's publish is not a coroutine, so this schedules rather than awaits. The write
        only happens when the answer changes, so the ordinary reading schedules a task that returns
        immediately.
        """
        lamp = self.lock
        if lamp is None or not lamp.is_borrowed:
            return
        _ = asyncio.ensure_future(lamp.follow(mode))  # noqa: RUF006 - fire and forget, by design
