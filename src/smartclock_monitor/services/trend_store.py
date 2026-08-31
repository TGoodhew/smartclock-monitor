"""Persisted readings, so a trend outlives the process that drew it.

§10.7 asks for ranges out to seven days and §10.7.2's Allan deviation asks for the raw series
behind them. Neither survives in a ring buffer: the application is stopped and started, and the
question the Timing page answers — *is this oscillator drifting* — is about days rather than about
the current session.

**The store is not the source of truth for what is displayed now.** The live reading comes from
the poll loop; this is history. A page that has a store shows a longer window, and a page without
one still works — which is why every entry point tolerates a store that could not be opened.

Three decisions worth stating, because each is load-bearing further up:

**Windows come back columnar, in ``array``s of doubles.** §9.10.2 requires 604 800 points to be
supported, and at that size a tuple of dataclasses costs something like 70 MB where three arrays
cost 15. The decimator and the fits want contiguous numeric storage anyway.

**A missing value is NaN inside a series and ``None`` at the edges.** §11.1's rule is about what
reaches the interface, and it still holds: :meth:`Series.ti_at` hands back ``None`` and the page
renders an em dash. Inside the arrays a hole has to be a float, and NaN is the float that means
*no value* — it compares false against everything, so a fit that forgot to mask it produces
obvious nonsense rather than a plausible wrong answer, which zero would.

**Time is stored as a UTC epoch double, not as text.** The rows are compared and bucketed far more
often than they are read by a human, and a decimator that has to parse a timestamp per sample is
the whole cost of drawing the chart.
"""

from __future__ import annotations

import math
import sqlite3
from array import array
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

from smartclock_device.clock import Clock
from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_monitor.services.polling import Reading

#: Bumped when the schema changes in a way an older build cannot read. Stored in the file's own
#: ``PRAGMA user_version``, which is what SQLite provides for exactly this and costs no table.
SCHEMA_VERSION: Final = 1

#: How much history to keep. §10.7's longest range is 7 d; the margin is what lets the 7 d range
#: actually contain seven days rather than seven days minus however long ago the last prune ran,
#: and it covers §10.7.1's fit reaching slightly further back than the chart draws.
RETENTION: Final = timedelta(days=8)

#: §10.7.1: samples inside the first 24 h after a power-up are excluded from the drift fit,
#: because the loop is settling and those readings bend it. §10.8's power-up guard uses the same
#: figure, so it is named once.
SETTLING: Final = timedelta(hours=24)

#: Pruning is a scan, so it does not run on every insert. At the 1 s fast cadence this is about
#: once an hour, against a retention of eight days — the file overshoots by around a thousandth.
_PRUNE_EVERY: Final = 3600

_SCHEMA: Final = """
CREATE TABLE IF NOT EXISTS reading (
    captured_at    REAL    NOT NULL,
    ti_nanoseconds REAL,
    efc_percent    REAL,
    mode           INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS reading_by_time ON reading (captured_at);
"""


class TrendStoreError(Exception):
    """The store could not be opened or used.

    Distinct from ``sqlite3.Error`` so a caller can catch *this* and carry on without a store,
    rather than catching a database exception it would otherwise have no business knowing about.
    """


def _epoch(moment: datetime) -> float:
    """A UTC epoch double, and **a naive datetime is refused rather than assumed**.

    ``astimezone`` on a naive value does not raise — it takes it to be local time and converts.
    That would file a reading under the host's UTC offset, silently, and the error would show up
    as a trend with an hour-shaped step in it wherever the offset changed. ``Clock`` is
    timezone-aware without exception for the same reason, and this is the boundary where something
    naive could get in.
    """
    if moment.tzinfo is None:
        raise ValueError(f"{moment!r} is naive; the store stores instants, not wall-clock times.")
    return moment.astimezone(UTC).timestamp()


def _moment(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, UTC)


def _or_nan(value: float | None) -> float:
    return math.nan if value is None else float(value)


def _or_none(value: float) -> float | None:
    return None if math.isnan(value) else value


