"""The diagnostic log parser: the guide's documented form, and the form the bench unit actually
sends.

The two differ, and the difference is the whole design of :func:`parse_all`. The guide (Command
Reference 5-33) describes ``:DIAG:LOG:READ:ALL?`` as quoted strings separated by commas; the
Z3805A returns them unquoted, wrapped across lines, and its messages contain commas of their own.
Splitting on commas cut "Holdover started, not tracking GPS" in half and left the second piece
masquerading as an entry — so the boundary is the ``Log NNN:`` prefix, which every entry starts
with and no message contains.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from smartclock_device.parsing import diagnostic_log

# ---- One entry ----------------------------------------------------------------------------


def test_the_documented_form_parses_whole() -> None:
    """The guide's own example shape: ``Log NNN: YYYYMMDD.HH:MM:SS: <log_message>``."""
    entry = diagnostic_log.parse("Log 001: 20060101.05:10:04: Power on")

    assert entry.number == 1
    assert entry.timestamp == datetime(2006, 1, 1, 5, 10, 4, tzinfo=UTC)
    assert entry.message == "Power on"
    assert entry.is_structured is True


def test_the_raw_text_is_kept_whole() -> None:
    """§11.1's rule that the parser never raises is only useful if what it could not parse
    survives — and the export writes this field."""
    line = "Log 001: 20060101.05:10:04: Power on"

    assert diagnostic_log.parse(line).raw_text == line


def test_a_quoted_entry_is_unquoted() -> None:
    """The guide's form arrives quoted; the bench unit's does not. Both are accepted."""
    entry = diagnostic_log.parse('"Log 012: 20060102.03:04:05: Locked to GPS"')

    assert entry.number == 12
    assert entry.message == "Locked to GPS"


def test_a_message_containing_a_colon_survives_intact() -> None:
    """The timestamp is taken by fixed width rather than by splitting on colons, which is what
    makes this work — the timestamp has two of its own."""
    entry = diagnostic_log.parse("Log 007: 20060101.05:10:04: Oscillator: warm")

    assert entry.message == "Oscillator: warm"
    assert entry.timestamp == datetime(2006, 1, 1, 5, 10, 4, tzinfo=UTC)


def test_a_message_containing_a_comma_survives_intact() -> None:
    """The entry the unit emits constantly, and the one that broke a comma-splitting parser."""
    entry = diagnostic_log.parse("Log 143: 20060102.03:04:05: Holdover started, not tracking GPS")

    assert entry.message == "Holdover started, not tracking GPS"


def test_the_timestamp_is_aware_so_it_can_meet_the_status_screen_s() -> None:
    """A naive value cannot be compared or differenced against the aware instants the status screen
    parser produces without raising ``TypeError``, and §11.1 forbids raising. The tag is a Python
    necessity, not a claim about the receiver's time scale."""
    entry = diagnostic_log.parse("Log 001: 20060101.05:10:04: Power on")

    assert entry.timestamp is not None
    assert entry.timestamp.tzinfo is not None


def test_a_rollover_correction_applies_to_a_log_timestamp() -> None:
    """The second of the two callers §7.4's module docstring names. This is what the aware tag is
    for: the arithmetic has to work on both sources."""
    from smartclock_device.models import gps_week_rollover

    entry = diagnostic_log.parse("Log 001: 20060101.05:10:04: Power on")
    corrected = gps_week_rollover.correct(entry.timestamp, 1)

    assert corrected is not None
    assert corrected == datetime(2025, 8, 17, 5, 10, 4, tzinfo=UTC)


# ---- Degrading rather than raising ---------------------------------------------------------


def test_a_line_with_no_prefix_keeps_its_text_and_loses_only_the_prefix() -> None:
    """A firmware revision that reorders the prefix must cost the user the sort order, not the
    log."""
    entry = diagnostic_log.parse("Something the receiver said")

    assert entry.raw_text == "Something the receiver said"
    assert entry.message == "Something the receiver said"
    assert entry.number is None
    assert entry.timestamp is None
    assert entry.is_structured is False


def test_a_prefix_with_an_unreadable_timestamp_keeps_the_number() -> None:
    entry = diagnostic_log.parse("Log 042: not-a-timestamp: Power on")

    assert entry.number == 42
    assert entry.timestamp is None
    assert entry.message == "not-a-timestamp: Power on"


def test_a_timestamp_of_the_right_shape_but_an_impossible_date_is_none() -> None:
    """20061301 is the thirteenth month. The shape matched; the value did not make a date."""
    entry = diagnostic_log.parse("Log 042: 20061301.05:10:04: Power on")

    assert entry.number == 42
    assert entry.timestamp is None


def test_a_misaligned_timestamp_is_rejected_rather_than_coerced() -> None:
    """``strptime`` is wider than the guide's fixed-width layout — its ``%m`` and ``%d`` accept one
    digit as readily as two — so the shape is matched before it is converted. A timestamp that is
    nearly right is worse than none: ``None`` renders as ``—``, a wrong date is read as fact."""
    entry = diagnostic_log.parse("Log 042: 2006011.05:10:040: Power on")

    assert entry.timestamp is None


