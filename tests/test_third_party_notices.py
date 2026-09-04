"""`THIRD-PARTY-NOTICES.md` names everything this project redistributes (#40).

**The way a notices file goes wrong is not being written badly — it is not being updated.** A
dependency added months later ships under terms nobody recorded, and nothing about the build says
so. So the file is checked against `pyproject.toml` rather than against a copy of itself.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTICES = ROOT / "THIRD-PARTY-NOTICES.md"
SPEC = ROOT / "build" / "smartclock-monitor.spec"
CARRIED = ROOT / "licenses"

#: Runtime dependencies that ship a licence inside their own distribution. The bundle collects it
#: with `copy_metadata`, which PyInstaller does **not** do by itself.
COLLECTED = ("qasync", "pyserial-asyncio", "markdown-it-py", "mdurl")

#: Runtime dependencies that ship no licence text anywhere, so this repository carries it.
#: `PySide6` covers Qt and shiboken6, which are licensed together.
VENDORED = {"PySide6": "LGPL-3.0.txt", "pyserial": "pyserial-LICENSE.txt"}

#: Shipped as files in the source tree rather than resolved by pip, and the reason this file
#: matters before anything is packaged: the OFL requires its text to travel with the font.
FONTS = ("Noto Sans", "Cascadia Mono")


def _runtime_dependencies() -> list[str]:
    """The distribution names `pyproject.toml` declares, without their version specifiers."""
    with (ROOT / "pyproject.toml").open("rb") as handle:
        project = tomllib.load(handle)["project"]

    names = []
    for requirement in project["dependencies"]:
        name = re.split(r"[<>=!~\[; ]", requirement, maxsplit=1)[0].strip()
        if name:
            names.append(name)
    return names


def test_there_are_dependencies_to_check() -> None:
    """Guard the guard: a parse returning nothing would make the assertion below vacuous."""
    found = _runtime_dependencies()

    assert len(found) >= 5, f"parsed {found} from pyproject's dependencies"
    assert "PySide6" in found


def test_every_runtime_dependency_is_named_in_the_notices() -> None:
    """Runtime only. Build and test tools — pytest, mypy, ruff, numpy, PyInstaller — ship nothing,
    and listing them would make the file describe the development environment rather than the
    thing that is handed to somebody else."""
    text = NOTICES.read_text(encoding="utf-8").lower()
    missing = [name for name in _runtime_dependencies() if name.lower() not in text]

    assert not missing, (
        "These are redistributed and are not named in THIRD-PARTY-NOTICES.md:\n  "
        + "\n  ".join(missing)
        + "\n\nAdd a row with its licence and which channels carry it."
    )


def test_the_bundled_fonts_are_named_with_their_licence() -> None:
    """The fonts ship in every channel, including a plain checkout, so their obligation is live
    now rather than at the first binary."""
    text = NOTICES.read_text(encoding="utf-8")

    for font in FONTS:
        assert font in text, f"{font} is shipped as a file and is not named"
    assert "Open Font License" in text, "the licence the fonts are under is not named"


def test_the_licence_files_are_beside_the_fonts_they_cover() -> None:
    """The OFL asks for the text to travel with the font, and naming it in a document is not the
    same as shipping it. These are the files the wheel and the bundle carry."""
    fonts = ROOT / "src" / "smartclock_monitor" / "themes" / "fonts"

    faces = sorted(path.name for path in fonts.glob("*.ttf"))
    licences = sorted(path.name for path in fonts.glob("*LICENSE*"))

    assert faces, "no typefaces found — has the directory moved?"
    assert len(licences) >= 2, f"only {licences} beside {faces}"


# ---- The texts themselves, not just their names --------------------------------------------------
#
# The first version of this module asserted that every dependency was *named* in the notices, and
# that passed while the bundle carried the code of four of them and the terms of none. Naming a
# licence is not shipping it. These check that a text is actually reachable.


def test_every_carried_licence_text_is_present_and_looks_like_one() -> None:
    """Qt, PySide6 and pyserial ship no licence file, so this repository carries theirs."""
    for dependency, filename in VENDORED.items():
        path = CARRIED / filename
        assert path.is_file(), f"{dependency} has no licence text at {path}"
        assert len(path.read_text(encoding="utf-8")) > 1000, f"{path} is too short to be a licence"

    # LGPL-3.0 is not complete on its own: it incorporates GPL-3.0 by reference in its first
    # paragraph, so carrying one without the other carries an incomplete grant.
    # Whitespace-normalised: the licence is hard-wrapped at 70 columns and splits the phrase
    # across a newline, so a literal search for it fails on a file that plainly contains it.
    lgpl = " ".join((CARRIED / "LGPL-3.0.txt").read_text(encoding="utf-8").split())
    assert "version 3 of the GNU General Public License" in lgpl
    assert (CARRIED / "GPL-3.0.txt").is_file(), "LGPL-3.0 references GPL-3.0 and it is not here"


def test_the_bundle_collects_the_licences_its_dependencies_do_ship() -> None:
    """**PyInstaller does not collect a dependency's `.dist-info` unless asked.**

    That is what `copy_metadata` is for, and the spec asked only for this project's own — so the
    bundle carried four dependencies' code and none of their terms, while this very file said it
    picked them up. Asserted against the spec because building a bundle needs a toolchain kept out
    of the dev extra, and the defect is the missing declaration.
    """
    spec = SPEC.read_text(encoding="utf-8")

    for dependency in COLLECTED:
        assert f'copy_metadata("{dependency}")' in spec, (
            f"the bundle would carry {dependency} without the licence it ships"
        )
    assert '(str(ROOT / "licenses"), "licenses")' in spec, (
        "the vendored licence texts do not reach the bundle"
    )
    assert '(str(ROOT / "THIRD-PARTY-NOTICES.md"), ".")' in spec


def test_the_notices_say_carried_software_keeps_its_own_terms() -> None:
    """The point a notices file exists to make, and the one most easily left implicit: being
    carried inside this project's wheel or bundle changes nothing about a component's licence."""
    text = NOTICES.read_text(encoding="utf-8")

    assert "terms of its original provider" in text
    assert "MIT licence in `LICENSE` covers the code written for this project" in text
