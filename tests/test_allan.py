"""§10.7.2's overlapping Allan deviation.

**Checked against theory, not against itself.** An Allan estimator that is subtly wrong still
produces a smooth, plausible curve, so a test that only asserted "it returns numbers that go down"
would pass on a broken one. Each noise type has a known slope and, for white phase noise, a known
absolute value — those are what is asserted.

White phase modulation of rms σx gives σy(τ) = √3·σx/τ. So 10 ns of independent per-sample jitter
predicts 1.73e−8 at τ = 1 s, halving with every octave. That single figure catches a missing
factor of two, a wrong denominator, a nanosecond conversion in the wrong direction, and a plain
rather than overlapping estimator all at once.
"""

from __future__ import annotations

import math
import random
from array import array
from collections.abc import Sequence
from datetime import timedelta
from itertools import pairwise

import pytest

from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_monitor.services.allan import (
    MINIMUM_DIFFERENCES,
    AllanPoint,
    allan_deviation,
    summarise,
)
from smartclock_monitor.services.trend_store import Series

MINUS = "\N{MINUS SIGN}"
EPOCH = 1.788e9


def series_from(times: Sequence[float], nanoseconds: Sequence[float | None]) -> Series:
    return Series(
        at=array("d", times),
        ti_nanoseconds=array("d", [math.nan if v is None else v for v in nanoseconds]),
        efc_percent=array("d", [0.0] * len(times)),
        mode=tuple([SmartClockMode.LOCKED] * len(times)),
        requested=timedelta(seconds=times[-1] - times[0] if times else 0),
    )


def white_phase(count: int, rms_nanoseconds: float, *, step: float = 1.0, seed: int = 7) -> Series:
    generator = random.Random(seed)
    times = [EPOCH + index * step for index in range(count)]
    return series_from(times, [generator.gauss(0.0, rms_nanoseconds) for _ in range(count)])


# ---- Against theory ----------------------------------------------------------------------------


def test_white_phase_noise_gives_the_deviation_theory_predicts() -> None:
    """σy(τ) = √3·σx/τ. 10 ns rms at τ = 1 s predicts 1.73e−8.

    The absolute value is what makes this a test of the estimator rather than of its own output:
    a missing factor of two, a wrong denominator or a nanosecond conversion in the wrong direction
    all move this number and none of them changes the shape of the curve.
    """
    points = allan_deviation(white_phase(4000, 10.0))

    assert points
    expected = math.sqrt(3.0) * 10e-9 / points[0].tau_seconds
    assert points[0].deviation == pytest.approx(expected, rel=0.05)


def test_white_phase_noise_falls_as_one_over_tau() -> None:
    """Halving per octave. A plain (non-overlapping) estimator gets this slope right too, which is
    why the absolute value above is asserted as well — but a wrong τ ladder shows up here."""
    points = allan_deviation(white_phase(4000, 10.0))

    for earlier, later in pairwise(points):
        assert later.deviation / earlier.deviation == pytest.approx(0.5, abs=0.06)


def test_a_frequency_offset_produces_no_instability() -> None:
    """**Phase in, deviation out.** A constant frequency offset is a phase *ramp*, and the second
    difference of a ramp is zero — a clock running steadily fast is not an unstable clock.

    If a frequency series were ever handed to this by mistake, a constant offset would come back
    as a large deviation at every τ. That is the mistake §10.7.2 forbids in as many words.
    """
    times = [EPOCH + index for index in range(500)]
    ramp = [index * 3.0 for index in range(500)]  # 3 ns per second, exactly

    points = allan_deviation(series_from(times, ramp))

    assert points
    for point in points:
        assert point.deviation < 1e-15, f"τ={point.tau_seconds}: a ramp is not instability"


def test_a_constant_phase_offset_produces_no_instability() -> None:
    """A receiver sitting 33 ns out but perfectly steady. The chart shows the offset; stability is
    a different question and the answer is zero."""
    times = [EPOCH + index for index in range(200)]

    points = allan_deviation(series_from(times, [-33.1] * 200))

    # Non-vacuously: the τ ladder must actually produce rows. Written as `all(...)` over a
    # possibly-empty tuple, this test passed while the estimator was returning nothing at all for
    # a steady series — which is the failure it was meant to catch.
    assert len(points) >= 5
    assert all(point.deviation == 0.0 for point in points)
    assert points[0].formatted() == "0.00e+0"


