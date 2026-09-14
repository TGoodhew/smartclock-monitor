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
    FieldSpec,
    ResponseFormat,
    SafetyTier,
    ScpiCommand,
)
from smartclock_device.models.satellite import FIRST_PRN, LAST_PRN

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

#: The §7.3 fast tier, in the order §7.3.1 requires. Exactly the six §7.3's table lists.
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

#: The time code itself. §8.2 lists it; this port did not have it until #113.
#:
#: **It answers, and it is slow.** The receiver emits the message on its own 1 Hz cadence, so a
#: request lands in the next slot and the transaction blocks for 0.4 to 1.0 s — measured on the
#: bench 13 Sep 2026, against 0.2 s for an ordinary scalar query on the same link in the same
#: minute. §10.14 says the same from its own measurement in Aug 2026. That is why it is a
#: catalogued query a user can ask for and **not** a poll-plan entry: five readings for five
#: queries' worth of wall time is not a bargain, and §7.3's fast tier is one second long.
TIME_CODE: Final = ScpiCommand(
    mnemonic=":PTIM:TCOD?",
    summary="The time code — the next 1 PPS, with both figures of merit (blocks up to a second)",
    response=ResponseFormat.TEXT,
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

#: §10.9: what the GPS receiver *inside* the instrument calls itself.
#:
#: **Documented, so an ordinary tier A query rather than one of §8.5's undocumented six** — Z3801A
#: User's Guide, Table 4-2, ``:DIAGnostic:IDENtification:GPSystem?``, *"returns a sequence of quoted
#: strings"*, described as *"the model number, serial number, and revision of the internal GPS
#: receiver"*.
#:
#: A SmartClock is a disciplining chassis wrapped around somebody else's GPS engine, and the two
#: revise on separate schedules. Asked of the bench Z3805A on 13 Sep 2026, whose own firmware is
#: ``1.01.03-A``, it answers::
#:
#:     "--","SFTW P/N # 4850266","SOFTWARE VER # 005","--","--",
#:     "MODEL # FURUNO GT-80","--","--","--","--"
#:
#: (one line on the wire; wrapped here)
#:
#: **Ten fields, seven of them ``--``, and the serial number the documentation was most specific
#: about is among the empty ones.** So nothing may assign meaning to position: the three that are
#: populated label themselves, and a firmware that fills two more slots gains two more lines rather
#: than shifting what the existing ones mean.
#:
#: Read on demand, never polled — the module inside cannot change while the instrument is powered.
GPS_ENGINE_IDENTITY: Final = ScpiCommand(
    mnemonic=":DIAG:IDEN:GPS?",
    summary="GPS receiver identity — the model and firmware of the engine inside the instrument",
    response=ResponseFormat.VALUE_LIST,
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

#: The Operation register's condition, for the same reason and by the same route.
#:
#: Its **bit 6 is the only fault in that register** — *diagnostic log almost full* — and the bench
#: receiver has it set (#110): `+90` against a log holding 222 entries. §10.9 reads this beside
#: the count, because a count is a number and the bit is a verdict.
OPERATION_CONDITION: Final = next(
    command for command in REGISTER_QUERIES if command.mnemonic == ":STAT:OPER:COND?"
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

# ---- §10.5's satellite exclusion -----------------------------------------------------------------
#
# §8.3 gives :IGN:ALL and :INCL:NONE their own sentences, and its amendment note explains why that
# matters more than it looks: :IGN:NONE shared the PRN form's sentence — "Exclude the selected
# satellites from tracking?" — for a command that *clears* the exclusion list, so a user confirming
# it would reasonably believe they were excluding satellites while making every one eligible again.


EXCLUDED_SATELLITES: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:IGN?",
    summary="Which satellites are excluded from tracking",
    response=ResponseFormat.VALUE_LIST,
)

EXCLUDE_SATELLITES: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:IGN",
    summary="Exclude satellites from tracking",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.INTEGER_LIST,
    minimum=FIRST_PRN,
    maximum=LAST_PRN,
    confirmation="Exclude the selected satellites from tracking?",
)

EXCLUDE_ALL_SATELLITES: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:IGN:ALL",
    summary="Exclude every satellite from tracking",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation=("Exclude all satellites? The receiver will lose lock and enter holdover."),
    requires_acknowledgement=True,
)

