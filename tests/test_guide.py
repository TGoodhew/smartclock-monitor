"""The guide, checked against the application it describes.

`docs/how-to-use.md` is the user's guide and also the application's `F1` help, so it is the one
document a user is *inside the application* when they read. It was inherited from WinZ3805A and
described that application; it now describes this one, and what keeps it describing this one is
here rather than review.

What is gated is what a machine can settle, which is narrower than "the guide is true": that every
picture it names exists, that no picture exists which it has stopped naming, that every picture
carries alt text — the pictures do not resolve in the `F1` window, so the alt text *is* the guide
there — and that every page the details window has is written about. What each page's prose says is
a matter for a person.

**The alt-text rule is not a formality here.** `QTextBrowser.setMarkdown` renders the guide with no
search path for relative images, so in the help window every one of them is its alt text and
nothing else. That is why the alt text in this guide describes layouts rather than saying "the
Overview page".
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT: Final = Path(__file__).resolve().parent.parent
GUIDE: Final = ROOT / "docs" / "how-to-use.md"
IMAGES: Final = ROOT / "docs" / "images" / "how-to-use"

#: ``![alt](images/how-to-use/name.png)``, which is the only form the guide uses.
_IMAGE = re.compile(r"!\[(?P<alt>[^\]]*)\]\((?P<path>images/how-to-use/[^)]+)\)")

#: Long enough to be a description rather than a label. The shortest real one in the guide is the
#: toolbar's, at a little over a hundred characters.
_ALT_FLOOR: Final = 60


def guide() -> str:
    return GUIDE.read_text(encoding="utf-8")


def references() -> list[tuple[str, str]]:
    """Every ``(alt, path)`` the guide carries, in the order it carries them."""
    return [(match["alt"], match["path"]) for match in _IMAGE.finditer(guide())]


def test_the_guide_names_some_pictures() -> None:
    """The check the others rest on.

    Without it, a guide that had lost every image would pass the two set comparisons below by
    matching an empty directory, and the alt-text rule by having nothing to check. A gate that
    passes when its subject has vanished is the failure mode CLAUDE.md calls out.
    """
    assert len(references()) >= 15


def test_every_picture_the_guide_names_exists() -> None:
    missing = sorted(path for _alt, path in references() if not (ROOT / "docs" / path).is_file())
    assert not missing, f"The guide points at pictures that are not there: {missing}"


def test_every_picture_in_the_directory_is_used() -> None:
    """The other direction, which is the one that rots quietly.

    A picture the guide has stopped referring to is dead weight that still looks maintained, and
    `tools/capture_guide_images.py` will keep rendering it for ever unless something notices.
    """
    named = {Path(path).name for _alt, path in references()}
    present = {path.name for path in IMAGES.glob("*.png")}
    assert present - named == set(), f"Pictures nothing refers to: {sorted(present - named)}"


def test_every_picture_carries_alt_text_that_describes_it() -> None:
    """In the `F1` window the alt text is all there is — see the module docstring."""
    thin = sorted(path for alt, path in references() if len(alt) < _ALT_FLOOR)
    assert not thin, f"Alt text too thin to stand in for the picture: {thin}"


def test_every_details_page_is_written_about() -> None:
    """A page added to the window and not to the guide is a page nobody is told about.

    Titles rather than headings: the guide gives Settings a heading of "Settings — `Ctrl+9`", and
    pinning the exact heading text would make this a formatting rule rather than a coverage one.
    """
    pytest.importorskip("PySide6.QtWidgets", reason="Qt is not available on this machine")

    from PySide6.QtWidgets import QApplication

    from smartclock_monitor.services.preferences import Preferences
    from smartclock_monitor.themes.tokens import Theme
    from smartclock_monitor.views.details_window import DetailsWindow

    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    assert application is not None

    window = DetailsWindow(Theme.LIGHT)
    # Both opt-in pages on: a page that is off by default is still a page the guide documents.
    window.apply_preferences(Preferences(advanced_console=True, undocumented_queries=True))

    text = guide()
    for page in window.pages:
        # Anchored to the start of a line and closed with a word boundary. A plain substring test
        # is a prefix test: it accepts "#### Holdovers" as a section about the Holdover page, which
        # is exactly the rename this exists to catch.
        heading = re.compile(rf"^#### {re.escape(page.title)}\b", re.MULTILINE)
        assert heading.search(text), f"No section for the {page.title} page."
    window.close()


def test_every_page_has_a_picture_named_after_it() -> None:
    """The naming `tools/capture_guide_images.py` writes, checked from the other end.

    This is what makes a renamed page fail loudly rather than leaving the guide showing the old
    page under the new name.
    """
    pytest.importorskip("PySide6.QtWidgets", reason="Qt is not available on this machine")

    from PySide6.QtWidgets import QApplication

    from smartclock_monitor.services.preferences import Preferences
    from smartclock_monitor.themes.tokens import Theme
    from smartclock_monitor.views.details_window import DetailsWindow

    existing = QApplication.instance()
    application = existing if isinstance(existing, QApplication) else QApplication([])
    assert application is not None

    import sys

    sys.path.insert(0, str(ROOT / "tools"))
    from capture_guide_images import slug

    window = DetailsWindow(Theme.LIGHT)
    window.apply_preferences(Preferences(advanced_console=True, undocumented_queries=True))

    for page in window.pages:
        expected = IMAGES / f"page-{slug(page.title)}.png"
        assert expected.is_file(), f"No picture for the {page.title} page at {expected.name}."
    window.close()
