"""Decimation and axis arithmetic — where a chart is right or wrong.

No Qt here on purpose. The property §9.10.2 spends a sentence on — that a one-second excursion
survives the 7-day range — is a fact about the reduction, and asserting it should not require
starting a window.
"""

from __future__ import annotations

import math
from array import array
from datetime import timedelta

import pytest

from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_monitor.services.trend_store import Series
from smartclock_monitor.widgets.chart_geometry import (
    EFC_DECIMALS,
    EFC_MINIMUM_SPAN_PERCENT,
    TI_FLOOR_NANOSECONDS,
    Axis,
    decimate,
    framed_axis,
    unlocked_runs,
    zero_anchored_axis,
)

MINUS = "\N{MINUS SIGN}"


def series_of(modes: list[SmartClockMode], *, step: float = 1.0) -> Series:
    at = array("d", [float(index) * step for index in range(len(modes))])
    blank = array("d", [0.0] * len(modes))
    return Series(
        at=at,
        ti_nanoseconds=blank,
        efc_percent=blank,
        mode=tuple(modes),
        requested=timedelta(seconds=len(modes)),
    )


# ---- Decimation --------------------------------------------------------------------------------


def test_a_one_second_excursion_survives_the_seven_day_range() -> None:
    """§9.10.2's stated reason for min/max decimation, asserted at the scale it names.

    A week of one-second readings into 800 pixel columns puts about 756 samples in a column. A
    sampled decimation would keep one of them, so a single-sample spike has roughly a 1-in-756
    chance of being drawn. This must be a certainty."""
    count = 7 * 24 * 3600
    at = [float(second) for second in range(count)]
    values = [0.0] * count

    # Deliberately mid-bucket. At 800 columns a bucket is 756 samples wide and count // 2 is
    # exactly a bucket boundary, so a spike placed there is the *first* sample in its column and
    # survives even a first-value-wins decimation — this test passed against a mutant that had had
    # its min/max removed. An excursion is not usually so considerate about where it lands.
    spike = count // 2 + 371
    values[spike] = 900.0

    columns = decimate(at, values, 800)

    assert max(column.high for column in columns) == 900.0


def test_a_negative_excursion_survives_too() -> None:
    """The other half of min/max. Keeping only the maximum would draw a chart that could never
    show the receiver running early."""
    values = [0.0] * 10_000
    values[4_321] = -777.0

    columns = decimate([float(i) for i in range(10_000)], values, 100)

    assert min(column.low for column in columns) == -777.0


def test_a_column_keeps_the_extremes_not_the_ends() -> None:
    """``low``/``high`` are the bucket's smallest and largest, not its first and last — which is
    the difference between a band that shows what happened and one that shows where it started."""
    columns = decimate([0.0, 1.0, 2.0, 3.0], [5.0, -9.0, 11.0, 6.0], 1)

    assert len(columns) == 1
    assert columns[0].low == -9.0
    assert columns[0].high == 11.0
    assert columns[0].count == 4


def test_columns_with_no_samples_are_omitted_rather_than_zeroed() -> None:
    """A stretch nothing was recorded in is a break in the trace. Emitting zero would be a
    reading, and on a 1 PPS chart a reading of zero says the receiver was perfect."""
    at = [0.0, 1.0, 98.0, 99.0]
    columns = decimate(at, [3.0, 4.0, 5.0, 6.0], 10)

    assert len(columns) == 2
    assert [column.index for column in columns] == [0, 9]
    assert all(column.count > 0 for column in columns)


def test_nan_samples_do_not_reach_a_column() -> None:
    """A hole in the record is not a value. It must not drag a column's minimum to NaN, which
    would poison every comparison drawn from it."""
    columns = decimate([0.0, 1.0, 2.0], [4.0, math.nan, 6.0], 1)

    assert len(columns) == 1
    assert columns[0].low == 4.0
    assert columns[0].high == 6.0
    assert columns[0].count == 2


def test_a_column_of_only_holes_is_not_emitted() -> None:
    columns = decimate([0.0, 1.0], [math.nan, math.nan], 4)

    assert columns == ()


def test_columns_come_back_in_time_order() -> None:
    """The chart walks them left to right; a dict's insertion order is not the axis order once
    samples arrive out of sequence."""
    at = [9.0, 1.0, 5.0, 3.0, 7.0]
    columns = decimate(sorted(at), [1.0, 2.0, 3.0, 4.0, 5.0], 5)

    assert [column.index for column in columns] == sorted(column.index for column in columns)
    assert [column.at for column in columns] == sorted(column.at for column in columns)


def test_a_sample_on_the_upper_bound_lands_in_the_last_column() -> None:
    """Not one past the end. The arithmetic ``int((t - lo) / width)`` gives exactly ``columns``
    for the final sample, and an unclamped version would either crash or silently drop the newest
    reading — which is the one being watched."""
    columns = decimate([0.0, 50.0, 100.0], [1.0, 2.0, 3.0], 10, start=0.0, end=100.0)

    assert max(column.index for column in columns) == 9
    assert columns[-1].high == 3.0


