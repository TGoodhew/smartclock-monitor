"""§10.7.1's drift fit and the advisory built on it.

**The refusals get as many tests as the arithmetic.** A fit that produces a number for every input
is the failure this card was specified to avoid, so the cases that must come back empty-handed —
too few readings, a slope lost in the scatter, a window too short to separate a daily term — are
asserted as carefully as the ones that produce a figure.

The synthetic series are built from a known slope so the recovered one can be checked against it.
That is the only way to tell a fit that works from one that returns something plausible.
"""

from __future__ import annotations

import math
from array import array
from datetime import timedelta

import pytest

from conftest import NOW
from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_monitor.services.drift import (
    EFC_AT_FULL_SCALE_BIT,
    EFC_NEAR_FULL_SCALE_BIT,
    PPM_PER_PERCENT,
    SEPARABLE,
    advise,
    fit_drift,
    project,
)
from smartclock_monitor.services.trend_store import Series
from smartclock_monitor.themes.severity import Severity

MINUS = "\N{MINUS SIGN}"


def series(
    *,
    hours: float,
    count: int,
    start_percent: float = -16.83,
    ppm_per_day: float = 0.0,
    diurnal_ppm: float = 0.0,
    noise_ppm: float = 0.0,
    mode: SmartClockMode = SmartClockMode.LOCKED,
    ending_at: float = 0.0,
) -> Series:
    """A synthetic EFC series with a known slope, daily term and repeatable scatter."""
    end = (NOW + timedelta(seconds=ending_at)).timestamp()
    start = end - hours * 3600.0
    step = (end - start) / max(1, count - 1)

    at = array("d")
    efc = array("d")
    for index in range(count):
        moment = start + index * step
        days = (moment - start) / 86_400.0
        value = start_percent + (ppm_per_day / PPM_PER_PERCENT) * days
        value += (diurnal_ppm / PPM_PER_PERCENT) * math.sin(2.0 * math.pi * days)
        # Deterministic, mean-free-ish scatter. A seeded generator would do, but this keeps the
        # test independent of the random module's stability across releases.
        value += (noise_ppm / PPM_PER_PERCENT) * math.sin(index * 2.399963)
        at.append(moment)
        efc.append(value)

    return Series(
        at=at,
        ti_nanoseconds=array("d", [0.0] * count),
        efc_percent=efc,
        mode=tuple([mode] * count),
        requested=timedelta(hours=hours),
    )


# ---- The fit -----------------------------------------------------------------------------------


def test_a_known_slope_comes_back() -> None:
    """The one test that separates a working fit from one that returns something plausible."""
    fit = fit_drift(series(hours=48, count=2000, ppm_per_day=-8.6))

    assert fit is not None
    assert fit.slope_ppm_per_day == pytest.approx(-8.6, abs=0.05)


def test_the_slope_survives_scatter_much_larger_than_itself() -> None:
    """#182's measured case: −8.6 ppm/day of drift under 32.4 ppm of unexplained scatter. If the
    fit could not do this the card would have nothing to say about a healthy oscillator."""
    fit = fit_drift(series(hours=48, count=4000, ppm_per_day=-8.6, noise_ppm=32.4))

    assert fit is not None
    assert fit.slope_ppm_per_day == pytest.approx(-8.6, abs=1.5)
    assert fit.residual_ppm == pytest.approx(32.4, rel=0.3)


def test_a_daily_swing_is_recovered_separately_from_the_trend() -> None:
    """§10.7.1 reports them separately because they are different claims. A fit that folded the
    daily term into the slope would report a drift that reversed sign every twelve hours."""
    fit = fit_drift(series(hours=72, count=3000, ppm_per_day=-8.6, diurnal_ppm=3.4))

    assert fit is not None
    assert fit.diurnal_ppm is not None
    assert fit.diurnal_ppm == pytest.approx(3.4, abs=0.5)
    assert fit.slope_ppm_per_day == pytest.approx(-8.6, abs=0.5)


def test_a_daily_swing_is_not_reported_under_a_day_of_data() -> None:
    """§10.7.1: below a day the fit drops to a plain line and says so, *rather than reporting a
    daily amplitude of zero — which would be a measurement*."""
    fit = fit_drift(series(hours=6, count=600, ppm_per_day=-8.6))

    assert fit is not None
    assert fit.diurnal_ppm is None


def test_the_separability_threshold_is_one_whole_cycle() -> None:
    """Just under a day gets a plain line; just over gets the daily term. The boundary is where
    #184's contradictory sentence came from, so it is pinned rather than left implied."""
    under = fit_drift(series(hours=23.9, count=1200, ppm_per_day=-8.6))
    over = fit_drift(series(hours=24.2, count=1200, ppm_per_day=-8.6))

    assert under is not None and under.diurnal_ppm is None
    assert over is not None and over.diurnal_ppm is not None
    assert timedelta(days=1) == SEPARABLE


