"""The result of one command-and-response exchange with the receiver (§7.2).

**A transaction reports rather than raises.** Timeouts and dropped links are ordinary events in a
lab on the end of a serial cable — §7.2 counts three consecutive timeouts before reconnecting — so
they are outcomes the caller inspects, not exceptions it has to catch. Caller cancellation is the
one exception, because there is no result to report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum

from smartclock_device.parsing.scalars import parse_integer
from smartclock_device.transport.faults import TransportFault


class TransactionOutcome(Enum):
    """How a transaction ended."""

    #: The prompt arrived. Whatever is in :attr:`Transaction.lines` is the complete response.
    COMPLETED = 0

    #: No prompt arrived within the timeout. Any lines received are kept, for diagnostics only.
    TIMED_OUT = 1

    #: The link failed. :attr:`Transaction.fault` says how.
    FAULTED = 2


@dataclass(frozen=True, slots=True)
class ScpiError:
    """One entry read from the receiver's error queue by ``:SYST:ERR?``.

    §7.2 requires ``:SYST:ERR?`` after every tier C command and nothing else, and §9.11's copy
    rules require the number *and* its plain-language meaning to reach the user. SCPI supplies both
    in the one response — ``-222,"Data out of range"`` — so this is a split, not a lookup table.
    That matters: a table of meanings written from the manual would be a second opinion about what
    the receiver just said, and would disagree with it on the firmware-specific codes.

    Distinct from :attr:`Transaction.prompt_status`, which is the ``E-nnn>`` token the prompt
    carries. That token says only that the queue was not empty; this says which error, in whose
    words.
    """

    #: Negative for the SCPI standard set, positive for device-specific errors, and ``0`` for the
    #: queue's "no error" reply.
    code: int

    #: The receiver's own description, with the surrounding quotes removed.
    message: str

    @property
    def is_error(self) -> bool:
        """Whether the receiver reported an actual error rather than an empty queue."""
        return self.code != 0

    def describe(self) -> str:
        """The error as one sentence, number first, per §9.11."""
        return f"The receiver returned error {self.code}, {self.message}."

    @staticmethod
    def parse(response: str | None) -> ScpiError | None:
        """Split an error-queue response into its number and message, or ``None``.

        Never raises, per §11.1. A response this cannot decompose is reported by the caller as the
        raw text it was, which is more useful than a fabricated code — and quieter than an
        exception on the confirmation path, where the command has already run and the user is owed
        an answer about it rather than a crash.
        """
        if response is None or not response.strip():
            return None

        text = response.strip()
        head, separator, tail = text.partition(",")
        if not separator:
            return None

        code = parse_integer(head)
        if code is None:
            return None

        # The message is quoted, but a receiver that has dropped a quote should still be readable
        # rather than rejected — the number is the part the user acts on.
        message = tail.strip().strip('"').strip()
        return ScpiError(code, message or "no description given")


@dataclass(frozen=True, slots=True)
class Transaction:
    """One exchange, however it ended."""

    #: The command as sent, without its terminator.
    command: str

    #: How the transaction ended.
    outcome: TransactionOutcome

    #: The response lines, echo removed and terminators stripped.
    #:
    #: Empty for a setter, and for a command the receiver rejected — §7.2 says both answer with the
    #: prompt alone.
    lines: tuple[str, ...] = ()

    #: Whether the first line received was the receiver echoing the command back, as it does under
    #: ``FDUPlex ON``. Detected per transaction, never assumed either way (§7.2).
    echo_discarded: bool = False

    #: Wall time from writing the command to the prompt, the timeout, or the fault.
    elapsed: timedelta = field(default_factory=timedelta)

    #: The error token the receiver put in the prompt, such as ``E-230``, or ``None``.
    #:
    #: **This reports the receiver's error queue, not this command.** §7.2 records the measurement:
    #: with a single error queued, three successive commands that each succeeded and returned
    #: correct data all carried an ``E-113`` prompt. The prompt names the *newest* queued error
    #: while ``:SYST:ERR?`` returns the oldest first, and it reverts to the ordinary prompt only
    #: once the queue is fully drained.
    #:
    #: Kept verbatim rather than parsed to a signed number: SCPI's standard codes are negative and
    #: the prompt prints no sign, and inventing one would put a guess on the Diagnostics page.
    prompt_status: str | None = None

    #: The link failure, when :attr:`outcome` is :attr:`~TransactionOutcome.FAULTED`.
    fault: TransportFault = TransportFault.NONE

    #: The failure text, when :attr:`outcome` is :attr:`~TransactionOutcome.FAULTED`.
    fault_message: str | None = None

    @property
    def succeeded(self) -> bool:
        """True only for :attr:`~TransactionOutcome.COMPLETED`."""
        return self.outcome is TransactionOutcome.COMPLETED

    @property
    def error_queue_not_empty(self) -> bool:
        """Whether the receiver's error queue was not empty as of the end of this transaction.

        **This says nothing about whether this command succeeded**, and the name says so because
        the previous one — ``has_device_error`` — did not, and three call sites read it as a
        verdict on the command they had just sent. Something queued by an earlier poll makes this
        true for a command that worked perfectly.
        """
        return self.prompt_status is not None

    @property
    def was_rejected(self) -> bool:
        """Whether the receiver answered with an error prompt and **no response body**.

        This is the honest test for "the receiver rejected this *query*", and it is sound because
        §7.2 establishes that a rejected command answers with the prompt and nothing else. A query
        that came back with lines came back with an answer, whatever is sitting in the queue.

        **It is not sound for a setter**, which answers with the prompt alone whether it worked or
        not — there is no body to distinguish the two. Nothing about the prompt can tell a caller
        whether a setter succeeded; that needs the queue drained beforehand or ``:SYST:ERR?``
        afterwards, which §7.2 gives to tier C alone.
        """
        return self.prompt_status is not None and not self.lines

    @property
    def text(self) -> str:
        """The response as one string, newline-separated. The status screen parser works on this."""
        return "\n".join(self.lines)

    @property
    def first_line(self) -> str | None:
        """The first response line, or ``None``. Scalar queries answer on one line."""
        return self.lines[0] if self.lines else None
