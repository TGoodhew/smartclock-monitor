"""One decoded ``:SYST:STAT?`` status screen — the receiver's entire visible state.

The shape follows §11.2. Almost every member is optional, and that is the type system carrying
§11.1's central rule: the parser never raises, an unparseable field becomes ``None``, and the UI
renders it as an em dash. ``mypy --strict`` is what makes a consumer that forgets a field a build
failure rather than a crash in the field; without it, this guarantee is a comment.

A frozen dataclass per §6.4 — one screen is one immutable value, and the polling loop replaces it
rather than mutating it, which is what makes it safe to hand to the UI thread without copying.
``kw_only`` because thirty positional fields of mostly the same type is a transposition waiting
to happen.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType

from smartclock_device.models.position import (
    GeoPosition,
    HeightDatum,
    PositionMode,
    PositionQualifier,
    SurveySuspendedReason,
)
from smartclock_device.models.satellite import PredictedSatellite, TrackedSatellite


class OutputValidity(Enum):
    """How far the receiver's 10 MHz and 1 PPS outputs can be trusted.

    Read from the bracketed annotation on the ``SYNCHRONIZATION`` banner. The middle value exists
    because a receiver that has lost GPS keeps driving its outputs from the oscillator, and the
    distinction between "usable but drifting" and "do not use" is the single most important thing
    the main window has to convey.
    """

    #: The banner carried no recognisable annotation.
    UNKNOWN = 0

    #: Outputs are not to be trusted.
    INVALID = 1

    #: Outputs are usable but the accuracy specification no longer holds.
    VALID_REDUCED = 2

    #: Outputs are within specification.
    VALID = 3


class SmartClockMode(Enum):
    """The receiver's SmartClock mode — HP's own term for the disciplining state machine, kept
    verbatim per Appendix B.

    The status screen prints all four modes as a menu and marks the active one with ``>>``, so the
    parser looks for the marker rather than for any particular mode word.
    """

    #: No mode line carried the ``>>`` marker.
    UNKNOWN = 0

    #: Locked to GPS and disciplining the oscillator.
    LOCKED = 1

    #: Reacquiring after a loss of GPS.
    RECOVERY = 2

    #: Running on the oscillator alone, with no GPS discipline.
    HOLDOVER = 3

    #: Warming up after power was applied.
    POWER_UP = 4


class SignalStrengthKind(Enum):
    """Which signal-strength scale the acquisition table is printed on.

    §11.1 is emphatic that the two are not interchangeable: ``C/N`` on 58503B-class units runs
    26–55 with 35 and above good, while ``SS`` on 59551A-class units runs 0–255 with 20–30 weak.
    A strength bar scaled to the wrong one is not merely mislabelled, it is wrong by a factor of
    five, so this is recorded from the header the receiver actually printed rather than inferred
    from the model number.
    """

    #: No signal-strength column was found, which is normal when nothing is tracked.
    UNKNOWN = 0

    #: Carrier-to-noise ratio, printed as ``C/N``.
    CARRIER_TO_NOISE = 1

    #: Raw signal strength, printed as ``SS``.
    SIGNAL_STRENGTH = 2


class TimeScale(Enum):
    """The time scale the receiver's clock display is referenced to."""

    #: The time row carried no recognisable scale.
    UNKNOWN = 0

    #: GPS time, which does not include leap seconds.
    GPS = 1

    #: Coordinated Universal Time.
    UTC = 2

    #: Local time derived from GPS time.
    LOCAL_GPS = 3

    #: Local time derived from UTC.
    LOCAL = 4


class LeapSecondPending(Enum):
    """Whether a leap second is scheduled at the end of the current UTC month."""

    #: No leap second is pending.
    NONE = 0

    #: A second will be inserted.
    PLUS = 1

    #: A second will be removed.
    MINUS = 2