#: Its **own** sentence — see the note above. This is the one §8.3 was amended for.
CLEAR_EXCLUSIONS: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:IGN:NONE",
    summary="Clear the exclusion list",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation=("Clear the exclusion list? Every satellite becomes eligible for tracking again."),
)

INCLUDE_SATELLITES: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:INCL",
    summary="Set the tracking inclusion list",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.INTEGER_LIST,
    minimum=FIRST_PRN,
    maximum=LAST_PRN,
    confirmation="Update the tracking inclusion list?",
)

INCLUDE_ALL_SATELLITES: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:INCL:ALL",
    summary="Make every satellite eligible for tracking",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation="Make every satellite eligible for tracking?",
)

INCLUDE_NO_SATELLITES: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:INCL:NONE",
    summary="Track no satellites",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation="Track no satellites? The receiver will lose lock and enter holdover.",
    requires_acknowledgement=True,
)

# ---- §10.6's survey ------------------------------------------------------------------------------
#
# ``:GPS:POSition <coords>`` was **deliberately absent** while its wire format was unknown (issue
# #12): a tier C command that changes the position every timing solution is computed from, where a
# plausible guess would be either rejected or, worse, accepted and wrong. It is here now because
# the format was **looked up rather than decided** — see ``position_argument.py``.

SET_POSITION: Final = ScpiCommand(
    mnemonic=":GPS:POSition",
    summary="Set the fixed antenna position the receiver times from",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.POSITION,
    confirmation=(
        "Set fixed antenna position? This cancels any survey in progress and the receiver will "
        "use these coordinates for all timing solutions. An incorrect position degrades timing "
        "accuracy."
    ),
    requires_acknowledgement=True,
)

SURVEY_PROGRESS: Final = ScpiCommand(
    mnemonic=":GPS:POS:SURV:PROG?",
    summary="How far through a position survey the receiver is",
    response=ResponseFormat.INTEGER,
    unit="%",
)

SURVEY_STATE: Final = ScpiCommand(
    mnemonic=":GPS:POS:SURV:STAT?",
    summary="Whether a position survey is running",
    response=ResponseFormat.KEYWORD,
)

SURVEY_ON_POWER_UP: Final = ScpiCommand(
    mnemonic=":GPS:POS:SURV:STAT:POW?",
    summary="Whether the receiver surveys on power-up",
    response=ResponseFormat.KEYWORD,
)

#: §10.6, amended by #229: on the bench Z3805A this is **refused with −300** when the receiver is
#: already holding a position, and no command in §8.2 or in any of the three family manuals
#: releases the hold. The command stays as specified — it is correct for the 58503A models the
#: catalog also serves — and what changes is that a −300 here is reported with the reason and the
#: route attached rather than as a bare device error the user can do nothing with.
START_SURVEY: Final = ScpiCommand(
    mnemonic=":GPS:POS:SURV:STAT ONCE",
    summary="Start a position survey",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation=(
        "Start a position survey? This takes approximately two hours with four or more "
        "satellites tracked."
    ),
)

ADOPT_SURVEYED_POSITION: Final = ScpiCommand(
    mnemonic=":GPS:POS SURV",
    summary="Stop surveying and adopt the computed position",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation="Stop surveying and adopt the computed average position?",
)

RESTORE_LAST_POSITION: Final = ScpiCommand(
    mnemonic=":GPS:POS LAST",
    summary="Cancel the survey and restore the last held position",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation="Cancel survey and restore the last held position?",
)

SET_SURVEY_ON_POWER_UP: Final = ScpiCommand(
    mnemonic=":GPS:POS:SURV:STAT:POW",
    summary="Change whether the receiver surveys on power-up",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.KEYWORD,
    keywords=("ON", "OFF"),
    confirmation="Change power-up behaviour?",
)

#: §10.6's client-side validation bounds. Rejected here rather than letting the device error —
#: which is also why they live beside the commands rather than in a page.
LATITUDE_DEGREES: Final = (0, 90)
LONGITUDE_DEGREES: Final = (0, 180)
ARC_MINUTES: Final = (0, 59)
ARC_SECONDS: Final = (0.0, 59.999)
HEIGHT_METRES: Final = (-1000.00, 18000.00)

