"""Render every picture `docs/how-to-use.md` shows, so the guide shows *this* application.

The images the guide inherited were captures of WinZ3805A's WinUI 3 windows. They were right about
a different application: this port has no notification area, no clock line on the main window and
no status pill in the details title bar, its navigation pane is in a different order, and its
Settings page offers three switches where that one offered six. A guide whose pictures disagree
with the window in front of the reader is worse than one with no pictures, because the reader
believes the picture.

**This is the only thing that writes into `docs/images/how-to-use/`.** `tests/test_guide.py` checks
the guide's image references against what this produces, in both directions, so a picture the guide
stopped referring to fails as loudly as one it refers to and nobody rendered.

**Deterministic on purpose.** A fixed clock, the captured fixtures and a fixed port list, so
running it twice produces the same bytes: `git status` after a run means the interface moved, not
that the wall clock did. That is what makes these images reviewable — the diff is the change.

**Whole surfaces, not viewports.** Each page is grabbed at the height its own content wants rather
than at whatever the window happened to be, because a guide that shows the top half of a page
teaches the top half. The trim is by pixel, from the bottom — see `_trimmed`.

Sibling of `capture_screenshots.py`, which is the *looking* tool: that one renders every page in
every theme at each window's minimum, where layout breaks, and exists to find defects. This one
renders the guide's chosen surfaces, in Light, at one stated width. Neither is a substitute for the
other and neither imports the other.

    python tools/capture_guide_images.py                 # straight into docs/images/how-to-use/
    python tools/capture_guide_images.py --out /tmp/g    # somewhere else, to compare first
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

# Before any Qt import: a display is optional, and CI has none.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QToolBar, QWidget  # noqa: E402

from smartclock_device.clock import FixedClock  # noqa: E402
from smartclock_device.commands.scpi_command import ScpiCommand  # noqa: E402
from smartclock_device.drivers.base import ReceiverDriver  # noqa: E402
from smartclock_device.drivers.capability import Capability  # noqa: E402
from smartclock_device.drivers.smartclock import SmartClockDriver  # noqa: E402
from smartclock_device.models.device_identity import DeviceIdentity  # noqa: E402
from smartclock_device.transport.transaction import (  # noqa: E402
    Transaction,
    TransactionOutcome,
)
from smartclock_monitor.services.commands import Then  # noqa: E402
from smartclock_monitor.services.polling import Reading  # noqa: E402
from smartclock_monitor.services.preferences import Preferences  # noqa: E402
from smartclock_monitor.themes.tokens import Theme, palette_for  # noqa: E402
from smartclock_monitor.views.connection_dialog import ConnectionDialog  # noqa: E402
from smartclock_monitor.views.details_window import DetailsWindow  # noqa: E402
from smartclock_monitor.views.main_window import MainWindow  # noqa: E402

#: Where the guide keeps its pictures, relative to the repository root.
IMAGES: Final = Path("docs") / "images" / "how-to-use"

#: The theme the guide says its pictures were taken in. Light, because a Markdown viewer on a white
#: background is what a guide is read on.
THEME: Final = Theme.LIGHT

#: One width for every details page, stated in the guide so a reader can reproduce it. Wide enough
#: that §10.5's two cards sit side by side, which is the layout the guide describes.
PAGE_WIDTH: Final = 980

#: Tall enough that no page scrolls while it is being grabbed. The picture is trimmed to its
#: content afterwards, so this only has to be *more* than the tallest page.
SCRATCH_HEIGHT: Final = 2600

#: The main window at a size someone would actually leave it: room for its two cards, and no more.
MAIN_SIZE: Final = (560, 400)

#: Pixels of the page's own background left below the last row that has anything on it.
BOTTOM_MARGIN: Final = 16

#: What a Z3805A answers when it is asked who it is, so the *Receiver* card shows the real shape.
IDENTITY_ANSWER: Final = "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"

#: The clock every picture is stamped from. Fixed, so the images do not change every day.
WHEN: Final = datetime(2026, 8, 27, 20, 52, 20, tzinfo=UTC)

#: What the connection dialog lists. Fixed for the same reason, and a USB adapter rather than a
#: motherboard port because that is what a receiver is almost always on.
PORTS: Final = [("/dev/ttyUSB0", "/dev/ttyUSB0 — FT232R USB UART")]


@dataclass
class _Connected:
    """Enough of a runner that the pages draw themselves the way they do when connected.

    It sends nothing. Every picture here is of a window nobody is clicking, so what this supplies
    is the one fact the pages gate their controls on — `is_connected` — and the driver they ask
    what this family supports.
    """

    driver_for: ReceiverDriver

    sent: list[str] = field(default_factory=list)

    @property
    def is_connected(self) -> bool:
        return True

    @property
    def driver(self) -> ReceiverDriver | None:
        return self.driver_for

    @property
    def is_busy(self) -> bool:
        return False

    def run(
        self,
        commands: Sequence[tuple[Capability | ScpiCommand, object]],
        then: Then | None = None,
    ) -> None:
        """Record, and drop. Nothing in this tool presses anything."""
        self.sent.extend(str(wanted) for wanted, _argument in commands)


def identity() -> DeviceIdentity:
    parsed = DeviceIdentity.parse(IDENTITY_ANSWER)
    assert parsed is not None, IDENTITY_ANSWER
    return parsed


def fixture(name: str) -> Path:
    """A capture by name, from wherever in `tests/fixtures/` it lives."""
    for path in sorted((ROOT / "tests" / "fixtures").rglob("*.txt")):
        if path.stem == name:
            return path
    raise SystemExit(f"No fixture named {name!r}.")


def reading(path: Path) -> Reading:
    """One captured status screen, parsed the way the application parses it."""
    driver = SmartClockDriver(clock=FixedClock(WHEN))
    lines = tuple(path.read_text(encoding="latin-1").splitlines())
    status = driver.parse_full(
        Transaction(command=":SYST:STAT?", outcome=TransactionOutcome.COMPLETED, lines=lines),
        None,
    )
    return Reading(status=status, captured_at=status.captured_at)


def slug(title: str) -> str:
    """A page's title as it appears in an image name."""
    return title.lower().replace(" ", "-").replace("&", "and")


