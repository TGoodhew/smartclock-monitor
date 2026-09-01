"""What a page wants done, named for the want rather than for how a family spells it.

CLAUDE.md's architecture rule: *"Every receiver-specific fact sits behind a driver. The application
never reaches the SmartClock driver or the NMEA driver directly; it asks the driver the session
selected."* Until this existed the pages imported ``commands.catalog`` and named its entries, which
is reaching the SmartClock catalog directly — fifty-odd times.

**The crash was already closed**; this is not that. ``views/capability.py``'s gate stopped a
reads-only family from throwing on navigation, and §9.11's *disabled and explained* is already how
an absent command renders. What remains is that a page asking
``driver.supports(catalog.RUN_SELF_TEST)`` hands one family's command object to another family's
driver, and works only because the second answers ``False``. It reads as decoupled and is not.

**Named for the want.** ``RUN_SELF_TEST`` rather than ``:DIAG:TEST``, so a family that spells it
differently — or achieves it a different way — answers the same question. That is also why these
names match the catalog's constants: those were already named for intent, and a second vocabulary
saying the same things in different words would be a translation layer to keep in step.

**A capability the family lacks is ``None``, never an error.** §9.11 again: the page disables the
control and says which family cannot do it. A talker answers ``None`` to every one of these, which
is the honest answer for a receiver that is never written to and has no command parser at all.

This diverges from WinZ3805A, which keeps mnemonics at the call site and gates on them
(``Views/Capability.cs``, #304). The gate is the same; what is added here is that the page no longer
knows there is such a thing as SCPI. `docs/divergences.md` records it.
"""

from __future__ import annotations

from enum import Enum


class Capability(Enum):
    """One thing a page may want a receiver to do.

    Membership is *not* a claim that any family offers it — :meth:`ReceiverDriver.command` answers
    that, per family and per connection.
    """

    # -- Reading -------------------------------------------------------------------------------
    ANTENNA_DELAY = "antenna delay"
    ELEVATION_MASK = "elevation mask"
    EXCLUDED_SATELLITES = "which satellites are excluded"
    SURVEY_ON_POWER_UP = "whether a survey runs at power-up"
    HOLDOVER_DURATION_THRESHOLD = "the holdover uncertainty threshold"
    DIAGNOSTIC_LOG = "the diagnostic log"
    LOG_COUNT = "how many log entries there are"
    LIFETIME_HOURS = "hours since manufacture"
    ERROR_QUEUE = "the error queue"
    HARDWARE_CONDITION = "the hardware status register"
    TIME_CODE_FORMAT = "the time-code output format"
    LEAP_ACCUMULATED = "accumulated leap seconds"
    LEAP_DATE = "the announced leap second's date"
    LEAP_DURATION = "the announced leap second's direction"
    LEAP_STATE = "whether a leap second is announced"

    # -- Writing -------------------------------------------------------------------------------
    SET_ANTENNA_DELAY = "set the antenna delay"
    SET_ELEVATION_MASK = "set the elevation mask"
    SET_HOLDOVER_DURATION_THRESHOLD = "set the holdover uncertainty threshold"
    SET_SURVEY_ON_POWER_UP = "set whether a survey runs at power-up"
    SET_POSITION = "set the fixed position"

    EXCLUDE_SATELLITES = "exclude satellites from tracking"
    EXCLUDE_ALL_SATELLITES = "exclude every satellite"
    CLEAR_EXCLUSIONS = "track every satellite again"

    START_SURVEY = "start a position survey"
    ADOPT_SURVEYED_POSITION = "adopt the surveyed position"
    RESTORE_LAST_POSITION = "restore the last held position"

    HOLDOVER_FORCE = "force holdover"
    HOLDOVER_RECOVER = "recover from holdover"
    HOLDOVER_IGNORE_RECOVERY_LIMIT = "ignore the recovery limit"

    RUN_SELF_TEST = "run a self test"
    CLEAR_DIAGNOSTIC_LOG = "clear the diagnostic log"


class CommandGroup(Enum):
    """A set a page offers together, where the set itself is the family's business.

    Separate from :class:`Capability` because the *number* of them is not fixed: §8.5 has six
    experimental queries for this receiver and might have none for another, and §10.10's register
    setters depend on how many registers the family has. A page renders one control per member and
    must not assume a count.
    """

    #: §8.5's undocumented read-only queries, behind §10.13's opt-in.
    EXPERIMENTAL = "experimental queries"

    #: §10.10's mask setters, one per register field.
    REGISTER_SETTERS = "status register setters"
