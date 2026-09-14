"""§7.4's 1024-week rollover: the period, and what applying it to an instant means.

A separate module because the correction has three callers with nothing else in common. The parser
applies it to the status screen's own date, comparing against the host clock to decide whether a
rollover has happened at all; the log export applies the epoch count the parser arrived at to
timestamps the receiver printed years earlier, where there is no host clock to compare against; and
the time-code decoder (#113) reads a date from a second, independent route and needs the same
answer about it.

**The third caller is why the detection moved here.** It had lived inside the status-screen parser,
which made it a fact about *that screen* rather than about §7.4 — and the time code carries the
same rolled-over date through a different query. Two implementations of a correction this port
exists to get right is exactly what this module was created to prevent.

The alternative was 1024 weeks written down twice, which is exactly the kind of duplication that
stays correct until one of the two is touched.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Final

#: One GPS epoch: 1024 weeks, after which an unpatched receiver's date wraps (§7.4).
EPOCH: Final = timedelta(days=7168)

#: How far from an exact multiple of :data:`EPOCH` still counts as a rollover (§7.4).
TOLERANCE: Final = timedelta(days=7)


def epochs_behind(device_time: datetime | None, now: datetime) -> int:
    """How many whole epochs behind the host clock the receiver's date is. Zero when none applies.

    §7.4's detection half. A receiver whose date is close to a whole number of epochs behind has
    rolled over; one that is a long way behind by some other amount has **the wrong date set**, and
    inventing a correction for that would be worse than showing what the device said — so the
    tolerance is a band around a multiple and not a floor.
    """
    if device_time is None:
        return 0

    delta = now - device_time
    # Both C#'s Math.Round(double) and Python's round() are banker's rounding, so this needs no
    # adjustment — unlike the coordinate seconds, where C# asks for AwayFromZero explicitly.
    epochs = round(delta / EPOCH)
    if epochs <= 0:
        return 0

    return epochs if abs(delta - EPOCH * epochs) <= TOLERANCE else 0


def correct(value: datetime | None, epochs: int) -> datetime | None:
    """Advance an instant by a number of epochs, or return ``None`` if there is nothing to advance.

    :param value: The instant the receiver reported.
    :param epochs: How many epochs behind the receiver is, from
        :attr:`ReceiverStatus.week_rollover_epochs`. Zero returns ``None`` rather than the input:
        no correction applies, and returning the value unchanged would imply one was computed and
        came to nothing.
    """
    if value is None or epochs <= 0:
        return None
    return value + EPOCH * epochs