def _trimmed(widget: QWidget) -> QPixmap:
    """The widget, cropped to the last row that has anything drawn on it.

    A page lives in a resizable scroll area, so it is exactly as tall as the viewport — which here
    is deliberately taller than any page, to stop them scrolling mid-grab. Cropping to the layout's
    size hint instead is the obvious answer and the wrong one: these pages are full of word-wrapped
    explanatory labels whose height depends on the width they end up with, and a hint taken before
    that resolves cuts the last paragraph in half.

    So it is measured from the pixels. The page's own background is whatever is in its top-left
    corner — that corner is layout margin on every one of them — and the crop is the last row that
    is not uniformly that colour, plus a margin. Sampled every fourth column, which is four times
    faster and cannot miss anything: nothing on these pages is under four pixels wide.
    """
    grabbed = widget.grab()
    image = grabbed.toImage()
    background = image.pixel(0, 0)

    last = 0
    for y in range(image.height() - 1, -1, -1):
        if any(image.pixel(x, y) != background for x in range(0, image.width(), 4)):
            last = y
            break

    return grabbed.copy(QRect(0, 0, image.width(), min(image.height(), last + BOTTOM_MARGIN)))


def _save(pixmap: QPixmap, out: Path, name: str) -> Path:
    target = out / f"{name}.png"
    if not pixmap.save(str(target), "PNG"):
        raise SystemExit(f"Could not write {target}.")
    return target


