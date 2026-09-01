"""The accumulating read buffer, and the prompt grammar that ends a transaction (§7.2, §6.4).

This is the piece §15 puts first, and the plan calls it the single highest-value thing to
unit-test. Three properties have to hold, and none of them is expressible with ``readline()``:

**The terminator is a prompt, not a newline.** A transaction ends at ``scpi > `` or ``E-nnn> ``,
which is what makes a setter (prompt only) and a 1,900-byte status screen the same shape of read.

**The prompt straddles reads.** At 9600 baud a status screen arrives in dozens of chunks and the
sentinel will land across a boundary. C# solves this with ``System.IO.Pipelines``, distinguishing
bytes *consumed* from bytes merely *examined*; Python has no equivalent, and
``asyncio.StreamReader.readuntil`` takes a fixed separator, which the prompt grammar is not. So the
plan's answer is what is implemented here: accumulate, and after each append test only the last
few bytes, because anything longer is an unfinished response line and testing it only wastes the
decode.

**CRLF is one line ending, not two.** A read that ends on a CR whose LF has not arrived yet must
not produce a blank line — which is silent corruption, and near-certain at 9600 baud.

Deliberately synchronous and transport-free. It is fed bytes from anywhere, which is what lets the
tests drive a captured screen through it one byte at a time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

_CR: Final = 0x0D
_LF: Final = 0x0A

#: The word the ordinary prompt is built from.
_PROMPT_WORD: Final = "scpi"

#: What the prompt shows instead of the word while the error queue is not empty (§7.2).
_ERROR_PROMPT_PREFIX: Final = "E-"

#: The longest tail worth testing against the prompt grammar.
#:
#: Anything longer is a response line that has not finished arriving, and testing it would only
#: waste the decode. The plan's figure.
MAX_PROMPT_LENGTH: Final = 32


@dataclass(frozen=True, slots=True)
class PromptMatch:
    """A complete prompt found at the start of the tail."""

    #: How many characters the prompt occupies.
    length: int

    #: The error token when the receiver is reporting one — ``E-230`` and the like — or ``None``
    #: for the ordinary prompt.
    status: str | None


def match_prompt(tail: str) -> PromptMatch | None:
    """Match a complete prompt at the start of ``tail``, which contains no line ending.

    §7.2's prompt grammar has two forms, both observed on a Z3805A running firmware 1.01.03-A —
    the literal ``"scpi> "`` the section used to give never matches at all:

    The ordinary prompt is ``"scpi > "``, **with a space before the bracket**. While the error
    queue is not empty the word is replaced entirely, ``"E-230> "`` and the like, with no space —
    the prompt doubles as the queue indicator, not as a verdict on the last command. A command that
    is rejected answers with *only* that prompt, so a protocol looking for the literal string waits
    out its full timeout on every failed command and then does it again on the next one.

    Matching is deliberately narrow rather than "anything ending in ``>``": the tail is also where
    a half-arrived response line sits, and a status screen line containing a bracket must not be
    mistaken for the end of the transaction.
    """
    index = 0
    while index < len(tail) and tail[index] == " ":
        index += 1

    token_start = index

    if tail.startswith(_PROMPT_WORD, index):
        index += len(_PROMPT_WORD)
    elif tail.startswith(_ERROR_PROMPT_PREFIX, index):
        index += len(_ERROR_PROMPT_PREFIX)
        digits_start = index
        while index < len(tail) and tail[index].isascii() and tail[index].isdigit():
            index += 1
        if index == digits_start:
            # "E-" with nothing after it yet: either a truncated prompt or not one at all. Both
            # mean wait, so neither needs distinguishing.
            return None
    else:
        return None

    token_end = index

    while index < len(tail) and tail[index] == " ":
        index += 1

    if index >= len(tail) or tail[index] != ">":
        return None

    index += 1
    if index < len(tail) and tail[index] == " ":
        index += 1

    token = tail[token_start:token_end]
    return PromptMatch(length=index, status=None if token == _PROMPT_WORD else token)


def _decode(data: bytes | bytearray) -> str:
    """Latin-1 rather than ASCII: it is the one single-byte encoding that never substitutes.

    A stray high byte from line noise reaches the parser as a character it can reject, instead of
    as a silent ``?``.
    """
    return bytes(data).decode("latin-1")


class ResponseBuffer:
    """Accumulates inbound bytes, yields complete lines, and detects the terminating prompt.

    Feed it chunks of any size, including one byte at a time. When :meth:`feed` returns ``True``
    the transaction is over, :attr:`lines` is the complete response and :attr:`prompt_status`
    carries the prompt's error token.
    """

    def __init__(self, *, detect_prompt: bool = True) -> None:
        # **Off for a broadcast link.** A talker sends no prompt, and a sentence fragment that
        # happened to match one would mark the buffer complete and freeze the stream for good —
        # a failure that needs the exact bytes to reproduce. Nothing to look for, so nothing looks.
        self._detect_prompt = detect_prompt
        self._buffer = bytearray()
        self._lines: list[str] = []
        self._prompt: PromptMatch | None = None

        # Set when a read ends on a CR whose LF has not arrived yet. Without it the pair is counted
        # as two line endings and a blank line appears between two real ones.
        self._pending_line_feed = False

    @property
    def lines(self) -> tuple[str, ...]:
        """The complete lines seen so far, terminators stripped."""
        return tuple(self._lines)

    @property
    def prompt_status(self) -> str | None:
        """The prompt's error token, or ``None`` for the ordinary prompt or no prompt at all."""
        return self._prompt.status if self._prompt is not None else None

    @property
    def is_complete(self) -> bool:
        """Whether the terminating prompt has arrived."""
        return self._prompt is not None

    @property
    def pending(self) -> str:
        """Whatever has arrived but is not yet a complete line. Diagnostics only."""
        return _decode(self._buffer)

    def feed(self, chunk: bytes) -> bool:
        """Append bytes and rescan. Returns whether the transaction is now complete.

        Once complete, further feeding does nothing: the remaining bytes belong to whatever comes
        next, and consuming them here would eat the following transaction's first line.
        """
        if self._prompt is not None:
            return True

        self._buffer.extend(chunk)
        self._extract_lines()

        # Whatever is left has no CR or LF in it — the loop above consumed every one — and the
        # prompt never contains a line ending. So the prompt, if it has arrived, is exactly this.
        tail = self._buffer
        if not self._detect_prompt or not tail or len(tail) > MAX_PROMPT_LENGTH:
            return False

        match = match_prompt(_decode(tail))
        if match is None:
            return False

        self._prompt = match
        del self._buffer[: match.length]
        return True

    def drain_lines(self) -> tuple[str, ...]:
        """Take the complete lines out and forget them.

        For a stream rather than a transaction: a talker sends the same sentences for weeks, and a
        buffer that accumulated every one would be a memory leak with a calendar on it.
        """
        taken = tuple(self._lines)
        self._lines.clear()
        return taken

    def _extract_lines(self) -> None:
        """Move every complete line out of the buffer, treating CRLF as one ending."""
        start = 0
        buffer = self._buffer

        if self._pending_line_feed:
            if len(buffer) == 0:
                return
            if buffer[0] == _LF:
                start = 1
            self._pending_line_feed = False

        while True:
            index = _index_of_line_break(buffer, start)
            if index < 0:
                break

            line = buffer[start:index]
            delimiter = buffer[index]
            start = index + 1

            if delimiter == _CR:
                if start < len(buffer):
                    if buffer[start] == _LF:
                        start += 1
                else:
                    # The LF, if there is one, is in the next chunk. Waiting for it here instead
                    # would stall a firmware that ends lines with a bare CR.
                    self._pending_line_feed = True

            self._lines.append(_decode(line))

        del buffer[:start]


def _index_of_line_break(buffer: bytearray, start: int) -> int:
    """The index of the next CR or LF at or after ``start``, or ``-1``."""
    carriage_return = buffer.find(_CR, start)
    line_feed = buffer.find(_LF, start)

    if carriage_return < 0:
        return line_feed
    if line_feed < 0:
        return carriage_return
    return min(carriage_return, line_feed)
