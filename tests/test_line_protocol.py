"""The §7.2 transaction loop, driven against the fake transport.

Phase 2's done-condition: *the protocol tests pass against the fake, including a status screen
delivered one byte at a time and a prompt split across a read boundary.* The byte-at-a-time and
split-prompt cases are exhaustive in ``test_response_buffer.py``, which is where the scanning
lives; here they are re-run through the whole protocol so that what is proved is the transaction,
not just the buffer.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import serial

from smartclock_device.clock import FixedClock
from smartclock_device.transport import timeouts
from smartclock_device.transport.fake import FakeTransport, error_prompt
from smartclock_device.transport.faults import TransportFault, classify, describe
from smartclock_device.transport.line_protocol import CONNECT_LABEL, LineProtocol
from smartclock_device.transport.transaction import ScpiError, TransactionOutcome

FIXTURES = Path(__file__).resolve().parent / "fixtures"
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)

#: Short enough that the timeout tests do not slow the suite, long enough not to be flaky.
BRIEF = timedelta(milliseconds=50)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("latin-1")


async def opened(transport: FakeTransport) -> LineProtocol:
    await transport.open()
    return LineProtocol(transport, FixedClock(NOW))


# ---- The ordinary shapes ---------------------------------------------------------------------


async def test_a_scalar_query_returns_its_one_line() -> None:
    transport = FakeTransport({":SYNC:TINT?": " -5.4E-009"})
    protocol = await opened(transport)

    result = await protocol.execute(":SYNC:TINT?")

    assert result.succeeded
    assert result.first_line == " -5.4E-009"
    assert result.prompt_status is None


async def test_the_command_is_written_with_a_crlf_terminator() -> None:
    transport = FakeTransport({"*IDN?": "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"})
    protocol = await opened(transport)

    await protocol.execute("*IDN?")

    assert transport.written == ["*IDN?"]


async def test_a_setter_completes_on_the_prompt_alone() -> None:
    """§7.2: a setter answers with the prompt and nothing else. Same shape of read as a screen."""
    transport = FakeTransport({":GPS:REF:ADEL 78.6": ""})
    protocol = await opened(transport)

    result = await protocol.execute(":GPS:REF:ADEL 78.6")

    assert result.succeeded
    assert result.lines == ()


async def test_a_status_screen_returns_every_line() -> None:
    screen = read_fixture("captured/locked-to-gps.txt")
    transport = FakeTransport({":SYST:STAT?": screen})
    protocol = await opened(transport)

    result = await protocol.execute(":SYST:STAT?")

    assert result.succeeded
    assert result.lines == tuple(screen.rstrip("\r\n").split("\r\n"))


@pytest.mark.parametrize("chunk", [1, 2, 7, 64, 4096])
async def test_a_status_screen_survives_every_delivery_size(chunk: int) -> None:
    """Phase 2's done-condition names one byte at a time. The rest are here because a bug that
    only shows at a particular chunk size is the kind this loop is prone to."""
    screen = read_fixture("captured/locked-to-gps.txt")
    transport = FakeTransport({":SYST:STAT?": screen}, chunk_size=chunk)
    protocol = await opened(transport)

    result = await protocol.execute(":SYST:STAT?")

    assert result.succeeded
    assert result.lines == tuple(screen.rstrip("\r\n").split("\r\n"))


# ---- Echo -------------------------------------------------------------------------------------


async def test_echo_is_detected_and_discarded() -> None:
    """P0-2. Under ``FDUPlex ON`` the receiver sends every character back."""
    transport = FakeTransport({":SYNC:TINT?": " -5.4E-009"}, echo=True)
    protocol = await opened(transport)

    result = await protocol.execute(":SYNC:TINT?")

    assert result.echo_discarded is True
    assert result.lines == (" -5.4E-009",)


async def test_no_echo_is_detected_as_no_echo() -> None:
    """The bench unit echoes nothing. Both states have to work, on every transaction, without
    configuration — which is why it is compared rather than assumed."""
    transport = FakeTransport({":SYNC:TINT?": " -5.4E-009"}, echo=False)
    protocol = await opened(transport)

    result = await protocol.execute(":SYNC:TINT?")

    assert result.echo_discarded is False
    assert result.lines == (" -5.4E-009",)


async def test_a_response_that_merely_resembles_the_command_is_not_eaten() -> None:
    """Echo detection compares the whole line. A reply that happens to start with the command's
    text is an answer, not an echo."""
    transport = FakeTransport({":SYST:ERR?": ":SYST:ERR? is not a valid reply"}, echo=False)
    protocol = await opened(transport)

    result = await protocol.execute(":SYST:ERR?")

    assert result.echo_discarded is False
    assert len(result.lines) == 1


async def test_an_echoing_receiver_returning_nothing_else_is_still_empty() -> None:
    """A setter under echo: the echo is the only line, and removing it leaves a correct empty
    response rather than one line of the app's own command presented as an answer."""
    transport = FakeTransport({"*CLS": ""}, echo=True)
    protocol = await opened(transport)

    result = await protocol.execute("*CLS")

    assert result.echo_discarded is True
    assert result.lines == ()