def test_tau_runs_in_octaves_from_the_sample_spacing() -> None:
    """The shortest τ that means anything is the cadence itself; below it there are no pairs."""
    points = allan_deviation(white_phase(2000, 5.0, step=2.0))

    assert [point.tau_seconds for point in points[:4]] == [2.0, 4.0, 8.0, 16.0]


def test_the_number_of_differences_is_reported_and_falls_with_tau() -> None:
    """§10.7.2 makes the count part of the reading rather than a footnote: confidence goes roughly
    as 1/√N, and an estimate over four differences deserves to be read as one."""
    points = allan_deviation(white_phase(1000, 5.0))

    counts = [point.differences for point in points]
    assert counts == sorted(counts, reverse=True)
    assert all(count >= MINIMUM_DIFFERENCES for count in counts)


# ---- Gaps, which the logged series is full of --------------------------------------------------


def test_a_gap_contributes_nothing_rather_than_being_treated_as_adjacent() -> None:
    """§10.7.2's second rule, and the one that changes the answer rather than the presentation.

    Two calm stretches either side of a twenty-minute disconnection, with a phase step across it.
    Pairing by index would take a second difference straight across the gap and report the step as
    instability at τ = 1 s; pairing by recorded time refuses the triple entirely.
    """
    quiet = [EPOCH + index for index in range(200)]
    later = [EPOCH + 1200.0 + index for index in range(200)]
    values = [0.0] * 200 + [900.0] * 200  # a 900 ns step across the gap

    points = allan_deviation(series_from(quiet + later, values))

    assert points
    assert points[0].tau_seconds == 1.0
    # 900 ns of step over 1 s would be σy ≈ 1e-6. Only the two calm stretches should be measured.
    assert points[0].deviation < 1e-12


def test_a_gap_reduces_the_count_rather_than_the_confidence_claim() -> None:
    """The corollary: the estimate is over fewer differences, and says so. A gap-aware estimator
    that silently kept its count would be claiming evidence it did not have."""
    unbroken = allan_deviation(white_phase(400, 5.0))

    times = [EPOCH + index for index in range(200)] + [
        EPOCH + 1200.0 + index for index in range(200)
    ]
    generator = random.Random(7)
    broken = allan_deviation(series_from(times, [generator.gauss(0.0, 5.0) for _ in range(400)]))

    assert broken[0].differences < unbroken[0].differences


def test_holes_in_the_readings_are_skipped() -> None:
    """§11.1: the receiver declines to answer and the field is ``None``. NaN would propagate into
    every sum and give a deviation of NaN at every τ, with nothing raised anywhere."""
    times = [EPOCH + index for index in range(400)]
    generator = random.Random(3)
    values: list[float | None] = [generator.gauss(0.0, 5.0) for _ in range(400)]
    for index in range(0, 400, 11):
        values[index] = None

    points = allan_deviation(series_from(times, values))

    assert points
    assert all(math.isfinite(point.deviation) for point in points)


def test_an_irregular_cadence_still_estimates() -> None:
    """The real receiver polls at about 2.2 s, not exactly. Samples must be matched within a
    tolerance rather than demanded on an exact grid, or every τ would find nothing."""
    generator = random.Random(11)
    times = []
    moment = EPOCH
    for _ in range(600):
        times.append(moment)
        moment += 2.2 + generator.uniform(-0.15, 0.15)

    points = allan_deviation(series_from(times, [generator.gauss(0.0, 8.0) for _ in range(600)]))

    assert points
    assert points[0].differences > 100


# ---- What it refuses ---------------------------------------------------------------------------


def test_a_series_too_short_for_any_tau_returns_nothing() -> None:
    """§10.7.2: *"A τ the series cannot support is dropped, not dashed."* Unlike a field the
    receiver declined to answer, a τ with no estimate is not a hole in the data — it is a question
    this series cannot speak to, and a row of dashes would imply otherwise."""
    assert allan_deviation(series_from([EPOCH, EPOCH + 1.0], [1.0, 2.0])) == ()
    assert allan_deviation(series_from([EPOCH], [1.0])) == ()


