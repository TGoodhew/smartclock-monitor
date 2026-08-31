"""§7.4's 1024-week rollover: the period, and what applying it to an instant means.

A separate module because the correction has two callers with nothing else in common. The parser
applies it to the status screen's own date, comparing against the host clock to decide whether a
rollover has happened at all; the log export applies the epoch count the parser arrived at to
timestamps the receiver printed years earlier, where there is no host clock to compare against.

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
