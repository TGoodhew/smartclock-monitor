"""The desktop identity this port owes, and the AppImage that carries it (#27).

D2 dropped the Microsoft Store and with it `Package.Current.DisplayName`, which had supplied the
application's identity — and nothing replaced it. So the window carried a generic icon in the shell,
its `.desktop` entry did not exist, and no package manager could describe it.

**Validated with the desktop's own validators where they are installed**, rather than by asserting
that a file parses. `desktop-file-validate` and `appstreamcli` know rules this suite does not, and a
file that satisfies a hand-written check and fails Flathub's is the wrong kind of green. Where they
are absent — CI's Windows runners, a minimal container — the structural checks still run, so the
identifiers cannot drift even where the tools cannot judge the files.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Final

ROOT = Path(__file__).resolve().parent.parent
PACKAGING = ROOT / "packaging"

#: The one identifier three files and the running application must agree on.
APP_ID: Final = "io.github.tgoodhew.SmartClockMonitor"

DESKTOP = PACKAGING / f"{APP_ID}.desktop"
METAINFO = PACKAGING / f"{APP_ID}.metainfo.xml"
ICON = PACKAGING / f"{APP_ID}.svg"


def _entries() -> dict[str, str]:
    found = {}
    for line in DESKTOP.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.startswith(("#", "[")):
            key, _, value = line.partition("=")
            found[key.strip()] = value.strip()
    return found


def test_the_identity_files_exist() -> None:
    """Named for the application id, which is what the desktop looks them up by."""
    for path in (DESKTOP, METAINFO, ICON):
        assert path.is_file(), f"{path.relative_to(ROOT)} is missing"


def test_the_application_id_is_the_same_everywhere() -> None:
    """Three files and the code. **A near-miss here is silent**: the entry installs, the icon
    installs, and the window still shows a generic icon because the compositor matched neither."""
    from smartclock_monitor.views.main_window import APPLICATION_ID

    assert APPLICATION_ID == APP_ID, "the code's id is not the one the files are named for"

    component = ElementTree.parse(METAINFO).getroot()
    assert component.findtext("id") == APP_ID
    assert component.findtext("launchable") == f"{APP_ID}.desktop"


def test_the_desktop_entry_says_what_it_must() -> None:
    """The keys a launcher actually reads, and the one Wayland pairs a window with."""
    entries = _entries()

    assert entries["Type"] == "Application"
    assert entries["Exec"] == "smartclock-monitor", "the entry must launch the console script"
    assert entries["Icon"] == APP_ID, "the icon is looked up by application id, not by file name"
    assert entries["Terminal"] == "false"
    assert entries["StartupWMClass"], "X11 pairs a window to this entry by WM_CLASS"
    assert "Science" in entries["Categories"]


def test_the_application_tells_the_desktop_which_entry_it_is() -> None:
    """`setDesktopFileName` is what makes the pairing work under Wayland, where a window carries no
    class to match on. Without it the entry exists and nothing uses it."""
    source = (ROOT / "src" / "smartclock_monitor" / "__main__.py").read_text(encoding="utf-8")

    assert "setDesktopFileName(APPLICATION_ID)" in source, (
        "nothing tells the compositor which launcher this window came from"
    )


def test_the_metainfo_carries_what_a_store_needs() -> None:
    """Flathub and GNOME Software show nothing useful without these, and `releases` is where the
    version the status bar reports becomes visible to a package manager."""
    component = ElementTree.parse(METAINFO).getroot()

    assert component.get("type") == "desktop-application"
    for element in ("name", "summary", "description", "metadata_license", "project_license"):
        assert component.findtext(element) or component.find(element) is not None, element

    releases = component.find("releases")
    assert releases is not None and len(releases), "no release is described"
    assert releases[0].get("version") and releases[0].get("date")


def test_the_icon_is_scalable_and_carries_no_raster() -> None:
    """`hicolor/scalable` wants an SVG that is actually vector — an embedded bitmap in an SVG is
    the usual way an icon ends up blurry at the one size somebody notices."""
    icon = ICON.read_text(encoding="utf-8")

    assert "<svg" in icon and "viewBox" in icon
    assert "data:image" not in icon, "a raster is embedded in the scalable icon"
    assert "<image" not in icon


def test_the_build_script_wires_the_identity_into_the_appdir() -> None:
    """appimagetool reads the entry and the icon **from the AppDir root**, by application id, and
    silently produces an image with no identity if they are only under `usr/share`."""
    script = (ROOT / "build" / "make-appimage.sh").read_text(encoding="utf-8")

    assert '"$appdir/$app_id.desktop"' in script, "no entry at the AppDir root"
    assert '"$appdir/$app_id.svg"' in script, "no icon at the AppDir root"
    assert "usr/share/metainfo" in script, "the AppStream data is not installed"
    assert "AppRun" in script


# ---- The desktop's own validators, where they are installed ------------------------------------


def test_the_desktop_entry_passes_desktop_file_validate() -> None:
    """The spec has rules this suite does not know. Skipped rather than faked where the tool is
    absent — CI's Windows runners have no freedesktop tooling and never will."""
    tool = shutil.which("desktop-file-validate")
    if tool is None:
        return

    finished = subprocess.run([tool, str(DESKTOP)], capture_output=True, text=True, check=False)

    assert finished.returncode == 0, finished.stdout + finished.stderr
    assert "error" not in finished.stdout.lower(), finished.stdout


def test_the_metainfo_passes_appstreamcli() -> None:
    """What Flathub runs. `--no-net` so the suite does not depend on a network."""
    tool = shutil.which("appstreamcli")
    if tool is None:
        return

    finished = subprocess.run(
        [tool, "validate", "--no-net", str(METAINFO)], capture_output=True, text=True, check=False
    )
    combined = finished.stdout + finished.stderr

    # Pedantic notes are allowed: a reverse-DNS id with capitals is one, and org.gnome.Calculator
    # has the same one.
    assert finished.returncode == 0 or re.search(r"pedantic: \d+\s*$", combined.strip()), combined
    assert not re.search(r"^E:", combined, re.MULTILINE), combined
