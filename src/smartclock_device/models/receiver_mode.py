"""What the receiver is doing, in the vocabulary every family is presented in.

§10.3 tabulates these against the SmartClock's ``:SYNC:STAT?`` answers, which is where they came
from — but the medallion, the tray icon and the announcer all switch on this enum rather than on
a token, so it is the application's vocabulary and not one receiver's. It lives in the device
layer so a driver can name a mode without the layer importing the application (#304): the
classification is the driver's, and the severity, glyph and label the mode is drawn with belong
to §9 and stay in the application.

**The set is deliberately closed.** A family whose states do not fit is a family whose driver
must choose the nearest honest member — the NMEA driver calls a fix :attr:`~ReceiverMode.LOCKED`
and no fix :attr:`~ReceiverMode.POWER_UP`, and says so — rather than one this enum grows a member
for. Growing it means a new severity, a new glyph and a new label, which is §9's decision and not
a driver author's.
"""

from __future__ import annotations

from enum import Enum


class ReceiverMode(Enum):
    """The closed set of states the application can draw."""

    #: Nothing is connected, the link has gone, or the receiver said something unrecognised.
    DISCONNECTED = 0

    #: Locked to GPS.
    LOCKED = 1

    #: Recovering toward lock.
    RECOVERING = 2

    #: Waiting before it may recover.
    WAITING = 3

    #: Running on the oscillator alone.
    HOLDOVER = 4

    #: Warming up after power was applied.
    POWER_UP = 5

    #: In diagnostics, or with outputs off.
    OFF = 6
