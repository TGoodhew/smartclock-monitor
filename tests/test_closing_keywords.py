"""A closing keyword closes an issue, and GitHub does not read the sentence around it (#131).

The last unported row of [`docs/ci-gate-map.md`](../docs/ci-gate-map.md), and the only one in that
table about **this repository's habits** rather than about WinUI. Most of the eighteen are
dispatcher handlers and resource dictionaries; this one is about writing, and this repository writes
a great deal — every commit message in it is long-form prose, and every pull request body carries
issue references in running text.

The exposure is not hypothetical. `Closes #111 and #114` merged here works by luck rather than by
rule: GitHub reads `Closes #111`, then sees `#114` as an ordinary reference, and closed both only
because someone noticed. A sentence like *"this does not close #97"* closes #97.

**Two halves, one implementation.** The commit messages are in the tree and are checked here; the
pull request body is not in the tree at all and is checked by a `ci.yml` job that pipes it through
the same module. Splitting the rule across two implementations is how the two come to disagree.

**The unit tests are the coverage and the range check is the gate.** The range — what this branch
adds to `main` — is empty on `main` itself and on a fresh clone, so a file that only checked the
range would enforce nothing most of the time while reading as though it did.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from closing_keywords import KEYWORDS, misuses  # noqa: E402

# ---- What the rule is ----------------------------------------------------------------------------


def test_every_keyword_github_documents_is_covered() -> None:
    """All nine, in all three tenses. A checker that knew six of them would be a checker people
    trusted for the other three."""
    assert set(KEYWORDS) == {
        "close",
        "closes",
        "closed",
        "fix",
        "fixes",
        "fixed",
        "resolve",
        "resolves",
        "resolved",
    }


@pytest.mark.parametrize(
    "text",
    [
        "Closes #42",
        "Fixes #42",
        "   Resolved #42",
        "Closes org/repo#42",
        "Closes https://github.com/TGoodhew/smartclock-monitor/issues/42",
    ],
    ids=["closes", "fixes", "indented", "cross-repo", "url"],
)
def test_a_keyword_that_opens_its_line_is_left_alone(text: str) -> None:
    """The trailer form, which is how this repository writes one when it means it. Indentation is
    allowed because a message quoted into a workflow log keeps its own, and the intent is
    unchanged."""
    assert misuses(text) == []


@pytest.mark.parametrize(
    "text",
    [
        "this does not close #42",
        "a follow-up, since #41 fixes #42 only for the SmartClock",
        "The measurement in #40 resolves #42 for the SmartClock and not for a talker",
        "Reverted because it fixed #42 the wrong way",
    ],
    ids=["negated", "mid-sentence", "qualified", "past-tense"],
)
def test_a_keyword_mid_line_is_reported(text: str) -> None:
    """Every one of these closes an issue on merge, and three of the four mean the opposite."""
    found = misuses(text)

    assert len(found) == 1
    assert "#42" in found[0]
    assert text.strip() in found[0]


@pytest.mark.parametrize(
    "text",
    [
        "see #42 for the reasoning",
        "Refs #42",
        "part of #42",
        "#42 is the tracking issue",
        "closes the connection when the port goes away",
        "fixes are welcome",
    ],
    ids=["see", "refs", "part-of", "bare", "no-reference", "no-reference-plural"],
)
def test_what_does_not_close_anything_is_not_reported(text: str) -> None:
    """The half that decides whether this gate is usable. A keyword with no issue reference after
    it closes nothing, and `see #42` is how a message refers to an issue it is not finishing — both
    are ordinary and neither may cry wolf."""
    assert misuses(text) == []


def test_a_real_commit_message_from_this_repository_passes() -> None:
    """Written the way the messages here are actually written: a trailer at the end, and issue
    numbers mentioned in the prose above it."""
    message = """Catalogue the thirty queries §8.2 lists and this port did not have

#118's first batch. The gate that should have caught the gap now exists.
Two questions fell out: #119 and #120. Neither is settled here.

Refs #118
"""
    assert misuses(message) == []


# ---- What is actually in the tree ----------------------------------------------------------------


def branch_messages() -> str | None:
    """Every commit message this branch adds to `main`, or ``None`` when that cannot be worked out.

    ``None`` rather than an empty string, so the test below can say *why* it checked nothing — on
    `main` there is nothing to check, and in a shallow clone there is no `origin/main` to compare
    against. Both are ordinary, and neither is a pass worth reporting as one.
    """
    try:
        base = subprocess.run(
            ["git", "rev-parse", "--verify", "origin/main"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
        if base.returncode != 0:
            return None
        log = subprocess.run(
            ["git", "log", "--format=%B", "origin/main..HEAD"],
            capture_output=True,
            text=True,
            cwd=ROOT,
            check=False,
        )
    except OSError:  # pragma: no cover - git is present wherever this runs
        return None
    return log.stdout if log.returncode == 0 else None


def test_no_commit_on_this_branch_closes_something_by_accident() -> None:
    messages = branch_messages()
    if messages is None:
        pytest.skip("no origin/main to compare against")
    if not messages.strip():
        pytest.skip("this branch adds no commits to main")

    found = misuses(messages)

    assert not found, "A commit message closes an issue mid-sentence:\n  " + "\n  ".join(found)
