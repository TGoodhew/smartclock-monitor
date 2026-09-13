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
from datetime import datetime
from typing import ClassVar

from smartclock_device.clock import Clock
from smartclock_device.commands import catalog
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.nmea.sentences import TIME_POLL_KEY as POLL_KEY
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

    #: When **this sweep** completed, from the injected clock.
    #:
    #: Distinct from ``status.captured_at``, and the difference is load-bearing rather than
    #: pedantic. §11.2 defines the status as what the *screen* reports, so its timestamp is when
    #: the screen was read — but the fast tier folds fresh figures of merit and a fresh 1 PPS
    #: interval into that object once a second through ``dataclasses.replace``, which keeps the
    #: original timestamp. A consumer that took ``status.captured_at`` as "when this reading was
    #: taken" would see one instant repeated for a whole full-poll interval: the trend store filed
    #: ten seconds of readings under a single timestamp, and the details window's "Updated" line
    #: advanced once every ten seconds while the numbers beside it changed every one.
    #:
    #: ``None`` only for a Reading built by hand in a test that does not care.
    captured_at: datetime | None = None

    #: Oscillator electronic frequency control, relative, as a percentage.
    efc_percent: float | None = None

    #: How many satellites the receiver says it is tracking.
    tracked_count: int | None = None

    #: What ``:SYNC:STAT?`` last answered, upper-cased.
    sync_state: str | None = None

    #: Whether §7.3.1 is currently suppressing the refusable reading.
    suppressed: bool = False

    #: When the **full** read last succeeded, and when the **fast** sweep last did.
    #:
    #: Separate from :attr:`captured_at`, which is when *this sweep* finished — and the difference
    #: is the whole of #61's staleness half. §7.3's tiers run at different rates and fail
    #: independently: a full read that has stopped answering leaves the screen's fields frozen
    #: while the fast sweep goes on delivering figures of merit once a second. Taking the newest of
    #: the two as "when this was updated" reports a page as current that is a minute old, which is
    #: the one reading a timing instrument must never give.
    full_at: datetime | None = None
    fast_at: datetime | None = None

    #: Whether the tier that fills most of the interface has gone quiet for longer than it should.
    #:
    #: Decided here rather than in a view, because the threshold comes from the driver's cadence
    #: and a view has no business knowing one. §9.4.1's caution row is *"recovering, waiting,
    #: reduced accuracy, stale data"*; this is the last of those.
    stale: bool = False

    @property
    def oldest_tier_at(self) -> datetime | None:
        """The older of the tiers that have delivered — how fresh the page as a whole is.

        A page fed by both tiers is only as fresh as its **slower** half. Returning the newest
        would report an Overview as current because one figure of merit arrived a second ago,
        while the status screen beside it had not been read for a minute.
        """
        stamps = [at for at in (self.full_at, self.fast_at) if at is not None]
        return min(stamps) if stamps else self.captured_at

    @classmethod
    def nothing_known(cls, captured_at: datetime) -> Reading:
        """A sweep that knows nothing — every field unfilled, so every surface renders §11.1's dash.

        **Rendered through the ordinary path rather than by a second one.** A window that could
        blank itself would have two ways to draw its unfilled state, and the one used once per
        connection is the one that goes stale: it would keep drawing a readout that `show_reading`
        had stopped drawing, and nothing would notice. Every consumer already handles ``None`` on
        every field, because §11.1 requires it and ``mypy --strict`` checks it, so a Reading with
        nothing in it draws the unfilled state for free.

        Used when a session opens (#61). The readings on screen belong to the link that just
        ended, and a new receiver must not inherit them.
        """
        return cls(status=ReceiverStatus(captured_at=captured_at), captured_at=captured_at)


@dataclass
class PollingService:
    """Runs the sweep until it is cancelled."""

    session: DeviceSession
    driver: ReceiverDriver
    clock: Clock

    #: Called with each new reading, on the event loop.
    on_reading: Callable[[Reading], None] | None = None

    #: Called the first time a late identity arrives, so the surfaces that name the receiver can be
    #: filled in. Never called for a session that identified at connect — `refresh_identity` only
    #: reports True after it has changed something.
    on_identity: Callable[[], None] | None = None

    _status: ReceiverStatus | None = field(default=None, init=False)
    _full_at: datetime | None = field(default=None, init=False)
    _fast_at: datetime | None = field(default=None, init=False)
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

    async def will_answer_the_poll(self) -> bool:
        """§7.2's **fourth** gate: will *this particular module* understand the sentence (D8).

        Deliberately **not** the driver's. `NmeaDriver` offers `$PUBX,04` for its catalogued entry
        on any talker, because willingness-to-transmit is a fact about the *family*. Whether the
        receiver on the other end is a u-blox is a fact about *this receiver*, and a driver is a
        singleton — one that remembered the answer would carry one module's to the next, which is
        the defect #61 was about.

        The evidence is the power-on banner, which lives on the status because the status is
        per-session. A receiver that was already running when the application connected has no
        banner here, and the honest answer is then **no**: not "probably", and not "ask and see".
        Asking anyway would put a proprietary sentence on a link belonging to a module that never
        said it was u-blox, which is precisely the trade D8 made and precisely the limit it set.
        """
        status = self._status
        if status is None:
            return False
        return any("U-BLOX" in line.upper() for line in status.banner)

    async def poll_full(self) -> None:
        """Read the full status and publish it.

        The identity is retried here first, on the slow tier, when the connect never got one
        (#29). It costs one attribute test on a session that identified normally, which is all of
        them but the ones this exists for.
        """
        if await self.session.refresh_identity() and self.on_identity is not None:
            self.on_identity()

        plan = self.driver.plan

        # §7.2 gate 4, before the full read so the answer lands in the same cycle. Asked every slow
        # tick rather than once: a banner can arrive late, and a session that joined a running
        # receiver may never see one at all.
        offers_poll = self.driver.outgoing_text_for(POLL_KEY) is not None
        if offers_poll and await self.will_answer_the_poll():
            await self.session.execute(POLL_KEY)

        result = await self.session.execute(plan.full.mnemonic)
        if isinstance(result, Refusal) or not result.succeeded:
            return

        self._status = self.driver.parse_full(result, self._status)
        self._full_at = self.clock.utc_now()
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
        self._fast_at = self.clock.utc_now()
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

    #: How many full-read intervals may pass before the page is called stale.
    #:
    #: Two rather than one: a single missed read is ordinary — a refusal, a retry, a receiver busy
    #: with a survey — and raising §9.4.1's caution row for it would be the gate that cries wolf.
    #: Two consecutive misses is a tier that has stopped.
    STALE_AFTER_INTERVALS: ClassVar[int] = 2

    def _is_stale(self, now: datetime) -> bool:
        """Whether the full read has gone quiet for longer than its own cadence allows.

        **The full tier, not the newest one.** The fast sweep can go on answering indefinitely
        while the status screen behind it is frozen, and it is the screen that fills the satellite
        table, the position and the health card.
        """
        if self._full_at is None:
            return False
        return now - self._full_at > self.driver.cadence.full * self.STALE_AFTER_INTERVALS

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

        now = self.clock.utc_now()
        reading = Reading(
            status=self._status,
            captured_at=now,
            efc_percent=efc,
            tracked_count=tracked,
            sync_state=sync,
            suppressed=self._suppressed_in_state is not None,
            full_at=self._full_at,
            fast_at=self._fast_at,
            stale=self._is_stale(now),
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
