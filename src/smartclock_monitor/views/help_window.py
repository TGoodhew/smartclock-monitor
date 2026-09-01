"""§9.7.5's `F1`: the user's guide, in its own window.

The row in §9.7.5 said *About* and was amended: nothing registered it, there was no About surface,
and **what a person pressing F1 wants is the guide** — the version line an About would have carried
sits at its foot instead.

**Rendered natively rather than handed to a browser.** The guide is Markdown, and Qt renders
Markdown into the same text engine every other surface uses, so the window inherits the
application's theme and its fonts. Opening a browser would put the one document explaining this
application outside it, in whatever styling the desktop happens to have — and on a machine with no
browser configured, nowhere at all.

**The guide is found, not assumed.** It ships inside the package for an installed copy and sits in
``docs/`` in a checkout, and a run from either has to work — the second is how it is read while
being written.
"""

from __future__ import annotations

from importlib import metadata
from pathlib import Path

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QTextBrowser, QWidget

from smartclock_monitor.themes.qss import stylesheet
from smartclock_monitor.themes.tokens import LIGHT, Palette

#: Where the guide lives inside an installed package.
_PACKAGED = Path(__file__).resolve().parent.parent / "resources" / "how-to-use.md"

#: And in a checkout: three levels up from ``src/smartclock_monitor/views``.
_IN_CHECKOUT = Path(__file__).resolve().parents[3] / "docs" / "how-to-use.md"


def guide_path() -> Path | None:
    """Where the guide is, or ``None`` if this build does not carry one."""
    for candidate in (_PACKAGED, _IN_CHECKOUT):
        if candidate.is_file():
            return candidate
    return None


def version() -> str:
    """The installed version, or a plain word where the package is not installed.

    Never a raised exception and never a fabricated number: §9.7.5 puts this at the guide's foot
    precisely so somebody reporting a problem can quote it, and a guess would be worse than an
    admission.
    """
    try:
        return metadata.version("smartclock-monitor")
    except metadata.PackageNotFoundError:
        return "not installed"


def guide_markdown() -> str:
    """The guide, with the version line §9.7.5 asks for appended.

    Appended at render time rather than written into the file: the document is shared with
    WinZ3805A and editing it here would fork it for a line that has to change every release
    anyway.
    """
    path = guide_path()
    if path is None:
        return (
            "# Guide not found\n\n"
            "This build does not carry `how-to-use.md`. It is in the repository under `docs/`.\n"
            f"\n---\n\nSmartClock Monitor {version()}\n"
        )

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        return f"# Guide could not be read\n\n{error}\n\n---\n\nSmartClock Monitor {version()}\n"

    return f"{text}\n\n---\n\nSmartClock Monitor {version()}\n"


class HelpWindow(QMainWindow):
    """The guide, laid out natively."""

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("How to use SmartClock Monitor")
        self.setMinimumSize(640, 560)
        self.setStyleSheet(stylesheet(palette))

        self._view = QTextBrowser()
        self._view.setOpenExternalLinks(True)
        self._view.setAccessibleName("The user's guide")
        self._view.setMarkdown(guide_markdown())
        self.setCentralWidget(self._view)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt's own casing
        """Close this window only.

        The main window's close is §10.3.1's hide-or-exit decision; this one is an ordinary window
        and must not inherit it, or dismissing the help would stop the receiver being polled.
        """
        event.accept()

    def apply_theme(self, palette: Palette) -> None:
        self.setStyleSheet(stylesheet(palette))

    @property
    def text(self) -> str:
        return self._view.toPlainText()