# ---- The prompt as queue indicator -----------------------------------------------------------


async def test_an_error_prompt_reports_the_queue_without_condemning_the_command() -> None:
    """§7.2's measurement: with a single error queued, three successive commands that each
    succeeded and returned correct data all carried an ``E-113`` prompt. The prompt names the
    queue, not the command."""
    transport = FakeTransport({":SYNC:TINT?": " -5.4E-009"}, prompt=error_prompt(113))
    protocol = await opened(transport)

    result = await protocol.execute(":SYNC:TINT?")

    assert result.succeeded
    assert result.error_queue_not_empty is True
    assert result.prompt_status == "E-113"
    # It answered. Whatever is in the queue, this query was not rejected.
    assert result.was_rejected is False
    assert result.first_line == " -5.4E-009"


async def test_a_query_rejected_outright_has_an_error_prompt_and_no_body() -> None:
    """The honest test for "the receiver rejected this query", sound because §7.2 establishes that
    a rejected command answers with the prompt and nothing else."""
    transport = FakeTransport({":NOSUCH?": ""}, prompt=error_prompt(113))
    protocol = await opened(transport)

    result = await protocol.execute(":NOSUCH?")

    assert result.was_rejected is True


async def test_a_rejected_command_costs_no_timeout() -> None:
    """A protocol looking for the literal ``"scpi> "`` waits out its full timeout on every failed
    command and then does it again on the next one. This one returns immediately."""
    transport = FakeTransport({":NOSUCH?": ""}, prompt=error_prompt(113))
    protocol = await opened(transport)

    result = await protocol.execute(":NOSUCH?", timedelta(seconds=30))

    assert result.succeeded


# ---- Timeouts, faults and realignment --------------------------------------------------------


async def test_an_unanswered_command_times_out_and_reports_it() -> None:
    """An unscripted command queues nothing at all, which is the honest simulation of a receiver
    that has been asked something it has not answered."""
    transport = FakeTransport()
    protocol = await opened(transport)

    result = await protocol.execute(":SYNC:TINT?", BRIEF)

    assert result.outcome is TransactionOutcome.TIMED_OUT
    assert result.succeeded is False


async def test_a_partial_response_is_kept_when_the_transaction_times_out() -> None:
    """A truncated response is the most useful thing Diagnostics can show.

    The lines are fed *after* the command is written, which is the only way this can happen on the
    wire — anything already waiting beforehand is stale and is discarded on purpose, which is what
    the test below asserts.
    """
    transport = FakeTransport()
    protocol = await opened(transport)

    task = asyncio.create_task(protocol.execute(":SYST:STAT?", BRIEF))
    await asyncio.sleep(0)  # let it write and start reading
    transport.feed("Tracking: 6\r\nNot Tracking: 2\r\n")  # no prompt ever arrives
    result = await task

    assert result.outcome is TransactionOutcome.TIMED_OUT
    assert result.lines == ("Tracking: 6", "Not Tracking: 2")


