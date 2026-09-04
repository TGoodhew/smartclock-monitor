"""Why WinZ3805A's ``Test-PageTeardown.ps1`` has no counterpart, kept true (#41).

That gate enforces #388: *a page that subscribes to something must let go of it when it is
navigated away from*. It was written against WinUI navigation, where a page object outlives the
frame that showed it and a subscription to a long-lived service keeps it alive with the page
attached to the other end.

**Neither half of that is true here, and both halves are asserted below rather than asserted in
prose.** The details window builds every page once into a ``QStackedWidget`` and never navigates
away from one — showing a page is changing an index — so there is no teardown to get wrong. And
every signal a page connects to belongs to a widget the page owns, which Qt destroys with it.

The point of this module is not that the rule is satisfied. It is that the *reasons* it does not
apply are the kind that stop being true quietly: a page that connected to a session's signal, or a
window that rebuilt its pages on navigation, would reintroduce exactly the leak #388 is about, and
nothing else here would notice.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QStackedWidget

from smartclock_monitor.themes.tokens import Theme
from smartclock_monitor.views.details_window import DetailsWindow

PAGES = Path(__file__).resolve().parent.parent / "src" / "smartclock_monitor" / "views" / "pages.py"


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


def test_pages_are_built_once_and_shown_by_index() -> None:
    """A page that is constructed per navigation is a page with a lifecycle to get wrong."""
    window = DetailsWindow(Theme.DARK)

    stacks = window.findChildren(QStackedWidget)
    assert stacks, "the details window is not a stack any more — the teardown question is back"

    stack = stacks[0]
    assert stack.count() >= 8, f"only {stack.count()} pages in the stack"

    before = [stack.widget(index) for index in range(stack.count())]
    stack.setCurrentIndex(stack.count() - 1)
    stack.setCurrentIndex(0)
    after = [stack.widget(index) for index in range(stack.count())]

    assert before == after, "navigating replaced a page object, so pages now have a lifecycle"
    window.close()


def test_no_page_subscribes_to_something_it_does_not_own() -> None:
    """Every ``.connect()`` in `pages.py` is to a signal on an attribute of the page.

    That is what makes the teardown question moot: Qt destroys a child with its parent and drops
    the connection with it. A page connecting to a signal on a session, a store or a supervisor —
    objects that outlive it — is the case WinUI's gate exists for, and it would show up here as a
    receiver that is not ``self.<something>``.
    """
    tree = ast.parse(PAGES.read_text(encoding="utf-8"))

    foreign: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "connect":
            continue

        # `self._button.clicked.connect(...)` — walk back to what owns the signal.
        owner = node.func.value
        while isinstance(owner, ast.Attribute):
            owner = owner.value
        if not (isinstance(owner, ast.Name) and owner.id == "self"):
            foreign.append(f"line {node.lineno}: {ast.unparse(node.func)[:70]}")

    assert not foreign, (
        "These connect to a signal the page does not own, so it outlives the page and the "
        "teardown rule WinZ3805A's Test-PageTeardown.ps1 enforces becomes live here:\n  "
        + "\n  ".join(foreign)
    )
