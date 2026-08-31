"""The §8.4 exclusion list, and the only place in this repository where it exists.

§8.4 requires that these commands are absent from the application in every user-visible sense: not
in the catalog, not in a picker, an autocomplete, help text, or any log a user can read. **They are
not catalog entries carrying a flag — they do not exist as data.** This module holds patterns,
never commands, and has exactly one route out: :func:`is_blocked`, which answers one question about
one candidate.

**The collection is deliberately private.** §8.4 once named it ``CommandCatalog.BlockedPatterns``
while requiring in the same sentence that it not be enumerable; a public member of that name is
enumerable by definition, and §8.4's correction let the requirement win over the name. So the
patterns are module-private, and what leaves here is a verdict. Nothing can bind to them, iterate
them, or render them into a list.

``tests/test_no_blocked_commands.py`` enforces that this file is the sole occurrence. It reads its
tokens out of this module and scans the tree, which is what keeps this the only place they appear —
and it is why that gate is ported in the same change as this file rather than after it.

The receiver accepts commands that can render it unusable. A receiver bricked by one of these is
bricked either way, which is why ``docs/provenance.md`` requires this list and WinZ3805A's to be
diffed against each other whenever either changes.

Generated from the C# original rather than retyped, so the two cannot drift through a typo.
"""

from __future__ import annotations

import re
from typing import Final

#: Every pattern is tested against a command's header — the text before any parameter — with the
#: leading colon optional and case ignored, because a user typing into a console will not match the
#: manual's capitalisation and must be stopped anyway.
#:
#: Each blocks its query form as well as its set form, with one deliberate exception noted below: a
#: query that cannot change anything is still a node the user should never see named in an error
#: message.
#:
#: The last pattern is the categorical case — any undocumented parser node **in set form**. Its
#: leading negative lookahead is what makes it set-only: §8.5 enables the query form of a small
#: subset as an opt-in read-only card, so a pattern that ignored the question mark would block a
#: feature the specification asks for two sections later. A set form has no way to be safe: these
#: nodes are undocumented, so what they write is unknown, and §8.4 gives them no override.
_PATTERNS: Final = (
    # firmware transfer
    re.compile(
        "^:?DIAG(NOSTIC)?:DOWN(LOAD)?\\??$",
        re.IGNORECASE,
    ),
    # flash erase
    re.compile(
        "^:?DIAG(NOSTIC)?:ERAS(E)?\\??$",
        re.IGNORECASE,
    ),
    # language node
    re.compile(
        "^:?SYST(EM)?:LANG(UAGE)?\\??$",
        re.IGNORECASE,
    ),
    # undocumented parser node, set form only
    re.compile(
        "^(?![^\\s]*\\?):?(?:[A-Z0-9]+:)*(?:TCO(?:EFFICIENT)?|PSTARTUP|DOUT(?:PUT)?|REST(?:RICTED)?|SOUR(?:CE)?|IREF(?:ERENCE)?|EGRESPONSE|OUTP(?:UT)?:PINS:PIN[1-8])$",
        re.IGNORECASE,
    ),
)


def is_blocked(candidate: str | None) -> bool:
    """Whether this command is excluded by §8.4.

    :param candidate: A command header, with any parameter already removed. ``None`` and blank are
        not blocked — they are not commands, and reporting them as excluded would be a false
        positive on the one path that must never cry wolf.

    This is the only route out of this module. It answers one question about one candidate and
    cannot be enumerated, iterated or bound to. There is no free-text command path in this
    application and there must never be one — §10.11's Advanced Console is a picker over the
    allowlist — so this exists for the catalog's own gate and for any future path that accepts
    typed text.
    """
    if not candidate:
        return False

    # The header only: anything from the first space onwards is a parameter, and a pattern anchored
    # on the header would otherwise be defeated by appending an argument.
    header = candidate.strip().split(" ", 1)[0]
    if not header:
        return False

    return any(pattern.search(header) for pattern in _PATTERNS)