# ---- §8.5's experimental queries -----------------------------------------------------------------
#
# **Query-only, and this list is fixed at exactly six.** The keywords come from the Z3801A firmware
# string dump named in §16 — a *sibling* model — so being in that dump means the node exists in that
# firmware's parser and says nothing about any other. Run against the bench Z3805A on 20 Aug 2026,
# five of the six answered E-113 and the error queue held exactly five entries afterwards.
#
# **E-113 is an answer, not a failure.** It is SCPI's *undefined header*: the node is not in this
# firmware's parser. For a card whose entire purpose is asking undocumented questions, "this
# receiver does not have that one" is a result, and the most useful one available for five of six.
#
# **The list is not filtered to what the connected receiver supports.** The application would have
# to probe all six to know, which is what the card does anyway; a list that changed shape by model
# would make the specification's "exactly" untrue; and a user who opted into asking undocumented
# questions is owed the answer rather than a shorter list.

EXPERIMENTAL: Final[tuple[ScpiCommand, ...]] = (
    ScpiCommand(
        mnemonic=":DIAG:ROSC:EFC:ABS?",
        # Answers +436061 on the bench receiver while the documented relative query returns
        # -16.83 per cent at the same moment. **Nothing states the units of the first, and nothing
        # may assume them**: it is shown as raw text and no part of the application computes
        # anything from it.
        summary="Oscillator EFC, absolute — units undocumented",
        response=ResponseFormat.TEXT,
    ),
    ScpiCommand(
        mnemonic=":DIAG:ROSC:EFC:TCO?",
        summary="Oscillator EFC temperature coefficient — undocumented",
        response=ResponseFormat.TEXT,
    ),
    ScpiCommand(
        mnemonic=":SYST:STAT:SLOG?",
        summary="System status short log — undocumented",
        response=ResponseFormat.TEXT,
    ),
    ScpiCommand(
        mnemonic=":DIAG:STAC?",
        summary="Diagnostic stack — undocumented",
        response=ResponseFormat.TEXT,
    ),
    ScpiCommand(
        mnemonic=":DIAG:PROC?",
        summary="Diagnostic process information — undocumented",
        response=ResponseFormat.TEXT,
    ),
    ScpiCommand(
        mnemonic=":DIAG:MEM?",
        summary="Diagnostic memory information — undocumented",
        response=ResponseFormat.TEXT,
    ),
)


# ---- §8.2's remainder, added by #118 -------------------------------------------------------------
#
# **Thirty entries §8.2 lists that this catalogue did not have.** §10.11's Advanced Console is a
# picker over the allowlist and there is no free-text path, so a command missing from here is a
# command this application cannot send at all, by anyone. That is what made the gap worth closing
# rather than noting.
#
# Every one below **answered on the bench Z3805A on 13 Sep 2026**, with the error queue drained
# before each and read after, so nothing here rests on a manual alone —
# `tests/fixtures/smartclock/catalogue-gap-13sep2026` is the sitting. Three of the summaries
# differ from the ones upstream carries, and they differ because the receiver said so; the
# divergences are named on the entries themselves.

#: IEEE 488.2's four status-reporting queries. They read the registers behind §10.10's page rather
#: than the SCPI-defined ones, and none of them is a receiver setting.
EVENT_ENABLE_MASK: Final = ScpiCommand(
    mnemonic="*ESE?",
    summary="Standard event status enable mask",
    response=ResponseFormat.INTEGER,
)

#: **Reading it clears it**, which is IEEE 488.2's own contract for an event register and not a
#: quirk. Catalogued as safe anyway: the register exists to be read, and nothing in this
#: application or any other holds state that a clear would lose.
EVENT_STATUS: Final = ScpiCommand(
    mnemonic="*ESR?",
    summary="Standard event status register — reading it clears it",
    response=ResponseFormat.INTEGER,
)

SERVICE_REQUEST_MASK: Final = ScpiCommand(
    mnemonic="*SRE?",
    summary="Service request enable mask",
    response=ResponseFormat.INTEGER,
)

