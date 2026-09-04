"""#33's versioning: the number is derived from git, and stays that way.

The version sat at ``0.0.1`` through every merge the port had, because a literal only changes when
somebody remembers and the thing it describes changes on every commit. It is now a function of the
repository state — and the two ways that quietly stops being true are what this module watches.
"""

from __future__ import annotations

import importlib.util
import re
import tomllib
from importlib import metadata
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _version_module() -> ModuleType:
    """Load `hatch_version.py` by path — the project root is not on the test path (src layout),
    and the build backend loads it by path too."""
    spec = importlib.util.spec_from_file_location("hatch_version", ROOT / "hatch_version.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _pyproject() -> dict[str, object]:
    with (ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)


def test_the_version_is_derived_rather_than_written_down() -> None:
    """No literal to bump, so no literal to forget.

    §6.3 forbids hard-coding the application's *name* because "a rename that has to be made in nine
    places gets made in eight". A version is that argument with a number and a shorter half-life:
    it changes every release, and a stale copy still looks authoritative.
    """
    project = _pyproject()["project"]
    assert isinstance(project, dict)

    assert "version" in project.get("dynamic", []), (
        "pyproject declares a literal version again — it will go stale the first time it is not "
        "bumped, which is the defect #33 removed"
    )
    assert "version" not in project, f"a literal version is back: {project.get('version')!r}"

    hatch = _pyproject()["tool"]
    assert isinstance(hatch, dict)
    version = hatch["hatch"]["version"]
    assert version["source"] == "code", "nothing derives the version any more"
    assert version["path"] == "hatch_version.py"


def test_ci_checks_out_enough_history_to_derive_a_version() -> None:
    """**The failure this exists for is silent.** Actions checks out a shallow clone with no tags,
    and `hatch-vcs` answers `0.0.0` rather than failing — so every artefact CI produced would carry
    the same wrong number and nothing would say so. A note in the workflow would have been read
    once; this is read on every run.
    """
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text()

    # Read as text rather than parsed: a YAML parser would be one more dependency for one check,
    # and what matters is a property of each checkout step, which its own block carries.
    steps = re.split(r"^\s*- (?=uses:|name:)", text, flags=re.MULTILINE)
    checkouts = [step for step in steps if step.startswith("uses: actions/checkout")]

    assert checkouts, "no checkout steps found — has the workflow moved?"
    for step in checkouts:
        assert "fetch-depth: 0" in step, (
            "a CI checkout is shallow, so hatch-vcs would derive 0.0.0 for it and say nothing:\n"
            f"{step.strip()[:200]}"
        )


def test_the_version_is_four_numeric_parts() -> None:
    """#36: `A.B.C.D`, matching WinZ3805A's manifest, with `D` counting check-ins since the tag.

    #33 derived the version but produced a PEP 440 developmental release with the commit in a
    local segment — `1.0.0.dev99+g482bde009`. Correct, and not the shape asked for. This asserts
    the shape rather than a number, because the number is derived and pinning one here would put
    the literal back in a test instead of in `pyproject.toml`.
    """
    version = metadata.version("smartclock-monitor")

    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", version), (
        f"{version!r} is not A.B.C.D — a scheme change has reverted to a default"
    )
    assert "dev" not in version, "a developmental release is not a four-part version"
    assert "+" not in version, "the local segment carries the commit hash #36 asked to remove"


def test_the_fourth_part_counts_check_ins_since_the_release() -> None:
    """`D` is the distance from the tag, so it moves on every commit and resets on a release.

    Asserted against git rather than against a number: the point is that the two agree, and a test
    carrying the expected distance would need editing on every commit — which is the class of
    chore this whole scheme exists to remove.
    """
    hatch_version = _version_module()

    found = hatch_version._release_and_distance()
    if found is None:  # a checkout with no tags fetched; the gate below covers CI
        return

    release, distance = found

    # **Derived here, not read from the installed metadata.** An editable install writes its
    # version once and does not re-derive it, so comparing it against today's commit count fails
    # on the first commit after an install — which is every working tree, most of the time. The
    # first version of this test did exactly that and would have cried wolf locally while passing
    # in CI, which installs fresh on every run. What is worth asserting is that the derivation
    # agrees with git, and that is answerable without an install at all.
    assert hatch_version.__version__.endswith(f".{distance}"), (
        f"{hatch_version.__version__} does not end in the {distance} commits git reports since "
        f"v{release}"
    )
    assert hatch_version._four_parts(release, distance).count(".") == 3


def test_a_tag_that_is_not_three_numbers_stops_the_build() -> None:
    """Tags are `vA.B.C` and nothing else; `D` is derived and is never tagged.

    **Rejected rather than coerced**, because the coercion produced plausible wrong numbers. An
    earlier version kept whichever components were digits, which turned `v1.0.0-rc1` into `1.0.0`
    — colliding with the release it precedes — and `v1.2.3beta` into `1.2.0`, which sorts *below*
    the `1.2.3` it was a beta of. Both looked like versions. A failed build at the moment the tag
    is cut is a fixable mistake; a version that is quietly wrong lasts as long as the tag.
    """
    hatch_version = _version_module()

    assert hatch_version._four_parts("1.0.0", 7) == "1.0.0.7"

    for bad in ("1.0", "1", "1.0.0-rc1", "1.2.3beta", "1.0.0.9", "1.0.x"):
        with pytest.raises(hatch_version.MalformedReleaseTagError, match=re.escape(bad)):
            hatch_version._four_parts(bad, 3)


def test_the_installed_version_is_readable_and_not_the_old_literal() -> None:
    """What the status bar and §9.7.5's guide footer actually read.

    Not asserted to be any particular number — it is derived, so pinning one here would put the
    literal back in a test instead of in `pyproject.toml`.
    """
    version = metadata.version("smartclock-monitor")

    assert version, "the package reports no version at all"
    assert version != "0.0.1", (
        "the installed version is the literal #33 removed — this environment predates the change "
        "and needs 'pip install -e .' again"
    )