class ClockAdvisory(Enum):
    """The ``1PPS CLK`` advisory as one of the §11.3 values.

    §11.3 requires an enum here "because the UI branches on them", and keeps no string form of the
    advisory on the model at all: the mapping from the device's text lives entirely in the parser,
    so no view is able to branch on a display string even by accident.

    ``Assessing stability`` is the case that shows why. It arrives with nought to three trailing
    dots, which animate on the device's own screen — four spellings of one state to a string
    comparison. The dots carry no information and are stripped before matching.
    """

    #: No advisory was printed.
    NONE = 0

    #: Locked and referenced to UTC.
    SYNCHRONIZED_TO_UTC = 1

    #: Locked and referenced to GPS time.
    SYNCHRONIZED_TO_GPS_TIME = 2

    #: Hysteresis is being applied before the receiver commits to a lock.
    ASSESSING_STABILITY = 3

    #: A 1 PPS is present but is not trusted.
    QUESTIONABLE_ACCURACY = 4

    #: Inaccurate because no satellites are being tracked.
    INACCURATE_NOT_TRACKING = 5

    #: Inaccurate because the position is not yet known.
    INACCURATE_INACCURATE_POSITION = 6

    #: No 1 PPS at all, or the GPS engine is idle.
    ABSENT_OR_FREQUENCY_ERROR = 7

    #: The GPS receiver engine reported an error.
    INVALID_GPS_RECEIVER_ERROR = 8

    #: An advisory this table does not cover. The device's wording is recorded in
    #: :attr:`ReceiverStatus.parse_warnings`.
    OTHER = 9


_NO_HEALTH_ITEMS: Mapping[str, bool] = MappingProxyType({})


