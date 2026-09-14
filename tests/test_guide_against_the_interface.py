"""The guide and the interface must agree about what is on each page (#99, part 4).

`docs/how-to-use.md` is the `F1` help. **A wrong sentence there costs more than anywhere else in
this repository**: a user who reads it is, by definition, someone who could not work the interface
out by looking, and the guide is what they are trusting instead of the window.

Every other check in this suite asks whether the application does what the code says. This asks
whether it does what the *documentation* says, in both directions:

- **Forward** — every card and control the guide names for a page exists on that page. Catches a
  rename that the guide did not follow.
- **Reverse** — every card on a page is named in that page's section of the guide. Catches a card
  added and never written up, which is the commoner failure because nothing else notices it.

**It found one on its first run.** §10.9's *GPS receiver* card — what module is inside the
instrument — had been built and never documented. Nobody would have known until a reader went
looking for it in the help and came back thinking the application had no such thing.

The extraction is **structural, not a search for bold text**. The guide names a card or control as
the leading bold span of a bullet, or as the first cell of a settings table row; bold elsewhere is
emphasis. A rule that swept up every bold span would report ``**not**`` as a missing control and
teach everyone to scroll past it.

**Every page is covered, as of 14 Sep 2026 (#128).** Two sections named their controls in prose —
*"use **Refresh all**"* — which this cannot read without sweeping up every emphasised phrase on the
page, so they were excluded by name and their buttons went unchecked. They are bullets now, which
was Tony'"'"'s call and the better one: the guide is more consistent and the gate is complete.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Final

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QAbstractButton, QApplication, QLabel, QWidget

from smartclock_monitor.views.console_page import ConsolePage
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.views.pages import Page

GUIDE: Final = Path(__file__).resolve().parent.parent / "docs" / "how-to-use.md"


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def guide_text() -> str:
    return GUIDE.read_text(encoding="utf-8")


def section(title: str) -> str | None:
    """The body of one ``#### Page — Ctrl+n`` section, or ``None`` if the guide has no such page."""
    return sections().get(title)


def names_in(body: str) -> list[str]:
    """What the guide names, by the two forms it uses to name things.

    A bullet opening in bold — ``- **Health monitor** — one pill per subsystem`` — and the first
    cell of a settings table row — ``| **Advanced Console** | …``.

    **Nested bullets count** (#128). The guide indents a control under the card it sits on — the two
    switches under *Advanced*, the two thresholds under *Thresholds* — and those are names in
    exactly the way the outer ones are.
    """
    bullets = re.findall(r"^\s*- \*\*(.+?)\*\*", body, re.M)
    cells = re.findall(r"^\| \*\*(.+?)\*\*\s*\|", body, re.M)
    return [name.strip() for name in (*bullets, *cells)]


def strings_on(page: QWidget) -> set[str]:
    """Every string a user can read on a page, hidden widgets included.

    Hidden counts: §9.11's rule is that an unavailable control stays where it is and explains
    itself, so a control absent from this set is absent from the interface rather than merely
    greyed. Accessible names are included because §9.12 requires one on every control without
    visible text, and the guide names those too.
    """
    found: set[str] = set()
    for child in page.findChildren(QWidget):
        if isinstance(child, QLabel | QAbstractButton):
            found.add(child.text())
        found.add(child.accessibleName())
    # `&` is Qt's mnemonic marker in button text and is not on the screen.
    return {text.replace("&", "") for text in found if text}


def card_titles(page: QWidget) -> list[str]:
    """The cards on a page, by the token §9.7.1 gives a card heading."""
    return [
        child.text()
        for child in page.findChildren(QLabel)
        if child.property("role") == "subtitle" and child.text()
    ]


#: Built once, and **not at collection time**. Parametrizing over widgets meant constructing them
#: before pytest had run a fixture — so before any ``QApplication`` existed — which segfaults rather
#: than failing. Everything the parametrization needs now comes from the guide, which is text.
_PAGES: list[Page] = []


def pages() -> list[Page]:
    """Every page a user can reach, the console included.

    The console is added and removed by §10.13's switch rather than hidden, so it is not in the
    window's list until the setting is on — and the guide documents it either way.
    """
    if not _PAGES:
        window = DetailsWindow()
        _PAGES.extend((*window.pages, ConsolePage()))
    return _PAGES


def page_named(title: str) -> Page:
    page = next((page for page in pages() if page.title == title), None)
    assert page is not None, f"the guide has a {title!r} section and the application has no page"
    return page


def sections() -> dict[str, str]:
    """Every ``#### Page — Ctrl+n`` section, as title to body. Text only: no Qt, so this is safe to
    call while pytest is still collecting."""
    text = guide_text()
    found: dict[str, str] = {}
    for match in re.finditer(r"^#### (.+?)$", text, re.M):
        title = re.sub(r"\s*—.*$", "", match.group(1)).strip()
        following = text.find("\n#### ", match.end())
        found[title] = text[match.end() : following if following > 0 else len(text)]
    return found


def cases() -> list[tuple[str, str]]:
    """``(page title, name)`` for every name the guide gives, as parametrized cases."""
    return [(title, name) for title, body in sections().items() for name in names_in(body)]


# ---- The guide is complete about what exists ----------------------------------------------------


def test_every_page_has_a_section() -> None:
    for page in pages():
        assert section(page.title) is not None, f"the guide has no section for {page.title}"


def test_the_extraction_finds_what_it_looks_like_it_finds() -> None:
    """Guarding the guard. A regex that matched nothing would leave every case below passing while
    checking nothing — the failure `test_layering.py` guards itself against, for the same reason."""
    found = cases()

    assert len(found) >= 45
    assert ("Overview", "Health monitor") in found
    assert ("Settings", "Advanced Console") in found
    assert {title for title, _ in found} >= {"Overview", "Diagnostics", "Time", "Settings"}


@pytest.mark.parametrize(("title", "name"), cases(), ids=lambda value: value)
def test_everything_the_guide_names_is_on_the_page(title: str, name: str) -> None:
    page = page_named(title)

    assert name in strings_on(page), (
        f"the guide's {title} section names {name!r} and the page has no such card or control"
    )


# ---- The guide is complete about what is there ---------------------------------------------------


@pytest.mark.parametrize("title", sorted(sections()))
def test_every_card_on_a_page_is_named_in_the_guide(title: str) -> None:
    """The direction that catches the commoner failure: a card built and never written up.

    It found §10.9's *GPS receiver* card on its first run — built, shipped, and absent from the help
    that is supposed to explain the page it is on.
    """
    page = page_named(title)
    body = section(title)
    assert body is not None

    for card in card_titles(page):
        assert card in body, f"the {title} page has a {card!r} card and the guide never mentions it"