def test_too_few_readings_is_none_rather_than_a_flat_fit() -> None:
    """A different answer from "the oscillator is not drifting", and the caller must be able to
    tell them apart — one is a measurement and the other is an absence of one."""
    assert fit_drift(series(hours=1, count=2)) is None
    assert fit_drift(series(hours=0, count=0)) is None


def test_a_window_at_one_instant_does_not_raise() -> None:
    """Every sample at one time makes the normal equations singular. That is a window that cannot
    answer the question, not an error to propagate into a paint event."""
    frozen = series(hours=0, count=50)

    assert fit_drift(frozen) is None


def test_holes_are_skipped_rather_than_fitted() -> None:
    """§11.1: EFC can be ``None`` for any reading. NaN would propagate through every sum and give
    a fit of NaN with no error raised anywhere — a card full of "nan ppm/day"."""
    window = series(hours=48, count=1000, ppm_per_day=-8.6)
    for index in range(0, 1000, 7):
        window.efc_percent[index] = math.nan

    fit = fit_drift(window)

    assert fit is not None
    assert math.isfinite(fit.slope_ppm_per_day)
    assert fit.count == 1000 - len(range(0, 1000, 7))


def test_settling_samples_are_excluded_and_counted() -> None:
    """§10.7.1: the first 24 h after a power-up bend the fit, so they are dropped — and the count
    of them is shown, because a fit that quietly discarded half its input would be reporting a
    different window from the one it named."""
    window = series(hours=48, count=2000, ppm_per_day=-8.6)
    boundary = window.moment_at(500)

    fit = fit_drift(window, settling_until=boundary)

    assert fit is not None
    assert fit.excluded_settling == 500
    assert fit.count == 1500
    assert fit.span < timedelta(hours=48)


def test_excluding_everything_is_none_rather_than_a_crash() -> None:
    """A window entirely inside a settling period. It has nothing to say and must say nothing."""
    window = series(hours=6, count=600)

    assert fit_drift(window, settling_until=NOW + timedelta(days=1)) is None


def test_the_fit_is_numerically_sound_at_epoch_scale() -> None:
    """Epoch seconds are around 1.8e9 and the spans here are hours, so an uncentred fit asks the
    solver to separate a slope from an intercept differing by ten orders of magnitude — badly, in
    the last digits, exactly where the answer lives. This is the assertion that catches a
    regression to an uncentred design matrix."""
    fit = fit_drift(series(hours=1, count=3600, ppm_per_day=-0.5))

    assert fit is not None
    assert fit.slope_ppm_per_day == pytest.approx(-0.5, abs=0.01)


# ---- The projection ----------------------------------------------------------------------------


def test_a_clear_trend_projects_to_a_rail() -> None:
    """Fast enough to reach the rail inside the horizon, and clean enough for the slope to clear
    its own error."""
    fit = fit_drift(series(hours=48, count=3000, start_percent=-90.0, ppm_per_day=-2000.0))
    assert fit is not None

    projection = project(fit, NOW)

    assert projection is not None
    assert projection.rail_percent == -100.0
    # -2000 ppm/day is -0.2 %/day. The fit ends near -90.4 %, so the -100 % rail is 48 days out.
    assert projection.days == pytest.approx(48.0, rel=0.05)
    assert projection.when == NOW + timedelta(days=projection.days)


def test_a_flat_trend_gets_no_projection() -> None:
    """§10.7.1: the advisory *withholds the projection where the window cannot support one*. A
    slope indistinguishable from zero produces a date invented out of scatter."""
    fit = fit_drift(series(hours=48, count=3000, ppm_per_day=0.0, noise_ppm=30.0))
    assert fit is not None

    assert project(fit, NOW) is None


def test_a_slope_lost_in_its_own_scatter_gets_no_projection() -> None:
    """The case that matters: a real but tiny slope under heavy noise. The fit still reports the
    slope — it is the best estimate — but refuses to forecast from it."""
    fit = fit_drift(series(hours=6, count=200, ppm_per_day=0.4, noise_ppm=400.0))
    assert fit is not None

    assert abs(fit.slope_ppm_per_day) < 2.0 * fit.slope_error_ppm_per_day
    assert project(fit, NOW) is None


def test_a_rate_that_would_take_centuries_gets_no_projection() -> None:
    """A date four hundred years out is a flat oscillator described at great length."""
    fit = fit_drift(series(hours=48, count=4000, start_percent=-16.83, ppm_per_day=-0.05))
    assert fit is not None

    assert project(fit, NOW) is None


# ---- The words ---------------------------------------------------------------------------------


def test_the_advisory_reports_in_ppm_not_per_cent() -> None:
    """#182: in per cent, a drift of −0.00086 %/day, a swing of 0.00034 % and a residual of
    0.00324 % all printed as zero or nearly so, and the card could not say that a double-oven
    oscillator holding 0.05 % of range across two days is the *good* case."""
    advisory = advise(
        series(hours=48, count=3000, ppm_per_day=-8.6, diurnal_ppm=3.4, noise_ppm=32.4), now=NOW
    )
    text = " ".join(advisory.lines)

    assert "ppm/day" in text
    assert f"{MINUS}8" in text or f"{MINUS}9" in text
    assert "0.00" not in text.split("ppm/day")[0]


