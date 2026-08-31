"""The accumulating buffer and the prompt grammar — the piece §15 puts first.

The plan calls this the single highest-value thing to unit-test, and names the two tests that
matter: feed it a captured screen **one byte at a time**, and again **in two chunks split at every
offset inside the prompt**. Both are here and both are exhaustive, because the failure they guard
against — a sentinel landing across a read boundary — is not occasional at 9600 baud, it is the
normal case for a 1,900-byte screen.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from smartclock_device.transport.response_buffer import (
    MAX_PROMPT_LENGTH,
    ResponseBuffer,
    match_prompt,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: The ordinary prompt, with the space before the bracket that §7.2's earlier wording omitted.
PROMPT = "scpi > "


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_bytes().decode("latin-1")


def feed_all(buffer: ResponseBuffer, data: bytes, chunk: int) -> bool:
    complete = False
    for at in range(0, len(data), chunk):
        complete = buffer.feed(data[at : at + chunk])
    return complete


# ---- The prompt grammar ---------------------------------------------------------------------


def test_the_ordinary_prompt_has_a_space_before_the_bracket() -> None:
    """§7.2 used to give the literal ``"scpi> "``, which never matches at all on firmware
    1.01.03-A. The observed prompt is ``"scpi > "``."""
    match = match_prompt("scpi > ")

    assert match is not None
    assert match.status is None
    assert match.length == 7


def test_the_error_prompt_has_no_space_and_carries_its_token() -> None:
    """While the error queue is not empty the word is replaced entirely."""
    match = match_prompt("E-230> ")

    assert match is not None
    assert match.status == "E-230"


def test_the_error_token_is_kept_verbatim_rather_than_signed() -> None:
    """SCPI's standard codes are negative and the prompt prints no sign. Inventing one would put a
    guess on the Diagnostics page."""
    match = match_prompt("E-113> ")

    assert match is not None
    assert match.status == "E-113"
    assert "-113" not in [match.status]  # it is the token "E-113", not the number -113


@pytest.mark.parametrize("tail", ["scpi >", "E-230>", " scpi > ", "scpi  > "])
def test_prompt_spacing_is_tolerated_where_it_can_be(tail: str) -> None:
    """Trailing space and space around the bracket vary; the shape does not."""
    assert match_prompt(tail) is not None


@pytest.mark.parametrize(
    "tail",
    [
        "",
        "scpi",
        "scpi ",
        "E-",
        "E-2",
        "E->",
        "SCPI > ",
        "notaprompt> ",
        "> ",
        "Tracking: 6 >",
        "  1PPS TI  -5.4E-009 ns >",
    ],
)
def test_a_tail_that_is_not_a_prompt_does_not_match(tail: str) -> None:
    """Matching is deliberately narrow rather than "anything ending in ``>``": the tail is also
    where a half-arrived response line sits, and a status screen line containing a bracket must not
    be mistaken for the end of the transaction."""
    assert match_prompt(tail) is None


@pytest.mark.parametrize("tail", ["E-1", "E-113", "E-113 "])
def test_an_error_prompt_without_its_bracket_waits(tail: str) -> None:
    """Digits with no bracket are a prompt still arriving, so it waits — and completes the moment
    the bracket lands."""
    assert match_prompt(tail) is None
    assert match_prompt(tail + ">") is not None


def test_an_error_prompt_with_no_digits_never_completes() -> None:
    """``E-`` alone is either a truncated prompt or not one at all, and ``E->`` is neither: a
    bracket does not rescue a token with no number in it. Both mean wait, so neither needs
    distinguishing — but the second must not be mistaken for a *complete* prompt carrying an empty
    status, which would report an error queue that nothing had said was non-empty."""
    assert match_prompt("E-") is None
    assert match_prompt("E-> ") is None


def test_the_prompt_word_is_case_sensitive() -> None:
    """The receiver prints it lower-case. Accepting any case would widen the sentinel for no
    reason, and the tail is shared with response text."""
    assert match_prompt("SCPI > ") is None


# ---- Lines ---------------------------------------------------------------------------------


def test_crlf_is_one_line_ending() -> None:
    buffer = ResponseBuffer()

    buffer.feed(b"first\r\nsecond\r\n")

    assert buffer.lines == ("first", "second")


def test_a_bare_cr_ends_a_line() -> None:
    """A firmware that ends lines with CR alone must not stall waiting for an LF."""
    buffer = ResponseBuffer()

    buffer.feed(b"first\rsecond\r")

    assert buffer.lines == ("first", "second")


def test_a_bare_lf_ends_a_line() -> None:
    buffer = ResponseBuffer()

    buffer.feed(b"first\nsecond\n")

    assert buffer.lines == ("first", "second")


def test_a_crlf_split_across_two_feeds_is_still_one_line_ending() -> None:
    """The defect this guards: counting the pair as two endings inserts a blank line between two
    real ones. Silent corruption, and near-certain at 9600 baud."""
    buffer = ResponseBuffer()

    buffer.feed(b"first\r")
    buffer.feed(b"\nsecond\r\n")

    assert buffer.lines == ("first", "second")


def test_a_cr_at_the_end_of_a_feed_followed_by_text_is_a_bare_cr() -> None:
    """The pending LF that never comes must not swallow the next line's first character."""
    buffer = ResponseBuffer()

    buffer.feed(b"first\r")
    buffer.feed(b"second\r\n")

    assert buffer.lines == ("first", "second")


