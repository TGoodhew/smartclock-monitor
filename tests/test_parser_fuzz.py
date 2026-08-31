"""The parser never raises — checked by corrupting the fixtures rather than by reading the code.

This is the second half of Phase 1's done-condition: *a fuzz test that feeds the parser truncated
and corrupted screens raises nothing*. It exists because §11.1's guarantee is the one the C#
compiler used to hold up and Python's cannot, and because a guarantee nothing exercises is a
comment.

It has already earned its place. Two conversions that raised — ``int()`` above CPython's
4300-digit limit, and ``timedelta``'s ``OverflowError`` past 999999999 days — were found by
writing cases of exactly this shape, not by reading either function.

**What "never raises" is asserted about.** Truncation is exhaustive: every fixture cut at every
offset, which is precisely what a read that ends early produces and the case a hand-written test
is least likely to guess. Substitution and injection are seeded rather than random, so a failure
is reproducible from the test name alone — an intermittent fuzz test is worse than none, because
the thing it reports cannot be investigated.
"""

from __future__ import annotations

import random
import string
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smartclock_device.clock import FixedClock
from smartclock_device.models.receiver_status import ReceiverStatus
from smartclock_device.parsing import diagnostic_log
from smartclock_device.parsing.scalars import (
    parse_boolean,
    parse_decimal,
    parse_first_of_list,
    parse_integer,
    parse_keyword,
    parse_seconds_as_nanoseconds,
)
from smartclock_device.parsing.self_test import SelfTestResult
from smartclock_device.parsing.status_screen import StatusScreenParser

FIXTURES = Path(__file__).resolve().parent / "fixtures"

#: Any instant will do; the rollover arithmetic is not what is under test here. Pinned anyway,
#: because an unpinned clock would make a failure depend on the day it was run.
NOW = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)


def fixture_paths() -> list[Path]:
    return sorted(FIXTURES.rglob("*.txt"))


def read_bytes_as_text(path: Path) -> str:
    """Latin-1, which never substitutes, so the bytes under test are the bytes on disk."""
    return path.read_bytes().decode("latin-1")


def parser() -> StatusScreenParser:
    return StatusScreenParser(FixedClock(NOW))


def assert_survived(status: ReceiverStatus) -> None:
    """The contract: a status comes back, and it can say what went wrong."""
    assert isinstance(status, ReceiverStatus)
    assert status.captured_at == NOW
    assert isinstance(status.parse_warnings, tuple)


def test_there_are_ten_fixtures_to_corrupt() -> None:
    """Guarding the guard. Every test below is parametrized over a glob, and a glob that matched
    nothing would leave the whole file passing while exercising the parser zero times — the exact
    failure mode ``test_layering.py`` guards itself against, for the same reason."""
    assert len(fixture_paths()) == 10


# ---- Truncation ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: p.name)
def test_a_screen_truncated_at_every_offset_raises_nothing(path: Path) -> None:
    """A read that ends early is the single most likely corruption in service: at 9600 baud the
    screen arrives in dozens of chunks, and Phase 2's line protocol is what will decide the
    response is complete. Until it exists, and after it does, the parser must survive being handed
    a prefix of one."""
    screen = read_bytes_as_text(path)
    subject = parser()

    for offset in range(len(screen) + 1):
        assert_survived(subject.parse(screen[:offset]))


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: p.name)
def test_a_screen_missing_its_head_raises_nothing(path: Path) -> None:
    """The mirror of truncation: a read that begins late, which is what a resynchronisation after
    a dropped byte produces."""
    screen = read_bytes_as_text(path)
    subject = parser()

    for offset in range(len(screen) + 1):
        assert_survived(subject.parse(screen[offset:]))


# ---- Corruption ---------------------------------------------------------------------------

#: The bytes a corrupted serial read actually produces: framing errors flip bits, so the result is
#: ordinary printable characters as often as it is control bytes or high bytes.
_NOISE = string.printable + "\x00\x01\x1b\x7f\xff\xfe\x80" + "0123456789" * 4


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: p.name)
def test_substituted_bytes_raise_nothing(path: Path) -> None:
    """One to forty bytes replaced, two hundred times per fixture, seeded on the fixture's name so
    the same corruption is generated on every run and on every machine."""
    screen = read_bytes_as_text(path)
    rng = random.Random(f"substitute:{path.name}")
    subject = parser()

    for _ in range(200):
        corrupted = list(screen)
        for _ in range(rng.randint(1, 40)):
            corrupted[rng.randrange(len(corrupted))] = rng.choice(_NOISE)
        assert_survived(subject.parse("".join(corrupted)))


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: p.name)
def test_injected_runs_of_digits_raise_nothing(path: Path) -> None:
    """The corruption that found both defects, generalised. A long run of digits reaching a
    numeric field is what breaks ``int()``, and a long run reaching a duration is what overflows
    ``timedelta`` — neither is exotic, because a stuck line reads as a repeated character."""
    screen = read_bytes_as_text(path)
    rng = random.Random(f"digits:{path.name}")
    subject = parser()

    for _ in range(100):
        run = rng.choice("0123456789") * rng.choice([12, 20, 400, 4301, 5000])
        at = rng.randrange(len(screen) + 1)
        assert_survived(subject.parse(screen[:at] + run + screen[at:]))


