"""The persisted trend store.

Every test here pins the clock. The store's retention, its windows and its power-up lookback are
all clock-dependent, and a suite that used the real one would pass in August and start failing
whenever somebody ran it eight days later.
"""

from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.trend_store import (
    RETENTION,
    SCHEMA_VERSION,
    Series,
    TrendStore,
    TrendStoreError,
    empty_series,
)


def reading(
    at: datetime,
    *,
    ti: float | None = -33.1,
    efc: float | None = -16.8,
    mode: SmartClockMode = SmartClockMode.LOCKED,
) -> Reading:
    return Reading(
        status=ReceiverStatus(captured_at=at, mode=mode, one_pps_ti_nanoseconds=ti),
        efc_percent=efc,
    )


def store_with(
    clock: FixedClock, count: int, *, step: timedelta = timedelta(seconds=1), **kwargs: object
) -> TrendStore:
    """``count`` readings ending at the clock's now, one every ``step``."""
    store = TrendStore.in_memory(clock)
    start = clock.utc_now() - step * (count - 1)
    for index in range(count):
        store.append(reading(start + step * index, **kwargs))  # type: ignore[arg-type]
    return store


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


# ---- Round-tripping -----------------------------------------------------------------------------


def test_a_reading_comes_back_as_it_went_in(clock: FixedClock) -> None:
    store = TrendStore.in_memory(clock)
    store.append(reading(NOW, ti=-33.1, efc=-16.8557, mode=SmartClockMode.HOLDOVER))

    series = store.window(timedelta(hours=1))

    assert len(series) == 1
    assert series.moment_at(0) == NOW
    assert series.ti_at(0) == pytest.approx(-33.1)
    assert series.efc_at(0) == pytest.approx(-16.8557)
    assert series.mode[0] is SmartClockMode.HOLDOVER


def test_readings_come_back_oldest_first_whatever_order_they_arrived(clock: FixedClock) -> None:
    """The charts assume ascending time and so does every fit. Insertion order is not guaranteed
    to be time order — a reconnect can deliver a status captured before the last one."""
    store = TrendStore.in_memory(clock)
    for offset in (0, -30, -10, -20):
        store.append(reading(NOW + timedelta(seconds=offset)))

    series = store.window(timedelta(hours=1))

    assert list(series.at) == sorted(series.at)
    assert series.span == timedelta(seconds=30)


def test_a_missing_value_is_nan_inside_and_none_at_the_edge(clock: FixedClock) -> None:
    """§11.1: an unparseable field is ``None`` on the model and renders as an em dash. Inside the
    arrays a hole has to be a float, and it must be NaN rather than zero — a zeroed 1 PPS reading
    is a *measurement*, and one that says the receiver is perfect."""
    store = TrendStore.in_memory(clock)
    store.append(reading(NOW, ti=None, efc=None))

    series = store.window(timedelta(hours=1))

    assert math.isnan(series.ti_nanoseconds[0])
    assert math.isnan(series.efc_percent[0])
    assert series.ti_at(0) is None
    assert series.efc_at(0) is None


def test_a_reading_with_nothing_in_it_is_still_stored(clock: FixedClock) -> None:
    """The *times* are data. §10.7.2's estimator pairs samples by their recorded times so that a
    gap contributes nothing; dropping empty rows would turn "the receiver said nothing for ten
    minutes" into "these two samples are adjacent seconds"."""
    store = TrendStore.in_memory(clock)
    store.append(reading(NOW, ti=None, efc=None))

    assert store.count() == 1


def test_a_mode_this_build_does_not_know_becomes_unknown(clock: FixedClock) -> None:
    """§11.1's discipline applied to reading our own file back. A row written by a later build is
    a value to handle, not a reason to lose the window around it."""
    store = TrendStore.in_memory(clock)
    store.append(reading(NOW))
    store._connection.execute("UPDATE reading SET mode = 99")

    series = store.window(timedelta(hours=1))

    assert series.mode[0] is SmartClockMode.UNKNOWN
    assert len(series) == 1


