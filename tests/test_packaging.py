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

import importlib.util
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from types import ModuleType
from typing import Final

ROOT = Path(__file__).resolve().parent.parent


def _by_path(name: str, path: Path) -> ModuleType:
    """Load a module that lives at the project root, which is not on the test path (src layout).

    The same device `test_versioning.py` uses for `hatch_version.py`, and for the same reason. It
    matters here that the *workflow's* helper is the one imported: the release gate and this test
    must agree about which entry "newest" means, and two readers of one file is how they stop.
    """
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


# ---- The Flatpak manifest (#93) ------------------------------------------------------------

FLATPAK: Final = PACKAGING / "flatpak"
MANIFEST: Final = FLATPAK / f"{APP_ID}.yml"


def manifest() -> dict[str, object]:
    import yaml

    return dict(yaml.safe_load(MANIFEST.read_text(encoding="utf-8")))


def module(name: str) -> dict[str, object]:
    import yaml

    return dict(yaml.safe_load((FLATPAK / name).read_text(encoding="utf-8")))


def test_the_manifest_is_named_for_the_application() -> None:
    """Flathub names a manifest for the application id and nothing else, and a bundle whose
    manifest disagrees with its own `id` installs under a name the desktop cannot look up."""
    assert MANIFEST.is_file()
    assert manifest()["id"] == APP_ID
    assert manifest()["command"] == "smartclock-monitor"


def test_the_runtime_is_pinned_to_a_version() -> None:
    """**D10.** `org.freedesktop.Platform` rather than `org.kde.Platform`, because a PySide6 wheel
    carries its own Qt regardless — so taking KDE's runtime for its Qt would ship a Qt nothing here
    has tested, while these wheels are the ones CI runs against.

    Pinned, because *"latest"* is not a version and a runtime that moves under a bundle changes the
    Qt a user gets without anything saying so.
    """
    found = manifest()

    assert found["runtime"] == "org.freedesktop.Platform"
    assert found["sdk"] == "org.freedesktop.Sdk"
    assert re.fullmatch(r"\d\d\.\d\d", str(found["runtime-version"]))


def test_the_sandbox_asks_for_the_serial_port_and_no_network() -> None:
    """**`--device=all` is the only permission that covers `/dev/ttyUSB0`.** Flatpak has no
    `--device=serial`; `--device=dri` is the graphics card. An application that monitors a receiver
    over RS-232 and cannot open a port is one nobody can use.

    And nothing here talks to a network, so a permission it never uses is one a reader would have
    to rule out.
    """
    args = list(manifest()["finish-args"])  # type: ignore[call-overload]

    assert "--device=all" in args
    assert "--socket=wayland" in args and "--socket=fallback-x11" in args
    assert not any(arg.startswith("--share=network") for arg in args)
    assert not any(arg.startswith("--filesystem=home") for arg in args)


def test_the_application_is_built_from_a_tag() -> None:
    """#93: *"builds reproducibly from a tag"*. A working copy would also lose `hatch_version.py`'s
    git history, and the version would silently become `0.0.0.0` — the failure `test_versioning.py`
    exists to prevent."""
    modules = list(manifest()["modules"])  # type: ignore[call-overload]
    app = next(entry for entry in modules if isinstance(entry, dict))
    source = next(s for s in app["sources"] if s.get("type") == "git")

    assert source["url"].endswith("smartclock-monitor.git")
    assert re.fullmatch(r"v\d+\.\d+\.\d+", str(source["tag"]))


def test_every_wheel_the_flatpak_installs_is_hashed() -> None:
    """`flatpak-builder` builds offline and Flathub requires it: a manifest that fetched whatever
    PyPI served that morning would not be reproducible."""
    for name in ("python3-modules.yml", "python3-build-backend.yml"):
        sources = list(module(name)["sources"])  # type: ignore[call-overload]
        assert sources
        for source in sources:
            assert source["type"] == "file"
            assert source["url"].startswith("https://files.pythonhosted.org/")
            assert re.fullmatch(r"[0-9a-f]{64}", str(source["sha256"]))


def test_the_pinned_wheels_are_the_versions_this_repository_tests_against() -> None:
    """**The gate that keeps the bundle honest.** A dependency bump that forgot the Flatpak would
    ship a bundle built from wheels nothing here has run — which is the worst way round, because CI
    would be green throughout."""
    from importlib.metadata import version

    sys.path.insert(0, str(ROOT / "tools"))
    from flatpak_requirements import PINNED

    for name, pinned in PINNED:
        assert version(name) == pinned, (
            f"the Flatpak pins {name} {pinned} and this environment has {version(name)}"
        )


