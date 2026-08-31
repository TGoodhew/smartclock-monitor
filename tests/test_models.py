"""The model layer: the rollover arithmetic, the figure-of-merit tables, and the clock.

The status screen parser is tested against the captured fixtures; these are the pieces it is
built out of, tested where their behaviour is decidable without a screen.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType

import pytest

from smartclock_device.clock import Clock, FixedClock, SystemClock
from smartclock_device.models import gps_week_rollover
from smartclock_device.models.figures_of_merit import pll_detail, pll_state, time_error
from smartclock_device.models.receiver_status import ReceiverStatus
from smartclock_device.models.satellite import TrackedSatellite

# ---- The rollover -------------------------------------------------------------------------


def test_an_epoch_is_1024_weeks() -> None:
    """§7.4's period, in the units the specification states it in rather than in days."""
    assert timedelta(weeks=1024) == gps_week_rollover.EPOCH


def test_correcting_advances_by_whole_epochs() -> None:
    reported = datetime(2006, 12, 27, 5, 10, 4, tzinfo=UTC)

    corrected = gps_week_rollover.correct(reported, 1)

    assert corrected == reported + timedelta(weeks=1024)


def test_two_epochs_advance_twice_as_far() -> None:
    """A receiver old enough to have wrapped twice is not a hypothetical; the first rollover was
    in 1999 and the second in 2019."""
    reported = datetime(2000, 1, 1, tzinfo=UTC)

    corrected = gps_week_rollover.correct(reported, 2)

    assert corrected == reported + timedelta(weeks=2048)


@pytest.mark.parametrize("epochs", [0, -1])
def test_no_correction_returns_none_rather_than_the_input(epochs: int) -> None:
    """Zero returns ``None`` rather than the value unchanged: no correction applies, and handing
    back the input would imply one was computed and came to nothing. The caller distinguishes
    "corrected to this" from "nothing to correct", and §7.4 requires the UI to badge only the
    first."""
    assert gps_week_rollover.correct(datetime(2006, 12, 27, tzinfo=UTC), epochs) is None


def test_nothing_to_correct_is_none() -> None:
    assert gps_week_rollover.correct(None, 1) is None


# ---- The figure-of-merit tables ------------------------------------------------------------


@pytest.mark.parametrize(
    ("tfom", "expected"),
    [(0, "less than 1 ns"), (3, "100 ns – 1 µs"), (9, "more than 100 ms")],
)
def test_a_tfom_names_its_time_error_range(tfom: int, expected: str) -> None:
    assert time_error(tfom) == expected


@pytest.mark.parametrize("tfom", [-1, 10, None])
def test_a_tfom_outside_the_table_has_no_range(tfom: int | None) -> None:
    """A receiver reporting one is not a parse failure — the value is simply not one the guide
    documents, and inventing a range for it would be worse than showing an em dash."""
    assert time_error(tfom) is None


def test_the_two_unlocked_ffoms_are_not_interchangeable() -> None:
    """FFOM 2 and 3 are both "PLL unlocked". 2 is holdover, where the output starts within
    specification and drifts out; 3 is unlocked while *not* in holdover, which the guide answers
    with "do not use the output". Collapsing them would tell a user in holdover to stop using an
    output that is currently fine."""
    assert pll_state(2) != pll_state(3)
    assert pll_detail(2) != pll_detail(3)

    holdover = pll_state(2)
    unlocked = pll_state(3)
    assert holdover is not None and "holdover" in holdover
    assert unlocked is not None and "do not use" in unlocked


@pytest.mark.parametrize("ffom", [-1, 4, None])
def test_an_ffom_outside_the_table_has_no_state(ffom: int | None) -> None:
    assert pll_state(ffom) is None
    assert pll_detail(ffom) is None


def test_the_documented_ranges_are_covered_end_to_end() -> None:
    """The guide documents TFOM 0–9 and FFOM 0–3, and a hole in either table would show as an em
    dash on a value the receiver is entitled to report. 0, 1 and 2 are the ones to watch: they
    are "not presently used in the 58503A and 59551A products", so they are the entries a tidy-up
    would remove — and the Z3805A's firmware is a sibling rather than the exact product the guide
    describes."""
    assert all(time_error(tfom) is not None for tfom in range(10))
    assert all(pll_state(ffom) is not None for ffom in range(4))
    assert all(pll_detail(ffom) is not None for ffom in range(4))


