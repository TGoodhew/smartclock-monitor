"""How a page asks for something to be sent.

The poll loop pushes readings at the interface once a second. This is the other direction: a
button that reads a register, runs a self-test, or applies a setting.

**A page never touches the session directly.** It is handed a runner, and the runner owns the
awkward parts — scheduling a coroutine from a click handler, delivering the answer back on the
event loop, and not letting two overlapping requests interleave on a link that serves one
transaction at a time (§7.2). A page that did this itself would do it four times, differently.

The seam is a Protocol rather than the concrete class so a test can drive a page with a runner that
answers immediately. Half of what these pages do is decide what to show when a read fails, and a
test that had to stand up an event loop to exercise that would not be written.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Protocol

from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_monitor.services.session import CommandOutcome, DeviceSession

#: What a caller gets back. One outcome per command, in the order they were asked for.
Then = Callable[[Sequence[CommandOutcome]], None]


class CommandRunner(Protocol):
    """Something that can send catalogued commands and hand back what they said."""

    def run(
        self,
        commands: Sequence[tuple[ScpiCommand, object]],
        then: Then | None = None,
    ) -> None:
        """Send these, in order, then call ``then`` with the outcomes.

        Fire-and-forget by design: the caller is a click handler and cannot await. A failure
        reaches the page as an unsuccessful :class:`CommandOutcome`, never as an exception — a
        traceback out of a Qt slot takes the window with it.
        """
        ...

    @property
    def is_connected(self) -> bool:
        """Whether there is a receiver to ask at all.

        Pages disable their controls on this rather than discovering it by sending: an Apply button
        that looks live and silently does nothing is worse than one that is greyed out.
        """
        ...


@dataclass
class SessionCommands:
    """The real runner: schedules against the session, delivers on the event loop."""

    session: DeviceSession

    #: Guards against a second request starting while the first is still going. The session has its
    #: own lock per transaction, but a *batch* — read five register fields, then redraw — must not
    #: interleave with another batch or the page would paint half of each.
    _busy: bool = field(default=False, init=False)

    #: Held only so the loop does not garbage-collect a bare task mid-flight — the documented
    #: hazard with ensure_future, which shows up as a request that silently never happens.
    _task: object = field(default=None, init=False)

    @property
    def is_connected(self) -> bool:
        from smartclock_monitor.services.session import ConnectionState

        return self.session.state is ConnectionState.CONNECTED

    @property
    def is_busy(self) -> bool:
        return self._busy

    def run(
        self,
        commands: Sequence[tuple[ScpiCommand, object]],
        then: Then | None = None,
    ) -> None:
        if self._busy or not commands:
            return
        self._busy = True
        self._task = asyncio.ensure_future(self._drive(commands, then))

    async def _drive(
        self, commands: Sequence[tuple[ScpiCommand, object]], then: Then | None
    ) -> None:
        outcomes: list[CommandOutcome] = []
        try:
            for command, argument in commands:
                outcomes.append(await self.session.execute_command(command, argument))
        except Exception as error:
            # Deliberately broad, and deliberately not re-raised. This runs as a bare task, so an
            # exception here is delivered to the event loop's handler and the page waits forever
            # for a callback that never comes. Whatever went wrong, the page's job is to stop
            # showing a spinner and say so.
            outcomes.append(
                CommandOutcome(
                    command=commands[len(outcomes)][0], transaction=None, error=str(error)
                )
            )
        finally:
            self._busy = False

        if then is not None:
            then(tuple(outcomes))