@dataclass(frozen=True, slots=True)
class Series:
    """One window of stored readings, held columnar.

    ``at`` is ascending and the three arrays are the same length; ``mode`` is parallel to them.
    Missing values are NaN — see the module docstring for why, and use :meth:`ti_at` and
    :meth:`efc_at` at any boundary where something is going to be displayed.
    """

    #: UTC epoch seconds, ascending.
    at: array[float]

    #: 1 PPS time interval, nanoseconds. NaN where the receiver did not report one.
    ti_nanoseconds: array[float]

    #: Oscillator electronic frequency control, per cent. NaN where not reported.
    efc_percent: array[float]

    #: The SmartClock mode each sample was taken in, for §10.7.1's unlocked shading.
    mode: tuple[SmartClockMode, ...]

    #: What was asked for, so a caller can say what it asked for as well as what it found.
    requested: timedelta

    def __len__(self) -> int:
        return len(self.at)

    def __bool__(self) -> bool:
        return len(self.at) > 0

    @property
    def span(self) -> timedelta:
        """From the first sample to the last — **what was found, not what was asked for**.

        §10.7's σ caption and §10.7.1's evidence line both report this rather than
        :attr:`requested`, because the application is not always running and an hour of wall clock
        routinely holds four minutes of readings.
        """
        if len(self.at) < 2:
            return timedelta(0)
        return timedelta(seconds=self.at[-1] - self.at[0])

    @property
    def start(self) -> datetime | None:
        return _moment(self.at[0]) if self.at else None

    @property
    def end(self) -> datetime | None:
        return _moment(self.at[-1]) if self.at else None

    def moment_at(self, index: int) -> datetime:
        return _moment(self.at[index])

    def ti_at(self, index: int) -> float | None:
        """The §11.1 boundary: NaN becomes ``None`` and the page renders an em dash."""
        return _or_none(self.ti_nanoseconds[index])

    def efc_at(self, index: int) -> float | None:
        return _or_none(self.efc_percent[index])


#: A window with nothing in it. Returned rather than ``None`` so every caller takes one code path;
#: a chart with no data draws its empty state, and ``len()`` is how it finds out.
def empty_series(requested: timedelta = timedelta(0)) -> Series:
    return Series(
        at=array("d"),
        ti_nanoseconds=array("d"),
        efc_percent=array("d"),
        mode=(),
        requested=requested,
    )


