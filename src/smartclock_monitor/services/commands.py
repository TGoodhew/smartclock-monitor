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
from dataclasses import dataclass, field, replace
from typing import Protocol

from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.capability import Capability
from smartclock_monitor.services.session import CommandOutcome, DeviceSession, Refusal

#: What a caller gets back. One outcome per command, in the order they were asked for.
Then = Callable[[Sequence[CommandOutcome]], None]


class CommandRunner(Protocol):
    """Something that can send catalogued commands and hand back what they said."""

    def run(
        self,
        commands: Sequence[tuple[Capability | ScpiCommand, object]],
        then: Then | None = None,
    ) -> None:
        """Send these, in order, then call ``then`` with the outcomes.

        **A page names a capability; the runner resolves it against the connected family.** That
        is the whole of §12's seam at this level: the page says what it wants done and never holds
        another family's mnemonic. A capability this family has no command for comes back as a
        refused outcome rather than being skipped, so a caller counting answers still gets one.

        A ``ScpiCommand`` is accepted too, for §10.11's console — which picks a concrete command
        out of the connected driver's own list and therefore already has one in hand.


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

    @property
    def driver(self) -> ReceiverDriver | None:
        """The driver the session selected, so a page can ask what this family supports.

        ``None`` before anything is connected. Exposed here rather than the session itself because
        a page has no business with a session — §12's seam is that the application asks *the driver
        the session selected*, and this is the narrowest thing that satisfies it.
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
    def driver(self) -> ReceiverDriver | None:
        return self.session.driver

    @property
    def is_busy(self) -> bool:
        return self._busy

    def run(
        self,
        commands: Sequence[tuple[Capability | ScpiCommand, object]],
        then: Then | None = None,
    ) -> None:
        if self._busy or not commands:
            return
        self._busy = True
        self._task = asyncio.ensure_future(self._drive(commands, then))

    def _resolve(self, wanted: Capability | ScpiCommand) -> ScpiCommand | None:
        if isinstance(wanted, Capability):
            driver = self.driver
            return None if driver is None else driver.command(wanted)
        return wanted

    async def _drive(
        self, commands: Sequence[tuple[Capability | ScpiCommand, object]], then: Then | None
    ) -> None:
        outcomes: list[CommandOutcome] = []
        try:
            for wanted, argument in commands:
                command = self._resolve(wanted)
                if command is None:
                    # The family has no command for this. A refusal rather than a skip: a caller
                    # that asked for five answers and got four would misread which is which.
                    outcomes.append(
                        CommandOutcome(
                            command=None,
                            capability=wanted if isinstance(wanted, Capability) else None,
                            refusal=Refusal(
                                str(wanted),
                                f"{self.driver.name if self.driver else 'This receiver'} has no "
                                f"command for this.",
                            ),
                        )
                    )
                    continue
                outcome = await self.session.execute_command(command, argument)
                if isinstance(wanted, Capability):
                    outcome = replace(outcome, capability=wanted)
                outcomes.append(outcome)
        except Exception as error:
            # Deliberately broad, and deliberately not re-raised. This runs as a bare task, so an
            # exception here is delivered to the event loop's handler and the page waits forever
            # for a callback that never comes. Whatever went wrong, the page's job is to stop
            # showing a spinner and say so.
            outcomes.append(
                CommandOutcome(
                    command=self._resolve(commands[len(outcomes)][0]),
                    transaction=None,
                    error=str(error),
                )
            )
        finally:
            self._busy = False

        if then is not None:
            then(tuple(outcomes))
