"""One catalogued command, and the two enums that classify it (§8.1, §8.2).

The catalog is an **allowlist**. A command that is not an entry here does not exist as far as this
application is concerned — there is no free-text path that could reach one, and §10.11's Advanced
Console is a picker over these entries rather than a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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

    @property
    def is_query(self) -> bool:
        """Whether this asks for something rather than changing it."""
        return self.mnemonic.rstrip().endswith("?")