def _normalised(name: str) -> str:
    """PEP 503's name comparison, so `PySide6_Essentials` and `pyside6-essentials` are one name."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared_runtime_dependencies() -> set[str]:
    import tomllib

    with (ROOT / "pyproject.toml").open("rb") as handle:
        requirements = tomllib.load(handle)["project"]["dependencies"]

    names = set()
    for requirement in requirements:
        match = re.match(r"[A-Za-z0-9._-]+", requirement)
        assert match, f"no distribution name in {requirement!r}"
        names.add(_normalised(match.group()))
    return names


def test_the_flatpak_pins_every_runtime_dependency() -> None:
    """**The gate above only ever looks at what `PINNED` already names.** A dependency *omitted*
    from it is examined by nothing — so v1.2.1 shipped a Flatpak with no `qasync`, which could not
    reach its own event loop and died on the import, while every check in this file stayed green
    (#144). Only `--doctor` still ran, because it imports nothing beyond the standard library, so
    the one instrument pointed at the bundle reported that there was nothing to fix.

    This asserts the other direction: every runtime dependency `pyproject.toml` declares reaches
    the bundle. Extra pins are fine — `shiboken6` is here because PySide6 loads it, and no
    dependency table names it.
    """
    sys.path.insert(0, str(ROOT / "tools"))
    from flatpak_requirements import PINNED, SUBSTITUTED

    pinned = {_normalised(name) for name, _ in PINNED}
    missing = sorted(
        declared
        for declared in _declared_runtime_dependencies()
        if SUBSTITUTED.get(declared, declared) not in pinned
    )

    assert not missing, (
        f"pyproject.toml requires {', '.join(missing)} and the Flatpak does not install "
        f"{'it' if len(missing) == 1 else 'them'} — add to PINNED in tools/flatpak_requirements.py "
        "and re-run it"
    )


def test_the_flatpak_ships_only_the_qt_modules_this_application_imports() -> None:
    """The bundle installs **PySide6-Essentials**, not the metapackage — 80 MB against several
    hundred, with the same binaries for everything used.

    An import from Addons would work in CI, which installs the metapackage, and fail in the
    Flatpak. That is the worst way round for a defect to be discovered, so it is a gate.
    """
    essentials = {"QtCore", "QtGui", "QtWidgets", "QtSvg", "QtNetwork", "QtOpenGL"}
    imported = set(
        re.findall(
            r"from PySide6\.(\w+)",
            "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src").rglob("*.py")),
        )
    )

    assert imported
    assert imported <= essentials, f"not in PySide6-Essentials: {sorted(imported - essentials)}"


def test_every_icon_size_a_desktop_wants_is_rendered() -> None:
    """**PNGs, and deliberately not only the scalable icon** (#140).

    `appstreamcli compose` — which `flatpak-builder` runs at the end of every build — cannot read
    our SVG: with it in the icon path the build fails with `file-read-error`, and with these PNGs
    and no SVG it prints `Success!`. `rsvg-convert` renders the same file without complaint, so the
    file is not at fault; a bundle that will not compose is not shippable.

    Not gated on bytes: two Qt builds may antialias differently, and a gate that fired on a Qt
    upgrade would be one people regenerate without looking. What is gated is that every size exists
    and is the size it claims.
    """
    import struct

    sys.path.insert(0, str(ROOT / "tools"))
    from render_icons import SIZES, destination

    for size in SIZES:
        path = destination(size)
        assert path.is_file(), f"{path.relative_to(ROOT)} is missing — run tools/render_icons.py"
        header = path.read_bytes()[:24]
        assert header[:8] == b"\x89PNG\r\n\x1a\n", f"{path.name} is not a PNG"
        width, height = struct.unpack(">II", header[16:24])
        assert (width, height) == (size, size), f"{path.name} is {width}x{height}"


def test_the_flatpak_installs_the_pngs_and_not_the_svg() -> None:
    """The whole of #140's fix, asserted where it would be undone: somebody tidying the manifest
    back to one `install` line for the scalable icon would break every build, and the error would
    name no file."""
    text = MANIFEST.read_text(encoding="utf-8")

    assert "packaging/icons/hicolor/" in text
    assert "scalable/apps" not in text


# ---- The version a software centre shows (#146) --------------------------------------------------


def test_the_newest_release_is_never_behind_the_version_this_tree_builds() -> None:
    """**The one version surface that is hand-typed**, and the drift that shipped v1.2.1 as 1.0.0.

    Everything else is derived from git by `hatch_version.py` and cannot drift. The metainfo's
    newest `<release>` is somebody remembering to add an entry, and when they did not the bundle
    reported `1.0.0` in `flatpak info` and in every software centre — while the wheel, the AppImage
    and the package version inside it were all correct.

    `test_the_metainfo_carries_what_a_store_needs` asserted an entry *existed* and had *a* version,
    which a stale entry satisfies. By `CLAUDE.md`'s own standard that is the worse kind of failure:
    it read as coverage.

    **Never behind, rather than exactly equal**, and the difference is the workflow this has to fit.
    A release is prepared by bumping the metainfo and the manifest in one commit and tagging that
    commit — so between the two the file legitimately names a version the tree has not been tagged
    as yet. Demanding equality here would fail every release preparation there is, which is a gate
    people would learn to work around. **Behind is the defect**; ahead is a release being cut.

    Exactness belongs at the moment it can be checked, and `release.yml`'s *The metainfo names the
    release this tag is for* is where the tag exists to compare against.
    """
    derived = _by_path("hatch_version", ROOT / "hatch_version.py").__version__
    newest = _by_path("newest_release", ROOT / "tools" / "newest_release.py").newest_release()

    assert newest is not None, "the metainfo describes no release at all"

    built = tuple(int(part) for part in derived.split(".")[:3])
    described = tuple(int(part) for part in newest.split("."))

    assert described >= built, (
        f"the metainfo's newest release is {newest} and this tree builds {derived} — a software "
        f"centre would show {newest}. Add a <release> entry, newest first."
    )


def test_the_releases_are_newest_first() -> None:
    """AppStream specifies it and every reader assumes it, including the gate above — which takes
    the first entry and would happily bless an ancient one at the top of a re-sorted file."""
    releases = ElementTree.parse(METAINFO).getroot().find("releases")
    assert releases is not None

    versions = [
        tuple(int(part) for part in (element.get("version") or "0").split("."))
        for element in releases
    ]

    assert versions == sorted(versions, reverse=True), f"not newest-first: {versions}"