def test_a_non_ascii_digit_is_not_a_digit() -> None:
    """``\\d`` matches every Unicode decimal digit and so does ``int()``; the receiver emits
    ASCII."""
    entry = diagnostic_log.parse("Log 042: ٢٠٠٦٠١٠١.05:10:04: Power on")

    assert entry.timestamp is None


def test_a_truncated_entry_keeps_what_there_was() -> None:
    entry = diagnostic_log.parse("Log 042: short")

    assert entry.number == 42
    assert entry.timestamp is None
    assert entry.message == "short"


def test_a_prefix_with_no_number_still_finds_the_rest() -> None:
    entry = diagnostic_log.parse("Log: 20060101.05:10:04: Power on")

    assert entry.number is None
    assert entry.timestamp == datetime(2006, 1, 1, 5, 10, 4, tzinfo=UTC)
    assert entry.message == "Power on"


@pytest.mark.parametrize("line", [None, "", "   ", '""'])
def test_an_empty_line_is_an_empty_entry(line: str | None) -> None:
    entry = diagnostic_log.parse(line)

    assert entry.message == ""
    assert entry.is_structured is False


@pytest.mark.parametrize(
    "line",
    [
        "Log",
        "Log ",
        "Log:",
        "Log 1:",
        "Log 99999999999999999999: x",
        ":",
        '"',
        '""""',
        "\x00\x01\x02",
        "Log 1: " + "x" * 5000,
        "\r\n",
        "Log 1: 20060101.05:10:04:",
    ],
)
def test_nothing_raises_whatever_arrives(line: str) -> None:
    """§11.1. Every one of these is a shape a truncated read can produce."""
    entry = diagnostic_log.parse(line)

    assert isinstance(entry.message, str)


# ---- The whole log ------------------------------------------------------------------------


def test_the_guide_s_quoted_comma_separated_form_splits() -> None:
    response = '"Log 001: 20060101.05:10:04: Power on","Log 002: 20060101.05:10:05: GPS acquired"'

    entries = diagnostic_log.parse_all(response)

    assert len(entries) == 2
    assert entries[0].number == 1
    assert entries[0].message == "Power on"
    assert entries[1].number == 2
    assert entries[1].message == "GPS acquired"


def test_the_bench_unit_s_unquoted_wrapped_form_splits() -> None:
    """Unquoted, one per line, which is what the Z3805A actually sends."""
    response = (
        "Log 143: 20060102.03:04:05: Holdover started, not tracking GPS\r\n"
        "Log 144: 20060102.03:14:05: Locked to GPS\r\n"
    )

    entries = diagnostic_log.parse_all(response)

    assert len(entries) == 2
    assert entries[0].message == "Holdover started, not tracking GPS"
    assert entries[1].message == "Locked to GPS"


def test_a_comma_inside_a_message_never_becomes_a_boundary() -> None:
    """The defect this parser was rewritten for: splitting on commas cut this entry in half and
    left "not tracking GPS" masquerading as an entry of its own."""
    response = "Log 143: 20060102.03:04:05: Holdover started, not tracking GPS"

    entries = diagnostic_log.parse_all(response)

    assert len(entries) == 1
    assert entries[0].message == "Holdover started, not tracking GPS"


def test_the_prefix_is_matched_however_it_is_spaced_or_cased() -> None:
    response = "log   1:20060101.05:10:04: a\nLOG 2: 20060101.05:10:05: b"

    entries = diagnostic_log.parse_all(response)

    assert len(entries) == 2
    assert [e.number for e in entries] == [1, 2]


def test_a_response_with_no_prefix_becomes_one_unparsed_entry() -> None:
    """One unparsed entry rather than nothing at all — the text is still the receiver's answer."""
    entries = diagnostic_log.parse_all("no entries here")

    assert len(entries) == 1
    assert entries[0].message == "no entries here"
    assert entries[0].number is None


def test_text_before_the_first_entry_is_discarded() -> None:
    """Framing, not an entry: the boundary is drawn at the first prefix."""
    entries = diagnostic_log.parse_all("noise Log 1: 20060101.05:10:04: a")

    assert len(entries) == 1
    assert entries[0].number == 1


@pytest.mark.parametrize("response", [None, "", "   ", "\r\n"])
def test_an_empty_log_is_no_entries(response: str | None) -> None:
    assert diagnostic_log.parse_all(response) == ()


def test_a_long_log_keeps_its_order() -> None:
    response = "\r\n".join(f"Log {n}: 20060101.05:10:{n:02d}: entry {n}" for n in range(1, 51))

    entries = diagnostic_log.parse_all(response)

    assert len(entries) == 50
    assert [e.number for e in entries] == list(range(1, 51))
    assert all(e.is_structured for e in entries)


@pytest.mark.parametrize(
    "response",
    ['"', '","', "Log", "Log 1:", "\x00", ",,,,", "Log 1: Log 2: Log 3:", "Log " * 1000],
)
def test_parse_all_raises_nothing_whatever_arrives(response: str) -> None:
    """§11.1, over the shapes a truncated or corrupted read produces."""
    entries = diagnostic_log.parse_all(response)

    assert all(isinstance(entry.message, str) for entry in entries)
