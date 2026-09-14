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
    GPS_ENGINE = "what GPS receiver is inside the instrument"
    ERROR_QUEUE = "the error queue"
    HARDWARE_CONDITION = "the hardware status register"
    OPERATION_CONDITION = "the operation status register"
    TIME_CODE_FORMAT = "the time-code output format"
    TIME_CODE = "the time code itself"
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


class ReceiverReading(Enum):
    """A reading the interface shows, which a family may have no way of ever supplying (#60).

    **The read-side counterpart of :class:`Capability`.** That one answers *"what may I send"*, and
    §9.11's rule for a command a family lacks — disabled and explained, never hidden — has worked
    since §12's #304. Nothing answered *"what may I ever know"*, so a field the family cannot carry
    rendered as an em dash — which §11.1 defines as a field that **did not parse** and §9.11 as one
    that has **not arrived yet**. Structural absence and a slow read were drawn identically, and a
    user could not tell *"this receiver will never tell you"* from *"this has not come in"*.

    §11 settles what to do about it, in wording added to the specification on 13 Sep 2026: a
    reading a family can never supply is **declined outright rather than dashed**, *"because the em
    dash means not yet and using it for never promises something that will not arrive"*.

    **An entry here is a question a page asks, not a field of the status model.** Several fields
    answer to one entry — :attr:`ONE_PPS_INTERVAL` covers the reading, its trend, the Allan
    deviation and the drift fit, because a family that cannot measure the interval cannot produce
    any of them — which keeps this to what the interface actually annotates.

    **It runs both ways.** A talker has no disciplined oscillator; a status screen has no dilution
    of precision. Neither family is the default.
    """

    # -- What a disciplined oscillator has and a talker has not -----------------------------------

    #: §10.4's time figure of merit — a quality number for the receiver's own time.
    TFOM = "the time figure of merit"

    #: §10.4's frequency figure of merit.
    FFOM = "the frequency figure of merit"

    #: §10.7's 1 PPS time interval against GPS, **and everything derived from it**: the trend, the
    #: Allan deviation and §10.7.1's drift fit. A family that cannot measure the interval cannot
    #: produce any of them.
    ONE_PPS_INTERVAL = "the 1 PPS time interval"

    #: §10.4's oscillator electronic frequency control, and its trend.
    OSCILLATOR_CONTROL = "the oscillator's frequency control"

    #: §10.8's holdover in every form — whether the receiver is in it, for how long, the predicted
    #: and present uncertainty, and the threshold.
    #:
    #: A receiver with no disciplined oscillator does not merely fail to report holdover: it has no
    #: oscillator to hold over, so *"not in holdover"* is a claim rather than a reading.
    HOLDOVER = "holdover"

    #: §10.7's antenna cable delay, as the receiver currently has it.
    ANTENNA_DELAY = "the antenna delay"

    #: §10.4's output validity.
    OUTPUT_VALIDITY = "whether the outputs are valid"

    #: §10.4's serial number and firmware revision.
    #:
    #: Model and manufacturer are **not** here: a driver always supplies those, even where it has
    #: invented them from what it overheard.
    DEVICE_IDENTITY = "the serial number and firmware revision"

    #: §10.14's accumulated GPS − UTC offset and any announced leap second.
    LEAP_SECOND = "the leap-second state"

    #: §10.11's time-code output format.
    TIME_CODE_FORMAT = "the time-code format"

    #: §10.9's total powered hours.
    POWER_ON_HOURS = "hours since manufacture"

    #: §10.9's identity of the GPS engine **inside** the instrument.
    #:
    #: Distinct from :attr:`DEVICE_IDENTITY`, which is the instrument's. A SmartClock is a
    #: disciplining chassis wrapped around somebody else's GPS receiver and the two revise on
    #: separate schedules — the bench unit reports firmware ``1.01.03-A`` while the engine inside it
    #: reports a Furuno GT-80 running software version 005. A talker **is** the GPS receiver, so
    #: there is no second one for it to describe.
    GPS_ENGINE_IDENTITY = "what GPS receiver is inside the instrument"

    #: §10.4 and §10.9's health monitor, and its per-subsystem items.
    HEALTH_MONITOR = "the health monitor"

    #: §10.10's status registers and their masks.
    STATUS_REGISTERS = "the status registers"

    #: §10.9's stored diagnostic log.
    DIAGNOSTIC_LOG = "the diagnostic log"

    #: §10.9's error queue.
    ERROR_QUEUE = "the error queue"

    #: A whole status screen parsed in one read, which is what §11.1's parse-health line reports on.
    #:
    #: A broadcast talker has no status screen at all, so reporting that the last one *"parsed
    #: completely"* is not a good outcome — it is a statement about something that did not happen.
    STATUS_SCREEN = "a parsed status screen"

    #: §10.5's elevation mask, as applied.
    #:
    #: Separate from the command that sets it: a family could report a mask it will not let anyone
    #: change, and §9.11 wants those annotated differently.
    ELEVATION_MASK = "the elevation mask"

    #: §10.6's position hold — surveyed, held or unknown, and any survey in progress.
    POSITION_HOLD = "whether the position is surveyed or held"

    # -- What a talker broadcasts and a status screen has no field for ----------------------------

    #: §10.6's one-sigma position error, from ``GST``.
    #:
    #: The first entry that runs the other way. Every reading above is one a SmartClock supplies
    #: and a talker may not; this is one a talker supplies and a SmartClock cannot — it prints a
    #: position and stops, so no firmware revision will ever add an error estimate to it.
    POSITION_UNCERTAINTY = "the position's error estimate"

    #: §10.6's receiver-autonomous integrity check, from ``GBS``.
    CONSTELLATION_INTEGRITY = "the constellation's integrity check"

    #: §10.14's accumulated GPS − UTC offset **as a talker reports it**, from the time poll.
    #:
    #: Distinct from :attr:`LEAP_SECOND`, which is the SmartClock's own query and covers the
    #: announcement as well as the offset. This is the one figure a broadcast family can produce,
    #: and only because D8 gave it a way to ask.
    GPS_UTC_OFFSET = "the GPS − UTC offset"

    #: §10.6's *kind* of fix — standalone, differential, RTK — as distinct from whether there is
    #: one. A status screen reports a disciplining mode, which is a different question entirely.
    FIX_QUALITY = "what kind of fix it has"


