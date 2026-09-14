"""The status registers and the status screen, taken in the same breath, must agree.

Both describe one instant. `status_register_map.py` says what each bit means — carried from the
Command Reference through `Models/StatusRegisterMap.cs` — and until this sitting **nothing in
either repository had ever put those meanings beside a screen from the same moment and asked**.
The audit against Lady Heather (#98) is what prompted the question: her HP masks are an
independent reading of the same register, and four of her five bit groups match this map exactly.
Agreement between two implementations is worth something. Agreement with the receiver is worth
more, and it is what this file checks.

The sitting is `tests/fixtures/smartclock/locked-log-almost-full-13sep2026.txt`, written by
`tools/capture_registers.py` so a second one can be taken by running something in this tree.

**It found the thing it is named for.** The Operation register's bit 6 — *diagnostic log almost
full* — is set on the bench receiver, and nothing in the application asks. The log holds 222
entries, which is what "almost full" means here; §10.9's Diagnostics card reports the count and
says nothing about the bit. That is #110.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.models import status_register_map as registers
from smartclock_device.models.position import PositionMode
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_device.parsing.scalars import parse_integer
from smartclock_device.parsing.status_screen import StatusScreenParser

SITTING: Final = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "smartclock"
    / "locked-log-almost-full-13sep2026.txt"
)

#: The marker `tools/capture_registers.py` opens a sent command with.
SENT: Final = ">>> "

#: Any instant will do — nothing here is clock-dependent — but an unpinned one would make a
#: failure depend on the day it ran.
NOW: Final = datetime(2026, 9, 14, 0, 52, 38, tzinfo=UTC)


def transcript(path: Path = SITTING) -> dict[str, tuple[str, ...]]:
    """A sitting, as a mnemonic to the lines it answered with.

    A mnemonic asked more than once — the time code is, eight times over (#113) — accumulates its
    answers in order, so a repeated command reads as the series it was.
    """
    replies: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in path.read_bytes().decode("latin-1").split("\r\n"):
        if line.startswith("#"):
            continue
        if line.startswith(SENT):
            current = replies.setdefault(line[len(SENT) :].strip(), [])
        elif current is not None and line:
            current.append(line)
    return {mnemonic: tuple(lines) for mnemonic, lines in replies.items()}


REPLIES: Final = transcript()


def answer(mnemonic: str) -> str:
    """The one-line answer to a query, which every query here but the screen gives."""
    lines = REPLIES[mnemonic]
    assert len(lines) == 1, f"{mnemonic} answered {len(lines)} lines"
    return lines[0]


def register_value(node: str) -> int:
    value = parse_integer(answer(f":STAT:{node}:COND?"))
    assert value is not None, node
    return value


def bits_set(value: int) -> set[int]:
    return {bit for bit in range(16) if value & (1 << bit)}


@pytest.fixture(scope="module")
def screen() -> ReceiverStatus:
    text = "\r\n".join(REPLIES[catalog.STATUS_SCREEN.mnemonic])
    return StatusScreenParser(FixedClock(NOW)).parse(text)


# ---- The sitting itself ----------------------------------------------------------------------


def test_every_command_in_the_sitting_is_on_the_allowlist() -> None:
    """The harness sends catalogue constants, and this is what says so about the artefact rather
    than about the code that wrote it. A transcript carrying a mnemonic §8.1 does not have would
    mean the tool had grown a command list of its own."""
    for mnemonic in REPLIES:
        assert catalog.is_allowed(mnemonic), mnemonic


def test_the_sitting_answers_every_command_it_asked() -> None:
    assert len(REPLIES) == 11
    for mnemonic, lines in REPLIES.items():
        assert lines, f"{mnemonic} answered nothing"


def test_the_screen_parses_without_a_warning(screen: ReceiverStatus) -> None:
    assert screen.parse_warnings == ()


# ---- What the registers say, against what the screen says -------------------------------------


def test_no_register_has_a_bit_set_that_the_map_cannot_name() -> None:
    """The general claim, and the one worth keeping. A bit set on real hardware that the map has
    no entry for means the map is short — which is exactly what a capture can discover and no
    amount of reading a manual can."""
    for register in registers.ALL:
        for bit in bits_set(register_value(register.node)):
            assert register.bit_at(bit) is not None, (
                f"{register.name} bit {bit} is set on the bench and undocumented here"
            )


def test_the_hardware_register_is_clear_and_every_health_item_is_ok(
    screen: ReceiverStatus,
) -> None:
    """§10.4's card inverts these bits, and six labels cover twelve. In the only state the corpus
    has, both agree that nothing is wrong — which is the weaker half of the claim, and all a
    healthy receiver can supply."""
    assert register_value("OPER:HARD") == 0
    assert screen.health_items
    assert all(screen.health_items.values())
    assert screen.health_ok is True


def test_the_operation_register_tells_the_same_story_as_the_screen(
    screen: ReceiverStatus,
) -> None:
    set_bits = bits_set(register_value("OPER"))

    assert (1 in set_bits) is (screen.mode is SmartClockMode.LOCKED)
    assert (3 in set_bits) is (screen.position_mode is PositionMode.HOLD)
    assert (4 in set_bits) is screen.gps_one_pps_valid
    assert (5 in set_bits) is (register_value("OPER:HARD") != 0)


def test_the_diagnostic_log_is_almost_full_and_the_register_says_so() -> None:
    """#110. The receiver reports the condition; no surface in the application asks for it.

    Pinned to the capture rather than to a threshold, because *how* full "almost" is on this
    firmware is not documented anywhere this port can cite — 222 entries is simply what the
    receiver had when it set the bit."""
    assert 6 in bits_set(register_value("OPER"))
    assert parse_integer(answer(catalog.LOG_COUNT.mnemonic)) == 222


def test_the_power_up_register_agrees_that_everything_has_happened(
    screen: ReceiverStatus,
) -> None:
    set_bits = bits_set(register_value("OPER:POW"))

    assert set_bits == {0, 1, 2}
    assert (0 in set_bits) is bool(screen.tracked)
    assert (2 in set_bits) is (screen.device_date_time is not None)


def test_the_holdover_register_is_clear_while_the_receiver_is_locked(
    screen: ReceiverStatus,
) -> None:
    assert register_value("OPER:HOLD") == 0
    assert screen.mode is SmartClockMode.LOCKED


def test_the_questionable_register_is_clear() -> None:
    assert register_value("QUES") == 0


def test_the_figures_of_merit_answer_what_the_screen_prints(screen: ReceiverStatus) -> None:
    """Two routes to one number. The poll takes the screen's; §10.11 can ask for the query's."""
    assert parse_integer(answer(catalog.TIME_FIGURE_OF_MERIT.mnemonic)) == screen.tfom
    assert parse_integer(answer(catalog.FREQUENCY_FIGURE_OF_MERIT.mnemonic)) == screen.ffom


def test_the_holdover_duration_query_says_what_the_screen_does_not(
    screen: ReceiverStatus,
) -> None:
    """#111. ``:SYNC:HOLD:DUR?`` answers with **two** fields — the duration, and a flag for
    whether holdover is current — and it answers while the receiver is locked, where the screen
    prints no duration at all. The catalogue describes it as a duration and nothing consumes it.

    Asserted here rather than fixed here: the reading is real, and what §10.6 should do with a
    *previous* holdover's duration is a question for that page, not for a parser."""
    duration, present = answer(catalog.HOLDOVER_DURATION.mnemonic).split(",")

    assert float(duration) == pytest.approx(1448.0)
    assert present == "0"
    assert screen.holdover_duration is None
