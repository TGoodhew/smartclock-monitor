"""The command allowlist (§8.1).

**This is an allowlist, and that is the whole safety model.** A command that is not an entry here
does not exist as far as the application is concerned. §8.4's exclusions are not entries carrying a
warning flag — they are not entries at all, and ``tests/test_catalog.py`` asserts that no entry
here is one, so the two mechanisms check each other rather than merely coexisting.

There is no free-text command path and there must never be one: §10.11's Advanced Console is a
picker over these entries.

**This is a working subset, not the whole of §8.2.** It holds what the §7.3 poll schedule, the
connect sequence, and the Holdover, Diagnostics, Status Registers and Time pages need. Adding a
command is adding a row here. Nothing is reachable that is not on this page.

**A setter is catalogued by its header alone.** ``:SYNC:HOLD:DUR:THR`` is the entry; the seconds
are supplied separately and validated by :meth:`ScpiCommand.rendered` against bounds declared on
the entry. Cataloguing the composed string instead would make the point-of-send check a prefix
match, which is a free-text path with extra steps. The exception is a keyword that changes what the
command *does* — ``:GPS:POSition LAST`` and ``:GPS:POSition SURVey`` are separate entries, because
§8.3 gives them different confirmations and one sentence cannot describe both.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from smartclock_device.commands.scpi_command import (
    ArgumentKind,
    ResponseFormat,
    SafetyTier,
    ScpiCommand,
)

#: Identity, per IEEE 488.2. The first thing asked, and what §8.6 keys the model profile on.
IDENTITY: Final = ScpiCommand(
    mnemonic="*IDN?",
    summary="Manufacturer, model, serial number and firmware revision",
    response=ResponseFormat.TEXT,
)

#: Clears the status registers. Tier S, and the one the connect sequence spends the DTR glitch on.
CLEAR_STATUS: Final = ScpiCommand(
    mnemonic="*CLS",
    summary="Clear the status registers and the error queue",
    response=ResponseFormat.NONE,
)

#: The whole status screen. The only source for the satellite elevation, azimuth and signal table,
#: which has no individual query — which is why §7.3 gives it a tier of its own.
STATUS_SCREEN: Final = ScpiCommand(
    mnemonic=":SYST:STAT?",
    summary="The full receiver status screen",
    response=ResponseFormat.STATUS_SCREEN,
)

#: The error queue, oldest first. §7.2 reads it after every tier C command.
ERROR_QUEUE: Final = ScpiCommand(
    mnemonic=":SYST:ERR?",
    summary="The oldest entry in the error queue",
    response=ResponseFormat.VALUE_LIST,
)

# ---- The §7.3 fast tier ----------------------------------------------------------------------
#
# Order matters. :SYNC:STAT? stays first because §7.3.1's rule depends on knowing the sync state
# before the rest of the tier is asked.

SYNC_STATE: Final = ScpiCommand(
    mnemonic=":SYNC:STAT?",
    summary="What the receiver is synchronised to",
    response=ResponseFormat.KEYWORD,
)

TIME_FIGURE_OF_MERIT: Final = ScpiCommand(
    mnemonic=":SYNC:TFOM?",
    summary="Time figure of merit",
    response=ResponseFormat.INTEGER,
)

FREQUENCY_FIGURE_OF_MERIT: Final = ScpiCommand(
    mnemonic=":SYNC:FFOM?",
    summary="Frequency figure of merit",
    response=ResponseFormat.INTEGER,
)

#: The time interval against GPS 1 PPS, in seconds on the wire and nanoseconds everywhere else.
#:
#: **This is the refusable one** (§7.3.1). While the receiver is unlocked there is no GPS 1 PPS to
#: measure against, so it answers nothing and puts an error in the prompt. That is the correct
#: answer; the question is the mistake. Asked once a second it filled the bench receiver's error
#: queue until real errors were being discarded to make room for poll noise.
TIME_INTERVAL: Final = ScpiCommand(
    mnemonic=":SYNC:TINT?",
    summary="Time interval to GPS 1 PPS",
    response=ResponseFormat.DECIMAL,
    unit="s",
)

OSCILLATOR_EFC: Final = ScpiCommand(
    mnemonic=":DIAG:ROSC:EFC:REL?",
    summary="Oscillator electronic frequency control, relative",
    response=ResponseFormat.DECIMAL,
    unit="%",
)

TRACKED_COUNT: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:COUN?",
    summary="How many satellites are being tracked",
    response=ResponseFormat.INTEGER,
)

#: The §7.3 fast tier, in the order §7.3.1 requires.
FAST_TIER: Final[tuple[ScpiCommand, ...]] = (
    SYNC_STATE,
    TIME_FIGURE_OF_MERIT,
    FREQUENCY_FIGURE_OF_MERIT,
    TIME_INTERVAL,
    OSCILLATOR_EFC,
    TRACKED_COUNT,
)

#: The one command whose refusal §7.3.1 suppresses until the sync state changes.
REFUSABLE: Final = TIME_INTERVAL

# ---- Diagnostics reads -------------------------------------------------------------------------

DIAGNOSTIC_LOG: Final = ScpiCommand(
    mnemonic=":DIAG:LOG:READ:ALL?",
    summary="The whole diagnostic log",
    response=ResponseFormat.MULTI_LINE,
)

SELF_TEST_RESULT: Final = ScpiCommand(
    mnemonic=":DIAG:TEST:RES?",
    summary="The result of the last self-test",
    response=ResponseFormat.VALUE_LIST,
)

TIME_CODE_FORMAT: Final = ScpiCommand(
    mnemonic=":PTIM:TCOD:FORM?",
    summary="Which time code format the receiver emits",
    response=ResponseFormat.KEYWORD,
)

LOG_COUNT: Final = ScpiCommand(
    mnemonic=":DIAG:LOG:COUN?",
    summary="How many entries the diagnostic log holds",
    response=ResponseFormat.INTEGER,
)

#: §10.9: the receiver reports **hours**, not a count — the mnemonic says COUNt and the manual says
#: otherwise. #316 nearly struck the requirement on the grounds that no such query existed; it does,
#: and what was wrong was the card's label.
LIFETIME_HOURS: Final = ScpiCommand(
    mnemonic=":DIAG:LIF:COUN?",
    summary="Power-on hours — the receiver's accumulated running time",
    response=ResponseFormat.INTEGER,
    unit="h",
)

# ---- §10.8 Holdover ----------------------------------------------------------------------------

#: **A value list, not a bare decimal**, and that was found by asking the receiver: it answers
#: ``+7.80000E+001,0`` — the figure and a validity flag. ``parse_decimal`` returns ``None`` for
#: that, so the page would have shown a dash for a value the receiver had given it. The same shape
#: applies to both uncertainty queries below.
HOLDOVER_DURATION: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:DUR?",
    summary="How long the receiver has been in holdover",
    response=ResponseFormat.VALUE_LIST,
    unit="s",
)

#: §10.8: read on navigation, on every reconnect, and again after a successful Apply — the limit has
#: one-second resolution, so what the receiver took need not be what was sent, and the editor is the
#: only place that figure appears.
HOLDOVER_DURATION_THRESHOLD: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:DUR:THR?",
    summary="The holdover duration limit",
    response=ResponseFormat.DECIMAL,
    unit="s",
)

HOLDOVER_DURATION_EXCEEDED: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:DUR:THR:EXC?",
    summary="Whether the holdover duration limit is currently exceeded",
    response=ResponseFormat.BOOLEAN,
)

HOLDOVER_UNCERTAINTY_PREDICTED: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:TUNC:PRED?",
    summary="Predicted 24 hour holdover uncertainty",
    response=ResponseFormat.VALUE_LIST,
    unit="s",
)

HOLDOVER_UNCERTAINTY_PRESENT: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:TUNC:PRES?",
    summary="Present holdover time error",
    response=ResponseFormat.VALUE_LIST,
    unit="s",
)

# ---- §10.14 Time, and the leap second ----------------------------------------------------------

RECEIVER_DATE: Final = ScpiCommand(
    mnemonic=":PTIM:DATE?",
    summary="The receiver's date",
    response=ResponseFormat.VALUE_LIST,
)

RECEIVER_TIME: Final = ScpiCommand(
    mnemonic=":PTIM:TIME?",
    summary="The receiver's time of day",
    response=ResponseFormat.VALUE_LIST,
)

RECEIVER_TIME_STRING: Final = ScpiCommand(
    mnemonic=":PTIM:TIME:STR?",
    summary="The receiver's time of day, formatted",
    response=ResponseFormat.TEXT,
)

TIME_ZONE: Final = ScpiCommand(
    mnemonic=":PTIM:TZON?",
    summary="The time zone offset applied to reported times",
    response=ResponseFormat.VALUE_LIST,
)

LEAP_ACCUMULATED: Final = ScpiCommand(
    mnemonic=":PTIM:LEAP:ACC?",
    summary="Accumulated leap seconds between GPS and UTC",
    response=ResponseFormat.INTEGER,
    unit="s",
)

LEAP_DATE: Final = ScpiCommand(
    mnemonic=":PTIM:LEAP:DATE?",
    summary="The date of the pending leap second",
    response=ResponseFormat.VALUE_LIST,
)

LEAP_DURATION: Final = ScpiCommand(
    mnemonic=":PTIM:LEAP:DUR?",
    summary="Whether the pending leap second adds or removes a second",
    response=ResponseFormat.INTEGER,
    unit="s",
)

#: Answers ``0`` rather than a keyword — asked, and it did. A KEYWORD format here would have had
#: the page render the string "0" as though it were a state name.
LEAP_STATE: Final = ScpiCommand(
    mnemonic=":PTIM:LEAP:STAT?",
    summary="Whether a leap second is pending",
    response=ResponseFormat.BOOLEAN,
)

# ---- §10.10 Status registers -------------------------------------------------------------------
#
# Five registers, five fields each. Generated rather than written out: twenty-five near-identical
# entries hand-typed is twenty-five chances to transpose a mnemonic, and a transposed one here is a
# page reporting one register's bits under another's name.

#: The register roots, in the order §10.10's selector lists them.
REGISTER_ROOTS: Final[tuple[tuple[str, str], ...]] = (
    (":STAT:OPER", "Operation"),
    (":STAT:OPER:HARD", "Operation — Hardware"),
    (":STAT:OPER:HOLD", "Operation — Holdover"),
    (":STAT:OPER:POW", "Operation — Power-up"),
    (":STAT:QUES", "Questionable"),
)

#: The five fields §10.10's table has a column for.
REGISTER_FIELDS: Final[tuple[tuple[str, str], ...]] = (
    ("COND", "condition"),
    ("EVEN", "event"),
    ("ENAB", "enable mask"),
    ("PTR", "positive transition mask"),
    ("NTR", "negative transition mask"),
)

#: Which of those fields can be written. Condition and event are the receiver's own state.
WRITABLE_REGISTER_FIELDS: Final[frozenset[str]] = frozenset({"ENAB", "PTR", "NTR"})


def _register_queries() -> tuple[ScpiCommand, ...]:
    return tuple(
        ScpiCommand(
            mnemonic=f"{root}:{field}?",
            summary=f"{label} register — {description}",
            response=ResponseFormat.INTEGER,
        )
        for root, label in REGISTER_ROOTS
        for field, description in REGISTER_FIELDS
    )


def _register_setters() -> tuple[ScpiCommand, ...]:
    return tuple(
        ScpiCommand(
            mnemonic=f"{root}:{field}",
            summary=f"Set the {label} register's {description}",
            response=ResponseFormat.NONE,
            tier=SafetyTier.CONFIRM,
            argument=ArgumentKind.INTEGER,
            minimum=0,
            maximum=32767,
            confirmation="Change status register mask?",
        )
        for root, label in REGISTER_ROOTS
        for field, description in REGISTER_FIELDS
        if field in WRITABLE_REGISTER_FIELDS
    )


REGISTER_QUERIES: Final[tuple[ScpiCommand, ...]] = _register_queries()

#: §10.7.1 surfaces hardware bits 6 and 7 on the drift card — "EFC voltage near full scale" and
#: "at full scale". Named here so the Timing page asks for a command rather than assembling a
#: mnemonic from a string it would have to keep in step with the roots above.
HARDWARE_CONDITION: Final = next(
    command for command in REGISTER_QUERIES if command.mnemonic == ":STAT:OPER:HARD:COND?"
)
REGISTER_SETTERS: Final[tuple[ScpiCommand, ...]] = _register_setters()


def register_query(root: str, field: str) -> ScpiCommand | None:
    """The query for one register field, or ``None`` if there is no such pair."""
    return find(f"{root}:{field}?")


def register_setter(root: str, field: str) -> ScpiCommand | None:
    return find(f"{root}:{field}")


# ---- §8.3 tier C: the setters, each carrying its own confirmation -------------------------------

#: §8.2 classes both recovery commands Safe: they move the unit *toward* lock, which is the desired
#: state, and cannot damage anything.
HOLDOVER_RECOVER: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:REC:INIT",
    summary="Recover from holdover now",
    response=ResponseFormat.NONE,
)

HOLDOVER_IGNORE_RECOVERY_LIMIT: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:REC:LIM:IGN",
    summary="Ignore the recovery limit and reacquire",
    response=ResponseFormat.NONE,
)

HOLDOVER_FORCE: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:INIT",
    summary="Force manual holdover",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation=(
        "Force manual holdover? The receiver will stop disciplining to GPS until you explicitly "
        "recover. Do not do this within the first 24 hours after power-up — it corrupts SmartClock "
        "oscillator learning."
    ),
    requires_acknowledgement=True,
)

SET_HOLDOVER_DURATION_THRESHOLD: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:DUR:THR",
    summary="Set the holdover duration limit",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    unit="s",
    argument=ArgumentKind.INTEGER,
    minimum=1,
    maximum=999_999,
    confirmation="Set the holdover duration limit?",
)

CLEAR_DIAGNOSTIC_LOG: Final = ScpiCommand(
    mnemonic=":DIAG:LOG:CLE",
    summary="Clear the diagnostic log",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation="Clear the diagnostic log? This cannot be undone.",
)

#: §10.9: twelve subsystem keywords, probed against the live receiver rather than taken on trust.
#: ``ALL`` is the default because one sweep is one disruption where eleven separate runs would be
#: eleven disruptions of a disciplined oscillator.
SELF_TEST_SUBSYSTEMS: Final[tuple[str, ...]] = (
    "ALL",
    "DISP",
    "PROC",
    "RAM",
    "EEPROM",
    "UART",
    "QSPI",
    "FPGA",
    "INTP",
    "IREF",
    "GPS",
    "POW",
)

RUN_SELF_TEST: Final = ScpiCommand(
    mnemonic=":DIAG:TEST?",
    summary="Run a subsystem diagnostic",
    response=ResponseFormat.INTEGER,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.KEYWORD,
    keywords=SELF_TEST_SUBSYSTEMS,
    confirmation=(
        "Run the diagnostic? The receiver will drop out of lock and re-acquire, so the 1 PPS "
        "output is degraded for several minutes. The test itself takes up to 30 seconds."
    ),
)

SET_ELEVATION_MASK: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:EMAN",
    summary="Set the elevation mask",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    unit="°",
    argument=ArgumentKind.INTEGER,
    minimum=0,
    maximum=90,
    confirmation=(
        "Set the elevation mask? Values above 15° during survey may prevent position "
        "determination; above 40° severely limits availability."
    ),
)

SET_ANTENNA_DELAY: Final = ScpiCommand(
    mnemonic=":GPS:REF:ADEL",
    summary="Set the antenna cable delay",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    unit="s",
    argument=ArgumentKind.DECIMAL,
    minimum=0.0,
    maximum=0.999999,
    confirmation=(
        "Set the antenna delay? Changing this while locked can push the receiver into holdover."
    ),
)

ELEVATION_MASK: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:EMAN?",
    summary="The elevation mask below which satellites are ignored",
    response=ResponseFormat.DECIMAL,
    unit="°",
)

ANTENNA_DELAY: Final = ScpiCommand(
    mnemonic=":GPS:REF:ADEL?",
    summary="The antenna cable delay the receiver is compensating for",
    response=ResponseFormat.DECIMAL,
    unit="s",
)

#: Every catalogued command. **The allowlist.**
ALL: Final[tuple[ScpiCommand, ...]] = (
    IDENTITY,
    CLEAR_STATUS,
    STATUS_SCREEN,
    ERROR_QUEUE,
    *FAST_TIER,
    DIAGNOSTIC_LOG,
    SELF_TEST_RESULT,
    TIME_CODE_FORMAT,
    LOG_COUNT,
    LIFETIME_HOURS,
    HOLDOVER_DURATION,
    HOLDOVER_DURATION_THRESHOLD,
    HOLDOVER_DURATION_EXCEEDED,
    HOLDOVER_UNCERTAINTY_PREDICTED,
    HOLDOVER_UNCERTAINTY_PRESENT,
    RECEIVER_DATE,
    RECEIVER_TIME,
    RECEIVER_TIME_STRING,
    TIME_ZONE,
    LEAP_ACCUMULATED,
    LEAP_DATE,
    LEAP_DURATION,
    LEAP_STATE,
    ELEVATION_MASK,
    ANTENNA_DELAY,
    *REGISTER_QUERIES,
    HOLDOVER_RECOVER,
    HOLDOVER_IGNORE_RECOVERY_LIMIT,
    HOLDOVER_FORCE,
    SET_HOLDOVER_DURATION_THRESHOLD,
    CLEAR_DIAGNOSTIC_LOG,
    RUN_SELF_TEST,
    SET_ELEVATION_MASK,
    SET_ANTENNA_DELAY,
    *REGISTER_SETTERS,
)

_BY_MNEMONIC: Final[MappingProxyType[str, ScpiCommand]] = MappingProxyType(
    {command.mnemonic.upper(): command for command in ALL}
)


def find(mnemonic: str | None) -> ScpiCommand | None:
    """The catalogued command with this mnemonic, or ``None`` if there is none.

    ``None`` is the important answer: it is how the session refuses to send anything that is not on
    the allowlist, which is the check §8.1 puts at the point of send.
    """
    if mnemonic is None or not mnemonic.strip():
        return None
    return _BY_MNEMONIC.get(mnemonic.strip().upper())


def is_allowed(mnemonic: str | None) -> bool:
    """Whether this command may be sent at all.

    The point-of-send check. It asks whether the command **is catalogued**, not whether it is
    excluded — an allowlist answers the first question, and answering the second instead is the
    architecture §8.1 rejects.
    """
    return find(mnemonic) is not None
