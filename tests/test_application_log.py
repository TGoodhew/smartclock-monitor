"""#127's application log.

**#127 is a warning about exactly the gap this closes.** In the original, `ILogger` was injected
into the transport, the protocol, the session and the poller, real instrumentation existed — and
nothing registered a provider, so every call site resolved to `NullLogger`. The feature was fully
wired and wrote nothing.

A card that names a folder and a writer that never runs is the same defect wearing a different hat,
which is why these tests assert that lines actually reach a file.
"""

from __future__ import annotations

import logging
import logging.handlers
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import NOW
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_monitor.services import logging as app_log
from smartclock_monitor.services.polling import Reading


@pytest.fixture(autouse=True)
def _clean_logger() -> None:
    """Each test starts with no handlers, so one does not read another's file."""
    logger = logging.getLogger(app_log.LOGGER_NAME)
    for handler in list(logger.handlers):
        handler.close()
        logger.removeHandler(handler)


def reading(mode: SmartClockMode = SmartClockMode.LOCKED, tracked: int | None = 8) -> Reading:
    return Reading(
        status=ReceiverStatus(captured_at=NOW, mode=mode),
        captured_at=NOW + timedelta(seconds=1),
        tracked_count=tracked,
    )


def _file_handlers() -> list[logging.handlers.RotatingFileHandler]:
    """Ours, not pytest's. The runner attaches a capture handler to every logger it touches."""
    return [
        handler
        for handler in logging.getLogger(app_log.LOGGER_NAME).handlers
        if isinstance(handler, logging.handlers.RotatingFileHandler)
    ]


def written(path: Path) -> str:
    for handler in logging.getLogger(app_log.LOGGER_NAME).handlers:
        handler.flush()
    return path.read_text(encoding="utf-8")


# ---- That it writes at all -----------------------------------------------------------------------


def test_configuring_produces_a_file_that_is_written_to(tmp_path: Path) -> None:
    """The assertion #127 exists for. Everything else here is about *what* is written."""
    path = app_log.configure(tmp_path)

    assert path is not None
    app_log.log().info("a line")

    assert "a line" in written(path)


def test_configuring_twice_does_not_double_every_line(tmp_path: Path) -> None:
    """Qt applications get restarted inside a process more often than one expects, and a doubled
    handler writes everything twice — which nobody notices until they are reading the log for
    something else."""
    first = app_log.configure(tmp_path)
    second = app_log.configure(tmp_path)

    assert first == second
    # Counted by *type*, not by length: pytest attaches its own capture handler to every logger,
    # so "there is exactly one handler" is a fact about the test runner rather than about this.
    assert len(_file_handlers()) == 1

    app_log.log().info("once")
    assert first is not None
    assert written(first).count("once") == 1


def test_a_folder_that_cannot_be_written_is_not_fatal(tmp_path: Path) -> None:
    """A read-only home directory is ordinary, and refusing to monitor a receiver because a
    diagnostic file would not open would be the tail wagging the dog."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")

    assert app_log.configure(blocker / "sub") is None


def test_it_rolls_at_a_megabyte_keeping_four(tmp_path: Path) -> None:
    """#127's own figures."""
    app_log.configure(tmp_path)
    handler = _file_handlers()[0]

    assert handler.maxBytes == 1_000_000
    assert handler.backupCount == 4


def test_it_does_not_print_to_the_console(tmp_path: Path) -> None:
    """A serial monitor writing to stdout is one whose output cannot be piped anywhere useful."""
    app_log.configure(tmp_path)

    assert logging.getLogger(app_log.LOGGER_NAME).propagate is False


# ---- What it writes ------------------------------------------------------------------------------


def test_the_four_events_section_10_9_names(tmp_path: Path) -> None:
    path = app_log.configure(tmp_path)
    assert path is not None
    changes = app_log.ChangeLog()

    changes.opened("/dev/ttyUSB0", "9600-8-N-1")
    changes.detected("19200-7-O-1", 2)
    changes.connected("/dev/ttyUSB0 @ 9600-8-N-1", "Z3805A")
    changes.observed(reading())
    changes.disconnected("the link went")

    text = written(path)
    assert "Opened /dev/ttyUSB0" in text
    assert "Auto-detect settled on 19200-7-O-1, on attempt 2" in text
    assert "Connected to Z3805A" in text
    assert "LOCKED" in text
    assert "Disconnected" in text


def test_the_attempt_number_is_logged(tmp_path: Path) -> None:
    """ "Found on the first" and "found on the eighth" are the difference between a working default
    and a lucky guess — and it is the figure §7.1's ordering is argued from."""
    path = app_log.configure(tmp_path)
    assert path is not None

    app_log.ChangeLog().detected("9600-7-O-1", 8)

    assert "on attempt 8" in written(path)


def test_nothing_is_written_while_nothing_moves(tmp_path: Path) -> None:
    """**Only on change.** A line per poll would put a megabyte on disk every few hours and bury
    the four events that matter."""
    path = app_log.configure(tmp_path)
    assert path is not None
    changes = app_log.ChangeLog()

    changes.observed(reading())
    before = written(path)
    for _ in range(200):
        changes.observed(reading())

    assert written(path) == before


def test_a_mode_change_is_written(tmp_path: Path) -> None:
    path = app_log.configure(tmp_path)
    assert path is not None
    changes = app_log.ChangeLog()

    changes.observed(reading(SmartClockMode.LOCKED))
    changes.observed(reading(SmartClockMode.HOLDOVER))

    assert "went from LOCKED to HOLDOVER" in written(path)


def test_a_satellite_count_change_is_written(tmp_path: Path) -> None:
    path = app_log.configure(tmp_path)
    assert path is not None
    changes = app_log.ChangeLog()

    changes.observed(reading(tracked=8))
    changes.observed(reading(tracked=7))

    assert "Tracking 7 satellites (was 8 satellites)" in written(path)


def test_an_unreported_count_is_not_logged_as_zero(tmp_path: Path) -> None:
    """§11.1 holds in a log line too. Observed on the real receiver: the first reading arrives
    before the fast tier has answered, and "0 satellites" would be a claim about the sky."""
    path = app_log.configure(tmp_path)
    assert path is not None

    app_log.ChangeLog().observed(reading(tracked=None))

    text = written(path)
    assert "unreported number of satellites" in text
    assert "0 satellites" not in text


def test_one_satellite_is_not_pluralised(tmp_path: Path) -> None:
    path = app_log.configure(tmp_path)
    assert path is not None

    app_log.ChangeLog().observed(reading(tracked=1))

    assert "1 satellite," in written(path) or "1 satellite." in written(path)
