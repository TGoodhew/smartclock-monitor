"""Desktop notifications, behind a per-OS implementation with a no-op fallback.

``platform/`` is where anything that differs between desktops goes, and **nothing outside it asks
what operating system it is running on**. A caller asks for a notifier and gets one that works or
one that does nothing; there is no third case for it to handle.

**Silence is a supported outcome.** P1-10's notification area and #274's taskbar badge are Windows
shell surfaces, and whether this port grows equivalents is `docs/platform-decisions.md` D5 (issue
#6) — undecided. Until it is, a desktop that offers no way to raise a notification gets the no-op,
and the application still shows the state in its own window, which is where §9.11 puts it anyway.
A notification is a *second* channel, never the only one.

**Nothing here blocks and nothing here raises.** A notifier is called from the poll loop's
callback, so a subprocess that hangs would stall the link, and an exception would take a Qt slot
with it. The Linux implementation spawns and forgets.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Final, Protocol

#: What a notification is titled. §9.4.3.1 wants whole sentences in the body; the title names the
#: application, because a notification with no attribution is one the user cannot act on.
TITLE: Final = "SmartClock Monitor"


class Notifier(Protocol):
    """Something that can put a sentence in front of the user, or decline to."""

    def notify(self, message: str) -> bool:
        """Show it. Returns whether anything was actually shown.

        The bool is for tests and for the log, never for a caller to branch on: a caller that did
        something different when notification failed would be treating a second channel as a
        first one.
        """
        ...


class NoNotifier:
    """The fallback. Says nothing, successfully.

    Returned wherever the desktop offers no route — which includes every platform this port has not
    settled a decision for, and any Linux without a notification daemon.
    """

    def notify(self, message: str) -> bool:
        del message
        return False


class CommandNotifier:
    """Runs a command-line notifier. Linux's ``notify-send``, today.

    Spawned and forgotten: this is called from the poll loop's callback, and waiting on a
    subprocess there would stall the link behind whatever the desktop's notification daemon is
    doing.
    """

    def __init__(self, executable: str) -> None:
        self._executable = executable

    def notify(self, message: str) -> bool:
        try:
            subprocess.Popen(
                [self._executable, TITLE, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            # The binary was there a moment ago and is not now, or the desktop has no daemon
            # behind it. Neither is worth reporting: the window already says what happened.
            return False
        return True


def for_this_desktop() -> Notifier:
    """The notifier for whatever this is running on.

    Linux gets ``notify-send`` where it is installed. Windows and macOS get the no-op **and a
    reason**: their equivalents are shell integrations, which is what issue #6 has to settle, and
    guessing at one here would be making that decision by writing code rather than by deciding it.
    """
    if sys.platform.startswith("linux"):
        found = shutil.which("notify-send")
        if found is not None:
            return CommandNotifier(found)

    return NoNotifier()
