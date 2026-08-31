"""The §7.3 fast tier's single-value answers.

Every case here uses a response shape actually observed on the reference unit, recorded in
``tests/fixtures/README.md`` — including the leading space, which is the single most likely
thing to break a naive parse and is invisible in a bug report.

The cases from ``ScalarParsersTests.cs`` are carried across one for one. The block at the end
has no counterpart there: they are the strings Python's builtins accept and C#'s
``TryParse`` does not, and they are the reason this module matches a grammar instead of
wrapping ``int()`` in a ``try``.
"""

from __future__ import annotations

import pytest

from smartclock_device.parsing.scalars import (
    parse_boolean,
    parse_decimal,
    parse_first_of_list,
    parse_integer,
    parse_keyword,
    parse_seconds_as_nanoseconds,
)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (" +3", 3),
        ("+3", 3),
        ("  +0", 0),
        (" -12", -12),
        (" +1\r\n", 1),
    ],
)
def test_an_integer_parses_through_its_leading_space_and_explicit_sign(
    response: str, expected: int
) -> None:
    """Responses arrive as ``_+3``, not ``+3``. Trimming in one place is what stops that framing
    artefact reaching six separate call sites."""
    assert parse_integer(response) == expected


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (" -5.4E-009", -5.4e-9),
        (" -1.68245E+001", -16.8245),
        (" +7.70000E-008", 7.7e-8),
        (" 0", 0.0),
    ],
)
def test_a_real_parses_in_the_receivers_scientific_notation(response: str, expected: float) -> None:
    actual = parse_decimal(response)

    assert actual is not None
    assert actual == pytest.approx(expected, abs=1e-12)


def test_the_time_interval_converts_from_seconds_to_nanoseconds() -> None:
    """The receiver answers the time interval in seconds; everything that displays it works in
    nanoseconds. Converting once here keeps the factor of a billion out of the view models."""
    nanoseconds = parse_seconds_as_nanoseconds(" -5.4E-009")

    assert nanoseconds is not None
    assert nanoseconds == pytest.approx(-5.4, abs=1e-9)


def test_a_keyword_is_upper_cased_so_comparisons_do_not_have_to_care() -> None:
    assert parse_keyword(" LOCK") == "LOCK"
    assert parse_keyword("lock") == "LOCK"


def test_the_first_field_of_a_list_is_taken_without_the_rest() -> None:
    """``:SYNC:HOLD:DUR?`` answers ``+6.00000E+002,0`` — a value and a flag. Only the first
    field is the duration."""
    seconds = parse_first_of_list(" +6.00000E+002,0")

    assert seconds is not None
    assert seconds == pytest.approx(600.0, abs=1e-6)


@pytest.mark.parametrize(("response", "expected"), [(" 0", False), (" 1", True), (" +1", True)])
def test_a_boolean_is_spelt_as_zero_or_one(response: str, expected: bool) -> None:
    assert parse_boolean(response) is expected


@pytest.mark.parametrize("response", [None, "", "   ", "E-113", "not a number", "\0\xff"])
def test_an_unparseable_answer_becomes_none_rather_than_an_exception(response: str | None) -> None:
    """Nothing here raises, on the same principle as the screen parser: a poll that raised would
    take down the loop that produced it, and one odd reply an hour would then look like a dead
    application."""
    assert parse_integer(response) is None
    assert parse_decimal(response) is None
    assert parse_seconds_as_nanoseconds(response) is None
    assert parse_first_of_list(response) is None
    assert parse_boolean(response) is None


# ---------------------------------------------------------------------------------------------
# Python's builtins are wider than the receiver's output. These have no counterpart in the C#
# tests because C#'s TryParse rejects them for free; here, each one is a way a corrupted read
# could become a plausible-looking number. See the module docstring in scalars.py.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("response", ["1_0", "+1_0", "1_0.5", "-1_0E+2"])
def test_pep515_digit_separators_are_not_a_receiver_spelling(response: str) -> None:
    """``int("1_0")`` is 10 and ``float("1_0.5")`` is 10.5. The receiver has never emitted an
    underscore, so this can only be damage."""
    assert parse_integer(response) is None
    assert parse_decimal(response) is None


def test_unicode_digits_are_not_a_receiver_spelling() -> None:
    """``int("٣")`` is 3, and ``\\d`` would match it. The grammar spells ``[0-9]`` for this
    reason — see the comment on ``_INTEGER``."""
    assert parse_integer("٣") is None
    assert parse_decimal("٣") is None


@pytest.mark.parametrize("response", ["nan", "NaN", "-nan", "inf", "-inf", "Infinity"])
def test_a_non_finite_literal_is_none_not_a_float(response: str) -> None:
    """``float("nan")`` succeeds, and a NaN reaching §9.10.2's medallion ring propagates
    silently through every calculation downstream of it. It stops here."""
    assert parse_decimal(response) is None
    assert parse_seconds_as_nanoseconds(response) is None
    assert parse_first_of_list(response) is None


def test_an_overflowing_real_is_none_rather_than_infinity() -> None:
    """``float("1E+400")`` is ``inf`` rather than an error."""
    assert parse_decimal("1E+400") is None
    assert parse_decimal("-1E+400") is None


def test_a_real_that_overflows_only_after_the_nanosecond_conversion_is_none() -> None:
    """The seconds value is finite and the nanoseconds value is not. Checking only the input
    would let an infinity out of the second function."""
    assert parse_decimal("1E+300") == pytest.approx(1e300)
    assert parse_seconds_as_nanoseconds("1E+300") is None


@pytest.mark.parametrize("response", ["2147483648", "-2147483649", "99999999999999999999"])
def test_an_integer_outside_the_signed_32_bit_range_is_none(response: str) -> None:
    """C#'s ``int.TryParse`` gives this for free; Python's unbounded ``int`` does not."""
    assert parse_integer(response) is None


@pytest.mark.parametrize("response", ["2147483647", "-2147483648"])
def test_the_edges_of_the_signed_32_bit_range_still_parse(response: str) -> None:
    """Guarding the guard: a bound that excluded its own endpoints would pass every test above
    while quietly dropping legitimate values."""
    assert parse_integer(response) == int(response)


@pytest.mark.parametrize("response", ["-5,4", "1.234,5", " 3,0"])
def test_a_comma_decimal_spelling_is_rejected_rather_than_reinterpreted(response: str) -> None:
    """The receiver is not localised. The danger in C# was parsing its output *against* a
    comma-decimal culture; in Python the builtins ignore the locale, so the danger is the
    mirror image — a comma arriving from a corrupted read and being silently truncated at the
    separator. ``parse_first_of_list`` is the one function for which a comma is meaningful."""
    assert parse_decimal(response) is None
    assert parse_integer(response) is None


def test_a_boolean_follows_the_integer_grammar_and_not_pythons_truthiness() -> None:
    """``bool("false")`` is ``True``. The receiver spells this ``0`` or ``1`` and nothing else."""
    assert parse_boolean("false") is None
    assert parse_boolean("true") is None
    assert parse_boolean(" -1") is True