@pytest.mark.parametrize("path", fixture_paths(), ids=lambda p: p.name)
def test_deleted_and_duplicated_lines_raise_nothing(path: Path) -> None:
    """Structural corruption rather than byte corruption: the parser reads by header position and
    by column extent, so a missing header or a doubled table is a different failure path from a
    flipped byte."""
    lines = read_bytes_as_text(path).split("\r\n")
    rng = random.Random(f"lines:{path.name}")
    subject = parser()

    for _ in range(100):
        mutated = list(lines)
        for _ in range(rng.randint(1, 5)):
            if not mutated:
                break
            index = rng.randrange(len(mutated))
            if rng.random() < 0.5:
                del mutated[index]
            else:
                mutated.insert(index, mutated[index])
        assert_survived(subject.parse("\r\n".join(mutated)))


@pytest.mark.parametrize(
    "screen",
    [
        None,
        "",
        " ",
        "\r\n",
        "\x00" * 100,
        "\xff" * 100,
        "9" * 10000,
        "Holdover Duration: " + "9" * 5000 + " m 0 s",
        ":" * 1000,
        "\r\n" * 1000,
    ],
    ids=[
        "none",
        "empty",
        "space",
        "crlf",
        "nulls",
        "high-bytes",
        "digits",
        "huge-duration",
        "colons",
        "blank-lines",
    ],
)
def test_a_screen_that_is_not_a_screen_raises_nothing(screen: str | None) -> None:
    assert_survived(parser().parse(screen))


# ---- The other parsers ---------------------------------------------------------------------

#: §11.1 is a rule about the parsing layer, not only about the status screen. The two ported in
#: this phase get the same treatment, at the same seed discipline.
_SCALAR_PARSERS = (
    parse_integer,
    parse_decimal,
    parse_seconds_as_nanoseconds,
    parse_keyword,
    parse_first_of_list,
    parse_boolean,
)


def fuzz_strings(seed: str, count: int = 2000) -> list[str]:
    rng = random.Random(seed)
    alphabet = _NOISE + "+-.eE,:\"' dhms"
    return ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 60))) for _ in range(count)]


def test_no_scalar_parser_raises_on_anything() -> None:
    """Including the digit runs that broke ``parse_integer``, which is why they are seeded in
    rather than left to chance — a random alphabet almost never produces 4301 consecutive
    digits."""
    candidates = fuzz_strings("scalars") + ["9" * n for n in (11, 4299, 4300, 4301, 5000)]

    for candidate in candidates:
        for scalar_parser in _SCALAR_PARSERS:
            scalar_parser(candidate)


def test_the_diagnostic_log_parser_raises_on_nothing() -> None:
    for candidate in fuzz_strings("diagnostic-log"):
        assert isinstance(diagnostic_log.parse(candidate).message, str)
        for entry in diagnostic_log.parse_all(candidate):
            assert isinstance(entry.raw_text, str)


def test_the_diagnostic_log_parser_survives_a_mangled_log() -> None:
    """Built from the real entry shape rather than from noise, so the corruption lands inside the
    prefix and the timestamp where the parsing actually is."""
    rng = random.Random("log-shapes")
    template = "Log 143: 20060102.03:04:05: Holdover started, not tracking GPS"

    for _ in range(2000):
        corrupted = list(template * rng.randint(1, 3))
        for _ in range(rng.randint(1, 12)):
            corrupted[rng.randrange(len(corrupted))] = rng.choice(_NOISE)
        text = "".join(corrupted)
        assert isinstance(diagnostic_log.parse(text).message, str)
        assert isinstance(diagnostic_log.parse_all(text), tuple)


def test_the_self_test_parser_raises_on_nothing() -> None:
    for candidate in fuzz_strings("self-test"):
        assert SelfTestResult.parse(candidate).passed in (True, False, None)
