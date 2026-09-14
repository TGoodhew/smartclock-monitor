"""Find a GitHub closing keyword standing somewhere its author probably did not mean it to.

**GitHub closes an issue on merge wherever a closing keyword stands immediately before an issue
reference. It reads those two words and nothing else** — not the sentence around them, not the
heading above them, and not the negation inside them. So all three of these close something:

    Closes #42
    this does not close #42
    a follow-up, since #41 fixes #42 only for the SmartClock

and two of the three mean the opposite of what happens.

This is #131's half of the problem that can be checked from the tree. A keyword is taken as
**deliberate** when it opens a line — the trailer form, `Closes #42` — and as an accident anywhere
else, because that is the shape a keyword takes when it has been swept up by prose. The rule is
crude on purpose: a checker that tried to read the sentence would be wrong in both directions, and
the cost of the crude one is a line break.

The other half is the pull request body, which is not in the tree at all. `ci.yml` pipes it through
this same module on `pull_request`, so the two halves are one rule with one implementation.

    python tools/closing_keywords.py --text "$BODY"
    git log --format=%B origin/main..HEAD | python tools/closing_keywords.py

Exits 1 when it finds one, and prints the line it found.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Final

#: GitHub's closing keywords, all of them, as its documentation lists them.
KEYWORDS: Final[tuple[str, ...]] = (
    "close",
    "closes",
    "closed",
    "fix",
    "fixes",
    "fixed",
    "resolve",
    "resolves",
    "resolved",
)

#: A keyword, then an issue reference. ``#42``, ``org/repo#42`` and the full URL all count to
#: GitHub, so all three count here.
_REFERENCE: Final = re.compile(
    r"(?i)\b(?P<keyword>" + "|".join(KEYWORDS) + r")\b[\s:]+"
    r"(?P<reference>(?:[\w.-]+/[\w.-]+)?#\d+|https://github\.com/[\w.-]+/[\w.-]+/issues/\d+)"
)


def misuses(text: str) -> list[str]:
    """Every line where a closing keyword closes something the line does not look like it meant to.

    A keyword that **opens its line** is the trailer form and is left alone — leading whitespace
    included, because a message quoted into a workflow log keeps its indentation and the intent is
    unchanged. Everything else is reported with its line, so the author can see what they wrote.
    """
    found: list[str] = []
    for line in text.splitlines():
        for match in _REFERENCE.finditer(line):
            if match.start() == len(line) - len(line.lstrip()):
                continue
            found.append(
                f"{match.group('keyword')} {match.group('reference')} — in: {line.strip()}"
            )
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--text", help="the text to check; read from standard input if absent")
    arguments = parser.parse_args(argv)

    text = arguments.text if arguments.text is not None else sys.stdin.read()
    found = misuses(text)
    if not found:
        return 0

    print("A closing keyword stands mid-line, where GitHub will act on it anyway:")
    for line in found:
        print(f"  {line}")
    print(
        "\nPut it at the start of its own line if you mean it, or reword it if you do not —\n"
        "'see #42' and 'part of #42' close nothing."
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
