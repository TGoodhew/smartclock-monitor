"""Turning an enum member into words a person reads.

``member.name.replace("_", " ").title()`` was written at fourteen call sites and it is wrong in a
particular way: it lower-cases acronyms. The Position page showed the height datum as **"Msl"**,
which is not a word, is not the abbreviation, and is not something a user can look up. ``GPS``
became ``Gps`` and ``SYNCHRONIZED_TO_UTC`` became ``Synchronized To Utc``.

**This module has no Qt in it and no page state**, so the mapping is testable directly rather than
by rendering a window and reading pixels.

Where a member needs real prose rather than a transformation of its own name — ``VALID_REDUCED``
reads *"Valid, reduced accuracy"* — the page carries a table instead. This is for the many cases
where the name **is** the wording, once the acronyms survive it.
"""

from __future__ import annotations

from enum import Enum
from typing import Final

#: Words that are not words. Kept upper-case wherever they appear.
#:
#: Every one is either the receiver's own vocabulary or the specification's: §7.4's GPS, §10.14's
#: UTC, §10.6's MSL datum, §10.5's PRN, and the oscillator figures §10.7 names.
ACRONYMS: Final[frozenset[str]] = frozenset(
    {"GPS", "UTC", "MSL", "PRN", "EFC", "TFOM", "FFOM", "PPS", "TI", "NMEA", "SCPI", "OCXO"}
)

#: Words that stay lower-case inside a phrase, so a label reads as a phrase rather than a headline.
MINOR_WORDS: Final[frozenset[str]] = frozenset(
    {"a", "and", "in", "not", "of", "on", "or", "the", "to"}
)


def humanise(member: Enum | None, absent: str = "—") -> str:
    """One enum member as display text, with acronyms intact.

    ``None`` renders as the em dash §11.1 requires — the same character a missing value takes
    everywhere else, so a state nobody read and a field nobody read look alike, which they are.
    """
    if member is None:
        return absent
    return humanise_name(member.name)


def humanise_name(name: str) -> str:
    """The same transformation, for a bare identifier."""
    words = name.split("_")
    rendered: list[str] = []
    for index, word in enumerate(words):
        if word.upper() in ACRONYMS:
            rendered.append(word.upper())
        elif index > 0 and word.lower() in MINOR_WORDS:
            rendered.append(word.lower())
        else:
            rendered.append(word.capitalize())
    return " ".join(rendered)
