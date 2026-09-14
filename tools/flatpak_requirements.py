"""Pin the wheels the Flatpak installs, with their hashes, so the build needs no network.

**`flatpak-builder` builds offline**, deliberately: a manifest that fetched whatever PyPI served
that morning would not be reproducible, and Flathub rejects one. Every file a build downloads is
declared with a `sha256` up front, and this writes those declarations.

    python tools/flatpak_requirements.py            # rewrite packaging/flatpak/python3-modules.yml
    python tools/flatpak_requirements.py --check    # fail if it is out of date

**The versions here are the versions this repository tests against**, and
`tests/test_packaging.py` asserts they match what is installed — so a dependency bump that forgets
the Flatpak fails the suite rather than shipping a bundle nobody built from the tested wheels.

**Only the Essentials wheel, not the metapackage.** The application imports `QtCore`, `QtGui` and
`QtWidgets` and nothing else, and all three are in `PySide6-Essentials` — 80 MB against the
metapackage's several hundred, with the same binaries for everything used. The gate that keeps that
true is in `tests/test_packaging.py`: an import from Addons would work in CI and fail in the
Flatpak, which is the worst way round for a defect to be discovered.

The wheels are `cp310-abi3`, so they run on any Python from 3.10 up and the runtime's own version
does not enter into it.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Final

#: Where the generated module list lands.
_FLATPAK: Final = Path(__file__).resolve().parent.parent / "packaging" / "flatpak"

#: Where the generated module lists land.
DESTINATION: Final = _FLATPAK / "python3-modules.yml"
BACKEND_DESTINATION: Final = _FLATPAK / "python3-build-backend.yml"

#: What the Flatpak installs **into the bundle**, pinned to what CI tests.
#:
#: `shiboken6` first because PySide6 imports it at load; the two pure-Python serial packages last,
#: because they are small and depend on nothing.
#:
#: **Every runtime dependency in `pyproject.toml` must appear here**, and
#: `test_the_flatpak_pins_every_runtime_dependency` is what says so. It did not, once: v1.2.1
#: shipped without `qasync` and could not reach its own event loop, while every gate stayed green
#: because each of them only ever looked at what this tuple already named (#144).
PINNED: Final[tuple[tuple[str, str], ...]] = (
    ("shiboken6", "6.11.2"),
    ("PySide6_Essentials", "6.11.2"),
    ("qasync", "0.28.0"),
    ("pyserial", "3.5"),
    ("pyserial-asyncio", "0.6"),
)

#: The one dependency whose distribution name is not what the bundle installs.
#:
#: `pyproject.toml` asks for `PySide6`; the Flatpak installs `PySide6-Essentials`, which carries the
#: same binaries for every module this application imports at a fraction of the size. The
#: substitution is deliberate, and the Qt-module gate in `test_packaging.py` is what keeps it safe,
#: so the coverage gate is told about it rather than tripping over it.
SUBSTITUTED: Final[dict[str, str]] = {"pyside6": "pyside6-essentials"}

#: What builds the wheel, and is **not** installed into the bundle.
#:
#: `hatchling` is the backend `pyproject.toml` names, and the rest are its own dependencies —
#: declared rather than resolved, because a build with no network cannot resolve anything. They go
#: to a directory of their own, so a build tool never ships beside the application.
BACKEND: Final[tuple[tuple[str, str], ...]] = (
    ("hatchling", "1.32.0"),
    ("packaging", "26.3"),
    ("pathspec", "1.1.1"),
    ("pluggy", "1.6.0"),
    ("tomlkit", "0.15.1"),
    ("trove-classifiers", "2026.6.1.19"),
)

#: Where the build backend goes.
#:
#: **Inside the prefix, and deleted from the finished bundle by the manifest's `cleanup`.** It was
#: `/tmp/backend` first, which failed: flatpak-builder gives each module its own build context, so
#: a directory one module writes outside the prefix is gone by the time the next one looks for it —
#: the app module failed with *"Cannot import \'hatchling.build\'"* against a backend that had
#: been installed and discarded.
#:
#: Free of a Python version, so the runtime\'s own never enters into it: the wheels are
#: `py3-none-any` and the interpreter reads them from `PYTHONPATH`.
BACKEND_PREFIX: Final = "${FLATPAK_DEST}/lib/build-backend"

#: The platform the wheels must run on. `manylinux_2_34` needs glibc 2.34 or later, which every
#: runtime this manifest targets has; a pure-Python wheel carries `none-any` instead.
_LINUX: Final = ("manylinux", "none-any")


def wheel_for(name: str, version: str) -> tuple[str, str]:
    """The Linux wheel's URL and hash, from PyPI's own metadata."""
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=60) as response:
        payload = json.load(response)

    for entry in payload["urls"]:
        filename = str(entry["filename"])
        if not filename.endswith(".whl"):
            continue
        if "manylinux" in filename and "x86_64" not in filename:
            continue
        if any(marker in filename for marker in _LINUX):
            return str(entry["url"]), str(entry["digests"]["sha256"])

    raise SystemExit(f"No Linux wheel for {name} {version}.")


_HEADER: Final = (
    "# Generated by tools/flatpak_requirements.py. Do not edit by hand.",
    "#",
    "# flatpak-builder builds offline, so every wheel is declared with its hash. The versions are",
    "# the ones this repository tests against, and tests/test_packaging.py asserts they still",
    "# match what is installed.",
)


def render(name: str, pins: tuple[tuple[str, str], ...], destination: str) -> str:
    """One module, installing `pins` into `destination`."""
    into = (
        f"--prefix={destination}"
        if destination.endswith("FLATPAK_DEST}")
        else f"--target={destination}"
    )
    lines = [
        *_HEADER,
        f"name: {name}",
        "buildsystem: simple",
        "build-commands:",
        '  - pip3 install --verbose --exists-action=i --no-index --find-links="file://${PWD}"',
        f"    --no-build-isolation {into}",
        *(f"    {package}" for package, _ in pins),
        "sources:",
    ]
    for package, version in pins:
        url, digest = wheel_for(package, version)
        lines += ["  - type: file", f"    url: {url}", f"    sha256: {digest}"]
    return "\n".join(lines) + "\n"


def generated() -> dict[Path, str]:
    """Every file this tool owns, against what it should contain."""
    return {
        DESTINATION: render("python3-dependencies", PINNED, "${FLATPAK_DEST}"),
        BACKEND_DESTINATION: render("python3-build-backend", BACKEND, BACKEND_PREFIX),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="fail if a generated file is out of date"
    )
    arguments = parser.parse_args(argv)

    wanted = generated()
    if not arguments.check:
        for path, text in wanted.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            print(f"{path.name}: written")
        return 0

    stale = [
        path.name
        for path, text in wanted.items()
        if not path.exists() or path.read_text(encoding="utf-8") != text
    ]
    if not stale:
        return 0
    print(f"out of date, re-run without --check: {', '.join(stale)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