@dataclass(frozen=True, slots=True, kw_only=True)
class ReceiverStatus:
    """The receiver's entire visible state, as of one status screen."""

    # ---- PROVENANCE -------------------------------------------------------------------------

    #: When this screen was parsed, from the injected :class:`~smartclock_device.clock.Clock`.
    #:
    #: Required, unlike the C# original where it defaults to the zero date. There is no
    #: defensible default for "when did this happen", and a status screen that cannot say is a
    #: status screen whose staleness display and trend row are both wrong. Making it required
    #: means ``mypy`` refuses a construction that forgot to inject a clock.
    captured_at: datetime

    # ---- SYNCHRONIZATION --------------------------------------------------------------------

    #: How far the outputs can be trusted.
    outputs: OutputValidity = OutputValidity.UNKNOWN

    #: The active SmartClock mode.
    mode: SmartClockMode = SmartClockMode.UNKNOWN

    #: The text after the mode name, such as ``stabilizing frequency``.
    mode_detail: str | None = None

    #: Time figure of merit, lower being better.
    tfom: int | None = None

    #: Frequency figure of merit, lower being better.
    ffom: int | None = None

    #: The 1 PPS time interval against GPS, in nanoseconds.
    one_pps_ti_nanoseconds: float | None = None

    #: The holdover threshold, in seconds.
    hold_threshold_seconds: float | None = None

    #: Predicted holdover uncertainty over the stated initial interval, in seconds.
    holdover_predicted_seconds: float | None = None

    #: Present holdover uncertainty, in seconds.
    holdover_present_seconds: float | None = None

    #: How long the receiver has been in holdover *and recovery*, together.
    #:
    #: Not "how long since the signal was lost", though it is easy to read it that way. The
    #: Z3801A guide states twice that this is "the cumulative duration of holdover and recovery
    #: operations", so the counter keeps running after the antenna is reconnected and only stops
    #: when lock is regained. What it measures is how long the outputs have been degraded, which
    #: is the question a user actually has.
    holdover_duration: timedelta | None = None

    # ---- ACQUISITION ------------------------------------------------------------------------

    #: Whether the GPS engine's own 1 PPS is valid, from the acquisition banner.
    gps_one_pps_valid: bool = False

    #: Satellites currently being tracked.
    tracked: tuple[TrackedSatellite, ...] = ()

    #: Satellites expected to be visible but not tracked.
    not_tracked: tuple[PredictedSatellite, ...] = ()

    #: The elevation mask below which satellites are ignored, in degrees.
    elevation_mask_degrees: int | None = None

    #: Which scale :attr:`TrackedSatellite.signal_strength` is expressed on.
    signal_strength_kind: SignalStrengthKind = SignalStrengthKind.UNKNOWN

    # ---- TIME -------------------------------------------------------------------------------

    #: The time scale the clock row is referenced to.
    time_scale: TimeScale = TimeScale.UNKNOWN

    #: The date and time exactly as the device reported it, uncorrected.
    device_date_time: datetime | None = None

    #: Whether the clock row carried the power-up marker, meaning the time has not yet been
    #: corrected from GPS (§11.2, #245).
    #:
    #: The receiver prints ``(?)`` between the time and the date — ``[?]`` in the Z3801A user
    #: guide, Figure 3-1 — and the guide says the value is *"the default power-up setting …
    #: corrected when the first satellite is tracked"*.
    #:
    #: **This flag is why the marker is not simply tolerated in the pattern.** The two known
    #: examples show how far apart a marked time can be from the truth: the screen captured from
    #: this unit read ``05:10:04 (?) 12 Jan 2007`` and was right to the minute, because the
    #: oscillator held time across the power cycle, while the manual's ``12:00:00[?] 01 JAN
    #: 1996`` is a placeholder that is arbitrarily wrong. **The marker is the only thing that
    #: distinguishes them.** Parsing the value and dropping the marker would convert a knowable
    #: caveat into a silent inaccuracy — worse than refusing the row, not better.
    #:
    #: Distinct from :attr:`one_pps_clock_advisory`, which describes the 1 PPS *signal* and is
    #: read from the ``GPS 1PPS …`` line two rows below. This is a property of the time-of-day
    #: reading itself.
    device_time_is_provisional: bool = False

    #: How many 1024-week GPS epochs the device's date is behind, per §7.4. Zero on a receiver
    #: whose firmware has not rolled over.
    week_rollover_epochs: int = 0

    #: :attr:`device_date_time` advanced by :attr:`week_rollover_epochs` epochs, or ``None`` when
    #: there is no date to correct.
    #:
    #: §7.4 forbids silently substituting this for the raw value: the UI shows the corrected date
    #: with a badge and keeps the device's own date in the tooltip, because a user who sees the
    #: wrong year and no explanation reasonably assumes the hardware has failed.
    corrected_date_time: datetime | None = None

    #: The ``1PPS CLK`` advisory, decoded (§11.3).
    one_pps_clock_advisory: ClockAdvisory = ClockAdvisory.NONE

    #: The configured antenna cable delay, in nanoseconds.
    antenna_delay_nanoseconds: float | None = None

    #: Whether a leap second is scheduled.
    leap_pending: LeapSecondPending = LeapSecondPending.NONE

    # ---- POSITION ---------------------------------------------------------------------------

    #: Whether the receiver is holding a position or surveying for one.
    position_mode: PositionMode = PositionMode.UNKNOWN

    #: Survey progress, 0 to 100, when a survey is running.
    survey_percent_complete: float | None = None

    #: Why a survey is suspended, decoded (§11.3).
    survey_suspended_reason: SurveySuspendedReason = SurveySuspendedReason.NONE

    #: The reported position.
    position: GeoPosition | None = None

    #: How much to trust the reported position.
    position_qualifier: PositionQualifier = PositionQualifier.UNKNOWN

    #: Which datum :attr:`GeoPosition.height_metres` is measured against.
    height_datum: HeightDatum = HeightDatum.UNKNOWN

    # ---- HEALTH -----------------------------------------------------------------------------

    #: Whether the health monitor banner read ``OK``.
    health_ok: bool = False

    #: Each health item the receiver listed, in screen order, against whether it passed.
    #:
    #: Keyed by the device's own label rather than a fixed set of fields, because the item list
    #: differs across the family and an unrecognised item must still reach the Diagnostics page
    #: rather than being dropped. Insertion order is screen order.
    #:
    #: The C# original keys this ``OrdinalIgnoreCase``; Python has no case-insensitive mapping,
    #: so the case-folding lives in :meth:`health_item` and the mapping itself stays exactly what
    #: the device printed. Look items up through that method, not with ``[]``.
    health_items: Mapping[str, bool] = _NO_HEALTH_ITEMS

    #: Everything the parser could not make sense of, in the order it was met.
    #:
    #: Surfaced on the Diagnostics page so that a field report about an odd firmware revision is
    #: actionable — "it shows dashes" is not a bug report, "unrecognised health item 'Xtal Pwr'"
    #: is.
    parse_warnings: tuple[str, ...] = ()

    def health_item(self, label: str) -> bool | None:
        """Whether a named health item passed, matched without regard to case.

        ``None`` when the receiver did not list it, which is not the same as listing it as
        failed — a family that has no oscillator-oven item has not got a cold oven.
        """
        folded = label.casefold()
        for name, passed in self.health_items.items():
            if name.casefold() == folded:
                return passed
        return None
