"""Rendering decimal degrees back into the degrees–minutes–seconds form §10.6 shows.

The carry is the whole difficulty. Rounding seconds to three decimals can produce 60.000, which
is the next minute rather than a number of seconds, and that carry can cascade into the degree.
Getting it wrong shifts a position by a minute of arc — about 1.8 km of latitude — silently, in
the one field a timing receiver exists to hold fixed.

Ported from ``CoordinatesTests.cs``. The rounding-mode test at the end has no counterpart there:
C# asks for ``MidpointRounding.AwayFromZero`` explicitly, and Python's ``round`` would quietly
give the other answer.
"""

from __future__ import annotations

import math

import pytest

from smartclock_device.models.coordinates import latitude, longitude, split


def test_the_fixture_position_round_trips_to_what_the_receiver_printed() -> None:
    """The captured fixture's own position, printed by the receiver as ``N  47:31:18.822`` /
    ``W 122:12:22.152``."""
    assert latitude(47 + 31 / 60.0 + 18.822 / 3600.0) == "N 47° 31′ 18.822″"
    assert longitude(-(122 + 12 / 60.0 + 22.152 / 3600.0)) == "W 122° 12′ 22.152″"


@pytest.mark.parametrize(
    ("degrees", "expected"),
    [
        (47.5, "N 47° 30′ 00.000″"),
        (-47.5, "S 47° 30′ 00.000″"),
        (0.0, "N 0° 00′ 00.000″"),
        (90.0, "N 90° 00′ 00.000″"),
    ],
)
def test_latitude_carries_its_hemisphere(degrees: float, expected: str) -> None:
    assert latitude(degrees) == expected


@pytest.mark.parametrize(
    ("degrees", "expected"),
    [
        (122.25, "E 122° 15′ 00.000″"),
        (-122.25, "W 122° 15′ 00.000″"),
        (180.0, "E 180° 00′ 00.000″"),
    ],
)
def test_longitude_carries_its_hemisphere(degrees: float, expected: str) -> None:
    assert longitude(degrees) == expected


def test_zero_is_on_the_positive_side() -> None:
    """There is no negative zero hemisphere. A receiver sitting on the equator or the prime
    meridian must not flip its letter on measurement noise."""
    for rendered in (latitude(0.0), latitude(-0.0)):
        assert rendered is not None
        assert rendered.startswith("N")

    prime_meridian = longitude(0.0)
    assert prime_meridian is not None
    assert prime_meridian.startswith("E")


def test_seconds_rounding_to_sixty_carry_into_the_minute() -> None:
    """The failure this guards against does not look like a bug — it prints ``47° 31′ 60.000″``,
    which is a real-looking coordinate that no instrument would ever display."""
    degrees = 47 + 31 / 60.0 + 59.9996 / 3600.0

    assert latitude(degrees) == "N 47° 32′ 00.000″"


def test_the_carry_cascades_through_the_minute_into_the_degree() -> None:
    """47° 59′ 59.9999″ — the seconds carry, then the minutes carry."""
    degrees = 47 + 59 / 60.0 + 59.9999 / 3600.0

    assert latitude(degrees) == "N 48° 00′ 00.000″"


def test_a_carry_to_exactly_the_pole_is_still_valid() -> None:
    """A carry at exactly the pole produces 90° 00′ 00.000″, which is legitimate; one past it
    must not be rounded back into range and presented as if it were fine."""
    degrees = 89 + 59 / 60.0 + 59.9999 / 3600.0

    assert latitude(degrees) == "N 90° 00′ 00.000″"


@pytest.mark.parametrize("degrees", [91.0, -90.5, math.nan, math.inf, -math.inf, None])
def test_an_impossible_latitude_has_no_rendering(degrees: float | None) -> None:
    """§11.1 forbids raising anywhere in this path, so a value past the pole degrades to no value
    exactly as an unparsed field does. It cannot be rendered honestly and must not be guessed."""
    assert latitude(degrees) is None


@pytest.mark.parametrize("degrees", [181.0, -180.5, None])
def test_an_impossible_longitude_has_no_rendering(degrees: float | None) -> None:
    assert longitude(degrees) is None


def test_the_marks_are_typographic() -> None:
    """Prime and double prime, not apostrophe and quotation mark. The typewriter marks are a
    different pair of characters and read as a quotation in the middle of a number."""
    rendered = latitude(47.5)

    assert rendered is not None
    assert "′" in rendered
    assert "″" in rendered
    assert "'" not in rendered
    assert '"' not in rendered


def test_minutes_and_seconds_are_zero_padded() -> None:
    """Fixed widths, so a column of coordinates stays aligned (§9.5.3). Degrees are not padded:
    they are the significant part."""
    assert latitude(5 + 4 / 60.0 + 3.2 / 3600.0) == "N 5° 04′ 03.200″"


def test_split_reports_the_components() -> None:
    parts = split(-47.5, "N", "S", 90)

    assert parts is not None
    assert parts.hemisphere == "S"
    assert parts.degrees == 47
    assert parts.minutes == 30
    assert parts.seconds == pytest.approx(0.0, abs=1e-3)


def test_a_hemisphere_letter_is_required() -> None:
    """The one place in this module that raises, and it is a programming error rather than a
    parse failure — an empty hemisphere letter would render a coordinate with no side."""
    with pytest.raises(ValueError, match="hemisphere"):
        split(47.5, "", "S", 90)


# ---------------------------------------------------------------------------------------------
# No counterpart in the C# tests.
# ---------------------------------------------------------------------------------------------


def test_the_midpoint_rounds_away_from_zero_and_not_to_even() -> None:
    """Python's ``round`` is banker's rounding: ``round(0.0005, 3)`` is 0.0, not 0.001. C# asks
    for ``MidpointRounding.AwayFromZero`` here, and taking Python's default would put every other
    midpoint half a millisecond of arc away from what the Windows build renders — a quiet,
    permanent disagreement between the two implementations on the same input.

    The midpoint has to be one binary floating point can hold exactly, or the test proves
    nothing: 0.0025 looks like a midpoint and is actually 0.00250000000000000005, which is above
    the line, so ``round`` and away-from-zero agree on it by luck. 0.0625 is 1/16 and is exact.
    ``round(0.0625, 3)`` is 0.062; away from zero gives 0.063.
    """
    exact_midpoint_seconds = 0.0625
    parts = split(exact_midpoint_seconds / 3600.0, "N", "S", 90)

    assert parts is not None
    assert parts.seconds == pytest.approx(0.063, abs=1e-9)
    assert round(exact_midpoint_seconds, 3) == 0.062, (
        "The premise of this test has changed: Python's round no longer disagrees here, so it "
        "would pass whichever rounding mode coordinates.py used."
    )