STATUS_BYTE: Final = ScpiCommand(
    mnemonic="*STB?",
    summary="Status byte summary register",
    response=ResponseFormat.INTEGER,
)

#: **What it counts is not established.** Upstream reads it as "how many lines the status screen
#: occupies"; the bench answers `+23` to a screen that arrives as 27 lines, 22 of them non-blank.
#: So the summary says what the receiver calls it and not what it means, which is the honest
#: position until a second reading in another state settles it (#119).
STATUS_SCREEN_LENGTH: Final = ScpiCommand(
    mnemonic=":SYST:STAT:LENG?",
    summary="The length the receiver reports for its status screen",
    response=ResponseFormat.INTEGER,
)

#: The same instant as :data:`RECEIVER_DATE` and :data:`RECEIVER_TIME`, by the other spelling the
#: manual documents — confirmed on the bench, which answered both pairs identically to the second.
#: Catalogued because §8.2 lists them and a console user reading a manual should find what it names.
SYSTEM_DATE: Final = ScpiCommand(
    mnemonic=":SYST:DATE?",
    summary="The receiver's date, as year, month and day",
    response=ResponseFormat.INTEGER_LIST,
)

SYSTEM_TIME: Final = ScpiCommand(
    mnemonic=":SYST:TIME?",
    summary="The receiver's time, as hours, minutes and seconds",
    response=ResponseFormat.INTEGER_LIST,
)

#: **Which port, not how it is configured.** Upstream reads this as the serial configuration; the
#: bench answers `SER1`, which names the port the receiver is talking on. The configuration is
#: under `:SYST:COMM:SER1:` and every one of those is a tier C setter.
SERIAL_PORT: Final = ScpiCommand(
    mnemonic=":SYST:COMM?",
    summary="Which serial port the receiver is communicating on",
    response=ResponseFormat.KEYWORD,
)

#: §11.1 names *waiting to recover* as a state no capture has ever produced, and this is the query
#: that would report it. The bench answers `NONE` — a keyword, where upstream expects a boolean.
HOLDOVER_WAIT: Final = ScpiCommand(
    mnemonic=":SYNC:HOLD:WAIT?",
    summary="Why the receiver is waiting before it recovers from holdover",
    response=ResponseFormat.KEYWORD,
)

REFERENCE_VALID: Final = ScpiCommand(
    mnemonic=":GPS:REF:VAL?",
    summary="Whether the GPS reference is currently valid",
    response=ResponseFormat.BOOLEAN,
)

#: Three positions, and they are **not the same reading**. The bench answered all three within one
#: sitting and `:GPS:POS:ACT?` differed from the other two in its last digits: the held position is
#: what the receiver is using for its timing solution, and the actual one is what the satellites
#: currently say. On a surveyed unit sitting still they agree to a few centimetres; on a unit
#: holding a position from another site they would not, which is the case worth being able to see.
POSITION: Final = ScpiCommand(
    mnemonic=":GPS:POS?",
    summary="The position the receiver is using for its timing solution",
    response=ResponseFormat.VALUE_LIST,
)

ACTUAL_POSITION: Final = ScpiCommand(
    mnemonic=":GPS:POS:ACT?",
    summary="The position currently computed from the satellites",
    response=ResponseFormat.VALUE_LIST,
)

LAST_HELD_POSITION: Final = ScpiCommand(
    mnemonic=":GPS:POS:HOLD:LAST?",
    summary="The last position the receiver held",
    response=ResponseFormat.VALUE_LIST,
)

POSITION_HOLD_STATE: Final = ScpiCommand(
    mnemonic=":GPS:POS:HOLD:STAT?",
    summary="Whether a fixed position is being held",
    response=ResponseFormat.BOOLEAN,
)

#: The satellite table without the screen. §10.5 reads its rows from `:SYST:STAT?` because only the
#: screen carries elevation, azimuth and signal strength — these carry the PRNs alone, which is the
#: part a console user can check a parse against.
TRACKED_SATELLITES: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC?",
    summary="Which satellites the receiver is tracking",
    response=ResponseFormat.INTEGER_LIST,
)