#: Every reading. Named so a gate can walk them without the enum being iterated at a call site,
#: where iterating would be the scatter of conditionals the driver seam exists to prevent.
ALL_READINGS: tuple[ReceiverReading, ...] = tuple(ReceiverReading)


#: Which :class:`~smartclock_device.models.receiver_status.ReceiverStatus` fields answer to each
#: reading, for the readings that live on that model at all.
#:
#: **Deliberately partial, and the gaps are the interesting part.** A reading is a question a page
#: asks, and several of them are answered from somewhere other than the status: the oscillator's
#: control voltage is carried on ``services.polling.Reading`` because it has no place on a status
#: screen's model, the diagnostic log and the error queue are read on demand rather than polled,
#: and the status registers have a model of their own. Those map to nothing here, and a caller that
#: needs them has to say which surface it means.
#:
#: This exists so the tier rule can be **checked** rather than asserted: `apply_fast` must fold
#: only the readings its plan says the fast tier carries, and without a mapping from reading to
#: field there is no way to ask whether it did.
STATUS_FIELDS: dict[ReceiverReading, tuple[str, ...]] = {
    ReceiverReading.TFOM: ("tfom",),
    ReceiverReading.FFOM: ("ffom",),
    ReceiverReading.ONE_PPS_INTERVAL: ("one_pps_ti_nanoseconds",),
    ReceiverReading.HOLDOVER: (
        "hold_threshold_seconds",
        "holdover_predicted_seconds",
        "holdover_present_seconds",
        "holdover_duration",
    ),
    ReceiverReading.ANTENNA_DELAY: ("antenna_delay_nanoseconds",),
    ReceiverReading.OUTPUT_VALIDITY: ("outputs",),
    ReceiverReading.LEAP_SECOND: ("leap_pending",),
    ReceiverReading.HEALTH_MONITOR: ("health_ok", "health_items"),
    ReceiverReading.STATUS_SCREEN: ("parse_warnings",),
    ReceiverReading.ELEVATION_MASK: ("elevation_mask_degrees",),
    ReceiverReading.POSITION_HOLD: (
        "position_mode",
        "survey_percent_complete",
        "survey_suspended_reason",
    ),
    ReceiverReading.POSITION_UNCERTAINTY: ("uncertainty",),
    ReceiverReading.CONSTELLATION_INTEGRITY: ("integrity",),
    ReceiverReading.FIX_QUALITY: ("fix_quality",),
    ReceiverReading.GPS_UTC_OFFSET: ("gps_utc_offset_seconds", "gps_utc_is_default"),
}
