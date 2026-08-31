"""The command allowlist (§8.1).

**This is an allowlist, and that is the whole safety model.** A command that is not an entry here
does not exist as far as the application is concerned. §8.4's exclusions are not entries carrying a
warning flag — they are not entries at all, and ``tests/test_catalog.py`` asserts that no entry
here is one, so the two mechanisms check each other rather than merely coexisting.

There is no free-text command path and there must never be one: §10.11's Advanced Console is a
picker over these entries.

**This is a working subset, not the whole of §8.2.** It holds what the §7.3 poll schedule, the
connect sequence and the Diagnostics reads need — enough for the application to run against real
hardware. The remaining catalogued reads and every tier C setter are still to come, and adding one
is adding a row here. Nothing is reachable that is not on this page.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from smartclock_device.commands.scpi_command import ResponseFormat, ScpiCommand

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