def test_a_series_of_only_holes_returns_nothing() -> None:
    times = [EPOCH + index for index in range(50)]

    assert allan_deviation(series_from(times, [None] * 50)) == ()


def test_every_sample_at_one_instant_returns_nothing_rather_than_dividing_by_zero() -> None:
    assert allan_deviation(series_from([EPOCH] * 40, [1.0] * 40)) == ()


def test_the_table_is_bounded_however_long_the_capture() -> None:
    """A week of one-second readings has nineteen octaves in it. The card is a table on a page,
    not a plot, and past a dozen rows it stops being read."""
    points = allan_deviation(white_phase(20000, 5.0), maximum_points=8)

    assert len(points) <= 8


# ---- Formatting --------------------------------------------------------------------------------


def test_the_mantissa_is_fixed_at_two_decimals() -> None:
    """§10.7.2: σy is **dimensionless**, so where §9.5.3 rule 6 would change the unit down a
    column, the exponent does that job and the mantissa stays comparable row to row."""
    assert AllanPoint(1.0, 1.734e-8, 100).formatted() == f"1.73e{MINUS}8"
    assert AllanPoint(1.0, 2.0e-11, 100).formatted() == f"2.00e{MINUS}11"


def test_the_exponent_sign_is_a_minus_sign_not_a_hyphen() -> None:
    """The same argument the confusables list makes for PRIME and MINUS SIGN."""
    text = AllanPoint(1.0, 4.29e-9, 100).formatted()

    assert MINUS in text
    assert "-" not in text


def test_a_positive_exponent_keeps_its_sign() -> None:
    """So the column aligns. A mantissa with a sign on some rows and not others does not."""
    assert AllanPoint(1.0, 1.5, 10).formatted() == "1.50e+0"


def test_a_mantissa_that_rounds_to_ten_is_normalised() -> None:
    """``9.999e-9`` formats as ``10.00e-9`` without this, which is not scientific notation and
    breaks the column's alignment as well as its meaning."""
    assert AllanPoint(1.0, 9.999e-9, 10).formatted() == f"1.00e{MINUS}8"


def test_a_deviation_of_zero_is_reported_as_zero_not_as_a_dash() -> None:
    """``log10(0)`` is the crash this avoids, but the answer is a measurement rather than a hole:
    every second difference at that τ cancelled, which on quantised data means the instability is
    below the receiver's resolution. §10.7.2 drops a τ the series *cannot support*; this one it
    supported, so it keeps its row and its count."""
    assert AllanPoint(1.0, 0.0, 10).formatted() == "0.00e+0"


def test_a_nonsense_deviation_renders_as_a_dash() -> None:
    """NaN or negative cannot arise from the estimator, but ``AllanPoint`` is a plain dataclass and
    §11.1's discipline is that a renderer takes what it is given."""
    assert AllanPoint(1.0, math.nan, 10).formatted() == MINUS
    assert AllanPoint(1.0, -1.0, 10).formatted() == MINUS


# ---- The summary sentence ----------------------------------------------------------------------


def test_an_empty_table_is_explained_in_words() -> None:
    """§10.7.2: *"When the series is too short for any τ, the card's summary sentence says so in
    words."* Which is the difference between a card that is waiting and one that looks broken."""
    short = series_from([EPOCH, EPOCH + 1.0], [1.0, 2.0])

    assert "not yet enough" in summarise((), short)


def test_no_readings_at_all_says_that_instead() -> None:
    """A different sentence, because it is a different situation: nothing stored versus not enough
    stored, and only one of them is fixed by waiting for this receiver."""
    empty = series_from([EPOCH + index for index in range(5)], [None] * 5)

    assert "No 1 PPS readings" in summarise((), empty)


def test_the_summary_says_whether_averaging_helps() -> None:
    """The question the table exists to answer, in one sentence for someone who will not read a
    column of exponents."""
    points = allan_deviation(white_phase(2000, 10.0))

    assert "improving with averaging" in summarise(points, white_phase(2000, 10.0))
