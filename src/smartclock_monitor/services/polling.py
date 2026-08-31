"""The §7.3 two-tier poll loop, and §7.3.1's rule about a reading the receiver will not give.

Two cadences, from the driver rather than from here: 1 s of scalars for the main window and the
trend charts, 10 s for the full screen that is the only source of the satellite table.

**The two tiers must never overlap.** They share one command channel, so the fast tier naturally
stalls behind a full-screen fetch — 3,521 ms measured of its 10 s window at 9600 baud. §7.3 says
that is acceptable and that interleaving them is not, so this runs one loop rather than two.

Qt-free. The status reaches the UI through a callback the caller supplies, which is what lets the
whole loop be driven by a fake clock and a fake transport in a test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field

from smartclock_device.clock import Clock
from smartclock_device.commands import catalog
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.models.receiver_status import ReceiverStatus
from smartclock_device.parsing.scalars import parse_decimal, parse_integer, parse_keyword
from smartclock_device.transport.transaction import Transaction
from smartclock_monitor.services.session import DeviceSession, Refusal


@dataclass(frozen=True, slots=True)
class Reading:
    """One sweep's worth of what the application shows.

    The status is what §11.2 defines — what the *screen* reports. The two extras are fast-tier
    scalars that have no place on it and are carried alongside rather than bolted on.
    """

    status: ReceiverStatus

    #: Oscillator electronic frequency control, relative, as a percentage.
    efc_percent: float | None = None

    #: How many satellites the receiver says it is tracking.
    tracked_count: int | None = None

    #: What ``:SYNC:STAT?`` last answered, upper-cased.
    sync_state: str | None = None

    #: Whether §7.3.1 is currently suppressing the refusable reading.
    suppressed: bool = False


@dataclass
class PollingService:
    """Runs the sweep until it is cancelled."""

    session: DeviceSession
    driver: ReceiverDriver
    clock: Clock

    #: Called with each new reading, on the event loop.
    on_reading: Callable[[Reading], None] | None = None

    _status: ReceiverStatus | None = field(default=None, init=False)
    _suppressed_in_state: str | None = field(default=None, init=False)
    _last: Reading | None = field(default=None, init=False)

    @property
    def latest(self) -> Reading | None:
        """The most recent reading, for a view that connects after the loop has started."""
        return self._last

    async def run(self) -> None:
        """Poll until cancelled.

        One loop rather than two. A full read is due every ``cadence.full``; the fast sweep runs
        otherwise. Nothing interleaves, because both tiers share one command channel and §7.3 is
        explicit that letting them overlap is not the answer.
        """
        cadence = self.driver.cadence
        fast_seconds = cadence.fast.total_seconds()
        every = max(1, round(cadence.full / cadence.fast))
        tick = 0

        # The first pass reads the screen, so there is something to show before the first second is
        # up rather than a window of dashes.
        await self.poll_full()

        while True:
            await asyncio.sleep(fast_seconds)
            tick += 1
            if tick % every == 0:
                await self.poll_full()
            else:
                await self.poll_fast()

    async def poll_full(self) -> None:
        """Read the full status and publish it."""
        plan = self.driver.plan
        result = await self.session.execute(plan.full.mnemonic)
        if isinstance(result, Refusal) or not result.succeeded:
            return

        self._status = self.driver.parse_full(result, self._status)
        self._publish()

    async def poll_fast(self) -> None:
        """Run the scalar sweep and fold it into the last full status."""
        plan = self.driver.plan
        results: dict[str, Transaction] = {}
        state: str | None = None

        for command in plan.fast:
            if command is plan.refusable and self._is_suppressed(state):
                continue

            outcome = await self.session.execute(command.mnemonic)
            if isinstance(outcome, Refusal):
                continue

            results[command.mnemonic] = outcome

            if command is plan.state_query and outcome.succeeded:
                state = parse_keyword(outcome.first_line)

            if command is plan.refusable:
                self._note_refusal(command_rejected=outcome.was_rejected, state=state)

        if self._status is None:
            return

        self._status = self.driver.apply_fast(self._status, results)
        self._publish(results, state)

    # -- §7.3.1 --------------------------------------------------------------------------------

    def _is_suppressed(self, state: str | None) -> bool:
        """Whether the refusable reading is currently suppressed.

        **Keyed on the state, not on a list of states.** Nothing here decides which sync states
        support which reading; the receiver is asked once and believed. That makes no claim about a
        sibling model whose firmware may answer where this one does not, and it costs at most one
        error per state transition instead of one per second.

        **It self-clears.** A receiver that regains lock reports a different state, so it is asked
        again on the next sweep.
        """
        return self._suppressed_in_state is not None and state == self._suppressed_in_state

    def _note_refusal(self, *, command_rejected: bool, state: str | None) -> None:
        """Record, or clear, the suppression.

        **Only a refusal counts.** A timeout or a dropped link says nothing about whether the
        receiver would have answered, and suppressing a reading because a cable was unplugged would
        keep it suppressed after the cable was plugged back in — which is why this keys on
        ``was_rejected`` (an error prompt *and no body*) rather than on "did not succeed".
        """
        if command_rejected:
            self._suppressed_in_state = state
        elif self._suppressed_in_state is not None and state != self._suppressed_in_state:
            self._suppressed_in_state = None

    # -- Publishing ----------------------------------------------------------------------------

    def _publish(
        self, results: dict[str, Transaction] | None = None, state: str | None = None
    ) -> None:
        if self._status is None:
            return

        previous = self._last
        efc = previous.efc_percent if previous else None
        tracked = previous.tracked_count if previous else None
        sync = previous.sync_state if previous else None

        if results is not None:
            efc = _value(results, catalog.OSCILLATOR_EFC.mnemonic, parse_decimal) or efc
            tracked = _value(results, catalog.TRACKED_COUNT.mnemonic, parse_integer) or tracked
            sync = state or sync

        reading = Reading(
            status=self._status,
            efc_percent=efc,
            tracked_count=tracked,
            sync_state=sync,
            suppressed=self._suppressed_in_state is not None,
        )
        self._last = reading

        if self.on_reading is not None:
            self.on_reading(reading)


def _value[T](
    results: dict[str, Transaction], mnemonic: str, parse: Callable[[str | None], T | None]
) -> T | None:
    transaction = results.get(mnemonic)
    if transaction is None or not transaction.succeeded:
        return None
    return parse(transaction.first_line)
