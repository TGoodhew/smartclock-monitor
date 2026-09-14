"""Print the newest ``<release version>`` in the AppStream metainfo, and nothing else.

**The version a software centre shows.** `flatpak info`, GNOME Software and Flathub all read the
first entry of `<releases>`, and it is hand-typed — so v1.2.1 shipped reporting `1.0.0` because
somebody added a tag and not a release entry (#146). Everything else about a build's version is
derived from git by `hatch_version.py` and cannot drift; this one could, and did.

Used by the release workflow to refuse a release whose metainfo names a different version, and by
`tests/test_packaging.py` to hold the checked-in file to the tag it was cut from.

**Newest first is the file's own order**, which is what AppStream specifies and what every reader
assumes; `test_packaging.py` checks that separately, so this does not re-sort and hide a file that
has them the wrong way round.
"""

from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree

METAINFO = (
    Path(__file__).resolve().parent.parent
    / "packaging"
    / "io.github.tgoodhew.SmartClockMonitor.metainfo.xml"
)


def newest_release() -> str | None:
    """The first ``<release>``'s version, or ``None`` where there is none to read."""
    releases = ElementTree.parse(METAINFO).getroot().find("releases")
    if releases is None or not len(releases):
        return None
    return releases[0].get("version")


def main() -> int:
    version = newest_release()
    if version is None:
        print("the metainfo describes no release at all", file=sys.stderr)
        return 1
    print(version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
