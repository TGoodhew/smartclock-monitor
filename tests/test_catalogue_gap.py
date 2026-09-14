"""What the receiver answers to everything this application may ask it (#118).

`tests/test_catalogue_covers_the_spec.py` asserts that the catalogue holds every query §8.2 lists.
That is a claim about two documents. **This is the claim about the hardware**: each of those
commands was sent to the bench Z3805A, in one sweep, and what came back is in
`tests/fixtures/smartclock/catalogue-gap-13sep2026.txt`.

The two are different guarantees and both are needed. A command can be correctly catalogued from a
manual and rejected by the firmware — §15 records three that are marked 59551A-only and answer
anyway, and two that are documented and answer `E-113`. Nothing but a receiver settles that.

**Three of the thirty summaries carried here differ from the ones upstream carries**, and each
differs because the receiver said so. They are asserted below rather than only written in a
comment, because a corrected summary that nothing checks is a comment that will be re-corrected
back one day.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from smartclock_device.commands import catalog
from smartclock_device.commands.scpi_command import ResponseFormat
from test_registers_against_screen import transcript

SITTING: Final = (
    Path(__file__).resolve().parent / "fixtures" / "smartclock" / "catalogue-gap-13sep2026.txt"
)

REPLIES: Final = transcript(SITTING)

#: The five that answered with no body, and why each of them has nothing to say while a receiver is
#: locked, steady and has been up for hours. Every one is the `E-230` class from #114 — the
#: firmware has the query and no data for it — rather than a query the receiver lacks.
_NOTHING_TO_SAY: Final[dict[str, str]] = {
    ":DIAG:TEST:RES?": "no self-test has been run this session",
    ":SYNC:HOLD:TUNC:PRES?": "the present holdover uncertainty, and it is not in holdover",
    ":PTIM:LEAP:DATE?": "§10.14: answers only while an announcement stands",
    ":PTIM:LEAP:DUR?": "§10.14: answers only while an announcement stands",
    ":GPS:POS:SURV:PROG?": "no survey is running",
}

#: A comma-separated list of signed integers, which is what a PRN list and a date both look like.
_INTEGER_LIST: Final = re.compile(r"^[+-]\d+(,[+-]\d+)*$")


def answer(mnemonic: str) -> str:
    lines = REPLIES[mnemonic]
    assert len(lines) == 1, f"{mnemonic} answered {len(lines)} lines"
    return lines[0]


# ---- The sweep itself ---------------------------------------------------------------------------


def test_the_sweep_asked_only_things_on_the_allowlist() -> None:
    for mnemonic in REPLIES:
        assert catalog.is_allowed(mnemonic), mnemonic


def test_every_query_answered_but_the_five_with_nothing_to_say() -> None:
    silent = {mnemonic for mnemonic, lines in REPLIES.items() if not lines}

    assert silent == set(_NOTHING_TO_SAY)


def test_the_sweep_covers_the_thirty_entries_it_was_taken_for() -> None:
    """The sitting is the evidence for #118 and has to actually contain it."""
    added = [
        "*ESE?",
        "*ESR?",
        "*SRE?",
        "*STB?",
        ":SYST:STAT:LENG?",
        ":SYST:DATE?",
        ":SYST:TIME?",
        ":SYST:COMM?",
        ":SYNC:HOLD:WAIT?",
        ":GPS:REF:VAL?",
        ":GPS:POS?",
        ":GPS:POS:ACT?",
        ":GPS:POS:HOLD:LAST?",
        ":GPS:POS:HOLD:STAT?",
        ":GPS:SAT:TRAC?",
        ":GPS:SAT:VIS:PRED?",
        ":GPS:SAT:VIS:PRED:COUN?",
        ":GPS:SAT:TRAC:IGN:COUN?",
        ":GPS:SAT:TRAC:INCL?",
        ":GPS:SAT:TRAC:INCL:COUN?",
        ":LED:ALAR?",
        ":LED:GPSL?",
        ":LED:HOLD?",
        ":LED:ACT?",
        ":LED:ENAB?",
        ":DIAG:QUER:RESP?",
    ]

    for mnemonic in added:
        assert REPLIES[mnemonic], f"{mnemonic} was added to the catalogue and answered nothing"


# ---- Where this port's summary differs from the original's, and why ------------------------------


