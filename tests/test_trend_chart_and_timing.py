"""The trend charts, and the Timing page that owns them.

Assertions are against ``TrendChart.plot()`` rather than against rendered pixels. The questions
worth asking of a chart — does the axis contain the data, did the excursion survive the reduction,
is the unlocked stretch shaded — are all decisions, and a screenshot comparison would answer none
of them while failing whenever a font changed.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.models.receiver_status import (
    ReceiverStatus,
    SmartClockMode,
)
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.trend_store import (
    TrendStore,
    TrendStoreError,
    empty_series,
)
from smartclock_monitor.themes.tokens import ALL_THEMES, Theme, palette_for
from smartclock_monitor.views.pages import SIGMA_WINDOW, TREND_RANGES, TimingPage
from smartclock_monitor.widgets.chart_geometry import TI_FLOOR_NANOSECONDS
from smartclock_monitor.widgets.trend_chart import AxisMode, TrendChart


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


def reading(
    at_offset: float,
    *,
    ti: float | None = -33.1,
    efc: float | None = -16.83,
    mode: SmartClockMode = SmartClockMode.LOCKED,
) -> Reading:
    at = NOW + timedelta(seconds=at_offset)
    return Reading(
        status=ReceiverStatus(captured_at=at, mode=mode, one_pps_ti_nanoseconds=ti),
        captured_at=at,
        efc_percent=efc,
    )


def stored(clock: FixedClock, readings: list[Reading]) -> TrendStore:
    store = TrendStore.in_memory(clock)
    for item in readings:
        store.append(item)
    return store


# ---- The chart's decisions -------------------------------------------------------------------


def test_the_one_pps_chart_is_anchored_on_zero_and_the_efc_chart_is_not(
    clock: FixedClock,
) -> None:
    """§10.7.1's central distinction. The two charts are given the same window and must frame it
    differently — 0 ns and 0 % are not the same zero."""
    store = stored(clock, [reading(-index, ti=-33.0, efc=-16.83) for index in range(60)])
    window = store.window(timedelta(hours=1), ending=NOW)

    ti_chart = TrendChart("TI", AxisMode.ZERO_ANCHORED, "ns")
    efc_chart = TrendChart("EFC", AxisMode.FRAMED, "%")
    ti_chart.show_series(window)
    efc_chart.show_series(window)

    assert ti_chart.axis().midpoint == 0.0
    assert efc_chart.axis().midpoint != 0.0
    assert efc_chart.axis().low <= -16.83 <= efc_chart.axis().high


def test_an_excursion_survives_the_chart_s_own_reduction(clock: FixedClock) -> None:
    """The end-to-end version of the decimation test: a single bad second put into the store and
    read back through the widget at a width where hundreds of samples share a column."""
    readings = [reading(-index, ti=-2.0) for index in range(2000)]
    readings[900] = reading(-900, ti=880.0)
    store = stored(clock, readings)

    chart = TrendChart("TI", AxisMode.ZERO_ANCHORED, "ns")
    chart.show_series(store.window(timedelta(hours=1), ending=NOW))
    plot = chart.plot(width=300)

    assert max(column.high for column in plot.columns) == 880.0
    assert plot.axis.high >= 880.0


def test_a_calm_receiver_is_not_drawn_as_a_crisis(clock: FixedClock) -> None:
    """The ±50 ns floor reaching the widget. A receiver holding a couple of nanoseconds must not
    fill the plot with its own noise."""
    store = stored(clock, [reading(-index, ti=1.5 if index % 2 else -1.5) for index in range(50)])

    chart = TrendChart("TI", AxisMode.ZERO_ANCHORED, "ns")
    chart.show_series(store.window(timedelta(hours=1), ending=NOW))

    assert chart.axis().high >= TI_FLOOR_NANOSECONDS


def test_only_the_one_pps_chart_shades_unlocked_stretches(clock: FixedClock) -> None:
    """§10.7.1 puts the shading on the 1 PPS chart. On the EFC chart it would be claiming that
    lock says something about the oscillator's control voltage, which is a different assertion and
    not one this application makes."""
    modes = [SmartClockMode.LOCKED] * 20 + [SmartClockMode.HOLDOVER] * 10
    store = stored(clock, [reading(-index, mode=mode) for index, mode in enumerate(modes)])
    window = store.window(timedelta(hours=1), ending=NOW)

    ti_chart = TrendChart("TI", AxisMode.ZERO_ANCHORED, "ns")
    efc_chart = TrendChart("EFC", AxisMode.FRAMED, "%")
    ti_chart.show_series(window)
    efc_chart.show_series(window)

    assert ti_chart.plot(width=200).unlocked
    assert efc_chart.plot(width=200).unlocked == ()


def test_an_empty_chart_still_has_an_axis() -> None:
    """Before the first reading. The chart draws its gridlines and labels and waits, rather than
    dividing by an empty range."""
    chart = TrendChart("TI", AxisMode.ZERO_ANCHORED, "ns")
    plot = chart.plot(width=400)

    assert plot.columns == ()
    assert plot.axis.high == TI_FLOOR_NANOSECONDS
    assert "no readings" in chart.accessibleDescription()


def test_a_chart_of_only_holes_says_so(clock: FixedClock) -> None:
    """§11.1: every field can be ``None``. A window of readings the receiver would not answer is
    not an empty window, and the two say different things to someone looking at it."""
    store = stored(clock, [reading(-index, ti=None) for index in range(30)])

    chart = TrendChart("TI", AxisMode.ZERO_ANCHORED, "ns")
    chart.show_series(store.window(timedelta(hours=1), ending=NOW))

    assert chart.plot(width=200).columns == ()
    assert "no readings in this window" in chart.accessibleDescription()


def test_the_chart_describes_itself_in_words(clock: FixedClock) -> None:
    """A11Y: the trace's meaning would otherwise rest entirely on shape. The description carries
    the count, the span and the range, which is what the chart is actually saying."""
    store = stored(clock, [reading(-index, ti=float(index % 7)) for index in range(120)])

    chart = TrendChart("1 PPS time interval", AxisMode.ZERO_ANCHORED, "ns")
    chart.show_series(store.window(timedelta(hours=1), ending=NOW))
    description = chart.accessibleDescription()

    assert "120 readings" in description
    assert "ns" in description


# ---- The diverging fill ------------------------------------------------------------------------


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda t: t.value)
def test_every_colour_the_fill_draws_is_a_token(theme: Theme) -> None:
    """§9.13's first prohibition stays checkable only while every drawn colour appears in the
    table. An interpolated ramp would paint values that exist nowhere in it, and the gate could
    not tell those from a hard-coded one."""
    palette = palette_for(theme)
    chart = TrendChart("TI", AxisMode.ZERO_ANCHORED, "ns", palette)
    axis = chart.axis()

    known = {colour.upper() for colour in palette.diverging}
    for value in (-500.0, -50.0, -1.0, 0.0, 1.0, 50.0, 500.0):
        assert chart._diverging_for(value, axis).name().upper() in known


def test_the_neutral_stop_means_exactly_zero() -> None:
    """§10.7.1: *"The neutral midpoint must map to exactly 0 ns, not to the data midpoint."* A
    stop that also covered merely small readings would make the chart say the receiver was on
    time when it was a nanosecond out."""
    chart = TrendChart("TI", AxisMode.ZERO_ANCHORED, "ns", palette_for(Theme.DARK))
    axis = chart.axis()
    neutral = palette_for(Theme.DARK).diverging[2]

    assert chart._diverging_for(0.0, axis).name().upper() == neutral.upper()
    assert chart._diverging_for(0.001, axis).name().upper() != neutral.upper()
    assert chart._diverging_for(-0.001, axis).name().upper() != neutral.upper()


def test_the_fill_separates_early_from_late() -> None:
    """The sign is the point of a diverging ramp. A receiver running early and one running late by
    the same amount must not be drawn the same colour."""
    chart = TrendChart("TI", AxisMode.ZERO_ANCHORED, "ns", palette_for(Theme.LIGHT))
    axis = chart.axis()

    assert chart._diverging_for(40.0, axis).name() != chart._diverging_for(-40.0, axis).name()


# ---- The Timing page ---------------------------------------------------------------------------


def test_the_page_works_with_no_store_at_all() -> None:
    """§10.7 has to work on a run whose store would not open. ``None`` is an ordinary state."""
    page = TimingPage()
    page.set_trend_store(None)

    assert page._ti_chart.series == empty_series(page._range)
    assert "No trend history" in page._evidence.text()


def test_the_page_draws_what_the_store_holds(clock: FixedClock) -> None:
    store = stored(clock, [reading(-index) for index in range(300)])
    page = TimingPage()
    page.show_reading(reading(0))
    page.set_trend_store(store)

    assert len(page._ti_chart.series) == 300
    assert len(page._efc_chart.series) == 300


def test_both_charts_are_given_the_same_window(clock: FixedClock) -> None:
    """§10.7.1: one range selector, shared. Two charts drawing different windows would be read as
    one picture and would be lying about it."""
    store = stored(clock, [reading(-index) for index in range(120)])
    page = TimingPage()
    page.show_reading(reading(0))
    page.set_trend_store(store)

    assert list(page._ti_chart.series.at) == list(page._efc_chart.series.at)


def test_choosing_a_range_redraws_at_once(clock: FixedClock) -> None:
    """The click *is* the request. Waiting for the next poll to honour it reads as the button not
    having worked, and at the 7 d range that wait is minutes."""
    store = stored(clock, [reading(-index * 60) for index in range(600)])  # ten hours, one a minute
    page = TimingPage()
    page.show_reading(reading(0))
    page.set_trend_store(store)

    one_hour = len(page._ti_chart.series)
    page._choose_range(2)  # 24 h

    assert page._range == TREND_RANGES[2][1]
    assert len(page._ti_chart.series) > one_hour


def test_sigma_is_always_the_last_hour_whatever_range_is_drawn(clock: FixedClock) -> None:
    """§10.7: it sits beside *Current* as a property of the receiver now, not of the window being
    drawn. A σ that changed when the user pressed 7 d would be a different statistic wearing the
    same label."""
    store = stored(clock, [reading(-index * 60, ti=float(index % 11)) for index in range(600)])
    page = TimingPage()
    page.show_reading(reading(0))
    page.set_trend_store(store)

    at_one_hour = page._sigma.text()
    page._choose_range(3)  # 7 d

    assert page._sigma.text() == at_one_hour
    assert timedelta(hours=1) == SIGMA_WINDOW


def test_the_caption_names_what_was_found_not_what_was_asked_for(clock: FixedClock) -> None:
    """§10.7 is explicit: the application is not always running, so an hour of wall clock
    routinely holds four minutes of readings, and the count goes beside the span because a
    deviation over 3,000 readings and one over 12 are not the same figure."""
    store = stored(clock, [reading(-index, ti=float(index % 5)) for index in range(240)])
    page = TimingPage()
    page.show_reading(reading(0))
    page.set_trend_store(store)

    assert "4 min" in page._evidence.text()
    assert "240 samples" in page._evidence.text()


def test_a_deviation_over_one_reading_is_withheld(clock: FixedClock) -> None:
    """Not rendered as zero. σ over a single sample is not a small number, it is not a number, and
    zero would say the receiver was perfectly stable."""
    store = stored(clock, [reading(0)])
    page = TimingPage()
    page.show_reading(reading(0))
    page.set_trend_store(store)

    assert "—" in page._sigma.text()
    assert "needs two" in page._evidence.text()


def test_a_store_that_fails_mid_run_costs_the_history_not_the_page(clock: FixedClock) -> None:
    """A removed drive, a deleted file. The rest of the Timing page is live data from the poll
    loop and must keep working — losing the receiver to protect a chart is the wrong trade."""
    store = stored(clock, [reading(-index) for index in range(50)])
    page = TimingPage()
    page.show_reading(reading(0))
    page.set_trend_store(store)
    assert len(page._ti_chart.series) == 50

    store.close()
    page._refresh_trends(force=True)

    assert page._store is None
    assert "No trend history" in page._evidence.text()
    with pytest.raises(TrendStoreError):
        store.count()


def test_the_page_does_not_re_read_the_store_on_every_reading(clock: FixedClock) -> None:
    """Re-reading a 7-day window once a second would redraw 604 800 rows to move the trace by
    less than a pixel."""
    store = stored(clock, [reading(-index) for index in range(60)])
    page = TimingPage()
    page.show_reading(reading(0))
    page.set_trend_store(store)

    reads = 0
    original = store.window

    def counting(*args: object, **kwargs: object) -> object:
        nonlocal reads
        reads += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    store.window = counting  # type: ignore[method-assign, assignment]
    for offset in range(1, 5):
        page.show_reading(reading(offset))

    assert reads == 0


def test_a_later_reading_does_eventually_refresh(clock: FixedClock) -> None:
    """The other half: a throttle that never released would freeze the chart at whatever was
    stored when the page opened."""
    store = stored(clock, [reading(-index) for index in range(60)])
    page = TimingPage()
    page.show_reading(reading(0))
    page.set_trend_store(store)

    store.append(reading(30))
    page.show_reading(reading(30))

    assert len(page._ti_chart.series) == 61


# ---- The timestamp defect this found -------------------------------------------------------------


def test_a_reading_carries_when_it_was_taken(clock: FixedClock) -> None:
    """Found against the real receiver: fifteen stored rows shared a single timestamp.

    The fast tier folds a fresh 1 PPS interval into the status object once a second through
    ``dataclasses.replace``, which keeps the original ``captured_at`` — so the status's own time
    is when the *screen* was read, up to a full-poll interval earlier. A trend filed under it has
    ten readings at one instant, no span, and no gaps for §10.7.2's estimator to see.
    """
    screen_read_at = NOW - timedelta(seconds=9)
    stale = ReceiverStatus(
        captured_at=screen_read_at, mode=SmartClockMode.LOCKED, one_pps_ti_nanoseconds=-4.0
    )

    store = TrendStore.in_memory(clock)
    for second in range(5):
        store.append(
            Reading(status=stale, captured_at=NOW + timedelta(seconds=second), efc_percent=-16.8)
        )

    series = store.window(timedelta(hours=1), ending=NOW + timedelta(minutes=1))

    assert len(series) == 5
    assert len(set(series.at)) == 5, "every reading must have its own instant"
    assert series.span == timedelta(seconds=4)


def test_a_reading_without_its_own_timestamp_falls_back_to_the_screen(clock: FixedClock) -> None:
    """``captured_at`` is optional on ``Reading`` so a test can build one without caring. The
    store must still file it somewhere sensible rather than refusing it."""
    store = TrendStore.in_memory(clock)
    store.append(Reading(status=ReceiverStatus(captured_at=NOW, mode=SmartClockMode.LOCKED)))

    assert store.window(timedelta(hours=1)).moment_at(0) == NOW
