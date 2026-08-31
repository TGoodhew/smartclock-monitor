"""The position section of the status screen: what it means, and what it reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PositionMode(Enum):
    """Whether the receiver is holding a fixed position or surveying for one."""

    #: The screen carried no recognisable position mode.
    UNKNOWN = 0

    #: A fixed position is in use — the normal state for a stationary timing receiver.
    HOLD = 1

    #: A position survey is in progress.
    SURVEY = 2


class PositionQualifier(Enum):
    """How much to trust the reported coordinates."""

    #: The screen carried no qualifier, which is the ordinary case on a held position.
    UNKNOWN = 0

    #: An initial estimate, not yet refined.
    INIT = 1

    #: An average accumulated by a survey in progress.
    AVERAGE = 2

    #: A held fixed position.
    HELD = 3


class HeightDatum(Enum):
    """Which vertical datum the height is measured against.

    Worth keeping distinct rather than normalising: the two differ by the geoid separation, which
    is tens of metres in places, and a user checking a surveyed position against a map needs to
    know which one the receiver printed.
    """

    #: The screen did not say.
    UNKNOWN = 0

    #: Height above the WGS-84 reference ellipsoid.
    GPS_ELLIPSOID = 1

    #: Height above mean sea level.
    MSL = 2


class SurveySuspendedReason(Enum):
    """Why a position survey stopped making progress (§11.3).

    An enum rather than free text because the UI branches on it: "fewer than four satellites" and
    "poor geometry" want different advice, and matching on a display string would break the day a
    firmware revision rewords one. §11.3 keeps no string form on the model for that reason — when
    the text does not match the table the value is :attr:`OTHER` and the device's exact wording
    goes to :attr:`ReceiverStatus.parse_warnings`.
    """

    #: The survey is not suspended.
    NONE = 0

    #: Fewer than the four satellites a three-dimensional fix needs.
    TOO_FEW_SATELLITES = 1

    #: Enough satellites, but their geometry gives too weak a solution.
    POOR_GEOMETRY = 2

    #: No tracking data available at all.
    NO_TRACK_DATA = 3

    #: Suspended for a reason this table does not cover. The device's wording is recorded in
    #: :attr:`ReceiverStatus.parse_warnings`.
    OTHER = 4


@dataclass(frozen=True, slots=True)
class GeoPosition:
    """A geodetic position as the receiver reports it.

    The receiver prints degrees, minutes and seconds with a hemisphere letter
    (``N  47:31:18.822``). This stores signed decimal degrees, which is what every consumer — the
    position readout, the map link, the distance-from-survey calculation — actually wants, while
    :attr:`ReceiverStatus.parse_warnings` records anything that would not convert.
    """

    #: Latitude in signed decimal degrees; positive north.
    latitude_degrees: float | None = None

    #: Longitude in signed decimal degrees; positive east.
    longitude_degrees: float | None = None

    #: Height in metres, measured against :attr:`ReceiverStatus.height_datum`.
    height_metres: float | None = None
