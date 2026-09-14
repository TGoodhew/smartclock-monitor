"""Render the application icon to the PNG sizes a desktop and a store want.

**The SVG is the source and stays the source.** These are derived from it, committed because the
Flatpak build has no renderer and because a desktop that finds only a scalable icon is a desktop
doing more work than it needs to at every size.

**And because `appstreamcli compose` cannot read ours** (#140). That was eight builds and a probe
to establish, and the evidence is unambiguous: with the SVG in the icon path, compose fails with
`file-read-error`; with these PNGs and no SVG, it prints `Success!`. `rsvg-convert` renders the same
file without complaint, so the file is not at fault — but a bundle that will not compose is not
shippable, and a desktop reading a PNG loses nothing.

Rendered by **Qt**, which is the toolkit that draws the application, so the icon a user sees in
their launcher is rasterised by the same code that draws the medallion it came from.

    python tools/render_icons.py

Not run by CI and not gated on byte-equality: two Qt builds may antialias differently, and a gate
that fired on a Qt upgrade would be a gate people regenerate without looking. What *is* gated is
that every size exists and is square and the right dimensions — `tests/test_packaging.py`.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

#: The sizes `hicolor` wants for an application. 64 and 128 are what AppStream asks for; 256 is
#: what a desktop uses when it draws the icon large.
SIZES: Final[tuple[int, ...]] = (64, 128, 256)

ROOT: Final = Path(__file__).resolve().parent.parent
SOURCE: Final = ROOT / "packaging" / "io.github.tgoodhew.SmartClockMonitor.svg"
ICONS: Final = ROOT / "packaging" / "icons"


def destination(size: int) -> Path:
    """Where `hicolor` expects one size to live."""
    return ICONS / f"hicolor/{size}x{size}/apps/io.github.tgoodhew.SmartClockMonitor.png"


def render() -> list[Path]:
    """Rasterise every size. Returns what was written."""
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QGuiApplication, QImage, QPainter
    from PySide6.QtSvg import QSvgRenderer

    # Offscreen, because this runs in a terminal and wants no display.
    application = QGuiApplication.instance() or QGuiApplication(
        ["render-icons", "-platform", "offscreen"]
    )
    renderer = QSvgRenderer(str(SOURCE))
    if not renderer.isValid():
        raise SystemExit(f"{SOURCE} is not an SVG Qt can read.")

    written: list[Path] = []
    for size in SIZES:
        image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
        # Transparent, not white: an icon is drawn over whatever the desktop's background is.
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        renderer.render(painter)
        painter.end()

        path = destination(size)
        path.parent.mkdir(parents=True, exist_ok=True)
        # The format is inferred from the suffix; naming it explicitly is refused by
        # this binding, which takes bytes at runtime and a str in its stubs.
        if not image.save(str(path)):
            raise SystemExit(f"Could not write {path}.")
        written.append(path)

    del application
    return written


def main() -> int:
    for path in render():
        print(f"{path.relative_to(ROOT)}: {path.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
