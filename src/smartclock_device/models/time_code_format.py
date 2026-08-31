"""Which of the two time code formats the receiver emits from ``:PTIM:TCOD?``.

The two differ in what they carry, not merely in spelling: T1 gives the time of the next 1 PPS as
a hexadecimal count of seconds since the GPS epoch, T2 as calendar fields. Nothing can decode a
time code without first knowing which it is looking at.

**The receiver is not necessarily in the documented default.** ``z3801.pdf`` states that "T1 is the
default time code format", and the bench Z3805A answers ``F2``. A decoder written against the
documented default would mis-parse every message that unit sends, so the format is read rather than
assumed. That is the whole reason this query is catalogued.

**The manual names the same two formats two ways**, and both spellings are accepted here. The
command's parameter is ``F1`` or ``F2``, while the header the message itself begins with is ``T1``
or ``T2``. Reading back an ``F`` and matching it against a ``T`` is an easy way to decide a
receiver is in an unknown state when it is not, and the cost of accepting both is one extra case.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

#: The query, as §8.2 lists it.
QUERY: Final = ":PTIM:TCOD:FORM?"


class TimeCodeFormat(Enum):
    """The two documented formats, and the honest absence of an answer."""

    #: Not read, or the receiver answered something neither format names.
    UNKNOWN = 0

    #: Seconds since the GPS epoch, hexadecimal — 19 characters.
    T1 = 1

    #: Calendar date and time — 23 characters.
    T2 = 2


#: How many characters a message in each format occupies, excluding the trailing ``CR LF``.
_MESSAGE_LENGTHS: Final[dict[TimeCodeFormat, int]] = {
    TimeCodeFormat.T1: 19,
    TimeCodeFormat.T2: 23,
}


def parse(response: str | None) -> TimeCodeFormat:
    """Decode one response line into a format, or :attr:`TimeCodeFormat.UNKNOWN`.

    Never raises (§11.1). An unreadable answer is :attr:`~TimeCodeFormat.UNKNOWN`, which the page
    renders as ``—`` — the receiver is in *some* format and this did not establish which, which is
    a different and more honest claim than naming one.
    """
    if response is None or not response.strip():
        return TimeCodeFormat.UNKNOWN

    # Every response arrives with a leading space, and the manual describes this one as a quoted
    # string though the bench receiver answers bare. Both are stripped rather than one being
    # assumed.
    value = response.strip().strip('"').strip().upper()

    if value in ("F1", "T1"):
        return TimeCodeFormat.T1
    if value in ("F2", "T2"):
        return TimeCodeFormat.T2
    return TimeCodeFormat.UNKNOWN


def message_length(code_format: TimeCodeFormat) -> int | None:
    """How many characters a message in ``code_format`` occupies, or ``None``.

    Excluding the trailing ``CR LF``. Useful as a cheap sanity check on a decoded message, and
    ``None`` for :attr:`~TimeCodeFormat.UNKNOWN` because there is nothing to expect.
    """
    return _MESSAGE_LENGTHS.get(code_format)
