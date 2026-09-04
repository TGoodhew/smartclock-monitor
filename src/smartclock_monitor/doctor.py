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

import json
import os
import pathlib
import platform
import shutil
import subprocess
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


#: One child process that starts Qt and registers the fonts, and reports what happened.
#:
#: **Both checks share it because a QApplication can only exist once**, and because the interesting
#: failure kills whichever process attempts it.
_PROBE: Final = """
import json, sys
from PySide6.QtWidgets import QApplication

application = QApplication([sys.argv[0]])
from smartclock_monitor.themes import fonts

print("PROBE " + json.dumps({"platform": application.platformName(), "fonts": list(fonts.load())}))
"""


@dataclass(frozen=True, slots=True)
class _GuiProbe:
    """What a child process found out about starting a GUI here."""

    platform_name: str | None
    fonts: tuple[str, ...]
    detail: str

    @property
    def started(self) -> bool:
        return self.platform_name is not None


def _probe_gui() -> _GuiProbe:
    """Ask a child process whether Qt can start, because asking in this one is unsurvivable.

    **Qt does not raise when it cannot load a platform plugin. It calls ``qFatal()``, which calls
    ``abort()``.** That never becomes a Python exception, so the ``except Exception`` this replaced
    could not see it: the process died mid-check and `--doctor` printed nothing at all — on exactly
    the machine it exists to diagnose, which is the one where Qt will not start (#46).

    In a child, that abort is an exit status. The parent reads it, reports it, and goes on to the
    checks after it — a machine missing one library still learns about its serial ports, its group
    membership and everything else.

    ``QT_QPA_PLATFORM=offscreen`` would also stop the abort and is **not** the fix: it answers a
    different question from "can this application open a window here", and answers it yes on a
    machine where the honest answer is no.
    """
    try:
        finished = subprocess.run(
            [sys.executable, "-c", _PROBE],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as error:  # pragma: no cover - depends on machine
        return _GuiProbe(None, (), f"could not run the probe ({type(error).__name__}: {error})")

    for line in finished.stdout.splitlines():
        if line.startswith("PROBE "):
            answer = json.loads(line[len("PROBE ") :])
            return _GuiProbe(answer["platform"], tuple(answer["fonts"]), "")

    # Qt's own complaint is the useful half of stderr, and it names the missing library.
    noise = [line for line in finished.stderr.splitlines() if line.strip()]
    said = next((line for line in noise if "qt.qpa" in line.lower()), noise[-1] if noise else "")
    died = f"the probe exited {finished.returncode}"
    return _GuiProbe(None, (), f"{died}: {said}" if said else died)


def _qt_platform(probe: _GuiProbe) -> Finding:
    """Whether Qt can actually start a GUI, which is a different question from importing it.

    This is the one that catches a headless server and a container without the EGL libraries, and
    it is the failure that otherwise arrives as ``qt.qpa.plugin: Could not load the Qt platform
    plugin "xcb"`` and an abort — which is precisely what it used to do here rather than report.
    """
    try:
        import PySide6  # noqa: F401
    except ImportError:
        return Finding("Qt platform", False, "PySide6 is not importable", "See above.")

    if probe.started:
        return Finding("Qt platform", True, f"{probe.platform_name!r}")

    return Finding(
        "Qt platform",
        False,
        f"cannot start a GUI — {probe.detail}",
        "On Linux: sudo apt install libegl1 libgl1 libxkbcommon0 libxcb-cursor0 — and a display. "
        "Over SSH, either forward one or run on the machine's own desktop. "
        "QT_QPA_PLATFORM=offscreen runs headless, which is a different thing from working.",
    )


def _fonts(probe: _GuiProbe) -> Finding:
    """§9.5's two faces, registered by the same child that started Qt.

    Registering them needs a QApplication, so this cannot be answered where the check above failed
    — and saying so is better than the invented failure the old code produced, which reported the
    fonts as missing whenever the display was.
    """
    try:
        from smartclock_monitor.themes import fonts  # noqa: F401
    except ImportError as error:
        return Finding("Bundled fonts", False, f"cannot import ({error})", "")

    if not probe.started:
        return Finding(
            "Bundled fonts",
            False,
            "not checked — Qt could not start, and registering a face needs a QApplication",
            "Fix the Qt platform above and run this again.",
        )

    ok = len(probe.fonts) >= 2
    return Finding(
        "Bundled fonts",
        ok,
        ", ".join(probe.fonts) if probe.fonts else "none registered",
        "" if ok else "The application still runs; §9.5's faces fall back to the desktop's.",
    )


def _pyserial() -> Finding:
    try:
        import serial
    except ImportError as error:
        return Finding("pyserial", False, f"cannot import ({error})", 'pip install -e "."')
    return Finding("pyserial", True, getattr(serial, "__version__", "present"))


#: Name fragments that denote a USB serial adapter, across the three platforms.
#:
#: Used *alongside* the USB vendor id rather than instead of it: a real adapter normally reports a
#: vid, and under WSL's usbipd passthrough it reports none at all — so either signal on its own
#: misses a receiver that is plugged in and working.
_ADAPTER_HINTS: Final = ("ttyusb", "ttyacm", "usbserial", "usbmodem", "com")


def _is_adapter(port: object) -> bool:
    if getattr(port, "vid", None) is not None:
        return True
    device = str(getattr(port, "device", "")).lower()
    return any(hint in device for hint in _ADAPTER_HINTS)


def _uart(count: int) -> str:
    return "port" if count == 1 else "ports"


def _ports() -> Finding:
    """Which ports could plausibly have a receiver on them.

    **Not a list of every device node.** A desktop Linux kernel offers ttyS0 through ttyS31 whether
    or not any of them exists in hardware, and printing all thirty-two buries the one fact that
    matters — whether an adapter is attached — in a wall of names. Reported from a clean VM, where
    that is exactly what it did; WSL offers eight, which is few enough that the problem never
    showed here.
    """
    try:
        from serial.tools import list_ports
    except ImportError:
        return Finding("Serial ports", False, "pyserial is not importable", "See above.")

    ports = sorted(list_ports.comports(), key=lambda port: port.device)
    adapters = [port for port in ports if _is_adapter(port)]
    builtin = len(ports) - len(adapters)

    if adapters:
        detail = ", ".join(
            port.device
            if port.description in ("n/a", "", None)
            else f"{port.device} ({port.description})"
            for port in adapters
        )
        if builtin:
            detail += f"  (+{builtin} built-in {_uart(builtin)}, which a receiver rarely sits on)"
        return Finding("Serial ports", True, detail)

    detail = "no USB adapter found"
    if builtin:
        detail += f" — {builtin} built-in {_uart(builtin)} only"

    remedy = "Nothing is plugged in, or the adapter needs its driver."
    if _is_wsl():
        remedy = (
            "Under WSL a USB adapter needs 'usbipd attach' from an elevated Windows prompt "
            "before it appears at all."
        )
    # Not a failure: --demo needs no port, and a machine with none is the ordinary case.
    return Finding("Serial ports", True, detail, remedy)


#: USB vendor ids that make serial adapters, and the name each is usually sold under.
#:
#: Not exhaustive and does not need to be: this exists to recognise the common cases well enough to
#: say "the adapter is on the bus and Linux made no port for it", which is a different problem from
#: "nothing is plugged in" and has different remedies.
_SERIAL_VENDORS: Final[dict[str, str]] = {
    "067b": "Prolific",
    "0403": "FTDI",
    "10c4": "Silicon Labs CP210x",
    "1a86": "QinHeng CH340",
    "04d8": "Microchip",
    "2341": "Arduino",
}


def _usb_serial_hardware(
    devices: pathlib.Path | None = None, has_port: bool | None = None
) -> Finding:
    """Whether a serial adapter is on the bus, and whether Linux gave it a port.

    **The gap this closes is the one that looks like nothing at all.** An adapter can be attached,
    enumerated and visible in ``lsusb`` while no ``/dev/ttyUSB*`` exists — and the port check above
    then reports, quite truthfully, that no adapter was found. The user is left believing the cable
    is wrong when the kernel simply handed the device to something else.

    On Ubuntu that something else is usually ``brltty``, which is installed by default and claims
    several of these chips because Braille displays share their vendor ids. Prolific is the usual
    casualty. It is not a misconfiguration anybody made and it is not discoverable without being
    told, which is exactly what a doctor is for.

    Read from sysfs rather than by running ``lsusb``, which is not installed everywhere.

    :param devices: where to look. Injected so the interesting case — hardware present, no port —
        can be tested on a machine that does not have it, which is every machine that is working.
    :param has_port: whether a tty exists. Injected for the same reason.
    """
    if devices is None:
        if platform.system() != "Linux":
            return Finding("USB serial hardware", True, "checked on Linux only")
        devices = pathlib.Path("/sys/bus/usb/devices")

    if not devices.is_dir():
        return Finding("USB serial hardware", True, "no USB bus visible")

    seen: list[str] = []
    for entry in sorted(devices.iterdir()):
        vendor = entry / "idVendor"
        try:
            identifier = vendor.read_text(encoding="ascii").strip().lower()
        except OSError:
            continue
        if identifier in _SERIAL_VENDORS:
            seen.append(_SERIAL_VENDORS[identifier])

    if not seen:
        return Finding("USB serial hardware", True, "none on the bus")

    names = ", ".join(sorted(set(seen)))
    if has_port is None:
        has_port = any(
            any(pathlib.Path("/dev").glob(pattern)) for pattern in ("ttyUSB*", "ttyACM*")
        )
    if has_port:
        return Finding("USB serial hardware", True, f"{names}, with a port")

    return Finding(
        "USB serial hardware",
        False,
        f"{names} is on the bus and Linux created no port for it",
        "Usually brltty, installed by default on Ubuntu desktop, which claims these chips because "
        "Braille displays share their vendor ids: 'sudo apt remove brltty', then unplug and "
        "replug. Otherwise 'dmesg | tail -30' will say what took it.",
    )


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

    # One child process answers both, and survives the abort that used to end the report.
    probe = _probe_gui()
    yield _qt_platform(probe)
    yield _fonts(probe)
    yield _pyserial()
    yield _ports()
    yield _usb_serial_hardware()
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
