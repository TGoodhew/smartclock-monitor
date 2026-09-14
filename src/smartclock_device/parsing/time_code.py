"""The message ``:PTIM:TCOD?`` answers with: the time of the *next* 1 PPS, and five flags.

**Twenty-three characters that carry five readings.** The date and time, the two figures of merit,
whether a leap second is announced, whether the receiver is asking for service, and whether it
considers its own time valid — in a line shorter than the mnemonic that asks for it. The status
screen carries the same five and is seventy times the size.

That is not a reason to poll it. §10.14 measured the cost and this port re-measured it on
13 Sep 2026: the receiver answers **on its own 1 Hz cadence**, so the transaction blocks until the
next emission slot — 0.4 to 1.0 s against 0.2 s for an ordinary scalar query, on the same link in
the same minute. One reading that costs five queries' worth of wall time is not a bargain, and
§7.3's fast tier is a second long. It is catalogued because §8.2 lists it and §10.11 should be able
to ask for it, and it is decoded here because a user shown `T2200701290050103000034` has been shown
nothing.

**The field layout is a citation confirmed by arithmetic.** Lady Heather's SCPI decoder reads the
message as a fixed-width sequence (#98), and `models/time_code_format.py` — written here from the
Z3801A guide, months earlier and without reference to her — records the two message lengths as 19
and 23 characters. Those two facts agree exactly: a T1 header, `#H`, eight hexadecimal digits, five
flags and a two-character checksum is nineteen characters, and the T2 calendar form is
twenty-three. Two sources that never saw each other, agreeing on a total.

**The checksum is the sum of every preceding character, modulo 256**, and it is checked rather
than trusted. #37 verified the rule on 103 of 103 messages in Aug 2026; 14 of 14 more on
13 Sep 2026. A message whose checksum does not match is still decoded — the fields are still the
receiver's own bytes — but :attr:`TimeCode.checksum_ok` says so, because a decoder that silently
dropped a message would turn a corrupted read into a missing one.

**T1 is decoded and has never been seen.** The bench receiver is in T2 and the setter that would
change it is deliberately not catalogued (§10.14.1). So the T1 path rests on the citation and on
the length agreeing, and its tests are built from that structure rather than captured from
hardware. That is stated here rather than left for a reader to discover, and it is why
:attr:`TimeCode.from_capture` exists.

Never raises (§11.1). Anything unrecognisable comes back as :data:`UNREADABLE`, whose fields are
all ``None`` and which renders as an em dash everywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from smartclock_device.models.receiver_status import LeapSecondPending
from smartclock_device.models.time_code_format import TimeCodeFormat

#: The GPS epoch, from which T1 counts seconds.
GPS_EPOCH: Final = datetime(1980, 1, 6, tzinfo=UTC)

#: How many characters the checksum occupies, at the end of every message in both formats.
_CHECKSUM_WIDTH: Final = 2

#: Where the five flags begin, by format. Everything before this is the time; everything after is
#: the checksum.
_FLAGS_AT: Final[dict[TimeCodeFormat, int]] = {TimeCodeFormat.T1: 12, TimeCodeFormat.T2: 16}

#: What the leap flag's three values mean.
_LEAP: Final[dict[str, LeapSecondPending]] = {
    "+": LeapSecondPending.PLUS,
    "-": LeapSecondPending.MINUS,
    "0": LeapSecondPending.NONE,
}


@dataclass(frozen=True, slots=True)
class TimeCode:
    """One decoded time-code message.

    Every field is optional and defaults to absent, because §11.1's rule is that a reading which
    did not parse is ``None`` and renders as an em dash — never a zero, and never a guess.
    """

    #: Which format the message was in, from its own header rather than from ``:PTIM:TCOD:FORM?``.
    #: The two should agree; this is the one that decoded the line in front of us.
    format: TimeCodeFormat = TimeCodeFormat.UNKNOWN

    #: The instant the message names, **as the receiver reported it** — so a rolled-over receiver's
    #: date arrives here two decades out, exactly as it does from the status screen. §7.4's
    #: correction is applied by the consumer and reported beside this, never in place of it.
    when: datetime | None = None

    #: Time and frequency figures of merit, as the message carries them.
    tfom: int | None = None
    ffom: int | None = None

    #: Whether a leap second is announced, and in which direction.
    leap_pending: LeapSecondPending = LeapSecondPending.NONE

    #: Whether the receiver is asking to be serviced.
    service_requested: bool | None = None

    #: Whether the receiver considers the time it just gave valid. ``False`` is the same claim the
    #: status screen makes with its ``(?)`` marker.
    time_valid: bool | None = None

    #: Whether the trailing checksum matched the characters before it. ``None`` when there was no
    #: checksum to check.
    checksum_ok: bool | None = None

    #: What arrived, stripped of framing and nothing else.
    text: str = ""

    #: Why a field is absent, where there is something to say.
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def decoded(self) -> bool:
        """Whether this is a message at all. A page shows the raw text either way."""
        return self.format is not TimeCodeFormat.UNKNOWN


#: What an unreadable line decodes to. Not an exception and not ``None``: §11.1's contract is that
#: a parser always returns a model, and that every field of it may be absent.
UNREADABLE: Final = TimeCode()


def parse(response: str | None) -> TimeCode:
    """Decode one time-code message. Never raises."""
    if response is None:
        return UNREADABLE

    text = response.strip()
    if len(text) < 4:
        return TimeCode(text=text, notes=("The line is too short to be a time code.",))

    header = text[:2].upper()
    layout = TimeCodeFormat.T1 if header == "T1" else TimeCodeFormat.T2 if header == "T2" else None
    if layout is None:
        return TimeCode(text=text, notes=(f"{header!r} is neither T1 nor T2.",))

    expected = _message_length(layout)
    if len(text) != expected:
        return TimeCode(
            text=text,
            notes=(
                f"A {layout.name} message is {expected} characters and this one is {len(text)}.",
            ),
        )

    flags_at = _FLAGS_AT[layout]
    when, notes = (
        _t1_instant(text[4:flags_at])
        if layout is TimeCodeFormat.T1
        else _t2_instant(text[2:flags_at])
    )
    if layout is TimeCodeFormat.T1 and text[2:4].upper() != "#H":
        notes = (*notes, "A T1 message's count is introduced by '#H' and this one is not.")
        when = None

    flags = text[flags_at : flags_at + 5]
    return TimeCode(
        format=layout,
        when=when,
        tfom=_digit(flags[0]),
        ffom=_digit(flags[1]),
        leap_pending=_LEAP.get(flags[2], LeapSecondPending.NONE),
        service_requested=_flag(flags[3]),
        # The receiver reports **in**validity, so the sense is inverted here rather than at every
        # reader: "1 means invalid" is the kind of fact that gets forgotten by the second consumer.
        time_valid=None if (raised := _flag(flags[4])) is None else not raised,
        checksum_ok=_checksum_matches(text),
        text=text,
        notes=notes,
    )


def from_capture(text: str) -> TimeCode:
    """:func:`parse`, named for what a test is doing when it hands over a captured line.

    A reading of this module should be able to tell at a glance which assertions rest on bytes a
    receiver sent and which on a message built from the documented structure — every T1 test is the
    second kind, and calling the same function two names is cheaper than a comment on each.
    """
    return parse(text)


def _message_length(layout: TimeCodeFormat) -> int:
    return _FLAGS_AT[layout] + 5 + _CHECKSUM_WIDTH


def _t2_instant(digits: str) -> tuple[datetime | None, tuple[str, ...]]:
    """``YYYYMMDDhhmmss`` as the receiver's own instant, or ``None``."""
    try:
        return datetime.strptime(digits, "%Y%m%d%H%M%S").replace(tzinfo=UTC), ()
    except ValueError:
        return None, (f"{digits!r} is not a calendar date and time.",)


def _t1_instant(digits: str) -> tuple[datetime | None, tuple[str, ...]]:
    """Eight hexadecimal digits counting seconds from the GPS epoch."""
    try:
        seconds = int(digits, 16)
    except ValueError:
        return None, (f"{digits!r} is not a hexadecimal count.",)
    try:
        return GPS_EPOCH + timedelta(seconds=seconds), ()
    except OverflowError:
        # The same defect `test_parser_fuzz` found in the status screen's durations: a count this
        # large cannot be a date, and raising here would break §11.1 for one corrupted read.
        return None, (f"A count of {seconds} seconds is past any representable date.",)


def _digit(character: str) -> int | None:
    return int(character) if character.isdigit() else None


def _flag(character: str) -> bool | None:
    if character == "0":
        return False
    if character == "1":
        return True
    return None


def _checksum_matches(text: str) -> bool | None:
    """The sum of every character before the checksum, modulo 256."""
    body, given = text[:-_CHECKSUM_WIDTH], text[-_CHECKSUM_WIDTH:]
    try:
        claimed = int(given, 16)
    except ValueError:
        return None
    return sum(ord(character) for character in body) % 256 == claimed