# ---- Windows ------------------------------------------------------------------------------------


def test_a_window_holds_only_what_falls_inside_it(clock: FixedClock) -> None:
    store = TrendStore.in_memory(clock)
    for minutes in (0, 30, 90, 200):
        store.append(reading(NOW - timedelta(minutes=minutes)))

    assert len(store.window(timedelta(hours=1))) == 2
    assert len(store.window(timedelta(hours=2))) == 3
    assert len(store.window(timedelta(hours=4))) == 4


def test_span_reports_what_was_found_and_requested_what_was_asked(clock: FixedClock) -> None:
    """§10.7's σ caption and §10.7.1's evidence line are explicit about this: the application is
    not always running, so an hour of wall clock routinely holds four minutes of readings, and a
    caption naming the range rather than the span would overstate its evidence."""
    store = store_with(clock, 240)  # four minutes at 1 s

    series = store.window(timedelta(hours=1))

    assert series.requested == timedelta(hours=1)
    assert series.span == timedelta(seconds=239)


def test_an_empty_window_is_a_series_rather_than_none(clock: FixedClock) -> None:
    """One code path for the caller. A chart with no data draws its empty state and finds out by
    asking ``len()``, not by testing for ``None`` at four call sites."""
    store = TrendStore.in_memory(clock)

    series = store.window(timedelta(hours=1))

    assert isinstance(series, Series)
    assert len(series) == 0
    assert not series
    assert series.span == timedelta(0)
    assert series.start is None and series.end is None


def test_a_single_sample_has_no_span(clock: FixedClock) -> None:
    """One reading is not a window. Reporting its span as anything but zero would let a σ over a
    single sample claim an hour of evidence."""
    store = TrendStore.in_memory(clock)
    store.append(reading(NOW))

    assert store.window(timedelta(hours=1)).span == timedelta(0)


def test_the_empty_series_helper_matches_a_real_empty_window(clock: FixedClock) -> None:
    """Used where a caller has no store at all, so it must behave identically to one with no rows
    — otherwise "no store" and "no data yet" are two different bugs."""
    store = TrendStore.in_memory(clock)
    real = store.window(timedelta(hours=1))
    stand_in = empty_series(timedelta(hours=1))

    assert len(stand_in) == len(real)
    assert stand_in.span == real.span
    assert stand_in.requested == real.requested
    assert bool(stand_in) is bool(real)


def test_a_window_can_end_somewhere_other_than_now(clock: FixedClock) -> None:
    """§10.7.1's fit reaches further back than the chart draws, and a test has to be able to pin
    both ends."""
    store = store_with(clock, 600)

    recent = store.window(timedelta(minutes=1))
    earlier = store.window(timedelta(minutes=1), ending=NOW - timedelta(minutes=5))

    assert len(recent) == 61
    assert earlier.end is not None
    assert earlier.end <= NOW - timedelta(minutes=5)


# ---- Retention ----------------------------------------------------------------------------------


def test_pruning_drops_what_is_older_than_the_retention_window(clock: FixedClock) -> None:
    store = TrendStore.in_memory(clock)
    store.append(reading(NOW - RETENTION - timedelta(hours=1)))
    store.append(reading(NOW - timedelta(hours=1)))

    dropped = store.prune()

    assert dropped == 1
    assert store.count() == 1


def test_pruning_is_measured_from_the_injected_clock(clock: FixedClock) -> None:
    """Not from the newest row. A store left alone for a fortnight and then opened should shed its
    stale history, and one whose receiver is briefly ahead of the host should not shed anything."""
    store = TrendStore.in_memory(clock)
    store.append(reading(NOW - timedelta(days=2)))

    assert store.prune() == 0

    clock.advance(RETENTION)
    assert store.prune() == 1