PREDICTED_SATELLITES: Final = ScpiCommand(
    mnemonic=":GPS:SAT:VIS:PRED?",
    summary="Which satellites the receiver expects to be visible",
    response=ResponseFormat.INTEGER_LIST,
)

PREDICTED_SATELLITE_COUNT: Final = ScpiCommand(
    mnemonic=":GPS:SAT:VIS:PRED:COUN?",
    summary="How many satellites the receiver expects to be visible",
    response=ResponseFormat.INTEGER,
)

EXCLUDED_SATELLITE_COUNT: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:IGN:COUN?",
    summary="How many satellites are excluded from tracking",
    response=ResponseFormat.INTEGER,
)

#: One satellite, by PRN. The bounds are §8.3's own: 1 to 32, the GPS constellation's numbering.
IS_SATELLITE_EXCLUDED: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:IGN:STAT?",
    summary="Whether one satellite is excluded from tracking",
    response=ResponseFormat.BOOLEAN,
    argument=ArgumentKind.INTEGER,
    minimum=1,
    maximum=32,
)

INCLUDED_SATELLITES: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:INCL?",
    summary="Which satellites are on the tracking inclusion list",
    response=ResponseFormat.INTEGER_LIST,
)

INCLUDED_SATELLITE_COUNT: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:INCL:COUN?",
    summary="How many satellites are on the inclusion list",
    response=ResponseFormat.INTEGER,
)

IS_SATELLITE_INCLUDED: Final = ScpiCommand(
    mnemonic=":GPS:SAT:TRAC:INCL:STAT?",
    summary="Whether one satellite is on the inclusion list",
    response=ResponseFormat.BOOLEAN,
    argument=ArgumentKind.INTEGER,
    minimum=1,
    maximum=32,
)

#: The four front-panel lamps. Two of them — Active and Enabled — are under software control and
#: their setters are §8.2 actions rather than queries; the other two report what the receiver is
#: doing. All four answer `0` or `1` on the bench, where upstream expects a keyword.
ALARM_LAMP: Final = ScpiCommand(
    mnemonic=":LED:ALAR?",
    summary="The front-panel Alarm indicator",
    response=ResponseFormat.BOOLEAN,
)

GPS_LOCK_LAMP: Final = ScpiCommand(
    mnemonic=":LED:GPSL?",
    summary="The front-panel GPS Lock indicator",
    response=ResponseFormat.BOOLEAN,
)

HOLDOVER_LAMP: Final = ScpiCommand(
    mnemonic=":LED:HOLD?",
    summary="The front-panel Holdover indicator",
    response=ResponseFormat.BOOLEAN,
)

ACTIVE_LAMP: Final = ScpiCommand(
    mnemonic=":LED:ACT?",
    summary="The front-panel Active indicator",
    response=ResponseFormat.BOOLEAN,
)

ENABLED_LAMP: Final = ScpiCommand(
    mnemonic=":LED:ENAB?",
    summary="The front-panel Enabled indicator",
    response=ResponseFormat.BOOLEAN,
)

#: **It repeats the previous query's answer.** Upstream carries it as *"reads a fixed response, used
#: to prove the link is alive"*, and the bench says otherwise: asked after `:SYNC:TFOM?` it answers
#: `+3`, after `:LED:GPSL?` it answers `1`, after `:GPS:SAT:VIS:PRED:COUN?` it answers `+10`, and
#: asked twice in a row it answers the same thing twice. A `*CLS` in between does not disturb it,
#: so what it holds is the last *query* response rather than the last reply of any kind.
#:
#: That still makes it a link test, which is presumably how it earned its name — but a console user
#: told it returns a fixed response would read a stale `+3` as the response and conclude nothing was
#: wrong. Four readings, four different values (#118).
LAST_QUERY_RESPONSE: Final = ScpiCommand(
    mnemonic=":DIAG:QUER:RESP?",
    summary="Repeats the answer to the previous query",
    response=ResponseFormat.TEXT,
)

