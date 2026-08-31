"""How long each class of command is given to answer (§7.2).

The spread is three orders of magnitude and it is not arbitrary: at 9600 baud a 15 kB diagnostic
log is sixteen seconds of wire time before the receiver has done any thinking, while a scalar query
answers in milliseconds. One timeout for everything is either too short for the log or long enough
that a dead link takes a minute to notice.
"""

from __future__ import annotations

from datetime import timedelta
from types import MappingProxyType
from typing import Final

#: A scalar query. The §7.3 fast tier lives here.
DEFAULT: Final = timedelta(seconds=3)

#: ``:SYST:STAT?`` — roughly 1,900 bytes, about two seconds of wire at 9600 baud.
STATUS_SCREEN: Final = timedelta(seconds=15)

#: ``:DIAG:TEST?`` — the receiver's own sweep took 12.4 s on the bench.
SELF_TEST: Final = timedelta(seconds=30)

#: ``:DIAG:LOG:READ:ALL?`` — the whole log, the longest read the application ever performs.
DIAGNOSTIC_LOG: Final = timedelta(seconds=60)

#: One auto-detect attempt. Short on purpose: eight of these run in sequence.
AUTO_DETECT_PROBE: Final = timedelta(seconds=2)

#: Committing a position, which ends a running survey and takes far longer than it looks.
POSITION_COMMIT: Final = timedelta(seconds=30)


def _spellings(*nodes: tuple[str, ...]) -> tuple[str, ...]:
    """Every legal abbreviation of a header, since SCPI permits short and long forms alike."""
    headers: tuple[str, ...] = ("",)
    for alternatives in nodes:
        headers = tuple(f"{head}:{node}" for head in headers for node in alternatives)
    return headers


def _build() -> MappingProxyType[str, timedelta]:
    lookup: dict[str, timedelta] = {}

    for header in _spellings(("SYST", "SYSTEM"), ("STAT", "STATUS")):
        lookup[header + "?"] = STATUS_SCREEN

    for header in _spellings(("DIAG", "DIAGNOSTIC"), ("TEST",)):
        lookup[header + "?"] = SELF_TEST

    # Only the whole-log read. :DIAG:LOG:READ? returns one entry and is a scalar by any measure, so
    # it keeps the default rather than being given a minute to hang in.
    for header in _spellings(("DIAG", "DIAGNOSTIC"), ("LOG",), ("READ",), ("ALL",)):
        lookup[header + "?"] = DIAGNOSTIC_LOG

    # *TST? is IEEE 488.2 common syntax: no node structure and no long form.
    lookup["*TST?"] = SELF_TEST

    # The position-commit setters. Registered without a trailing "?" because they are setters, and
    # with their keyword argument, because ":GPS:POSition LAST" and ":GPS:POSition SURVey" are
    # distinct commands rather than one command with a parameter.
    #
    # The bare ":GPS:POSition" is included on reasoning rather than measurement: it commits a
    # position by the same route and would tear down a running survey the same way. It has never
    # been run against hardware, so leaving it at 3 s would mean rediscovering the defect the next
    # time somebody types coordinates in.
    #
    # ":GPS:POSition:SURVey:STATe ONCE" is deliberately NOT here. It answers promptly — observed
    # four times, well inside the default — and starting an accumulation is not the same work as
    # ending one.
    for header in _spellings(("GPS",), ("POS", "POSITION")):
        lookup[header] = POSITION_COMMIT
        for argument in ("LAST", "SURV", "SURVEY"):
            lookup[f"{header} {argument}"] = POSITION_COMMIT

    return MappingProxyType(lookup)


_BY_COMMAND: Final = _build()


def _normalise(command: str) -> str:
    """Upper-cased and stripped of the leading colon, which is optional in SCPI."""
    return command.strip().upper()


def for_command(command: str) -> timedelta:
    """The timeout §7.2 assigns to a command, or :data:`DEFAULT`.

    Unknown commands get the default rather than the longest timeout: a command nobody has
    catalogued is a scalar until shown otherwise, and erring long would mean a typo hangs the poll
    loop for a minute.
    """
    normalised = _normalise(command)
    if not normalised.startswith(":") and not normalised.startswith("*"):
        normalised = ":" + normalised
    return _BY_COMMAND.get(normalised, DEFAULT)
