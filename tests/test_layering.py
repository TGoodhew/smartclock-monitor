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

DEVICE = Path(__file__).resolve().parent.parent / "src" / "smartclock_device"

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
