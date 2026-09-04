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