def test_the_retention_window_covers_the_longest_range_the_spec_draws() -> None:
    """§10.7's longest range is 7 d and §10.7.1's fit reaches slightly past whatever is drawn. A
    retention of exactly seven days would make the 7 d range hold seven days minus however long
    ago the last prune ran."""
    assert timedelta(days=7) < RETENTION


def test_seven_days_of_history_survives_and_comes_back(clock: FixedClock) -> None:
    """The §9.10.2 case, at a cadence the store can actually be tested at: a week of readings, one
    a minute, read back as one window."""
    store = TrendStore.in_memory(clock)
    for minute in range(7 * 24 * 60):
        store.append(reading(NOW - timedelta(minutes=minute)))

    series = store.window(timedelta(days=7))

    assert len(series) == 7 * 24 * 60
    assert series.span >= timedelta(days=6, hours=23)
    assert list(series.at) == sorted(series.at)


# ---- Power-up, for §10.7.1's settling exclusion --------------------------------------------------


def test_the_last_power_up_is_found_before_the_window_begins(clock: FixedClock) -> None:
    """The case the query exists for: the warm-up finished before the drawn range starts, so no
    sample in the window is marked POWER_UP, and the fit would otherwise see no sign one had
    happened. Widening the window instead would mean reading a day to draw an hour."""
    store = TrendStore.in_memory(clock)
    store.append(reading(NOW - timedelta(hours=20), mode=SmartClockMode.POWER_UP))
    store.append(reading(NOW - timedelta(hours=19), mode=SmartClockMode.LOCKED))
    store.append(reading(NOW - timedelta(minutes=30), mode=SmartClockMode.LOCKED))

    found = store.last_power_up(NOW - timedelta(hours=1))

    assert found == NOW - timedelta(hours=20)


def test_the_power_up_anchor_is_the_end_of_the_warm_up(clock: FixedClock) -> None:
    """Conservative on purpose — it excludes slightly more. Documented in the store because the
    two readings of "after a power-up" differ by however long the receiver reported the mode,
    which is minutes against a 24 h exclusion."""
    store = TrendStore.in_memory(clock)
    for minute in range(10):
        store.append(
            reading(
                NOW - timedelta(hours=5) + timedelta(minutes=minute), mode=SmartClockMode.POWER_UP
            )
        )

    assert store.last_power_up(NOW) == NOW - timedelta(hours=5) + timedelta(minutes=9)


def test_no_power_up_in_the_record_is_none_not_an_error(clock: FixedClock) -> None:
    """A receiver that has been up longer than the store has existed is the ordinary case, and it
    is the one where the fit should exclude nothing."""
    store = store_with(clock, 100)

    assert store.last_power_up(NOW) is None


# ---- Files, schemas and failures -----------------------------------------------------------------


def test_a_store_on_disk_survives_being_closed_and_reopened(
    clock: FixedClock, tmp_path: Path
) -> None:
    """The whole point of the module: a trend outlives the process that drew it."""
    path = tmp_path / "trend.db"
    first = TrendStore.open(path, clock)
    first.append(reading(NOW, ti=-12.5))
    first.close()

    second = TrendStore.open(path, clock)
    series = second.window(timedelta(hours=1))
    second.close()

    assert len(series) == 1
    assert series.ti_at(0) == pytest.approx(-12.5)


def test_opening_creates_the_directory_it_was_pointed_at(clock: FixedClock, tmp_path: Path) -> None:
    """On a first run the data directory does not exist yet, and failing there would mean the
    application had no history on precisely the run that would have started collecting it."""
    store = TrendStore.open(tmp_path / "nested" / "deeper" / "trend.db", clock)
    store.append(reading(NOW))
    store.close()

    assert (tmp_path / "nested" / "deeper" / "trend.db").exists()