def test_blank_lines_inside_a_response_survive() -> None:
    """The status screen has them, and they carry column alignment."""
    buffer = ResponseBuffer()

    buffer.feed(b"first\r\n\r\nthird\r\n")

    assert buffer.lines == ("first", "", "third")


def test_an_incomplete_line_is_not_yet_a_line() -> None:
    buffer = ResponseBuffer()

    buffer.feed(b"partial")

    assert buffer.lines == ()
    assert buffer.pending == "partial"


# ---- Completion -----------------------------------------------------------------------------


def test_a_setter_answers_with_the_prompt_alone() -> None:
    """§7.2: a setter, and a rejected command, answer with the prompt and nothing else. That is
    what makes this the same shape of read as a 1,900-byte screen."""
    buffer = ResponseBuffer()

    assert buffer.feed(PROMPT.encode()) is True
    assert buffer.lines == ()
    assert buffer.prompt_status is None


def test_a_rejected_command_answers_with_an_error_prompt_alone() -> None:
    buffer = ResponseBuffer()

    assert buffer.feed(b"E-113> ") is True
    assert buffer.lines == ()
    assert buffer.prompt_status == "E-113"


def test_a_response_completes_at_its_prompt() -> None:
    buffer = ResponseBuffer()

    assert buffer.feed(b"+0\r\n" + PROMPT.encode()) is True
    assert buffer.lines == ("+0",)


def test_feeding_after_completion_changes_nothing() -> None:
    """The bytes after the prompt belong to whatever comes next; consuming them here would eat the
    following transaction's first line."""
    buffer = ResponseBuffer()
    buffer.feed(b"+0\r\n" + PROMPT.encode())

    assert buffer.feed(b"the next transaction\r\n") is True
    assert buffer.lines == ("+0",)


def test_a_tail_longer_than_the_prompt_window_is_not_tested() -> None:
    """Anything longer than the window is an unfinished response line, and testing it would only
    waste the decode."""
    buffer = ResponseBuffer()

    assert buffer.feed(b"x" * (MAX_PROMPT_LENGTH + 1)) is False


def test_high_bytes_survive_as_characters_rather_than_substitutions() -> None:
    """Latin-1 is the one single-byte encoding that never substitutes, so line noise reaches the
    parser as something it can reject instead of as a silent question mark."""
    buffer = ResponseBuffer()

    buffer.feed(b"\xff\xfe\r\n" + PROMPT.encode())

    assert buffer.lines == ("\xff\xfe",)


# ---- The two tests the plan names -----------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "locked-stabilizing.txt",
        "captured/locked-to-gps.txt",
        "captured/holdover-gps-1pps-invalid.txt",
    ],
)
def test_a_captured_screen_arrives_one_byte_at_a_time(name: str) -> None:
    """The plan's first named test. At 9600 baud a 1,900-byte screen is delivered in dozens of
    chunks, and one byte at a time is that case taken to its limit."""
    screen = read_fixture(name)
    wire = (screen if screen.endswith("\r\n") else screen + "\r\n") + PROMPT

    buffer = ResponseBuffer()
    complete = feed_all(buffer, wire.encode("latin-1"), chunk=1)

    assert complete is True
    assert buffer.prompt_status is None
    assert buffer.lines == tuple(screen.rstrip("\r\n").split("\r\n"))


