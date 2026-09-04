"""PyInstaller spec: one self-contained directory, no Python required to run it.

Run from the repository root:

    pip install -e ".[package]"
    pyinstaller build/smartclock-monitor.spec

**A directory rather than a single file.** `--onefile` unpacks ~150 MB of Qt into a temporary
directory on every launch, which costs seconds a run and breaks on machines that mount /tmp
noexec — for an application somebody leaves docked beside a spectrum analyser for weeks, a slow
start every time is the wrong trade. The directory is what an AppImage or an installer wraps
anyway.

**The data files are the part that goes wrong silently.** Qt's own plugins PyInstaller finds by
itself; ours it cannot know about — the bundled typefaces are read through `importlib.resources`
and the guide through the same, so both are invisible to the dependency graph. Left out, the
application starts and renders in the wrong font with a help key that opens an apology, which is
exactly the sort of failure that ships.
"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

ROOT = Path(SPECPATH).parent  # noqa: F821 - PyInstaller injects SPECPATH

# Read through importlib.resources at runtime, so nothing static references them.
datas = [
    # The package's own .dist-info. Without it `importlib.metadata.version` raises
    # PackageNotFoundError in the bundle and every surface that reports the release — §9.7.5's
    # guide footer, and the status bar — answers "not installed". That is wrong in the one
    # distribution channel where the user has no other way to find the number, and it fails
    # silently: the fallback is a legitimate answer everywhere else.
    *copy_metadata("smartclock-monitor"),
    *collect_data_files("smartclock_monitor.themes.fonts", include_py_files=False),
    (str(ROOT / "docs" / "how-to-use.md"), "smartclock_monitor/resources"),
    # The bundle is the one channel that redistributes Qt, PySide6 and every dependency rather than
    # declaring them, so it is the channel the notices exist for. A bundle that carried the code and
    # not the notices would be the licence problem THIRD-PARTY-NOTICES.md was written to prevent.
    (str(ROOT / "THIRD-PARTY-NOTICES.md"), "."),
    (str(ROOT / "LICENSE"), "."),
    # **The dependencies' own licences.** PyInstaller does not collect a dependency's .dist-info,
    # so without these lines the bundle carried every one of them and none of their terms. These
    # four ship a licence inside their distribution and `copy_metadata` brings it along; Qt,
    # PySide6 and pyserial ship none at all, which is what `licenses/` in the repository is for.
    *copy_metadata("qasync"),
    *copy_metadata("pyserial-asyncio"),
    *copy_metadata("markdown-it-py"),
    *copy_metadata("mdurl"),
    (str(ROOT / "licenses"), "licenses"),
    # --demo replays these. Left out, the bundle starts and shows nothing for ever, which reads as
    # a receiver that has not answered rather than as a missing file.
    (str(ROOT / "tests" / "fixtures"), "smartclock_monitor/resources/fixtures"),
]

analysis = Analysis(  # noqa: F821
    [str(ROOT / "src" / "smartclock_monitor" / "__main__.py")],
    pathex=[str(ROOT / "src")],
    datas=datas,
    hiddenimports=[
        # Reached only through the driver registry and the transport factory, both of which
        # resolve by value rather than by import at the call site.
        "smartclock_device.drivers.nmea",
        "smartclock_device.transport.serial_port",
    ],
    # Qt's WebEngine is enormous and nothing here uses it; tkinter comes along uninvited.
    excludes=["tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.Qt3DCore"],
    noarchive=False,
)

pyz = PYZ(analysis.pure)  # noqa: F821

executable = EXE(  # noqa: F821
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="smartclock-monitor",
    console=False,
    # Stripping and UPX are deliberately off: both have a long history of producing binaries that
    # fail only on someone else's machine, and neither is worth that on an application whose whole
    # value is being trusted about what a receiver said.
    strip=False,
    upx=False,
)

COLLECT(  # noqa: F821
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name="smartclock-monitor",
)