# ---- The clock ----------------------------------------------------------------------------


def test_both_clocks_satisfy_the_protocol() -> None:
    """The protocol is what the device layer takes; if an implementation stopped matching it,
    every injection site would still type-check against the concrete class it happened to use."""
    assert isinstance(SystemClock(), Clock)
    assert isinstance(FixedClock(datetime(2026, 8, 12, tzinfo=UTC)), Clock)


def test_the_system_clock_answers_in_utc_and_aware() -> None:
    """Naive against aware raises ``TypeError`` on comparison, and §11.1 forbids the parser from
    raising. So awareness is not a nicety here — it is the thing that keeps the rollover
    comparison from being an exception."""
    now = SystemClock().utc_now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_a_fixed_clock_does_not_move_on_its_own() -> None:
    pinned = datetime(2026, 8, 12, 9, 30, tzinfo=UTC)
    clock = FixedClock(pinned)

    assert clock.utc_now() == pinned
    assert clock.utc_now() == pinned

    clock.advance(timedelta(hours=2))
    assert clock.utc_now() == pinned + timedelta(hours=2)


def test_a_fixed_clock_refuses_a_naive_instant() -> None:
    """Accepting one would push the ``TypeError`` to the first comparison, which is a long way
    from the line that caused it."""
    with pytest.raises(ValueError, match="aware"):
        FixedClock(datetime(2026, 8, 12))


def test_a_fixed_clock_normalises_to_utc() -> None:
    """A test that pins the clock in a local zone still gets a UTC answer, so nothing downstream
    has to ask which zone it was handed."""
    chatham = timezone(timedelta(hours=12, minutes=45))
    clock = FixedClock(datetime(2026, 8, 12, 9, 30, tzinfo=chatham))

    assert clock.utc_now().utcoffset() == timedelta(0)
    assert clock.utc_now() == datetime(2026, 8, 11, 20, 45, tzinfo=UTC)


# ---- The status record --------------------------------------------------------------------


def test_a_status_is_immutable() -> None:
    """§6.4: one screen is one value. The polling loop replaces it rather than mutating it, which
    is what makes it safe to hand to the UI thread without copying."""
    status = ReceiverStatus(captured_at=datetime(2026, 8, 12, tzinfo=UTC))

    with pytest.raises(FrozenInstanceError):
        status.tfom = 3  # type: ignore[misc]


def test_a_status_defaults_to_knowing_nothing() -> None:
    """Every field an unparsed screen leaves out is ``None`` or its unknown member — never a
    plausible zero. A TFOM defaulting to 0 would read as the best possible time error."""
    status = ReceiverStatus(captured_at=datetime(2026, 8, 12, tzinfo=UTC))

    assert status.tfom is None
    assert status.ffom is None
    assert status.position is None
    assert status.tracked == ()
    assert status.parse_warnings == ()


def test_health_items_are_matched_without_regard_to_case() -> None:
    """The C# original keys this ``OrdinalIgnoreCase``; Python has no case-insensitive mapping,
    so the folding lives in the accessor and the mapping keeps the device's own spelling."""
    status = ReceiverStatus(
        captured_at=datetime(2026, 8, 12, tzinfo=UTC),
        health_items=MappingProxyType({"Power Supplies": True, "Oscillator": False}),
    )

    assert status.health_item("power supplies") is True
    assert status.health_item("OSCILLATOR") is False
    assert list(status.health_items) == ["Power Supplies", "Oscillator"]


def test_an_unlisted_health_item_is_none_and_not_a_failure() -> None:
    """Not the same as listing it as failed — a family that has no oscillator-oven item has not
    got a cold oven."""
    status = ReceiverStatus(captured_at=datetime(2026, 8, 12, tzinfo=UTC))

    assert status.health_item("Oven") is None


def test_satellites_are_immutable_values() -> None:
    satellite = TrackedSatellite(prn=15, elevation_degrees=42, azimuth_degrees=210)

    assert satellite.signal_strength is None
    with pytest.raises(FrozenInstanceError):
        satellite.prn = 16  # type: ignore[misc]
