"""#127's application log: what *this* application saw.

Distinct from the receiver's own diagnostic log, and §10.9 carries both cards because the two
answer different questions. "Did the receiver drop out" and "did we lose the port" look identical
from the outside and have completely different fixes.

**#127 is a warning about exactly this gap.** In the original, `ILogger` was injected into the
transport, the protocol, the session and the poller, and real instrumentation existed — and nothing
registered a provider, so every call site resolved to `NullLogger`. The feature was fully wired and
wrote nothing. A card that names a folder and a writer that never runs is the same defect wearing a
different hat, which is why this landed in the same change as the card.

**Only what §10.9 names, and only on change.** The port opening, the settings auto-detect settled
on, every connection change, and the receiver's mode and satellite count *whenever they move*. A
line per poll would put a megabyte on disk every few hours and bury the four events that matter.

**Timestamps come from the system clock, not the injected one**, and that is deliberate rather than
an oversight of the §7.4 rule. A log records when *this application* observed something; the
injected clock exists so a fixture captured in 2026 parses the same way in 2031, and a log written
against a pinned clock would date every line to the fixture.
"""

from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from typing import Final

from smartclock_monitor.platform.paths import log_directory
from smartclock_monitor.services.polling import Reading

#: The one logger this application writes through.
LOGGER_NAME: Final = "smartclock"

#: #127's own figures: roll at 1 MB, keep four rolled files.
MAXIMUM_BYTES: Final = 1_000_000
KEPT_FILES: Final = 4

LOG_FILE: Final = "smartclock.log"


def configure(directory: Path | None = None) -> Path | None:
    """Start writing. Returns the file, or ``None`` if it could not be opened.

    **A log that cannot be written is not an error worth stopping for.** A read-only home
    directory is ordinary, and refusing to monitor a receiver because a diagnostic file would not
    open would be the tail wagging the dog — the same argument the trend store makes.

    Idempotent: called twice, it does not stack handlers. Qt applications get restarted inside a
    process more often than one expects, and a doubled handler writes every line twice, which is
    the kind of thing nobody notices until they are reading the log for something else.
    """
    target = (log_directory() if directory is None else directory) / LOG_FILE
    logger = logging.getLogger(LOGGER_NAME)

    for existing in list(logger.handlers):
        if isinstance(existing, logging.handlers.RotatingFileHandler):
            return Path(existing.baseFilename)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            target, maxBytes=MAXIMUM_BYTES, backupCount=KEPT_FILES, encoding="utf-8"
        )
    except OSError:
        return None

    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-8s %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    )
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    # Not propagated: the root logger may have a handler that prints to the console, and a serial
    # monitor writing to stdout is a monitor whose output cannot be piped anywhere useful.
    logger.propagate = False
    return target


def log() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


class ChangeLog:
    """Writes the four things §10.9 names, and nothing else.

    Holds the last mode and count so it can write **only when they move**. Stateful for that one
    reason: the alternative is a line per second, and a log that has to be filtered before it can
    be read is one nobody reads.
    """

    def __init__(self) -> None:
        self._mode: str | None = None
        self._tracked: int | None = None

    def opened(self, port: str, settings: object) -> None:
        log().info("Opened %s at %s.", port, settings)

    def detected(self, settings: object, attempts: int) -> None:
        """What the auto-detect walk settled on, and how far in.

        The attempt number is logged because "found on the first" and "found on the eighth" are
        the difference between a working default and a lucky guess — and it is the figure §7.1's
        ordering is argued from.
        """
        log().info("Auto-detect settled on %s, on attempt %d.", settings, attempts)

    def connected(self, description: str, model: str | None) -> None:
        log().info("Connected to %s on %s.", model or "an unidentified receiver", description)

    def disconnected(self, reason: str) -> None:
        log().warning("Disconnected: %s", reason)

    def observed(self, reading: Reading) -> None:
        """The receiver's mode and satellite count, **whenever they move**."""
        mode = reading.status.mode.name
        tracked = reading.tracked_count

        if mode == self._mode and tracked == self._tracked:
            return

        if self._mode is None:
            log().info("Receiver is %s, tracking %s.", mode, _count(tracked))
        elif mode != self._mode:
            log().info(
                "Receiver went from %s to %s, tracking %s.", self._mode, mode, _count(tracked)
            )
        else:
            log().info("Tracking %s (was %s).", _count(tracked), _count(self._tracked))

        self._mode = mode
        self._tracked = tracked


def _count(tracked: int | None) -> str:
    """§11.1 in a log line too: an unread count is not zero satellites."""
    if tracked is None:
        return "an unreported number of satellites"
    return f"{tracked} satellite{'' if tracked == 1 else 's'}"
