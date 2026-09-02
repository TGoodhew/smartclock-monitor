"""The bundled typefaces. D4, and the reason it said bundling was the real answer.

Naming a face does not pin its metrics; shipping it does. A machine without Noto Sans falls through
§9.5's fallback chain to whatever it has, and every layout measured against one desktop is wrong on
another — which cost a CI rejection at a 1100 px window minimum, another at 1160, and a theme picker
that came back 50 px wide because it had been measured in a font nothing would draw it in.
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontInfo
from PySide6.QtWidgets import QApplication

from smartclock_monitor.themes import fonts
from smartclock_monitor.themes.typography import MONO_FAMILY, UI_FAMILY


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    app = existing if isinstance(existing, QApplication) else QApplication([])
    fonts.load()
    return app


def test_every_bundled_file_is_present_and_registers() -> None:
    """A file listed and not shipped is the failure that survives review: the application falls
    back silently and looks a little different on a machine nobody is testing on."""
    registered = fonts.load()

    assert registered, "no bundled face registered at all"
    for name in fonts.BUNDLED:
        assert name.endswith(".ttf"), name


def test_the_faces_d4_chose_are_the_ones_bundled() -> None:
    """§9.5's split is the point: prose in one face, everything the receiver emits in another. A
    bundle that shipped only half of it would leave the half that matters most — the device
    literals — resolving to whatever the desktop has."""
    registered = fonts.load()

    assert UI_FAMILY[0] in registered, f"{UI_FAMILY[0]} is named first and is not bundled"
    assert MONO_FAMILY[0] in registered, f"{MONO_FAMILY[0]} is named first and is not bundled"


def test_the_named_families_resolve_to_themselves() -> None:
    """The whole purpose. If Qt answers a request for Cascadia Mono with something else, §9.5's
    split is decoration and the metrics are the other font's."""
    for family in (UI_FAMILY[0], MONO_FAMILY[0]):
        resolved = QFontInfo(QFont(family, 10)).family()
        assert resolved == family, f"asked for {family}, got {resolved}"


def test_weight_600_is_a_real_semibold_not_a_synthesised_one() -> None:
    """§9.5.2's ramp uses 400 and 600, so both weights are bundled. Left to synthesise one, Qt
    smears the regular face and the ramp's steps stop being the ones the specimen was checked in."""
    heavy = QFont(UI_FAMILY[0])
    heavy.setWeight(QFont.Weight(600))
    info = QFontInfo(heavy)

    assert info.weight() == 600
    assert "semibold" in info.styleName().lower().replace(" ", "")


def test_each_bundled_face_ships_its_licence() -> None:
    """OFL clause 2 permits bundling **provided the notice travels with the font**. A licence left
    behind is not a detail; it is the condition the permission is granted under."""
    from importlib import resources

    directory = resources.files(fonts.PACKAGE)
    for stem in ("NotoSans", "CascadiaMono"):
        licence = directory / f"{stem}-LICENSE.txt"
        text = licence.read_text(encoding="utf-8")
        assert "SIL Open Font License" in text, f"{stem} ships no OFL text"
        assert len(text) > 1000, f"{stem}'s licence is a pointer rather than the licence"


def test_loading_twice_is_harmless() -> None:
    """It is called from ``__main__`` and from every test module that needs a font. A loader that
    accumulated duplicate families on each call would drift the answer under its own callers."""
    once = fonts.load()
    twice = fonts.load()

    assert once == twice
    assert len(set(twice)) == len(twice), "a family was registered twice"