def test_a_screen_delivered_whole_parses_identically_to_one_delivered_by_byte() -> None:
    """The chunking must not be observable in the result. If it is, everything above is testing
    the wrong thing."""
    screen = read_fixture("captured/locked-to-gps.txt")
    wire = (screen + PROMPT).encode("latin-1")

    whole = ResponseBuffer()
    whole.feed(wire)

    by_byte = ResponseBuffer()
    feed_all(by_byte, wire, chunk=1)

    assert whole.lines == by_byte.lines
    assert whole.is_complete and by_byte.is_complete


@pytest.mark.parametrize("split", range(1, len(PROMPT) + 1))
def test_the_prompt_split_at_every_offset_inside_it(split: int) -> None:
    """The plan's second named test, and the reason Pipelines exists in the C# original: the
    sentinel lands across a read boundary and must cost nothing when it does."""
    screen = read_fixture("captured/locked-to-gps.txt")
    wire = (screen + PROMPT).encode("latin-1")
    boundary = len(wire) - len(PROMPT) + split

    buffer = ResponseBuffer()
    first = buffer.feed(wire[:boundary])
    second = buffer.feed(wire[boundary:])

    assert (first or second) is True
    assert buffer.prompt_status is None
    assert buffer.lines == tuple(screen.rstrip("\r\n").split("\r\n"))


@pytest.mark.parametrize("split", range(1, 8))
def test_an_error_prompt_split_at_every_offset_inside_it(split: int) -> None:
    """The error prompt carries a token that has to survive the same treatment — and a half-read
    ``E-1`` must not be mistaken for a complete ``E-1``."""
    wire = b"E-230> "
    buffer = ResponseBuffer()

    buffer.feed(wire[:split])
    buffer.feed(wire[split:])

    assert buffer.is_complete
    assert buffer.prompt_status == "E-230"


@pytest.mark.parametrize("chunk", [1, 2, 3, 7, 13, 64, 512, 4096])
def test_every_chunk_size_gives_the_same_answer(chunk: int) -> None:
    screen = read_fixture("captured/holdover-gps-1pps-invalid.txt")
    wire = (screen + PROMPT).encode("latin-1")

    buffer = ResponseBuffer()
    complete = feed_all(buffer, wire, chunk)

    assert complete is True
    assert buffer.lines == tuple(screen.rstrip("\r\n").split("\r\n"))


def test_the_captured_prompt_ends_the_transaction_and_the_banner_is_the_next_one() -> None:
    """``power-up-gps-acquisition.txt`` ends ``scpi > SYMMETRICOM,Z3805A,3625A02931,1.01.03-A``.

    That is not a formatting quirk, it is the evidence for why the synchronise step exists. On the
    wire the prompt arrives with no line ending — it is the tail — and the identity string that
    follows is **unsolicited**, emitted because DTR was asserted. The capture has the two glued
    together because nothing separated them in time.

    So the prompt terminates the transaction, and every byte after it belongs to whatever comes
    next. A protocol that read the whole capture as one response would take the receiver's
    announcement as the answer to whatever it had asked, and every reply afterwards would be one
    behind — which is exactly the misalignment `LineProtocol.synchronise` absorbs.
    """
    captured = read_fixture("captured/power-up-gps-acquisition.txt")
    at = captured.index(PROMPT)
    wire = captured.encode("latin-1")

    buffer = ResponseBuffer()
    complete = feed_all(buffer, wire[: at + len(PROMPT)], chunk=1)

    assert complete is True
    assert buffer.prompt_status is None
    # The screen itself, and not the announcement that followed it.
    assert buffer.lines[0].startswith("---")
    assert not any("SYMMETRICOM" in line for line in buffer.lines)

    # And what is left is the next transaction's bytes, intact.
    assert wire[at + len(PROMPT) :].decode("latin-1").startswith("SYMMETRICOM,Z3805A")
