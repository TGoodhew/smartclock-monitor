"""The receiver's line protocol: write a command, discard the echo, read until the prompt (§7.2).

Three things make this harder than it looks, and all three are why §15 puts it first.

**The device may echo.** The manual's default is ``FDUPlex ON``, sending every character back; the
bench unit echoes nothing (§7.2). The echo is *detected* by comparing the first line received to
the line transmitted, never assumed — a session that assumes echo-on eats the first line of every
response the day it meets a unit with echo off, and one that assumes echo-off reads its own command
back as the answer.

**The terminator is a prompt, not a newline**, and **the prompt straddles reads.** Both live in
:mod:`smartclock_device.transport.response_buffer`, which is where the interesting tests are.

This type does not own the transport and does not close it. It also does not serialise callers: the
receiver is strictly one transaction at a time and §7.2 puts that duty on the session service's
single-consumer queue.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from smartclock_device.clock import Clock
from smartclock_device.transport import timeouts
from smartclock_device.transport.base import Transport
from smartclock_device.transport.faults import (
    TransportError,
    TransportFault,
    classify,
    is_transport_fault,
)
from smartclock_device.transport.response_buffer import ResponseBuffer
from smartclock_device.transport.transaction import Transaction, TransactionOutcome

#: Stands in for a command in the transaction returned by :meth:`LineProtocol.synchronise`.
CONNECT_LABEL = "(connect)"

#: Tier S (§8.2), clears the status registers, and answers with nothing worth keeping.
_CLEAR_STATUS = "*CLS"


class LineProtocol:
    """One transaction at a time, over a borrowed transport."""

    def __init__(self, transport: Transport, clock: Clock) -> None:
        self._transport = transport
        self._clock = clock

        # How long the next command may spend realigning the stream, or None when it is already
        # aligned. See _resynchronise.
        self._resynchronise_within: timedelta | None = None

    # ASYNC109 wants the caller to wrap the call in asyncio.timeout() instead. That is the wrong
    # shape here: §7.2 assigns a timeout *class* per command - three seconds for a scalar, sixty
    # for the whole diagnostic log - and the whole point is that a caller does not have to know
    # which. The deadline is applied with asyncio.timeout() internally, which is what the rule is
    # really asking for.
    async def execute(
        self,
        command: str,
        timeout: timedelta | None = None,  # noqa: ASYNC109 - see the comment above
    ) -> Transaction:
        """Run one transaction.

        :param timeout: Defaults to the class §7.2 assigns to the command.

        Returns a :class:`Transaction` for every outcome except caller cancellation, which
        propagates ``CancelledError`` because there is nothing to report.
        """
        sent = command.strip()
        if not sent:
            raise ValueError("A command must not be blank.")

        budget = timeout if timeout is not None else timeouts.for_command(sent)
        if budget <= timedelta():
            raise ValueError("A timeout must be positive.")

        # Realigning happens before this command's clock starts, and that is not a detail: the
        # budget for clearing somebody else's abandoned reply can be sixty seconds, while a scalar
        # query's own deadline is three. Charged to this command, one cancelled diagnostic-log read
        # would time out the next poll and the two after it — and §7.2 reconnects on three
        # consecutive timeouts, so navigating away from a page would drop the link.
        await self._resynchronise()

        started_at = self._clock.utc_now()
        buffer = ResponseBuffer()

        try:
            self._transport.discard_input()
            await self._transport.write(f"{sent}\r\n".encode("latin-1"))

            async with asyncio.timeout(budget.total_seconds()):
                await self._read_until_prompt(buffer)

        except TimeoutError:
            # Whatever arrived is kept: a truncated response is the most useful thing Diagnostics
            # can show.
            lines, echo = _discard_echo(sent, buffer.lines)
            self._needs_resynchronising(len(lines), budget)
            return Transaction(
                command=sent,
                outcome=TransactionOutcome.TIMED_OUT,
                lines=lines,
                echo_discarded=echo,
                elapsed=self._elapsed_since(started_at),
            )

        except asyncio.CancelledError:
            # The caller gave up waiting. The receiver did not give up sending — it answers one
            # command at a time and finishes what it started — so the rest of this reply is still
            # coming, and would be read as the next command's answer.
            self._needs_resynchronising(len(buffer.lines), budget)
            raise

        except Exception as exception:
            if not is_transport_fault(exception):
                raise
            # §6.4: every one of these is reachable when the adapter is pulled mid-transaction, and
            # P0-14 requires the app to report Disconnected rather than fall over.
            lines, echo = _discard_echo(sent, buffer.lines)
            return Transaction(
                command=sent,
                outcome=TransactionOutcome.FAULTED,
                lines=lines,
                echo_discarded=echo,
                elapsed=self._elapsed_since(started_at),
                fault=classify(exception),
                fault_message=str(exception),
            )

        lines, echo = _discard_echo(sent, buffer.lines)
        return Transaction(
            command=sent,
            outcome=TransactionOutcome.COMPLETED,
            lines=lines,
            echo_discarded=echo,
            elapsed=self._elapsed_since(started_at),
            prompt_status=buffer.prompt_status,
        )

    async def synchronise(
        self,
        timeout: timedelta = timeouts.AUTO_DETECT_PROBE,  # noqa: ASYNC109 - see execute
    ) -> Transaction:
        """Listen, without sending anything, until the receiver's first prompt or the timeout.

        Call once after opening the port and before the first command. Asserting DTR makes this
        receiver announce itself — a Z3805A emits its identity string and a prompt with nothing
        asked of it — and the announcement takes long enough to arrive that it lands *after* the
        first command has gone out. The first transaction then reads the banner as its own
        response, and every reply after that is one behind: ``*IDN?`` answers with the banner, the
        next query answers with the identity, and nothing ever reports an error because every
        transaction does complete. Absorbing the banner first is what keeps the session aligned.

        The returned transaction carries the banner text, which is worth keeping: it names the
        model and firmware revision before a single command has been sent, and §8.6 needs the model
        to decide which commands exist. A receiver that says nothing costs one timeout here and
        nothing afterwards, so keep the timeout short.
        """
        started_at = self._clock.utc_now()
        buffer = ResponseBuffer()

        try:
            async with asyncio.timeout(timeout.total_seconds()):
                await self._read_until_prompt(buffer)
            outcome = TransactionOutcome.COMPLETED

        except TimeoutError:
            # Silence is a perfectly good answer: this receiver announces itself, a sibling model
            # may not, and neither case is a failure to connect.
            outcome = TransactionOutcome.TIMED_OUT

        except Exception as exception:
            if not is_transport_fault(exception):
                raise
            return Transaction(
                command=CONNECT_LABEL,
                outcome=TransactionOutcome.FAULTED,
                lines=buffer.lines,
                elapsed=self._elapsed_since(started_at),
                fault=classify(exception),
                fault_message=str(exception),
            )

        await self._clear_status()

        return Transaction(
            command=CONNECT_LABEL,
            outcome=outcome,
            lines=buffer.lines,
            elapsed=self._elapsed_since(started_at),
            prompt_status=buffer.prompt_status if outcome is TransactionOutcome.COMPLETED else None,
        )

    # -- internals ---------------------------------------------------------------------------

    async def _clear_status(self) -> None:
        """Send the status-clear command and throw the answer away, twice if the first is refused.

        The first command after the port opens is unreliable on this hardware. Asserting DTR and
        RTS puts a glitch on the line that the receiver reads as a character, and it answers the
        next thing it is asked with ``E-362>`` — SCPI's framing error — having discarded that
        command unexecuted. Left alone, the cost is a mystifying failure on whatever the app
        happens to send first, which during auto-detect is the identity query that decides whether
        a receiver is there at all.

        So the connect sequence spends the glitch deliberately, on the one tier S command whose
        whole purpose is to clear status and whose response nobody wants. Twice, because the first
        attempt is the one being sacrificed.
        """
        cleared = await self.execute(_CLEAR_STATUS, timeouts.AUTO_DETECT_PROBE)

        # error_queue_not_empty is the right test here, unusually: this wants "not clean yet", not
        # "that command failed". Spending the glitch is done when the queue is empty.
        if not cleared.succeeded or cleared.error_queue_not_empty:
            await self.execute(_CLEAR_STATUS, timeouts.AUTO_DETECT_PROBE)

    def _needs_resynchronising(self, lines_received: int, budget: timedelta) -> None:
        """Note that a reply was abandoned part-read, so the next command realigns before sending.

        **Only when something had already arrived.** A transaction that received nothing at all was
        talking to a device that is silent or gone, and there is no tail to drain — waiting for a
        prompt that was never coming would add a second timeout to every one of §7.2's three
        consecutive failures before it reconnects, which is exactly the wrong place to spend time.
        """
        if lines_received > 0:
            self._resynchronise_within = budget

    async def _resynchronise(self) -> None:
        """Read and discard up to the next prompt, so a half-read reply is not the next answer.

        **Why discarding the input buffer is not enough.** That drains what has already arrived.
        The bytes that cause this are the ones that have *not* — a 15 kB diagnostic log is sixteen
        seconds of wire at 9600 baud, so a read abandoned three seconds in leaves thirteen seconds
        of reply still to come. Discarding at the moment the next command is written clears none of
        it; it arrives afterwards and is read as that command's answer.

        That is a defect with a measured cost. Navigating away from the Diagnostics page cancels
        its log read, and the next three polls parsed the tail: one stored an EFC reading as a sync
        state, and two wrote time intervals of two and three *seconds* into the trend store, where
        three bad samples out of 12,488 made every chart over a seven-day window unreadable.

        **The caller's cancellation is deliberately not honoured here.** Cancelling meant "stop
        waiting for my answer", not "leave the link misaligned for whoever asks next" — and a
        resynchronise that could itself be cancelled would fix nothing. It is bounded instead by
        the budget of the transaction that was abandoned, which is the longest its remaining reply
        can take, and a link that has actually died surfaces as a transport fault rather than a
        wait.
        """
        budget = self._resynchronise_within
        if budget is None:
            return

        # Cleared first: a resynchronise that faults must not leave the flag set and repeat itself
        # on every subsequent command.
        self._resynchronise_within = None

        discarded = ResponseBuffer()
        try:
            async with asyncio.timeout(budget.total_seconds()):
                await self._read_until_prompt(discarded)
        except TimeoutError:
            # The tail never ended. Nothing more can be done here and the next transaction's own
            # timeout is the backstop.
            pass
        except Exception as exception:
            if not is_transport_fault(exception):
                raise
            # The link died while realigning. Swallowed on purpose: the command that follows is
            # about to touch the same port and will report it as a Faulted transaction, which is
            # the shape every caller already handles. Raising a raw transport error from here would
            # make one path report failure differently from all the others.
            pass

    async def _read_until_prompt(self, buffer: ResponseBuffer) -> None:
        """Feed the buffer until it says the transaction is over.

        A zero-length read means the device has gone: the pipe closed with no prompt, which is a
        removal rather than a timeout and is reported as one.
        """
        while not buffer.is_complete:
            chunk = await self._transport.read()
            if not chunk:
                raise TransportError(
                    TransportFault.DEVICE_REMOVED,
                    f"{self._transport.description} closed with no prompt after "
                    f"{len(buffer.lines)} line(s).",
                )
            buffer.feed(chunk)

    def _elapsed_since(self, started_at: datetime) -> timedelta:
        """Wall time from the injected clock, never from ``time.monotonic()``.

        A ``FixedClock`` therefore reports zero elapsed unless a test advances it, which is the
        point: the figure is deterministic rather than a real duration that varies per run.
        """
        return self._clock.utc_now() - started_at


def _discard_echo(command: str, lines: tuple[str, ...]) -> tuple[tuple[str, ...], bool]:
    """Drop the leading line when it is the command coming back, and report whether it was.

    §7.2: detect echo by comparing the first received line to the transmitted line. Comparing is
    the point — ``FDUPlex`` is a device setting this application deliberately does not change, so
    both states have to work, on every transaction, without configuration.
    """
    if lines and lines[0].strip() == command:
        return lines[1:], True
    return lines, False