def test_the_schema_version_is_stamped_on_the_file(clock: FixedClock, tmp_path: Path) -> None:
    path = tmp_path / "trend.db"
    TrendStore.open(path, clock).close()

    connection = sqlite3.connect(path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    finally:
        connection.close()


def test_a_file_from_a_newer_build_is_refused_rather_than_rewritten(
    clock: FixedClock, tmp_path: Path
) -> None:
    """Refusing costs a chart. Opening it and writing to it could cost somebody a week of history
    that a later build knew how to read — so the store declines, and the caller runs without it."""
    path = tmp_path / "trend.db"
    TrendStore.open(path, clock).close()
    connection = sqlite3.connect(path)
    connection.execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    connection.close()

    with pytest.raises(TrendStoreError):
        TrendStore.open(path, clock)


def test_an_unopenable_path_raises_the_store_s_own_error(clock: FixedClock, tmp_path: Path) -> None:
    """``TrendStoreError`` rather than ``sqlite3.Error``, so the caller can catch the one thing it
    understands — "no history this run" — without importing a database exception."""
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")

    with pytest.raises(TrendStoreError):
        TrendStore.open(blocker / "trend.db", clock)


def test_a_file_that_is_not_a_database_is_refused_cleanly(
    clock: FixedClock, tmp_path: Path
) -> None:
    """Somebody's unrelated file, or a truncated one. It must not take the application down."""
    path = tmp_path / "trend.db"
    path.write_bytes(b"this is not a SQLite file, and it is long enough to look like one" * 8)

    with pytest.raises(TrendStoreError):
        TrendStore.open(path, clock)


def test_using_a_closed_store_raises_the_store_s_own_error(clock: FixedClock) -> None:
    """A store closed under a page that is still holding it. Same contract as every other
    failure: one exception type, and the caller carries on without history."""
    store = TrendStore.in_memory(clock)
    store.close()

    with pytest.raises(TrendStoreError):
        store.window(timedelta(hours=1))
    with pytest.raises(TrendStoreError):
        store.append(reading(NOW))


def test_the_store_is_per_device_rather_than_shared(clock: FixedClock, tmp_path: Path) -> None:
    """§12's rule about the session applies here for the same reason: nothing about the store is
    module-level, so a second receiver gets a second store rather than interleaving into the
    first one's history."""
    one = TrendStore.open(tmp_path / "one.db", clock)
    two = TrendStore.open(tmp_path / "two.db", clock)
    one.append(reading(NOW))
    one.append(reading(NOW - timedelta(seconds=1)))
    two.append(reading(NOW))

    assert one.count() == 2
    assert two.count() == 1

    one.close()
    two.close()


def test_the_record_reports_where_it_starts(clock: FixedClock) -> None:
    """What the σ caption needs in order to say how much of an hour it actually found."""
    store = TrendStore.in_memory(clock)
    assert store.earliest() is None

    store.append(reading(NOW - timedelta(hours=3)))
    store.append(reading(NOW))

    assert store.earliest() == NOW - timedelta(hours=3)


def test_a_naive_datetime_is_never_accepted_into_a_window(clock: FixedClock) -> None:
    """Timezone-awareness without exception, as ``Clock`` puts it: a naive datetime compared
    against an aware one raises, and this is the boundary where one could get in."""
    store = TrendStore.in_memory(clock)

    with pytest.raises((TypeError, ValueError)):
        store.between(datetime(2026, 8, 31), datetime(2026, 9, 1))


def test_stored_times_survive_the_round_trip_to_the_microsecond(clock: FixedClock) -> None:
    """Time is stored as an epoch double so the decimator does not parse a timestamp per sample.
    A double holds an epoch second to well under a microsecond, and the poll cadence is 1 s — but
    the Allan estimator pairs samples by their recorded times, so this is worth pinning."""
    precise = NOW - timedelta(seconds=1, microseconds=522847)
    store = TrendStore.in_memory(clock)
    store.append(reading(precise))

    recovered = store.window(timedelta(hours=1)).moment_at(0)

    assert abs((recovered - precise).total_seconds()) < 1e-6