#: One entry of the diagnostic log. The whole-log form is :data:`DIAGNOSTIC_LOG`, which is why this
#: takes a required entry number where upstream's takes an optional one: §8.1 catalogues a header
#: and the two forms are two headers, so an optional argument would make one entry mean two
#: commands.
LOG_ENTRY: Final = ScpiCommand(
    mnemonic=":DIAG:LOG:READ?",
    summary="One entry of the diagnostic log, by number",
    response=ResponseFormat.MULTI_LINE,
    argument=ArgumentKind.INTEGER,
    minimum=1,
    maximum=999,
)


# ---- §8.2's two Safe setters, and §8.3's two mask setters (#118) ---------------------------------

#: §8.2's third Safe non-query and the only Safe command that takes a value.
#:
#: **Safe because it changes no receiver behaviour** — no timing, no discipline, nothing that
#: outlives the lamp — so a §8.3 confirmation would be asking permission to change nothing. It is
#: documented (`z3801.pdf` Table 4-2, *"Sets or queries Active LED"*), so §8.4's permanent block on
#: undocumented set forms does not reach it.
#:
#: Confirmed on the bench 13 Sep 2026 with the error queue **drained first**: both spellings write,
#: the lamp reads back as commanded, and neither queues an error. That last clause needs the drain
#: to mean anything — read without one, these writes appear to raise `E-221` and the errors are a
#: previous sweep's (#105).
SET_ACTIVE_LAMP: Final = ScpiCommand(
    mnemonic=":LED:ACTive",
    summary="Turn the front-panel Active indicator on or off",
    response=ResponseFormat.NONE,
    argument=ArgumentKind.KEYWORD,
    keywords=("ON", "OFF"),
)

#: The second user-definable indicator. `z3801.pdf`'s *Front Panel at a Glance* names both:
#: *"User-definable indicators labeled Enabled and Active"*.
SET_ENABLED_LAMP: Final = ScpiCommand(
    mnemonic=":LED:ENABled",
    summary="Turn the front-panel Enabled indicator on or off",
    response=ResponseFormat.NONE,
    argument=ArgumentKind.KEYWORD,
    keywords=("ON", "OFF"),
)

#: IEEE 488.2's two mask setters, at §8.3's tier with §8.3's sentence.
#:
#: **The sentence is shared and is the specification's own.** §8.3 gives one row to both, and its
#: wording covers both operations — which is the shape §8.3's own amendment note warns about, where
#: `:IGN:NONE` shared a sentence with the command that did the opposite. It is carried verbatim
#: rather than improved, because §8.3's text is the authority and a divergence in a confirmation
#: sentence is exactly the kind that should be argued in an issue rather than made in a catalogue.
SET_EVENT_ENABLE_MASK: Final = ScpiCommand(
    mnemonic="*ESE",
    summary="Set the standard event status enable mask",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.INTEGER,
    minimum=0,
    maximum=65535,
    confirmation="Change event/service-request enable mask?",
)

SET_SERVICE_REQUEST_MASK: Final = ScpiCommand(
    mnemonic="*SRE",
    summary="Set the service request enable mask",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.INTEGER,
    minimum=0,
    maximum=65535,
    confirmation="Change event/service-request enable mask?",
)


# ---- §8.3's remaining Confirm commands (#118) ----------------------------------------------------
#
# **Every sentence below is §8.3's, verbatim.** A confirmation is the last thing between a user and
# a consequence, and §8.3's table is the authority for its wording — so these are copied rather
# than composed, and where one reads awkwardly it is noted rather than improved.
#
# **None of these was sent to a receiver.** The five that do something would have cost the bench
# unit its configuration, its alarm masks or its 1 PPS phase to verify, and nothing about
# cataloguing them needs that. The queries in #122's batch were all exercised; these are on the
# strength of §8.3 listing them, and that difference is recorded here rather than left for someone
# to assume otherwise.

#: Factory defaults. §8.3's sentence names exactly what is lost, which is the point of it: a user
#: who has spent two hours on a survey should be told the position goes with it.
#:
#: **Not one of §9.7.4's four.** The four commands carrying the extra "I understand" tick are named
#: there and this is not among them, so it is not given one here — adding a fifth would be this
#: repository deciding a §9.7.4 question in a catalogue.
PRESET_RECEIVER: Final = ScpiCommand(
    mnemonic=":SYST:PRESet",
    summary="Reset the receiver's settings to factory defaults",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation=(
        "Reset all receiver settings to factory defaults? Antenna delay, position, elevation "
        "mask, and satellite selections will be lost. Serial port settings are not affected."
    ),
)