async def test_a_removal_mid_transaction_is_a_fault_rather_than_a_raise() -> None:
    """P0-14: the adapter is pulled mid-transaction and the app reports Disconnected rather than
    falling over.

    A removal is not a close. The transport still believes it is open — the handle outlives the
    hardware behind it — and the first sign of it is a read that returns nothing where a prompt
    was expected.
    """
    transport = FakeTransport()
    protocol = await opened(transport)

    task = asyncio.create_task(protocol.execute(":SYNC:TINT?", BRIEF))
    await asyncio.sleep(0)
    transport.simulate_removal()
    result = await task

    assert result.outcome is TransactionOutcome.FAULTED
    assert result.fault is TransportFault.DEVICE_REMOVED
    assert result.fault_message is not None


async def test_using_a_closed_link_is_reported_as_not_open() -> None:
    """The orderly case, and a different fault from the removal above: the caller knows it closed
    the port, and telling them the device was removed would send them looking for a cable."""
    transport = FakeTransport()
    protocol = await opened(transport)
    await transport.close()

    result = await protocol.execute(":SYNC:TINT?", BRIEF)

    assert result.outcome is TransactionOutcome.FAULTED
    assert result.fault is TransportFault.NOT_OPEN


async def test_an_abandoned_reply_is_drained_before_the_next_command() -> None:
    """The defect with a measured cost: a half-read reply arriving late is read as the *next*
    command's answer. Three such samples out of 12,488 made every chart over a seven-day window
    unreadable.

    Here the first command times out having received part of a reply; the tail then arrives. The
    second command must get its own answer, not the tail.
    """
    transport = FakeTransport({":SYNC:TINT?": " -5.4E-009"})
    protocol = await opened(transport)

    transport.feed("stale line one\r\n")  # arrives, but no prompt: the read is abandoned
    first = await protocol.execute(":SYST:STAT?", BRIEF)
    assert first.outcome is TransactionOutcome.TIMED_OUT

    # The rest of the abandoned reply lands now, terminated.
    transport.feed("stale line two\r\nscpi > ")

    second = await protocol.execute(":SYNC:TINT?")

    assert second.succeeded
    assert second.first_line == " -5.4E-009"
    assert not any("stale" in line for line in second.lines)


async def test_nothing_is_drained_when_nothing_had_arrived() -> None:
    """A transaction that received nothing was talking to a device that is silent or gone, and
    there is no tail to drain. Waiting for a prompt that was never coming would add a second
    timeout to each of §7.2's three consecutive failures before it reconnects."""
    transport = FakeTransport({":SYNC:TINT?": " -5.4E-009"})
    protocol = await opened(transport)

    first = await protocol.execute(":SYST:STAT?", BRIEF)
    assert first.outcome is TransactionOutcome.TIMED_OUT
    assert first.lines == ()

    # If a drain were scheduled, this would spend the previous budget before sending.
    second = await protocol.execute(":SYNC:TINT?")

    assert second.succeeded


async def test_stale_bytes_are_discarded_before_writing() -> None:
    """Anything already waiting on a query/response link is the late tail of a timed-out
    transaction. Leaving it would prepend one dead response to every subsequent one."""
    transport = FakeTransport({":SYNC:TINT?": " -5.4E-009"})
    protocol = await opened(transport)
    transport.feed("left over from before\r\n")

    result = await protocol.execute(":SYNC:TINT?")

    assert result.first_line == " -5.4E-009"


# ---- Connecting ------------------------------------------------------------------------------


async def test_synchronise_absorbs_the_power_up_banner() -> None:
    """A Z3805A announces its identity when DTR is asserted. Absorbed here, the session stays
    aligned; left alone, every reply afterwards is one behind."""
    transport = FakeTransport({"*CLS": ""}, banner="SYMMETRICOM,Z3805A,3625A02931,1.01.03-A\r\n")
    protocol = await opened(transport)

    result = await protocol.synchronise(BRIEF)

    assert result.command == CONNECT_LABEL
    assert result.succeeded
    assert result.lines == ("SYMMETRICOM,Z3805A,3625A02931,1.01.03-A",)


