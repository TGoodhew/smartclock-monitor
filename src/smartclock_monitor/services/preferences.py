"""§10.13's preferences. **They fail safe and they fail silent.**

Two rules from §10.13, and both are about what happens when the file is wrong rather than when it is
right:

**A file that is missing, truncated or unreadable reads as the defaults**, and the default for
anything advanced is *off*. A store that failed *open* would enable an advanced surface because a
disk went wrong — which is the wrong direction for a failure to point.

**A write that fails is not reported.** A preference is by definition something the user can set
again, and nothing load-bearing may live in one of these files. An error dialog because a setting
could not be saved would be interrupting the user about the least important thing on screen.

**Three preferences were removed with D5** (issue #6): the lock-loss alert, keep-running-when-closed
and start-in-the-notification-area. Each of them could only ever be honoured by a tray or a desktop
notifier, and this port ships neither — a switch that cannot do what it says is worse than an absent
one, because the user sets it and believes it.

**Opting in changes what is reachable, never what is permitted.** No preference here may add a
command, and none may relax a §8.3 confirmation. The Advanced Console is a picker over the same §8.1
allowlist every other page uses, so enabling it adds nothing the application could not already send;
the §8.4 exclusions are absent from the catalog and therefore absent from the console, opted in or
not. ``test_preferences.py`` asserts that no field here is capable of changing either.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any, Final

from smartclock_monitor.platform.paths import data_directory

#: What the preferences file is called inside the per-desktop data directory.
PREFERENCES_FILE: Final = "preferences.json"


@dataclass(frozen=True, slots=True)
class Preferences:
    """Every preference, with §10.13's defaults.

    Frozen: a preference change produces a new value rather than mutating one somebody else is
    holding, so a page cannot be looking at a half-applied set.
    """

    #: §10.11's console. Off — it reveals a surface a user has to go looking for.
    advanced_console: bool = False

    #: §8.5's queries. Off for the same reason, and §8.5 says so itself: they may return errors or
    #: nonsense, and a user who has not asked for them should not meet them.
    undocumented_queries: bool = False

    #: P1-6. Off, because a window that outranks everything else is a decision about the *desktop*
    #: rather than about this application, and §9.1's user has a spectrum analyser to look at too.
    always_on_top: bool = False


DEFAULTS: Final = Preferences()


def preferences_path(directory: Path | None = None) -> Path:
    return (data_directory() if directory is None else directory) / PREFERENCES_FILE


def load(path: Path | None = None) -> Preferences:
    """Read the preferences, or the defaults if anything at all is wrong.

    **Every failure takes the same branch**, deliberately: a missing file, a directory where a file
    should be, invalid JSON, a JSON value that is not an object, an unknown key, a value of the
    wrong type. Distinguishing them would produce a diagnostic nobody can act on for a file whose
    entire contents are re-settable from the Settings page.
    """
    target = preferences_path() if path is None else path

    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return DEFAULTS

    if not isinstance(raw, dict):
        return DEFAULTS

    known = {field.name for field in fields(Preferences)}
    values: dict[str, Any] = {}
    for name, value in raw.items():
        # An unknown key is ignored rather than rejected: a file written by a later build should
        # not cost this one every preference in it.
        if name in known and isinstance(value, bool):
            values[name] = value

    return replace(DEFAULTS, **values)


def save(preferences: Preferences, path: Path | None = None) -> bool:
    """Write them. Returns whether it worked, and **no caller is required to care**.

    The bool is there for the tests rather than for the interface: §10.13 says a failed write is
    not reported, and a caller that raised a dialog over one would be interrupting the user about
    the least important thing on screen.
    """
    target = preferences_path() if path is None else path

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(asdict(preferences), indent=2) + "\n", encoding="utf-8")
    except (OSError, TypeError, ValueError):
        return False
    return True