#: **A step change in the 1 PPS**, which is the output half of this instrument's whole purpose. Any
#: equipment disciplined to it sees the step too, which is why §8.3's sentence says so plainly.
RESYNCHRONISE: Final = ScpiCommand(
    mnemonic=":SYNC:IMMediate",
    summary="Force an immediate resynchronisation of the 1 PPS output",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation=(
        "Force immediate resynchronisation? This causes a step change in the 1 PPS output."
    ),
)

#: The offset **the receiver itself reports in**, which is not the zone this application displays
#: in — §10.14.1's question 2 declines to offer it for that reason. It is catalogued because §8.3
#: tiers it; no surface sends it, and `time_zone_argument.py` says why the argument is its own kind.
SET_TIME_ZONE: Final = ScpiCommand(
    mnemonic=":PTIM:TZONe",
    summary="Set the time zone offset the receiver reports in",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.FIELD_LIST,
    fields=(FieldSpec("Hours", -12, 14), FieldSpec("Minutes", 0, 59)),
    confirmation=(
        "Change time zone offset? All reported times change, including the timecode output."
    ),
)

# ---- §8.3's three acquisition aids ---------------------------------------------------------------
#
# **Valid only before the first satellite is tracked**, which is what §8.3's shared sentence says
# and what makes them one row: they are the same operation told three ways, helping a cold receiver
# find the sky faster. Sent late, the receiver answers `-221` and nothing happens.
#
# The wire format is the one §10.11 gives literally — `:GPS:INIT:DATE 1994,7,4` — and the field
# ranges are the calendar's own. Three fields with three different ranges is exactly what
# `ArgumentKind.FIELD_LIST` exists for; an integer list would accept month 31.

_ACQUISITION_AID: Final = (
    "Send initial acquisition aid? Only valid before the first satellite is tracked; the receiver "
    "will return error −221 otherwise."
)

INITIAL_DATE: Final = ScpiCommand(
    mnemonic=":GPS:INIT:DATE",
    summary="Tell a cold receiver today's date, to speed acquisition",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.FIELD_LIST,
    fields=(FieldSpec("Year", 1980, 2099), FieldSpec("Month", 1, 12), FieldSpec("Day", 1, 31)),
    confirmation=_ACQUISITION_AID,
)

INITIAL_TIME: Final = ScpiCommand(
    mnemonic=":GPS:INIT:TIME",
    summary="Tell a cold receiver the time, to speed acquisition",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.FIELD_LIST,
    fields=(FieldSpec("Hours", 0, 23), FieldSpec("Minutes", 0, 59), FieldSpec("Seconds", 0, 59)),
    confirmation=_ACQUISITION_AID,
)

#: The position form takes §10.6's nine-part argument, the same one `:GPS:POSition` takes — so it
#: is validated by the same module and cannot drift from it.
INITIAL_POSITION: Final = ScpiCommand(
    mnemonic=":GPS:INIT:POSition",
    summary="Tell a cold receiver roughly where it is, to speed acquisition",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.POSITION,
    confirmation=_ACQUISITION_AID,
)

PRESET_ALARM_MASKS: Final = ScpiCommand(
    mnemonic=":STAT:PRESet:ALARm",
    summary="Reset the alarm masks to their defaults",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    confirmation="Reset alarm masks to defaults?",
)

#: §10.10's Questionable register has a **user-defined** bit, and these two drive it: one sets or
#: clears the condition, the other chooses which transition latches the event.
#:
#: §8.3 gives both one row and one sentence. That is the shape §8.3's own amendment note warns
#: about — `:IGN:NONE` shared a sentence with the command that did the opposite — and it is carried
#: verbatim anyway, because the sentence is the specification's and a divergence in a confirmation
#: belongs in an issue rather than in a catalogue (#125).
SET_USER_QUESTIONABLE_BIT: Final = ScpiCommand(
    mnemonic=":STAT:QUES:COND:USER",
    summary="Set or clear the user-defined questionable status bit",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.KEYWORD,
    keywords=("SET", "CLE"),
    confirmation="Change user-defined questionable status bit?",
)