async def test_the_banner_names_the_model_before_a_command_is_sent() -> None:
    """§8.6 needs the model to decide which commands exist, and this arrives for free."""
    transport = FakeTransport({"*CLS": ""}, banner="SYMMETRICOM,Z3805A,3625A02931,1.01.03-A\r\n")
    protocol = await opened(transport)

    result = await protocol.synchronise(BRIEF)

    assert "Z3805A" in result.text


async def test_a_silent_receiver_is_not_a_failure_to_connect() -> None:
    """This receiver announces itself; a sibling model may not, and neither case is a failure."""
    transport = FakeTransport({"*CLS": ""})
    protocol = await opened(transport)

    result = await protocol.synchronise(BRIEF)

    assert result.outcome is TransactionOutcome.TIMED_OUT
    assert result.lines == ()


async def test_connecting_spends_the_dtr_glitch_on_a_command_nobody_wants() -> None:
    """Asserting DTR and RTS puts a glitch on the line the receiver reads as a character, and it
    answers the *next* thing it is asked with a framing error, having discarded that command
    unexecuted. So the connect sequence spends it deliberately on ``*CLS`` — tier S, whose whole
    purpose is to clear status and whose response nobody wants.

    Spent by the *caller*, after synchronise: it is this receiver's own power-up behaviour, and
    doing it inside synchronise wrote two commands to a broadcast talker before any driver had
    been asked."""
    transport = FakeTransport({"*CLS": ""})
    protocol = await opened(transport)

    await protocol.synchronise(BRIEF)
    assert transport.written == [], "synchronise listens; it does not send"

    await protocol.spend_startup_glitch()

    assert transport.written == ["*CLS"]


async def test_the_glitch_is_spent_twice_when_the_first_attempt_is_refused() -> None:
    """The first attempt is the one being sacrificed, so a receiver still reporting a non-empty
    queue gets a second."""
    transport = FakeTransport({"*CLS": ""}, prompt=error_prompt(362))
    protocol = await opened(transport)

    await protocol.synchronise(BRIEF)
    await protocol.spend_startup_glitch()

    assert transport.written == ["*CLS", "*CLS"]


# ---- Timeout selection ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (":SYNC:TINT?", timeouts.DEFAULT),
        (":SYST:STAT?", timeouts.STATUS_SCREEN),
        (":SYSTEM:STATUS?", timeouts.STATUS_SCREEN),
        (":DIAG:TEST?", timeouts.SELF_TEST),
        ("*TST?", timeouts.SELF_TEST),
        (":DIAG:LOG:READ:ALL?", timeouts.DIAGNOSTIC_LOG),
        (":DIAG:LOG:READ?", timeouts.DEFAULT),
        (":GPS:POS LAST", timeouts.POSITION_COMMIT),
        (":GPS:POSITION SURVEY", timeouts.POSITION_COMMIT),
        (":NOSUCH:COMMAND?", timeouts.DEFAULT),
    ],
)
def test_each_command_gets_its_tier(command: str, expected: timedelta) -> None:
    """The spread is three orders of magnitude, and one timeout for everything is either too short
    for the log or long enough that a dead link takes a minute to notice."""
    assert timeouts.for_command(command) == expected


def test_the_whole_log_read_is_the_only_log_command_given_a_minute() -> None:
    """``:DIAG:LOG:READ?`` returns one entry and is a scalar by any measure."""
    assert timeouts.for_command(":DIAG:LOG:READ?") == timeouts.DEFAULT
    assert timeouts.for_command(":DIAG:LOG:READ:ALL?") == timeouts.DIAGNOSTIC_LOG


def test_starting_a_survey_is_not_given_the_commit_timeout() -> None:
    """It answers promptly — observed four times, well inside the default — and starting an
    accumulation is not the same work as ending one."""
    assert timeouts.for_command(":GPS:POS:SURV:STAT ONCE") == timeouts.DEFAULT