def test_the_time_range_can_be_given_rather_than_taken_from_the_data() -> None:
    """Two charts share one range selector (§10.7.1). If each took its extent from its own data
    they would disagree about where a moment sits, and a feature at 3 pm on one would be somewhere
    else on the other."""
    dense = decimate([10.0, 11.0, 12.0], [1.0, 2.0, 3.0], 100, start=0.0, end=100.0)

    assert all(column.index < 15 for column in dense)


def test_asking_for_no_columns_returns_nothing_rather_than_dividing_by_zero() -> None:
    """A chart is laid out before it is drawn, and a zero-width widget is an ordinary moment in
    that sequence rather than a bug to crash on."""
    assert decimate([0.0, 1.0], [1.0, 2.0], 0) == ()
    assert decimate([], [], 100) == ()


def test_a_window_one_instant_wide_still_draws() -> None:
    """A single reading, or a window narrower than one poll. Dividing by a zero span would be the
    obvious crash; showing nothing at all would be the quiet one."""
    columns = decimate([5.0, 5.0], [2.0, 8.0], 100)

    assert len(columns) == 1
    assert (columns[0].low, columns[0].high) == (2.0, 8.0)


def test_every_sample_is_counted_exactly_once() -> None:
    """The conservation property. A bucket-index off-by-one shows up as samples going missing or
    being counted twice, and neither is visible in the drawn shape."""
    at = [float(index) * 0.37 for index in range(5000)]
    values = [float(index % 17) for index in range(5000)]

    columns = decimate(at, values, 97)

    assert sum(column.count for column in columns) == 5000


# ---- The zero-anchored axis (1 PPS) ------------------------------------------------------------


def test_the_one_pps_axis_is_symmetric_about_exactly_zero() -> None:
    """§10.7.1: the diverging fill's neutral midpoint maps to exactly 0 ns. It can only do that on
    an axis whose midpoint *is* zero, which is why this is a separate function rather than a flag
    on the framed one."""
    axis = zero_anchored_axis([-33.1, 12.0, 47.9])

    assert axis.midpoint == 0.0
    assert axis.low == -axis.high


def test_a_calm_loop_is_not_magnified_into_noise() -> None:
    """The ±50 ns floor, which §9.10.2 gives the medallion ring for the same reason. A receiver
    holding ±2 ns drawn against a ±2 ns axis looks like it is falling apart."""
    axis = zero_anchored_axis([-1.8, 0.4, 2.1])

    assert axis.high >= TI_FLOOR_NANOSECONDS


def test_the_axis_still_contains_an_excursion_past_the_floor() -> None:
    """The floor is a floor, not a clamp. A 900 ns excursion drawn against a ±50 ns axis would be
    a chart that hides the one thing on it worth seeing."""
    axis = zero_anchored_axis([-33.0, 900.0])

    assert axis.high >= 900.0
    assert axis.low <= -900.0


def test_an_empty_one_pps_axis_is_still_drawable() -> None:
    """Before the first reading arrives. The chart draws its gridlines and its labels and waits."""
    axis = zero_anchored_axis([])

    assert axis.high == TI_FLOOR_NANOSECONDS
    assert axis.midpoint == 0.0


def test_holes_do_not_reach_the_axis_bounds() -> None:
    """NaN propagates through min and max, so an unmasked hole would give an axis of NaN and a
    chart of nothing, with no error anywhere."""
    axis = zero_anchored_axis([math.nan, 120.0, math.nan])

    assert math.isfinite(axis.low) and math.isfinite(axis.high)
    assert axis.high >= 120.0


# ---- The framed axis (EFC) ---------------------------------------------------------------------


def test_the_efc_axis_frames_the_data_rather_than_zero() -> None:
    """#183, measured on the 22–24 Aug 2026 capture: a receiver holding −16.8557…−16.8041 % over
    47 hours, drawn against a ±25 % axis, put 0.05 percentage points of real structure into about
    a thousandth of the plot height and the trace read as dead flat."""
    axis = framed_axis([-16.8557, -16.8041])

    assert axis.low <= -16.8557
    assert axis.high >= -16.8041
    assert axis.span < 0.5  # not ±25


def test_the_efc_axis_contains_its_data() -> None:
    """The property snapping can break: rounding the centre can push a bound past an extreme, so
    the implementation widens until it fits rather than assuming one pass is enough."""
    for low, high in [
        (-16.8557, -16.8041),
        (0.0004, 0.0006),
        (-99.9, 99.9),
        (12.3456, 12.3457),
        (-0.005, 0.005),
    ]:
        axis = framed_axis([low, high])
        assert axis.low <= low, (low, high, axis)
        assert axis.high >= high, (low, high, axis)


