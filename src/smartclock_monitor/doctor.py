"""``--doctor``: what this machine is missing, and the command that fixes it.

**A first run on a clean machine fails in ways that do not name themselves.** PySide6 imports and
then cannot create a window because ``libEGL`` is absent; a serial port exists and cannot be opened
because the user is not in ``dialout``; ``python -m venv`` fails on a distribution that ships
``venv`` in a separate package. Each produces a traceback about something three layers below what is
actually wrong, and none of them is the application's fault — which is exactly why the application
should be the thing that says so.

**Every check reports rather than raises, and the report is the point.** A doctor that stopped at
the first failure would send somebody round the loop once per problem; this one runs everything and
prints the whole list, because the machine that is missing Qt's libraries is usually the machine
that is also not in ``dialout``.

Nothing here is imported at module scope beyond the standard library, so ``--doctor`` still works on
the installation where PySide6 itself is the broken thing.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

#: The minimum this project claims to run on. `pyproject.toml` is the authority; repeated here
#: because the doctor must work before the package metadata is necessarily readable.
MINIMUM_PYTHON: Final = (3, 12)


@dataclass(frozen=True, slots=True)
class Finding:
    """One check, its verdict, and what to do about it."""

    name: str
    ok: bool
    detail: str

    #: The command or action that fixes it. Empty where there is nothing to fix.
    remedy: str = ""

    def rendered(self) -> str:
        mark = "ok  " if self.ok else "FAIL"
        line = f"  [{mark}] {self.name}: {self.detail}"
        return line if self.ok or not self.remedy else f"{line}\n         → {self.remedy}"


def _python() -> Finding:
    version = ".".join(str(part) for part in sys.version_info[:3])
    ok = sys.version_info[:2] >= MINIMUM_PYTHON
    wanted = ".".join(str(part) for part in MINIMUM_PYTHON)
    return Finding(
        "Python",
        ok,
        f"{version} at {sys.executable}",
        "" if ok else f"This needs Python {wanted} or newer.",
    )


def _pyside() -> Finding:
    try:
        import PySide6
    except ImportError as error:
        return Finding(
            "PySide6",
            False,
            f"cannot import ({error})",
            'pip install -e "." — inside the virtual environment, not outside it.',
        )
    return Finding("PySide6", True, f"{PySide6.__version__}")


def _qt_platform() -> Finding:
    """Whether Qt can actually start a GUI, which is a different question from importing it.

    This is the one that catches a headless server and a container without the EGL libraries, and
    it is the failure that otherwise arrives as ``qt.qpa.plugin: Could not load the Qt platform
    plugin "xcb"`` and an abort.
    """
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return Finding("Qt platform", False, "PySide6 is not importable", "See above.")

    if QApplication.instance() is not None:
        return Finding("Qt platform", True, "already running")

    try:
        application = QApplication([sys.argv[0]])
    except Exception as error:  # pragma: no cover - depends on the machine
        return Finding(
            "Qt platform",
            False,
            f"cannot open a display ({type(error).__name__}: {error})",
            "On Linux: sudo apt install libegl1 libgl1 libxkbcommon0 — and a display, or "
            "QT_QPA_PLATFORM=offscreen to run headless.",
        )
    # **Left running for the checks below.** Shutting it down here reported the fonts as having
    # nowhere to register — a failure invented by the doctor rather than found by it, which is the
    # one kind of finding that would make the whole report untrustworthy.
    return Finding("Qt platform", True, f"{application.platformName()!r}")


def _fonts() -> Finding:
    try:
        from smartclock_monitor.themes import fonts
    except ImportError as error:
        return Finding("Bundled fonts", False, f"cannot import ({error})", "")

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return Finding("Bundled fonts", False, "PySide6 is not importable", "See above.")

    if QApplication.instance() is None:
        # The platform check ordinarily leaves one running; this covers being called on its own.
        try:
            QApplication([sys.argv[0]])
        except Exception:  # pragma: no cover - depends on the machine
            return Finding("Bundled fonts", False, "no display to register them with", "")

    families = fonts.load()
    ok = len(families) >= 2
    return Finding(
        "Bundled fonts",
        ok,
        ", ".join(families) if families else "none registered",
        "" if ok else "The application still runs; §9.5's faces fall back to the desktop's.",
    )


def _pyserial() -> Finding:
    try:
        import serial
    except ImportError as error:
        return Finding("pyserial", False, f"cannot import ({error})", 'pip install -e "."')
    return Finding("pyserial", True, getattr(serial, "__version__", "present"))


def _ports() -> Finding:
    try:
        from serial.tools import list_ports
    except ImportError:
        return Finding("Serial ports", False, "pyserial is not importable", "See above.")

    found = [port.device for port in list_ports.comports()]
    if found:
        return Finding("Serial ports", True, ", ".join(sorted(found)))

    remedy = "Nothing is plugged in, or the adapter needs its driver."
    if _is_wsl():
        remedy = (
            "Under WSL a USB adapter needs 'usbipd attach' from an elevated Windows prompt "
            "before it appears at all."
        )
    # Not a failure: --demo needs no port, and this is the ordinary state of a dev machine.
    return Finding("Serial ports", True, "none found", remedy)


def _dialout() -> Finding:
    """Group membership, on the systems where it decides whether a port can be opened.

    Checked against the *current process*, deliberately. Being listed in ``/etc/group`` and not
    having the group in this session is the commonest form of this problem — a shell opened before
    the group was granted keeps the old set, and the port keeps refusing until the user logs out.
    """
    if platform.system() != "Linux":
        return Finding("dialout group", True, "not applicable on this platform")

    try:
        import grp

        wanted = grp.getgrnam("dialout").gr_gid
    except (ImportError, KeyError):
        return Finding("dialout group", True, "no dialout group on this system")

    if wanted in os.getgroups():
        return Finding("dialout group", True, "this session is in it")

    return Finding(
        "dialout group",
        False,
        "this session is not in it, so opening a port will be refused",
        "sudo usermod -aG dialout $USER — then log out and back in, or run 'newgrp dialout'. "
        "Never chmod the device node.",
    )


def _is_wsl() -> bool:
    if platform.system() != "Linux":
        return False
    try:
        return "microsoft" in open("/proc/version", encoding="utf-8").read().lower()
    except OSError:
        return False


def checks() -> Iterator[Finding]:
    """Run every check, in the order a first run meets them."""
    yield _python()
    yield _pyside()
    yield _qt_platform()
    yield _fonts()
    yield _pyserial()
    yield _ports()
    yield _dialout()


def report() -> int:
    """Print the findings. Returns a process exit status: 0 when nothing is broken."""
    where = f"{platform.system()} {platform.release()}"
    if _is_wsl():
        where += " (WSL)"
    print(f"smartclock-monitor doctor — {where}, {platform.machine()}")
    if shutil.which("apt") and platform.system() == "Linux":
        print("  (Debian/Ubuntu detected; remedies below use apt.)")
    print()

    failures = 0
    for finding in checks():
        print(finding.rendered())
        failures += not finding.ok

    print()
    if failures:
        print(f"{failures} thing{'' if failures == 1 else 's'} to fix. The remedies are above.")
    else:
        print("Nothing to fix. 'smartclock-monitor --demo' will run without a receiver.")
    return 1 if failures else 0