def test_a_command_is_matched_however_it_is_cased_or_prefixed() -> None:
    assert timeouts.for_command("syst:stat?") == timeouts.STATUS_SCREEN
    assert timeouts.for_command("SYST:STAT?") == timeouts.STATUS_SCREEN
    assert timeouts.for_command(" :SYST:STAT? ") == timeouts.STATUS_SCREEN


# ---- The error queue --------------------------------------------------------------------------


def test_an_error_reply_splits_into_its_number_and_the_receiver_s_own_words() -> None:
    """A split, not a lookup table: a table of meanings written from the manual would be a second
    opinion about what the receiver just said."""
    error = ScpiError.parse('-222,"Data out of range"')

    assert error is not None
    assert error.code == -222
    assert error.message == "Data out of range"
    assert error.is_error is True
    assert error.describe() == "The receiver returned error -222, Data out of range."


def test_an_empty_queue_is_not_an_error() -> None:
    error = ScpiError.parse('+0,"No error"')

    assert error is not None
    assert error.is_error is False


def test_an_unquoted_message_is_still_readable() -> None:
    """A receiver that has dropped a quote should still be readable rather than rejected — the
    number is the part the user acts on."""
    error = ScpiError.parse("-113,Undefined header")

    assert error is not None
    assert error.message == "Undefined header"


@pytest.mark.parametrize("reply", [None, "", "  ", "no comma here", "notanumber,message"])
def test_an_undecomposable_error_reply_is_none(reply: str | None) -> None:
    """§11.1. The caller reports the raw text, which is more useful than a fabricated code."""
    assert ScpiError.parse(reply) is None


# ---- Fault classification ----------------------------------------------------------------------
#
# These use the exact shapes pyserial produces. The permission case is a regression test: it was
# found by pointing the application at a real Z3805A on a machine whose user was not in `dialout`.


def test_a_permission_failure_is_not_reported_as_a_missing_port() -> None:
    """**The regression**, and it has to be built from ``serial.SerialException`` to bite.

    pyserial wraps a permission failure in a ``SerialException`` whose message reads *"[Errno 13]
    could not open port /dev/ttyUSB0: [Errno 13] Permission denied"*. A classifier that matched
    "could not open port" first called that a missing port and told the user their adapter might
    be unplugged — sending them to check a cable when the fix is ``usermod -aG dialout``. §9.11
    requires the copy to be actionable, and that copy was worse than silence because it was
    confidently wrong.

    **The first version of this test used ``OSError(13, ...)`` and passed against the broken
    code.** Python's ``OSError.__new__`` maps errno 13 to ``PermissionError``, which the old
    classifier caught by type — so the synthetic case never reached the message-matching branch
    where the bug lived. ``SerialException`` is a user subclass and gets no such remapping: it
    carries ``errno == 13`` and is *not* a ``PermissionError``, which is the entire defect.

    A regression test that does not reproduce the regression is worse than none, because it reads
    as coverage.
    """
    raised = serial.SerialException(
        13, "could not open port /dev/ttyUSB0: [Errno 13] Permission denied"
    )

    assert not isinstance(raised, PermissionError), "The premise of this test has changed."
    assert classify(raised) is TransportFault.ACCESS_DENIED
    assert "dialout" in describe(TransportFault.ACCESS_DENIED, "/dev/ttyUSB0")


def test_the_errno_is_believed_over_the_message() -> None:
    """The message is prose that has changed between pyserial releases; the errno has not."""
    misleading = serial.SerialException(13, "could not open port: does not exist")

    assert classify(misleading) is TransportFault.ACCESS_DENIED


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (13, TransportFault.ACCESS_DENIED),  # EACCES
        (1, TransportFault.ACCESS_DENIED),  # EPERM
        (2, TransportFault.PORT_NOT_FOUND),  # ENOENT
        (19, TransportFault.DEVICE_REMOVED),  # ENODEV
        (6, TransportFault.DEVICE_REMOVED),  # ENXIO
        (5, TransportFault.IO),  # EIO
    ],
)
def test_each_errno_maps_to_its_fault(code: int, expected: TransportFault) -> None:
    """Raised as pyserial raises them, so the type mapping ``OSError`` does for some errnos cannot
    make one of these pass for the wrong reason."""
    assert classify(serial.SerialException(code, "something")) is expected