def test_the_efc_axis_has_a_minimum_span() -> None:
    """§10.7.1: 0.01 % is about 55 EFC codes on the bench receiver, whose step measures roughly
    0.00018 %. Below that the chart draws the converter's least significant bit."""
    axis = framed_axis([-16.83000, -16.83002])

    # To within representation. The bounds land on -16.835 and -16.825, whose difference is
    # 0.009999999999998 as doubles — the floor is a statement about the oscillator, not about
    # binary floating point, and asserting it exactly would be a gate that fails on arithmetic.
    assert axis.span >= EFC_MINIMUM_SPAN_PERCENT * (1.0 - 1e-9)


def test_the_efc_midpoint_lands_on_a_value_its_own_label_can_state() -> None:
    """An axis label that disagrees with the gridline it sits on is worse than a coarse axis.
    With the extent snapped but not the centre, a midpoint of −16.825 gets labelled −16.83 at
    §10.7.1's fixed two decimals and is drawn 0.005 away from it."""
    axis = framed_axis([-16.8557, -16.8041])

    assert axis.midpoint == pytest.approx(float(f"{axis.midpoint:.{EFC_DECIMALS}f}"), abs=1e-9)


def test_an_empty_efc_axis_is_still_drawable() -> None:
    axis = framed_axis([])

    assert axis.span >= EFC_MINIMUM_SPAN_PERCENT
    assert math.isfinite(axis.low) and math.isfinite(axis.high)


# ---- Labels ------------------------------------------------------------------------------------


def test_an_axis_carries_three_labels_low_middle_high() -> None:
    """§9.10.2: the two bounds and the midpoint, in that order bottom to top."""
    low, middle, high = Axis(low=-50.0, high=50.0, decimals=0).labels()

    assert (low, middle, high) == (f"{MINUS}50", "0", "50")


def test_a_negative_label_uses_a_minus_sign_not_a_hyphen() -> None:
    """§9.5.3's typesetting applies to an axis as much as to a readout. The same argument the
    PRIME and MINUS SIGN entries in the confusables list make: a hyphen is not a minus."""
    low, _, _ = Axis(low=-16.9, high=-16.8, decimals=EFC_DECIMALS).labels()

    assert low.startswith(MINUS)
    assert "-" not in low


def test_a_midpoint_of_zero_is_never_labelled_minus_zero() -> None:
    """Which is what ``f"{-0.0001:.0f}"`` gives, and it reads as a receiver running fractionally
    early rather than as the middle of the axis."""
    axis = Axis(low=-50.0000001, high=49.9999999, decimals=0)

    assert axis.labels()[1] == "0"


def test_labels_hold_their_precision_across_ranges() -> None:
    """§9.5.3 item 6, which §10.7.1 restates for this chart: a precision that varies with the
    selected range is what the rule forbids, so both come back at two decimals regardless."""
    tight = framed_axis([-16.8300, -16.8302]).labels()
    wide = framed_axis([-16.9, -16.7]).labels()

    for label in tight + wide:
        assert len(label.split(".")[1]) == EFC_DECIMALS


# ---- Unlocked stretches ------------------------------------------------------------------------


def test_an_unlocked_stretch_comes_back_as_one_range() -> None:
    """§10.7.1 shades these. One rectangle per stretch, rather than a decision per sample — at the
    7-day range that would be 604 800 decisions producing the same shape."""
    modes = (
        [SmartClockMode.LOCKED] * 3 + [SmartClockMode.HOLDOVER] * 4 + [SmartClockMode.LOCKED] * 3
    )

    assert unlocked_runs(series_of(modes)) == ((3.0, 7.0),)


def test_every_mode_that_is_not_locked_shades() -> None:
    """Holdover, recovery, power-up and unknown alike. The chart's claim is about whether the
    reading was disciplined, and only one mode means it was."""
    for mode in (
        SmartClockMode.HOLDOVER,
        SmartClockMode.RECOVERY,
        SmartClockMode.POWER_UP,
        SmartClockMode.UNKNOWN,
    ):
        runs = unlocked_runs(series_of([SmartClockMode.LOCKED, mode, SmartClockMode.LOCKED]))
        assert runs == ((1.0, 2.0),), mode


def test_a_stretch_still_open_at_the_end_stops_at_the_last_reading() -> None:
    """Not at the window's edge. The record ends where the readings end, and shading past that
    would claim knowledge of a period nothing was recorded in."""
    modes = [SmartClockMode.LOCKED, SmartClockMode.HOLDOVER, SmartClockMode.HOLDOVER]

    assert unlocked_runs(series_of(modes)) == ((1.0, 2.0),)


def test_several_stretches_come_back_separately() -> None:
    modes = [
        SmartClockMode.LOCKED,
        SmartClockMode.HOLDOVER,
        SmartClockMode.LOCKED,
        SmartClockMode.RECOVERY,
        SmartClockMode.LOCKED,
    ]

    assert unlocked_runs(series_of(modes)) == ((1.0, 2.0), (3.0, 4.0))


def test_a_fully_locked_window_shades_nothing() -> None:
    assert unlocked_runs(series_of([SmartClockMode.LOCKED] * 5)) == ()


def test_an_empty_window_shades_nothing() -> None:
    assert unlocked_runs(series_of([])) == ()
