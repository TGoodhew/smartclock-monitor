"""One catalogued command, and the two enums that classify it (§8.1, §8.2).

The catalog is an **allowlist**. A command that is not an entry here does not exist as far as this
application is concerned — there is no free-text path that could reach one, and §10.11's Advanced
Console is a picker over these entries rather than a terminal.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from smartclock_device.commands.position_argument import PositionArgument


class SafetyTier(Enum):
    """How much ceremony a command needs before it is sent (§8.2, §8.3)."""

    #: Reads, and writes that cannot lose anything. Sent without asking.
    SAFE = 0

    #: Changes the receiver's configuration or its outputs. §8.3 requires a confirmation naming
    #: what will happen, and §7.2 requires the error queue read afterwards.
    CONFIRM = 1


class ResponseFormat(Enum):
    """What shape of answer to expect, so the caller knows which scalar parser to use."""

    #: A setter. The prompt alone.
    NONE = 0

    #: A signed integer, e.g. ``+3``.
    INTEGER = 1

    #: A real in scientific notation, e.g. ``-5.4E-009``.
    DECIMAL = 2

    #: ``0`` or ``1``.
    BOOLEAN = 3

    #: An enumerated keyword, e.g. ``LOCK``.
    KEYWORD = 4

    #: A comma-separated list whose first field is the value of interest.
    VALUE_LIST = 5

    #: Free text on one line.
    TEXT = 6

    #: Several lines of free text.
    MULTI_LINE = 7

    #: The ``:SYST:STAT?`` screen, which only the status screen parser understands.
    STATUS_SCREEN = 8


class ArgumentKind(Enum):
    """What a command takes after its header, if anything.

    **The header stays the allowlisted thing.** A setter is catalogued by its header alone and the
    argument is supplied separately and validated here, so the point-of-send check remains an exact
    match against the catalog. Composing a string and then asking whether *that* is allowed would
    turn the allowlist into a prefix match, which is a free-text path with extra steps.
    """

    #: Takes nothing. Queries, and setters whose keyword is part of the mnemonic — ``:GPS:POSition
    #: LAST`` and ``:GPS:POSition SURVey`` are separate entries rather than one with a parameter,
    #: because they do different things and §8.3 gives them different confirmations.
    NONE = 0

    #: A whole number, bounded by :attr:`ScpiCommand.minimum` and :attr:`ScpiCommand.maximum`.
    INTEGER = 1

    #: A real, bounded the same way. Sent in the receiver's own notation.
    DECIMAL = 2

    #: One of :attr:`ScpiCommand.keywords`, matched case-insensitively and sent upper-cased.
    KEYWORD = 3

    #: Several whole numbers, comma-joined — the form the 58503A programming guide gives, e.g.
    #: ``:GPS:INIT:DATE 1994,7,4``. Every element goes through the same bounds a single value
    #: would, so the console cannot accept what a page would reject.
    INTEGER_LIST = 4

    #: §10.6's nine-part position: hemisphere, degrees, minutes, seconds for each of latitude and
    #: longitude, then a height. Supplied as a
    #: :class:`~smartclock_device.commands.position_argument.PositionArgument`, which owns both the
    #: ranges and the exact text — see that module for why the format is a looked-up fact rather
    #: than a choice.
    POSITION = 5


@dataclass(frozen=True, slots=True)
class ScpiCommand:
    """One entry in the allowlist."""

    #: The header as sent, e.g. ``:SYNC:TINT?``. Includes any keyword argument, because
    #: ``:GPS:POSition LAST`` and ``:GPS:POSition SURVey`` are distinct commands rather than one
    #: command with a parameter.
    mnemonic: str

    #: What it is for, in the words §10.11's picker shows.
    summary: str

    #: What shape of answer to expect.
    response: ResponseFormat

    #: How much ceremony it needs.
    tier: SafetyTier = SafetyTier.SAFE

    #: The unit the answer is in, where it has one. Shown beside the value, never inferred.
    unit: str | None = None

    #: What it takes after the header.
    argument: ArgumentKind = ArgumentKind.NONE

    #: Bounds for a numeric argument. Inclusive.
    minimum: float | None = None
    maximum: float | None = None

    #: The permitted keywords, upper-cased, for :attr:`ArgumentKind.KEYWORD`.
    keywords: tuple[str, ...] = ()

    #: §8.3's confirmation sentence, verbatim.
    #:
    #: **Carried on the command rather than assembled by the dialog.** §8.3's own amendment note
    #: records why: ``:IGN:NONE`` shared the exclusion sentence for a command that *clears* the
    #: exclusion list, so a user confirming it would reasonably believe they were excluding
    #: satellites. The sentence has to describe *this* operation, and the place to review that is
    #: beside the mnemonic it belongs to.
    confirmation: str | None = None

    #: Whether §9.7.4's extra "I understand" tick gates the confirm button.
    requires_acknowledgement: bool = False

    @property
    def is_query(self) -> bool:
        """Whether this asks for something rather than changing it."""
        return self.mnemonic.rstrip().endswith("?")

    @property
    def needs_confirmation(self) -> bool:
        return self.tier is SafetyTier.CONFIRM

    def _rendered_list(self, argument: object) -> str | None:
        """A comma-joined list, or ``None`` if any element is not one this command accepts.

        **Any element**, not most of them: a partially-valid list sent with the bad entries
        dropped would do something the user did not ask for, quietly, and the thing it did would
        be a subset of a destructive operation.
        """
        if isinstance(argument, str) or not isinstance(argument, Iterable):
            return None

        values: list[int] = []
        for element in argument:
            try:
                value = float(element)
            except (TypeError, ValueError):
                return None
            if value != int(value) or not math.isfinite(value):
                return None
            if self.minimum is not None and value < self.minimum:
                return None
            if self.maximum is not None and value > self.maximum:
                return None
            values.append(int(value))

        if not values:
            return None
        return f"{self.mnemonic} " + ",".join(str(value) for value in values)

    def rendered(self, argument: object = None) -> str | None:
        """The exact text to send, or ``None`` if the argument is not one this command accepts.

        ``None`` rather than an exception: a caller handing over a value out of range is the
        ordinary case of a user typing one, and §11.1's discipline — refuse and say so, never raise
        into a paint event — applies as much on the way out as on the way in.
        """
        if self.argument is ArgumentKind.NONE:
            return self.mnemonic if argument is None else None

        if argument is None:
            return None

        if self.argument is ArgumentKind.INTEGER_LIST:
            return self._rendered_list(argument)

        if self.argument is ArgumentKind.POSITION:
            if not isinstance(argument, PositionArgument):
                return None
            text = argument.rendered()
            return None if text is None else f"{self.mnemonic} {text}"

        if self.argument is ArgumentKind.KEYWORD:
            text = str(argument).strip().upper()
            return f"{self.mnemonic} {text}" if text in self.keywords else None

        try:
            value = float(argument)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        if not math.isfinite(value):
            return None
        if self.minimum is not None and value < self.minimum:
            return None
        if self.maximum is not None and value > self.maximum:
            return None

        if self.argument is ArgumentKind.INTEGER:
            if value != int(value):
                return None
            return f"{self.mnemonic} {int(value):d}"

        # A decimal argument is sent as the receiver spells them: plain, not in exponent notation,
        # which the antenna-delay setter takes in seconds and would otherwise be handed "6e-08".
        return f"{self.mnemonic} {value:.12f}".rstrip("0").rstrip(".")