def test_an_oserror_with_no_errno_falls_back_to_its_message() -> None:
    """pyserial does not always set one."""
    nothing = serial.SerialException
    assert classify(nothing("could not open port /dev/ttyUSB9")) is TransportFault.PORT_NOT_FOUND
    assert classify(nothing("Permission denied")) is TransportFault.ACCESS_DENIED
    assert classify(nothing("something odd")) is TransportFault.IO


def test_a_port_used_after_close_reads_as_a_removal() -> None:
    """pyserial raises ValueError there. The handle outlives the hardware behind it, which is the
    surprise-removal shape rather than a programming error."""
    assert classify(ValueError("Port is closed")) is TransportFault.DEVICE_REMOVED


def test_every_fault_has_copy_a_user_can_act_on() -> None:
    """§9.11. A fault with no sentence behind it reaches the status bar as an enum name."""
    for fault in TransportFault:
        if fault is TransportFault.NONE:
            continue
        sentence = describe(fault, "/dev/ttyUSB0")
        assert sentence.endswith(".")
        assert "/dev/ttyUSB0" in sentence


# ---- A port closed underneath a live operation (§6.4) --------------------------------------------


class _ClosedUnderneath:
    """A pyserial stand-in that fails the way a real one does when closed mid-read.

    Closing a port while a read is blocked in a worker thread sets the descriptor to ``None``
    underneath it, and pyserial then raises ``TypeError: 'NoneType' object cannot be interpreted as
    an integer``. Reproduced against a Z3805A rather than imagined.
    """

    is_open = False

    def read(self, size: int) -> bytes:
        raise TypeError("'NoneType' object cannot be interpreted as an integer")

    def write(self, data: bytes) -> int:
        raise TypeError("'NoneType' object cannot be interpreted as an integer")

    def flush(self) -> None:
        return None


def test_a_read_that_fails_after_the_port_closed_is_a_removal() -> None:
    """§6.4's own case. The exception classifies as UNKNOWN and reached the user as *"failed for
    an unrecognised reason"* — which tells someone whose adapter has just been pulled nothing they
    can act on, and is exactly what §9.11's copy rule exists to prevent.

    The state of the port is better evidence than the exception, because we can see it went away.
    """
    from smartclock_device.transport.serial_port import SerialTransport

    transport = SerialTransport("/dev/fake")
    transport._serial = _ClosedUnderneath()

    fault = transport._fault_for(TypeError("'NoneType' object cannot be interpreted as an integer"))

    assert fault is TransportFault.DEVICE_REMOVED
    assert describe(fault, "/dev/fake") == "/dev/fake was disconnected."
    assert "unrecognised" not in describe(fault, "/dev/fake")


def test_a_failure_on_a_port_that_is_still_open_keeps_its_own_classification() -> None:
    """The narrowing matters: the port's state only overrides the exception when the port has
    actually gone. A live port that reports a permission problem must still say so."""
    import serial as pyserial

    from smartclock_device.transport.serial_port import SerialTransport

    class _StillOpen(_ClosedUnderneath):
        is_open = True

    transport = SerialTransport("/dev/fake")
    transport._serial = _StillOpen()

    denied = pyserial.SerialException("could not open port /dev/fake: Permission denied")
    denied.errno = 13
    assert transport._fault_for(denied) is TransportFault.ACCESS_DENIED


def test_an_unopened_transport_reports_removal_rather_than_guessing() -> None:
    """Before ``open()`` there is no port, and a failure surfacing then is the same shape."""
    from smartclock_device.transport.serial_port import SerialTransport

    transport = SerialTransport("/dev/fake")

    assert transport._fault_for(TypeError("anything")) is TransportFault.DEVICE_REMOVED
