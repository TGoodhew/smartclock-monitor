"""Parses the receiver's diagnostic log entries.

The format is documented, not guessed. 58503A/59551A guide, Command Reference 5-33
(``:DIAGnostic:LOG:READ?``): ``"Log NNN: YYYYMMDD.HH:MM:SS: <log_message>"``, where ``NNN`` is the
entry number, the timestamp is the entry's date and time, and the message runs to 255 characters.
``:DIAG:LOG:READ:ALL?`` answers with the same strings, comma-separated.

**Nothing here raises** (§11.1). A line that does not match keeps its raw text and loses only its
number and timestamp — a firmware revision that reorders the prefix must cost the user the sort
order, not the log.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Final

from smartclock_device.models.diagnostic_log_entry import DiagnosticLogEntry
from smartclock_device.parsing.scalars import parse_integer

#: The timestamp layout the guide gives, fixed width at 17 characters.
_STAMP_FORMAT: Final = "%Y%m%d.%H:%M:%S"

#: How many characters that layout occupies. ``YYYYMMDD`` + ``.`` + ``HH:MM:SS``.
_STAMP_LENGTH: Final = 17

#: The timestamp's shape, matched before it is converted.
#:
#: The same reasoning as :mod:`smartclock_device.parsing.scalars`: ``strptime`` is considerably
#: wider than the guide's fixed-width layout — its ``%m`` and ``%d`` accept one digit as readily as
#: two, so a misaligned slice can still yield a plausible date — and ``[0-9]`` rather than ``\d``
#: because ``\d`` matches every Unicode decimal digit. A timestamp that is nearly right is worse
#: than none: ``None`` renders as ``—``, a wrong date is read as fact.
_STAMP_SHAPE: Final = re.compile(r"^[0-9]{8}\.[0-9]{2}:[0-9]{2}:[0-9]{2}$")

#: The entry prefix: the word Log, an entry number, and the colon that follows it.
_ENTRY_PREFIX: Final = re.compile(r"Log\s+[0-9]+\s*:", re.IGNORECASE)


def _unquote(text: str) -> str:
    trimmed = text.strip()

    if len(trimmed) >= 2 and trimmed[0] == '"' and trimmed[-1] == '"':
        return trimmed[1:-1].strip()
    return trimmed


def _parse_stamp(text: str) -> datetime | None:
    """Convert the fixed-width timestamp, or return ``None``.

    Tagged UTC rather than left naive — see
    :attr:`~smartclock_device.models.diagnostic_log_entry.DiagnosticLogEntry.timestamp` for why the
    tag is a Python necessity rather than a claim about the receiver's time scale.
    """
    if not _STAMP_SHAPE.match(text):
        return None

    try:
        return datetime.strptime(text, _STAMP_FORMAT).replace(tzinfo=UTC)
    except ValueError:
        # The shape matched but the values did not make a date — 20061301, or the 31st of
        # February. §11.1: that is a missing timestamp, not an error.
        return None


def _unrecognised(text: str) -> DiagnosticLogEntry:
    return DiagnosticLogEntry(raw_text=text, message=text)


def parse(line: str | None) -> DiagnosticLogEntry:
    """Parse one entry, quoted or not, as the receiver returned it."""
    text = _unquote(line or "")

    if not text:
        return DiagnosticLogEntry(raw_text=text, message="")

    if not text.upper().startswith("LOG"):
        return _unrecognised(text)

    after_number = text.find(":")
    if after_number < 0:
        return _unrecognised(text)

    number = parse_integer(text[3:after_number])

    # Fixed width rather than a split: the timestamp contains colons of its own, so counting
    # separators would cut it in half.
    remainder = text[after_number + 1 :].lstrip()

    if len(remainder) < _STAMP_LENGTH:
        return DiagnosticLogEntry(raw_text=text, number=number, message=remainder)

    stamp = _parse_stamp(remainder[:_STAMP_LENGTH])

    if stamp is None:
        return DiagnosticLogEntry(raw_text=text, number=number, message=remainder)

    message = remainder[_STAMP_LENGTH:].lstrip()
    if message.startswith(":"):
        message = message[1:].lstrip()

    return DiagnosticLogEntry(
        raw_text=text,
        number=number,
        timestamp=stamp,
        message=message,
    )


def parse_all(response: str | None) -> tuple[DiagnosticLogEntry, ...]:
    """Split the answer to ``:DIAG:LOG:READ:ALL?`` into entries.

    **Split on the entry prefix, not on the separator.** The guide describes the response as quoted
    strings separated by commas — ``"XYZ", ...`` — but the Z3805A on the bench returns them
    *unquoted*, wrapped across lines, and its messages contain commas of their own: "Holdover
    started, not tracking GPS" is a single entry it emits constantly. Splitting on commas cut that
    in half and left the second piece masquerading as an entry.

    The ``Log NNN:`` prefix is the one thing every entry starts with and no message contains, so it
    is what the boundary is drawn at. That works for the guide's quoted form and the unit's
    unquoted one without having to know which arrived.
    """
    if response is None or not response.strip():
        return ()

    # Quotes and commas between entries become whitespace; a comma inside a message is left alone,
    # because the split below never looks at commas at all.
    text = response.replace('"', " ")

    starts = [match.start() for match in _ENTRY_PREFIX.finditer(text)]

    if not starts:
        # No recognisable prefix anywhere: one unparsed entry rather than nothing at all.
        return (parse(text),)

    entries: list[DiagnosticLogEntry] = []

    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else len(text)

        # Trailing separators belong to the format, not to the message. The guide's form leaves a
        # comma behind after the quotes are stripped; the unit's leaves whitespace.
        piece = text[start:end].strip().rstrip(",").strip()
        if piece:
            entries.append(parse(piece))

    return tuple(entries)
