"""The receiver: transport, line protocol, command catalog, parser, drivers.

**This package must never import Qt, and must never import the application.**

That is not a style rule. In the WinUI original the equivalent boundary is enforced by the
build — ``WinZ3805A.Device`` may not reference ``Microsoft.UI.*`` — and it is the single
reason this port is a translation exercise rather than a rewrite: every line of parsing,
command classification and transport is testable headlessly, against captured status screens,
with no display and no hardware.

``tests/test_layering.py`` enforces it here. Read it before adding a dependency.
"""

__all__: list[str] = []