SET_USER_QUESTIONABLE_TRANSITION: Final = ScpiCommand(
    mnemonic=":STAT:QUES:EVEN:USER",
    summary="Choose which transition latches the user-defined questionable bit",
    response=ResponseFormat.NONE,
    tier=SafetyTier.CONFIRM,
    argument=ArgumentKind.KEYWORD,
    keywords=("PTR", "NTR"),
    confirmation="Change user-defined questionable status bit?",
)


#: IEEE 488.2's self-test, and **§8.3 gives it a row of its own**.
#:
#: §8.2 also lists it, under a heading that reads *"all queries plus non-disruptive actions"* — and
#: that looked like a contradiction worth escalating (#120) until §8.3's table turned out to carry
#: it explicitly, with a sentence naming the consequence. The specific row wins over the general
#: heading, so this is Confirm, and the apparent conflict was a misreading rather than a defect.
#:
#: `transport/timeouts.py` already mapped `*TST?` to the self-test class before anything could send
#: it — the sweep reached 24.0 s on the bench for the `GPS` subsystem alone.
RUN_FULL_SELF_TEST: Final = ScpiCommand(
    mnemonic="*TST?",
    summary="Run the receiver's full self-test",
    response=ResponseFormat.INTEGER,
    tier=SafetyTier.CONFIRM,
    confirmation=(
        "Run the receiver's full self-test? The receiver will drop out of lock and re-acquire, so "
        "the 1 PPS output is degraded for several minutes. The test itself takes up to 30 seconds."
    ),
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
    TIME_CODE,
    LOG_COUNT,
    LIFETIME_HOURS,
    GPS_ENGINE_IDENTITY,
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
    EXCLUDED_SATELLITES,
    EXCLUDE_SATELLITES,
    EXCLUDE_ALL_SATELLITES,
    CLEAR_EXCLUSIONS,
    INCLUDE_SATELLITES,
    INCLUDE_ALL_SATELLITES,
    INCLUDE_NO_SATELLITES,
    SURVEY_PROGRESS,
    SURVEY_STATE,
    SURVEY_ON_POWER_UP,
    START_SURVEY,
    ADOPT_SURVEYED_POSITION,
    RESTORE_LAST_POSITION,
    SET_POSITION,
    SET_SURVEY_ON_POWER_UP,
    EVENT_ENABLE_MASK,
    EVENT_STATUS,
    SERVICE_REQUEST_MASK,
    STATUS_BYTE,
    STATUS_SCREEN_LENGTH,
    SYSTEM_DATE,
    SYSTEM_TIME,
    SERIAL_PORT,
    HOLDOVER_WAIT,
    REFERENCE_VALID,
    POSITION,
    ACTUAL_POSITION,
    LAST_HELD_POSITION,
    POSITION_HOLD_STATE,
    TRACKED_SATELLITES,
    PREDICTED_SATELLITES,
    PREDICTED_SATELLITE_COUNT,
    EXCLUDED_SATELLITE_COUNT,
    IS_SATELLITE_EXCLUDED,
    INCLUDED_SATELLITES,
    INCLUDED_SATELLITE_COUNT,
    IS_SATELLITE_INCLUDED,
    ALARM_LAMP,
    GPS_LOCK_LAMP,
    HOLDOVER_LAMP,
    ACTIVE_LAMP,
    ENABLED_LAMP,
    LAST_QUERY_RESPONSE,
    LOG_ENTRY,
    SET_ACTIVE_LAMP,
    SET_ENABLED_LAMP,
    SET_EVENT_ENABLE_MASK,
    SET_SERVICE_REQUEST_MASK,
    PRESET_RECEIVER,
    RESYNCHRONISE,
    SET_TIME_ZONE,
    INITIAL_DATE,
    INITIAL_TIME,
    INITIAL_POSITION,
    PRESET_ALARM_MASKS,
    SET_USER_QUESTIONABLE_BIT,
    SET_USER_QUESTIONABLE_TRANSITION,
    RUN_FULL_SELF_TEST,
    *EXPERIMENTAL,
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