def test_a_negative_drift_is_typeset_with_a_minus_sign() -> None:
    """§9.5.3, and the same argument the confusables list makes: a hyphen is not a minus."""
    advisory = advise(series(hours=48, count=2000, ppm_per_day=-8.6), now=NOW)

    assert MINUS in advisory.lines[0]


def test_the_span_is_rounded_down_never_across_the_threshold() -> None:
    """#184, exactly. A 23.98-hour span rounded to nearest reads "24.0 hours" beside a verdict
    saying a daily swing cannot be separated in under a day of data — a label and a verdict
    contradicting each other in one sentence."""
    advisory = advise(series(hours=23.98, count=2000, ppm_per_day=-8.6), now=NOW)
    evidence = next(line for line in advisory.lines if "spanning" in line)

    assert "23.9 hours" in evidence
    assert "24.0 hours" not in evidence
    assert "cannot be separated" in " ".join(advisory.lines)


def test_the_daily_swing_says_it_was_inferred() -> None:
    """§10.7.1: *"a user who reads 'diurnal' will otherwise assume something measured it"* — and
    there is no internal temperature query on this receiver."""
    advisory = advise(series(hours=72, count=3000, diurnal_ppm=3.4), now=NOW)
    text = " ".join(advisory.lines)

    assert "inferred" in text
    assert "no temperature is reported" in text


def test_the_advisory_hedges_rather_than_asserts() -> None:
    """§10.7.1: *"It is consistent-with, never is."*"""
    advisory = advise(
        series(hours=48, count=3000, start_percent=-90.0, ppm_per_day=-2000.0), now=NOW
    )
    text = " ".join(advisory.lines)

    assert "consistent with" in text
    assert "will reach" not in text


def test_settled_readings_are_named_as_settled() -> None:
    window = series(hours=48, count=2000, ppm_per_day=-8.6)
    advisory = advise(window, now=NOW, settling_until=window.moment_at(400))
    evidence = next(line for line in advisory.lines if "settled" in line)

    assert "1,600 settled readings" in evidence
    assert "400 excluded" in evidence


def test_too_little_history_says_so_and_stays_neutral() -> None:
    """Not a success and not a warning. §9.4.3's NEUTRAL is for "unknown, not applicable", which
    is exactly what an unfitted window is."""
    advisory = advise(series(hours=1, count=2), now=NOW)

    assert advisory.severity is Severity.NEUTRAL
    assert advisory.fit is None
    assert "too few stored readings" in advisory.lines[0]


# ---- The hardware bits, which outrank the fit --------------------------------------------------


def test_an_unread_register_is_not_reported_as_clear() -> None:
    """An unread bit and a clear bit are different facts, and reporting the first as the second is
    how an alarm gets missed. The poll loop does not read the status registers yet, so this is the
    state the card is actually in today."""
    advisory = advise(series(hours=48, count=2000), now=NOW, register_bits=None)

    assert "have not been read" in " ".join(advisory.lines)
    assert "both clear" not in " ".join(advisory.lines)


def test_a_clear_register_is_reported_as_clear() -> None:
    advisory = advise(series(hours=48, count=2000), now=NOW, register_bits=[False] * 8)

    assert "both clear" in " ".join(advisory.lines)
    assert advisory.severity is Severity.SUCCESS


def test_bit_7_is_critical_however_flat_the_trend_looks() -> None:
    """§10.7.1: *"Hardware register bits 6 and 7 … are the alarm; the slope is the gauge."* The
    hardware is reporting a state and the fit is inferring one, so a set bit outranks it."""
    bits = [False] * 8
    bits[EFC_AT_FULL_SCALE_BIT] = True

    advisory = advise(series(hours=48, count=2000, ppm_per_day=0.0), now=NOW, register_bits=bits)

    assert advisory.severity is Severity.CRITICAL
    assert "full scale" in advisory.headline
    assert "bit 7 is set" in " ".join(advisory.lines)


def test_bit_6_is_a_caution() -> None:
    bits = [False] * 8
    bits[EFC_NEAR_FULL_SCALE_BIT] = True

    advisory = advise(series(hours=48, count=2000), now=NOW, register_bits=bits)

    assert advisory.severity is Severity.CAUTION
    assert "near full scale" in advisory.headline


def test_a_healthy_oscillator_reads_as_nothing_remarkable() -> None:
    """The wireframe's own wording, and the case the card is in almost all of the time."""
    advisory = advise(
        series(hours=48, count=3000, ppm_per_day=-8.6, noise_ppm=32.4),
        now=NOW,
        register_bits=[False] * 8,
    )

    assert advisory.severity is Severity.SUCCESS
    assert advisory.headline == "Nothing remarkable"
