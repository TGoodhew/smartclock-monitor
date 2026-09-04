"""P1-5's self-test: ``:DIAG:TEST:RES?`` and ``:DIAG:TEST? <keyword>``, and how far
their answers can be read (#53).

Only ``0`` is a pass. Everything else is a test-specific code the manuals do not decode, so this
reports the number and declines to interpret it — and reports ``None`` rather than a failure when
nothing parsed at all, because "the receiver did not answer" and "the receiver failed" are
different things to put in front of someone.
"""

from __future__ import annotations

import pytest

from smartclock_device.models import self_test_subsystem
from smartclock_device.parsing.self_test import SelfTestResult


def test_the_observed_pass_parses() -> None:
    """``+0,ALL``, from the live receiver on 28 Aug 2026."""
    result = SelfTestResult.parse("+0,ALL")

    assert result.code == 0
    assert result.passed is True
    assert result.subsystem == self_test_subsystem.ALL
    assert result.raw_subsystem == "ALL"


def test_the_observed_failure_parses() -> None:
    """``+65536,GPS``, from the same sitting — the antenna was disconnected."""
    result = SelfTestResult.parse("+65536,GPS")

    assert result.code == 65536
    assert result.passed is False
    assert result.subsystem is not None
    assert result.subsystem.keyword == "GPS"


def test_the_leading_space_the_receiver_frames_every_answer_with_is_trimmed() -> None:
    result = SelfTestResult.parse(" +0,ALL")

    assert result.passed is True


def test_a_code_is_read_without_its_sign_being_required() -> None:
    """The sign is always present on this unit; not requiring it costs nothing."""
    assert SelfTestResult.parse("0,ALL").code == 0
    assert SelfTestResult.parse("-1,GPS").code == -1


@pytest.mark.parametrize("reply", [None, "", "    "])
def test_no_answer_is_not_a_failure(reply: str | None) -> None:
    """``None`` throughout, and ``passed`` is ``None`` rather than ``False``. §11.1's distinction
    between an unparseable field and a bad one."""
    result = SelfTestResult.parse(reply)

    assert result.code is None
    assert result.passed is None
    assert result.subsystem is None
    assert result.raw_subsystem is None


@pytest.mark.parametrize(
    "reply",
    [
        "nonsense",
        "ALL,+0",
        ",",
        "+,ALL",
        "0x10,GPS",
        "+1e3,GPS",
        "999999999999999999999,GPS",
    ],
)
def test_an_unreadable_code_is_none_rather_than_a_guess(reply: str) -> None:
    """A number that is not the receiver's grammar is worse than no number: it renders as fact."""
    result = SelfTestResult.parse(reply)

    assert result.code is None
    assert result.passed is None


def test_an_error_reply_is_read_as_a_code_which_is_the_caller_s_problem() -> None:
    """``-113,"Undefined header"`` has the shape of a result and parses as one: code ``-113``,
    which is not zero, which reads as a failed self-test.

    This is faithful to the C# original — ``int.TryParse`` takes ``-113`` there too — and it is
    recorded rather than defended against, because the fix does not belong here. The error queue
    is reported by the *prompt* (``E-nnn>``), which the line protocol reads in Phase 2, and it is
    that layer's job not to hand an error reply to a result parser. A guess here — treating any
    negative code as an error rather than a test-specific code — would be this parser inventing a
    meaning the manuals do not give it.
    """
    result = SelfTestResult.parse('-113,"Undefined header"')

    assert result.code == -113
    assert result.passed is False
    assert result.subsystem is None


def test_an_unknown_keyword_is_kept_verbatim_even_though_it_matches_no_row() -> None:
    """The subsystem is unrecognised; the echo is still what the receiver said."""
    result = SelfTestResult.parse("+0,ZZNOSUCH")

    assert result.subsystem is None
    assert result.raw_subsystem == "ZZNOSUCH"
    assert result.passed is True


def test_a_code_with_no_keyword_still_reports_the_code() -> None:
    result = SelfTestResult.parse("+0")

    assert result.code == 0
    assert result.subsystem is None
    assert result.raw_subsystem is None


def test_a_running_test_takes_its_subsystem_from_the_request() -> None:
    """``:DIAG:TEST? <keyword>`` answers ``+0,+0,+0`` and does not name what it tested."""
    gps = self_test_subsystem.by_keyword("GPS")
    assert gps is not None

    result = SelfTestResult.parse_run("+0,+0,+0", gps)

    assert result.subsystem == gps
    assert result.raw_subsystem == "GPS"
    assert result.code == 0
    assert result.passed is True


def test_only_the_first_of_the_three_integers_is_read() -> None:
    """**What the other two mean is unknown**, and a number shown on a diagnostics page is read as
    meaningful. They would be decoration."""
    gps = self_test_subsystem.by_keyword("GPS")
    assert gps is not None

    result = SelfTestResult.parse_run("+65536,+1,+2", gps)

    assert result.code == 65536
    assert result.passed is False


def test_a_run_with_no_answer_still_names_what_was_asked() -> None:
    """The request is known even when the reply is not; the row has a name and an empty result."""
    result = SelfTestResult.parse_run(None, self_test_subsystem.ALL)

    assert result.subsystem == self_test_subsystem.ALL
    assert result.raw_subsystem == "ALL"
    assert result.code is None
    assert result.passed is None


@pytest.mark.parametrize(
    "reply",
    ["", " ", ",", ",,,,", '"', "\x00", "+0,", "\r\n", "0" * 5000, "ALL", "+0,ALL,extra"],
)
def test_nothing_raises_whatever_arrives(reply: str) -> None:
    """§11.1, which is a rule about the parser and not only about the status screen."""
    result = SelfTestResult.parse(reply)

    assert result.passed in (True, False, None)
