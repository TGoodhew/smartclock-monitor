"""Where this application keeps its own files, per desktop.

``platform/`` is where anything that differs between desktops goes, and nothing outside it should
ask what operating system it is running on — so the rest of the codebase asks for a path and gets
one, rather than branching on ``sys.platform`` at the point of use.

**The environment variables win where they are set.** ``XDG_DATA_HOME`` on Linux and ``APPDATA`` on
Windows are the documented ways for a user or a sandbox to say where an application's data belongs,
and honouring them is what makes the application behave under Flatpak, under a roaming profile, and
under a test that wants to point it somewhere else.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final

#: The directory name, used under whichever base the platform gives.
APPLICATION_DIRECTORY: Final = "smartclock-monitor"

#: What the trend store is called inside it.
TREND_DATABASE: Final = "trend.db"


def data_directory(environment: dict[str, str] | None = None) -> Path:
    """Where per-user application data belongs on this desktop.

    Takes the environment as an argument so a test can assert each platform's answer without
    setting process-wide variables — the same reason the clock is injected.
    """
    env = os.environ if environment is None else environment

    if sys.platform == "win32":
        base = env.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Roaming"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support"
    else:
        base = env.get("XDG_DATA_HOME")
        root = Path(base) if base else Path.home() / ".local" / "share"

    return root / APPLICATION_DIRECTORY


def trend_database(environment: dict[str, str] | None = None) -> Path:
    """The default path for the trend store."""
    return data_directory(environment) / TREND_DATABASE