def test_the_serial_query_names_a_port_rather_than_a_configuration() -> None:
    """Upstream reads `:SYST:COMM?` as *"the current serial port configuration"*. The receiver
    answers with a port name. The configuration lives under `:SYST:COMM:SER1:` and every one of
    those is a tier C setter."""
    assert answer(":SYST:COMM?") == "SER1"
    assert "serial port" in catalog.SERIAL_PORT.summary
    assert catalog.SERIAL_PORT.response is not ResponseFormat.VALUE_LIST


def test_the_holdover_wait_query_answers_a_keyword_rather_than_a_boolean() -> None:
    """Upstream expects a boolean. `NONE` is not one, and `parse_boolean` would read it as absent —
    which is the same answer it would give for a receiver that never replied."""
    assert answer(":SYNC:HOLD:WAIT?") == "NONE"
    assert catalog.HOLDOVER_WAIT.response is ResponseFormat.KEYWORD


def test_the_query_response_query_repeats_the_previous_answer() -> None:
    """Upstream carries it as *"reads a fixed response, used to prove the link is alive"*.

    It is not fixed. In the sweep it follows `:LED:ENAB?` and answers what that answered; a hand
    probe on the same bench put four different values through it — `+3` after `:SYNC:TFOM?`, `1`
    after `:LED:GPSL?`, `+10` after `:GPS:SAT:VIS:PRED:COUN?` — and asked twice in a row it repeats
    itself rather than advancing. A `*CLS` in between does not disturb it, so what it holds is the
    last *query* response.

    It is still a link test, which is presumably how it earned its name. But a user told it returns
    a fixed response would read a stale value as *the* response and conclude the link was fine.
    """
    mnemonics = list(REPLIES)
    preceding = mnemonics[mnemonics.index(":DIAG:QUER:RESP?") - 1]

    assert preceding == ":LED:ENAB?"
    assert answer(":DIAG:QUER:RESP?") == answer(preceding)
    assert "previous query" in catalog.LAST_QUERY_RESPONSE.summary


# ---- What the answers look like, so a wrong response format is caught ----------------------------


@pytest.mark.parametrize(
    "mnemonic",
    [":SYST:DATE?", ":SYST:TIME?", ":GPS:SAT:TRAC?", ":GPS:SAT:VIS:PRED?", ":GPS:SAT:TRAC:INCL?"],
)
def test_the_lists_are_lists_of_integers(mnemonic: str) -> None:
    """`INTEGER_LIST` exists because `VALUE_LIST` means *"a list whose first field is the value"*,
    and taking the first field of `+2007,+1,+29` is reading a year as a date."""
    assert _INTEGER_LIST.match(answer(mnemonic)), answer(mnemonic)
    command = catalog.find(mnemonic)
    assert command is not None
    assert command.response is ResponseFormat.INTEGER_LIST


@pytest.mark.parametrize(
    ("mnemonic", "value"),
    [
        (":LED:ALAR?", "0"),
        (":LED:GPSL?", "1"),
        (":LED:HOLD?", "0"),
        (":GPS:REF:VAL?", "1"),
        (":GPS:POS:HOLD:STAT?", "1"),
    ],
)
def test_the_lamps_and_flags_answer_zero_or_one(mnemonic: str, value: str) -> None:
    """Upstream expects keywords from the lamp queries. This receiver answers `0` or `1`, which
    `parse_boolean` reads and a keyword parser would hand back as the string `"0"` — truthy, and
    therefore wrong in the one direction that matters for an alarm lamp."""
    assert answer(mnemonic) == value
    command = catalog.find(mnemonic)
    assert command is not None
    assert command.response is ResponseFormat.BOOLEAN


def test_the_three_positions_are_three_readings() -> None:
    """`:GPS:POS?` and `:GPS:POS:HOLD:LAST?` agree to the digit; `:GPS:POS:ACT?` does not.

    The held position is what the receiver uses for its timing solution and the actual one is what
    the satellites currently say. On a surveyed unit sitting still they agree to a few centimetres —
    on a unit holding a position from another site they would not, which is the case worth being
    able to see, and the reason all three are catalogued rather than one.
    """
    held = answer(":GPS:POS?")

    assert answer(":GPS:POS:HOLD:LAST?") == held
    assert answer(":GPS:POS:ACT?") != held
    assert held.startswith("N,+47,+31,") and ",W,+122,+12," in held


def test_reading_the_event_register_clears_it() -> None:
    """IEEE 488.2's contract, and the reason `*ESR?` reads `+16` here against `+48` in the probe an
    hour earlier: the probe read it, which cleared it, and the errors that accumulated between the
    two are what is left."""
    assert answer("*ESR?") == "+16"
    assert "clears it" in catalog.EVENT_STATUS.summary