class TrendStore:
    """Readings on disk, and the windows the Timing page reads back.

    Not a singleton and not module state — §12's rule about the session applies here for the same
    reason. A second receiver gets a second store.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        clock: Clock,
        *,
        retention: timedelta = RETENTION,
    ) -> None:
        self._connection = connection
        self._clock = clock
        self._retention = retention
        self._since_prune = 0

    # -- Opening ---------------------------------------------------------------------------------

    @classmethod
    def open(
        cls,
        path: Path | str,
        clock: Clock,
        *,
        retention: timedelta = RETENTION,
    ) -> TrendStore:
        """Open or create the store at ``path``.

        Raises :class:`TrendStoreError` rather than letting a ``sqlite3.Error`` out, so the caller
        can decide to run without history — which it must be able to do, because a read-only home
        directory or a file written by a newer build are both ordinary and neither is a reason to
        refuse to monitor a receiver.
        """
        target = Path(path)
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(target, isolation_level=None)
        except (OSError, sqlite3.Error) as error:
            raise TrendStoreError(f"{target} could not be opened: {error}") from error

        try:
            cls._prepare(connection)
        except sqlite3.Error as error:
            connection.close()
            raise TrendStoreError(f"{target} is not a usable trend store: {error}") from error

        return cls(connection, clock, retention=retention)

    @classmethod
    def in_memory(cls, clock: Clock, *, retention: timedelta = RETENTION) -> TrendStore:
        """A store that is never written to disk. For tests, and for a run told not to persist."""
        connection = sqlite3.connect(":memory:", isolation_level=None)
        cls._prepare(connection)
        return cls(connection, clock, retention=retention)

    @staticmethod
    def _prepare(connection: sqlite3.Connection) -> None:
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version > SCHEMA_VERSION:
            # Refuse rather than migrate downwards. A newer build's file may have columns this one
            # would drop on the next write, and silently discarding a week of somebody's history
            # is worse than running without a chart.
            raise sqlite3.DatabaseError(
                f"schema version {version} was written by a newer build "
                f"(this one reads {SCHEMA_VERSION})"
            )

        # WAL so a read for the chart does not block the poll loop's insert, and NORMAL because
        # losing the last second of a trend to a power cut costs a pixel.
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.executescript(_SCHEMA)
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        self._connection.close()

    @contextmanager
    def _guarded(self) -> Iterator[sqlite3.Connection]:
        try:
            yield self._connection
        except sqlite3.Error as error:
            raise TrendStoreError(str(error)) from error

    # -- Writing ---------------------------------------------------------------------------------

    def append(self, reading: Reading) -> None:
        """Store one reading.

        Every reading, including one whose TI and EFC are both missing: the *times* are data. A
        gap in the record means the application was not running, and §10.7.2's estimator pairs
        samples by their recorded times precisely so it can tell that from a quiet receiver.
        """
        status = reading.status
        # ``reading.captured_at`` rather than ``status.captured_at``: the fast tier refreshes the
        # 1 PPS interval once a second into a status object that keeps the timestamp of the last
        # full screen, so the status's own time would file ten readings under one instant. Found
        # against the real receiver, where fifteen stored rows shared a single timestamp.
        taken = reading.captured_at or status.captured_at
        with self._guarded() as connection:
            connection.execute(
                "INSERT INTO reading (captured_at, ti_nanoseconds, efc_percent, mode)"
                " VALUES (?, ?, ?, ?)",
                (
                    _epoch(taken),
                    status.one_pps_ti_nanoseconds,
                    reading.efc_percent,
                    status.mode.value,
                ),
            )

        self._since_prune += 1
        if self._since_prune >= _PRUNE_EVERY:
            self.prune()

    def prune(self) -> int:
        """Drop everything older than the retention window. Returns how many rows went."""
        self._since_prune = 0
        cutoff = _epoch(self._clock.utc_now() - self._retention)
        with self._guarded() as connection:
            cursor = connection.execute("DELETE FROM reading WHERE captured_at < ?", (cutoff,))
        return cursor.rowcount if cursor.rowcount > 0 else 0

    # -- Reading ---------------------------------------------------------------------------------

    def window(self, span: timedelta, *, ending: datetime | None = None) -> Series:
        """The readings from ``ending - span`` to ``ending``, oldest first.

        ``ending`` defaults to now, and is a parameter because §10.7.1's fit reaches slightly
        further back than the chart draws and a test has to be able to ask for a fixed window.
        """
        end = self._clock.utc_now() if ending is None else ending
        return self.between(end - span, end, requested=span)

    def between(
        self,
        start: datetime,
        end: datetime,
        *,
        requested: timedelta | None = None,
    ) -> Series:
        """Every reading in ``[start, end]``, oldest first."""
        at = array("d")
        ti = array("d")
        efc = array("d")
        modes: list[SmartClockMode] = []

        with self._guarded() as connection:
            rows = connection.execute(
                "SELECT captured_at, ti_nanoseconds, efc_percent, mode FROM reading"
                " WHERE captured_at BETWEEN ? AND ? ORDER BY captured_at",
                (_epoch(start), _epoch(end)),
            )
            for captured_at, ti_value, efc_value, mode in rows:
                at.append(captured_at)
                ti.append(_or_nan(ti_value))
                efc.append(_or_nan(efc_value))
                modes.append(_mode_of(mode))

        return Series(
            at=at,
            ti_nanoseconds=ti,
            efc_percent=efc,
            mode=tuple(modes),
            requested=end - start if requested is None else requested,
        )

    def count(self) -> int:
        with self._guarded() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM reading").fetchone()[0])

    def earliest(self) -> datetime | None:
        """When the record starts, or ``None`` if nothing is stored."""
        with self._guarded() as connection:
            row = connection.execute("SELECT MIN(captured_at) FROM reading").fetchone()
        return None if row[0] is None else _moment(row[0])

    def last_power_up(self, before: datetime) -> datetime | None:
        """The most recent sample at or before ``before`` taken in power-up mode.

        §10.7.1 excludes the first 24 h after a power-up from the drift fit, and a window that
        begins after the warm-up ended would otherwise show no sign one had happened. Answered by
        an indexed query rather than by widening the window, because the lead-in needed is a day
        and the window may be an hour.

        **Anchored on the end of the warm-up rather than its start**, which is the conservative
        reading: it excludes slightly more. The two differ by however long the receiver reported
        power-up mode — minutes, against a 24 h exclusion.
        """
        with self._guarded() as connection:
            row = connection.execute(
                "SELECT MAX(captured_at) FROM reading WHERE mode = ? AND captured_at <= ?",
                (SmartClockMode.POWER_UP.value, _epoch(before)),
            ).fetchone()
        return None if row[0] is None else _moment(row[0])


def _mode_of(value: int) -> SmartClockMode:
    """A stored mode that is not one of ours becomes UNKNOWN.

    §11.1's discipline extends to reading our own file back: a row written by a build with a mode
    this one does not have is a value to be handled, not a reason to lose the window around it.
    """
    try:
        return SmartClockMode(value)
    except ValueError:
        return SmartClockMode.UNKNOWN
