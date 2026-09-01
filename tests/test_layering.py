"""The device layer may not import Qt, and may not import the application.

This is the boundary that makes the whole port tractable, so it is checked rather than
trusted. In the WinUI original the equivalent rule is enforced by the build: the device
assembly may not reference ``Microsoft.UI.*``, and the consequence is that its parser, its
command classifier and its transport are all testable with no display and no hardware.

The check is a source scan rather than an import-time one on purpose. Importing every module
to see what it pulls in would need PySide6 installed and would miss a conditional import
inside a function; reading the AST catches both, costs nothing, and works on a tree that does
not yet run.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVICE = ROOT / "src" / "smartclock_device"

#: Importing any of these from the device layer is the defect this test exists to catch.
FORBIDDEN_ROOTS = frozenset({"PySide6", "PyQt5", "PyQt6", "shiboken6", "smartclock_monitor"})


def _imported_roots(source: str) -> set[str]:
    """Every top-level module name imported anywhere in *source*, function bodies included."""
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        # level > 0 is a relative import, which cannot reach outside the package.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_device_layer_imports_no_ui() -> None:
    offenders: list[str] = []

    for path in sorted(DEVICE.rglob("*.py")):
        banned = _imported_roots(path.read_text(encoding="utf-8")) & FORBIDDEN_ROOTS
        offenders.extend(
            f"{path.relative_to(DEVICE.parent.parent)} imports {name}" for name in sorted(banned)
        )

    assert not offenders, (
        "The device layer must stay free of the UI and of the application:\n  "
        + "\n  ".join(offenders)
    )


def test_the_check_can_actually_fail() -> None:
    """Guard the guard.

    A rule that matches nothing is a rule that enforces nothing, and this one would pass
    silently if the AST walk were ever broken — the tree it scans is nearly empty. So it is
    tested against a deliberate violation, which is how the original repository tests the
    equivalent gates.
    """
    violation = "from PySide6.QtWidgets import QWidget\n"
    assert _imported_roots(violation) & FORBIDDEN_ROOTS == {"PySide6"}

    hidden = "def f():\n    import smartclock_monitor\n"
    assert _imported_roots(hidden) & FORBIDDEN_ROOTS == {"smartclock_monitor"}


# ---- §12's seam, in the other direction ---------------------------------------------------------


#: The one module a page may never import. Everything in it is *this* family's spelling.
FORBIDDEN_IN_VIEWS = "smartclock_device.commands.catalog"


def _imported_modules(source: str) -> set[str]:
    """Every fully-qualified module imported anywhere in *source*, function bodies included.

    Separate from :func:`_imported_roots`, which keeps only the top-level name: the rule here is
    about one module inside a package the views legitimately use, so the whole path is needed.
    """
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_no_page_reaches_the_command_catalog() -> None:
    """CLAUDE.md: *"Every receiver-specific fact sits behind a driver. The application never
    reaches the SmartClock driver or the NMEA driver directly; it asks the driver the session
    selected."* Issue #13.

    A page that imports the catalog names **one family's** mnemonics. It worked, because the other
    family answers ``False`` to everything it is asked about them — which is exactly the problem:
    it read as decoupled while a second family's arrival was still a rewrite of every page.

    Pages ask for a :class:`Capability` now, and the driver answers with its own command or with
    nothing. The catalog is still where the SmartClock's commands live; it is simply not something
    a view knows about.
    """
    views = ROOT / "src" / "smartclock_monitor" / "views"
    offenders = [
        str(path.relative_to(ROOT))
        for path in sorted(views.rglob("*.py"))
        if FORBIDDEN_IN_VIEWS in _imported_modules(path.read_text(encoding="utf-8"))
    ]

    assert not offenders, (
        "These pages reach the SmartClock catalog directly instead of asking the driver:\n  "
        + "\n  ".join(offenders)
    )


def test_the_catalog_check_can_actually_fail() -> None:
    """Guard the guard, the same way the one above is guarded — and this one needs it more, since
    it scans for the *absence* of a string in a directory that mostly does not contain it."""
    for violation in (
        "from smartclock_device.commands.catalog import ALL\n",
        "from smartclock_device.commands import catalog\n",
        "import smartclock_device.commands.catalog\n",
        "def f():\n    from smartclock_device.commands import catalog\n",
    ):
        assert FORBIDDEN_IN_VIEWS in _imported_modules(violation), violation

    assert FORBIDDEN_IN_VIEWS not in _imported_modules(
        "from smartclock_device.drivers.capability import Capability\n"
    )
