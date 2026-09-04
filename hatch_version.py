"""The version, as ``A.B.C.D`` with ``D`` counting check-ins since the release tag.

WinZ3805A ships four-part versions — its manifest carries ``Version="1.0.6.0"`` — and this port
matches that shape (#36). ``A.B.C`` is the tag; ``D`` is how many commits have landed since it, so
it increments on every check-in and resets when a new release is tagged, which is what the fourth
component of a four-part version conventionally means.

**Nothing here is written down and nothing is a hash.** #33 replaced a literal that had not moved
in ninety-nine commits; what it produced was a PEP 440 developmental release with the commit id in
a local segment (``1.0.0.dev99+g482bde009``), which is precise and is not the shape asked for.

**Read at build time by hatchling's ``code`` version source.** A wheel therefore bakes in the
number it was built at, which is what makes ``importlib.metadata`` — and so the status bar and
§9.7.5's guide footer — able to report it from an installation that has no git at all.

The counting is only well defined on linear history, which ``CLAUDE.md``'s rebase-merge rule keeps
true of ``main``.

**A source distribution keeps the number it was cut with.** This module answers :data:`FALLBACK`
where there is no git to ask — an unpacked sdist has none — but hatchling reads the version from
the sdist's ``PKG-INFO`` rather than re-deriving it, so ``sdist -> wheel`` carries the real version
through. That is what lets a distribution build the package without a clone, which #27 will need.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Final

#: What to answer where the question cannot be asked — an unpacked sdist, a build from a tarball,
#: or a checkout whose tags were never fetched.
#:
#: **A legible symptom rather than a crash.** A build backend that raised here would make a source
#: install impossible for want of a version number, and `tests/test_versioning.py` fails on the
#: cause CI could actually have (a shallow checkout) rather than on this consequence.
FALLBACK: Final = "0.0.0.0"

#: Only tags that look like releases. A stray annotated tag would otherwise become the base of
#: every version after it.
_MATCH: Final = "v[0-9]*"


def _git(*arguments: str) -> str | None:
    """Run one git command in the project directory, or return ``None`` if it cannot be run."""
    try:
        finished = subprocess.run(
            ["git", *arguments],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    return finished.stdout.strip() if finished.returncode == 0 else None


def _release_and_distance() -> tuple[str, int] | None:
    """The latest release tag and how many commits are past it."""
    # Two commands rather than parsing one. `git describe --long` gives `v1.0.0-1-g1e91d4d`, and
    # picking the distance out of it means splitting on separators a tag is allowed to contain —
    # while `--abbrev=0`, which would drop the hash, is rejected outright alongside `--long`.
    # Asking for the tag and then for the count is unambiguous whatever the tag is called.
    tag = _git("describe", "--tags", "--abbrev=0", "--match", _MATCH)
    if not tag:
        return None

    distance = _git("rev-list", "--count", f"{tag}..HEAD")
    if distance is None or not distance.isdigit():
        return None

    return tag.lstrip("v"), int(distance)


def _four_parts(release: str, distance: int) -> str:
    """``A.B.C`` from the tag, padded if it is shorter, with ``D`` appended."""
    numbers = [part for part in release.split(".") if part.isdigit()][:3]
    while len(numbers) < 3:
        numbers.append("0")
    return ".".join([*numbers, str(distance)])


def _derive() -> str:
    found = _release_and_distance()
    return FALLBACK if found is None else _four_parts(*found)


__version__ = _derive()
