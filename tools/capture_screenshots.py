"""Render every window and page to PNG, so they can be *looked at*.

**This exists because looking found things nothing else did.** The test suite was green at 1 346
tests when this was first run, and one pass over the images turned up twelve defects: a `QToolBar`
taking the desktop's palette, spin boxes rendering as white rectangles with unreadable values, two
cards sharing a title on the first page anyone opens, `Valid_Reduced` and `Msl` reaching the screen
as identifiers, the outputs pill collapsing its most important state into neutral grey, a theme
picker squeezed to one letter, and five pages scrolling sideways.

None of those are things a unit test was ever going to notice, because each one is a *rendered*
fact. Several are now gated in `tests/test_accessibility.py` — the background rule, the pointer
targets, the sideways-scroll rule — and those gates were written from what this found. That is the
intended cycle: **look, then encode what you saw as a rule**, so the next person does not have to
find it again.

Outside `src/` and imported by nothing there. It needs no receiver: it drives the pages from the
captured fixtures, so it runs anywhere the tests do, offscreen and in CI if that is ever wanted.

    python tools/capture_screenshots.py --out /tmp/shots
    python tools/capture_screenshots.py --out /tmp/shots --theme light --fixture holdover

The alt text in `docs/how-to-use.md` describes the *WinUI 3* application, whose layout differs in
places this port has deliberately not followed. Regenerating the guide's images is therefore not
just a matter of pointing this at the right pages, and it is not what this tool claims to do.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Before any Qt import: a display is optional, and CI has none.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from PySide6.QtWidgets import QApplication  # noqa: E402

from smartclock_device.clock import SystemClock  # noqa: E402
from smartclock_device.drivers.smartclock import SmartClockDriver  # noqa: E402
from smartclock_device.transport.transaction import Transaction, TransactionOutcome  # noqa: E402
from smartclock_monitor.services.polling import Reading  # noqa: E402
from smartclock_monitor.services.preferences import Preferences  # noqa: E402
from smartclock_monitor.themes.tokens import Theme  # noqa: E402
from smartclock_monitor.views.details_window import DetailsWindow  # noqa: E402
from smartclock_monitor.views.main_window import MainWindow  # noqa: E402

#: What the windows are opened at. **Their own minimums**, because that is where layout breaks and
#: it is the size the application actually opens at — a generous window hides exactly the defects
#: this is looking for.
AT_MINIMUM = "minimum"


def reading_from(fixture: Path) -> Reading:
    """One captured status screen, parsed the way the application parses it."""
    driver = SmartClockDriver(clock=SystemClock())
    lines = tuple(fixture.read_text(encoding="latin-1").splitlines())
    status = driver.parse_full(
        Transaction(command=":SYST:STAT?", outcome=TransactionOutcome.COMPLETED, lines=lines),
        None,
    )
    return Reading(status=status, captured_at=status.captured_at)


def capture(out: Path, theme: Theme, reading: Reading, size: tuple[int, int] | None) -> list[Path]:
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    written: list[Path] = []

    details = DetailsWindow(theme)
    # Both opt-in surfaces on: a page that is off by default is still a page, and §10.11's console
    # is one of the two this pass found defects in.
    details.apply_preferences(Preferences(advanced_console=True, undocumented_queries=True))
    details.resize(*(size or (details.minimumWidth(), details.minimumHeight())))
    details.show_reading(reading)
    details.show()
    application.processEvents()

    for index, page in enumerate(details.pages):
        details._navigation.setCurrentRow(index)
        application.processEvents()
        name = page.title.lower().replace(" ", "-").replace("&", "and")
        target = out / f"{theme.value}-details-{index}-{name}.png"
        details.grab().save(str(target))
        written.append(target)

    main = MainWindow(theme)
    main.resize(*(size or (main.minimumWidth(), main.minimumHeight())))
    main.show_reading(reading)
    main.show()
    application.processEvents()
    target = out / f"{theme.value}-main.png"
    main.grab().save(str(target))
    written.append(target)

    details.close()
    main.close()
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, required=True, help="directory to write PNGs into")
    parser.add_argument(
        "--theme",
        default="all",
        choices=["all", *(theme.value for theme in Theme)],
        help="which token set to render in (default: every one)",
    )
    parser.add_argument(
        "--fixture",
        default="locked-stabilizing",
        help="which captured status screen to drive the pages from, without the .txt",
    )
    parser.add_argument(
        "--size",
        default=AT_MINIMUM,
        help=f"WIDTHxHEIGHT, or {AT_MINIMUM!r} for each window's own minimum (the default)",
    )
    arguments = parser.parse_args()

    # rglob: nine of the ten captures live in fixtures/captured/.
    captures = {path.stem: path for path in sorted((ROOT / "tests" / "fixtures").rglob("*.txt"))}
    fixture = captures.get(arguments.fixture)
    if fixture is None:
        parser.error(f"no fixture {arguments.fixture!r}. There are: {', '.join(sorted(captures))}")

    size: tuple[int, int] | None = None
    if arguments.size != AT_MINIMUM:
        try:
            width, height = (int(part) for part in arguments.size.lower().split("x", 1))
        except ValueError:
            parser.error(f"--size wants WIDTHxHEIGHT or {AT_MINIMUM!r}, not {arguments.size!r}")
        size = (width, height)

    arguments.out.mkdir(parents=True, exist_ok=True)
    themes = list(Theme) if arguments.theme == "all" else [Theme(arguments.theme)]

    reading = reading_from(fixture)
    written: list[Path] = []
    for theme in themes:
        written.extend(capture(arguments.out, theme, reading, size))

    for path in written:
        print(path)
    print(f"\n{len(written)} images from {fixture.name}. Now look at them.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