def _main_window(application: QApplication, sweep: Reading, out: Path) -> list[Path]:
    """§10.3's window: whole, then the two cards it is made of, then compact."""
    window = MainWindow(THEME)
    window.resize(*MAIN_SIZE)
    window.set_identity(identity(), IDENTITY_ANSWER)
    window.show_reading(sweep)
    window.set_connection_text("Connected to Z3805A — /dev/ttyUSB0 @ 9600-8-N-1")
    window.show()
    application.processEvents()

    written = [_save(window.grab(), out, "main-window")]

    glance = window.medallion.parentWidget()
    assert glance is not None
    written.append(_save(glance.grab(), out, "main-medallion-and-mode"))
    written.append(_save(window.readouts_card.grab(), out, "main-readouts"))

    window.set_compact(True)
    application.processEvents()
    written.append(_save(window.grab(), out, "main-compact"))

    window.close()
    return written


def _holdover(application: QApplication, out: Path) -> list[Path]:
    """The same card in the state the guide's table is really about.

    One picture of a green tick teaches a reader what *locked* looks like and nothing else, and the
    state they will one day open the application to find is this one.
    """
    window = MainWindow(THEME)
    window.resize(*MAIN_SIZE)
    window.show_reading(reading(fixture("holdover-gps-1pps-invalid")))
    window.show()
    application.processEvents()

    glance = window.medallion.parentWidget()
    assert glance is not None
    written = [_save(glance.grab(), out, "main-medallion-holdover")]
    window.close()
    return written


def _connection(application: QApplication, out: Path) -> list[Path]:
    dialog = ConnectionDialog(palette_for(THEME), list_ports=lambda: list(PORTS))
    dialog.adjustSize()
    dialog.show()
    application.processEvents()
    written = [_save(dialog.grab(), out, "connection-dialog")]
    dialog.close()
    return written


def _details(application: QApplication, sweep: Reading, out: Path) -> list[Path]:
    """§10.4 – §10.11: the toolbar, the navigation pane, and every page whole.

    Both opt-in surfaces are on. A page that is off by default is still a page the guide documents,
    and a reader who has just turned the console on wants to see what they turned on.
    """
    window = DetailsWindow(THEME)
    window.apply_preferences(Preferences(advanced_console=True, undocumented_queries=True))
    window.set_command_runner(_Connected(SmartClockDriver(clock=FixedClock(WHEN))))
    window.set_identity(identity(), IDENTITY_ANSWER)
    window.resize(PAGE_WIDTH, SCRATCH_HEIGHT)
    window.show_reading(sweep)
    window.show()
    application.processEvents()

    bars = window.findChildren(QToolBar)
    assert bars, "§10.4's command bar has gone; the guide describes it."
    written = [_save(bars[0].grab(), out, "details-toolbar")]
    written.append(_save(window.navigation.grab(), out, "details-nav"))

    for index, page in enumerate(window.pages):
        window.navigation.setCurrentRow(index)
        application.processEvents()
        written.append(_save(_trimmed(page), out, f"page-{slug(page.title)}"))

    # The two halves of §10.5 on their own, because the page is the one place where the picture of
    # the whole is too wide to read either half in.
    satellites = window.page_named("Satellites")
    window.navigation.setCurrentRow(list(window.pages).index(satellites))
    application.processEvents()
    written.append(_save(satellites.plot.grab(), out, "satellites-sky-plot"))  # type: ignore[attr-defined]
    written.append(_save(satellites.table.grab(), out, "satellites-table"))  # type: ignore[attr-defined]

    window.close()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT / IMAGES,
        help="where to write them (default: the guide's own image directory)",
    )
    arguments = parser.parse_args()

    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)

    out = arguments.out
    out.mkdir(parents=True, exist_ok=True)

    sweep = reading(fixture("locked-to-gps"))
    written = [
        *_main_window(application, sweep, out),
        *_holdover(application, out),
        *_connection(application, out),
        *_details(application, sweep, out),
    ]

    for path in written:
        print(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path)
    print(f"\n{len(written)} images. Now look at them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
