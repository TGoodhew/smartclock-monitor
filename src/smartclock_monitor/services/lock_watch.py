"""P1-9: tell the user when the receiver loses GPS lock — and stay quiet when it has not.

**The quiet is the feature.** §10.13 defaults this preference *on*, and says it is only safe to
default on because the watch stays quiet through the flapping a real receiver's log is full of.
That is not hypothetical: the bench Z3805A's diagnostic log alternates *GPS lock started* and
*Holdover started, not tracking GPS* for most of its 222 entries. A watch that fired on every
transition would produce dozens of notifications a day, and the user would turn it off — which
means it would be silent at the moment it existed for.

So a loss must be **sustained** before it is worth saying, and recovery must be sustained before
the next loss can be announced. One notification per real event, and nothing for a receiver
breathing.

**It reports the transition, not the state.** Something that fired while unlocked would be a
repeating alarm, and a repeating alarm about a condition the user has already seen is how an alert
channel gets muted.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Final

from smartclock_device.models.receiver_status import SmartClockMode
from smartclock_monitor.services.polling import Reading

#: How long the receiver must stay unlocked before the loss is worth a notification.
#:
#: A minute. The receiver's own recovery from a brief obstruction is measured in seconds, so this
#: is above the noise and well below the point at which somebody would rather have been told.
SUSTAINED_LOSS: Final = timedelta(minutes=1)

#: How long it must stay locked again before the *next* loss can be announced. The hysteresis is
#: what stops a receiver hovering at the edge from producing a notification per cycle.
SUSTAINED_RECOVERY: Final = timedelta(minutes=5)


class Watched(Enum):
    """What the watch believes, which is not the same as what the last reading said."""

    #: Nothing seen yet.
    UNKNOWN = 0

    #: Locked, and settled there.
    LOCKED = 1

    #: Not locked, but not for long enough to say so.
    SLIPPING = 2

    #: Not locked, long enough that it has been announced.
    LOST = 3

    #: Locked again after a loss, but not yet long enough to re-arm.
    RECOVERING = 4


@dataclass
class LockWatch:
    """Decides when a lock loss is worth telling someone about."""

    #: Called once per sustained loss, with a sentence.
    on_lost: Callable[[str], None] | None = None

    #: Called once per sustained recovery.
    on_recovered: Callable[[str], None] | None = None

    #: §10.13's preference. While off, the watch still tracks state — so switching it on does not
    #: immediately announce a loss that happened an hour ago — but says nothing.
    enabled: bool = True

    loss_after: timedelta = SUSTAINED_LOSS
    recovery_after: timedelta = SUSTAINED_RECOVERY

    _state: Watched = field(default=Watched.UNKNOWN, init=False)
    _since: datetime | None = field(default=None, init=False)
    _mode: SmartClockMode = field(default=SmartClockMode.UNKNOWN, init=False)

    @property
    def state(self) -> Watched:
        return self._state

    def observe(self, reading: Reading) -> None:
        """Take one reading. Fires a callback at most once per real transition.

        Time comes from the reading rather than from a clock of its own: the reading carries the
        instant it was taken, and a watch that asked a clock would be measuring how long *it* had
        been running rather than how long the receiver had been out.
        """
        now = reading.captured_at or reading.status.captured_at
        locked = reading.status.mode is SmartClockMode.LOCKED
        self._mode = reading.status.mode

        match self._state:
            case Watched.UNKNOWN:
                # The first reading never announces. An application that started while the
                # receiver was in holdover would otherwise open with an alert about a condition
                # that predates it, which the user cannot act on and did not cause.
                self._enter(Watched.LOCKED if locked else Watched.SLIPPING, now)

            case Watched.LOCKED:
                if not locked:
                    self._enter(Watched.SLIPPING, now)

            case Watched.SLIPPING:
                if locked:
                    # It came back before the loss was worth mentioning. This is the flapping the
                    # preference's default depends on being invisible.
                    self._enter(Watched.LOCKED, now)
                elif self._held_for(now, self.loss_after):
                    self._enter(Watched.LOST, now)
                    self._say(self.on_lost, self._lost_sentence())

            case Watched.LOST:
                if locked:
                    self._enter(Watched.RECOVERING, now)

            case Watched.RECOVERING:
                if not locked:
                    # Back out again before it settled. Return to LOST **without announcing**: the
                    # user was already told, and telling them again is the repeating alarm this is
                    # built to avoid.
                    self._enter(Watched.LOST, now)
                elif self._held_for(now, self.recovery_after):
                    self._enter(Watched.LOCKED, now)
                    self._say(self.on_recovered, "The receiver is locked to GPS again.")

    def _enter(self, state: Watched, now: datetime) -> None:
        if state is not self._state:
            self._state = state
            self._since = now

    def _held_for(self, now: datetime, span: timedelta) -> bool:
        return self._since is not None and now - self._since >= span

    def _say(self, handler: Callable[[str], None] | None, sentence: str) -> None:
        if self.enabled and handler is not None:
            handler(sentence)

    def _lost_sentence(self) -> str:
        """A whole sentence, per §9.4.3.1: *"Holdover" alone is this application's vocabulary*, and
        someone meeting it in a desktop notification has no other context to read it in."""
        match self._mode:
            case SmartClockMode.HOLDOVER:
                return (
                    "The receiver has lost GPS lock and is in holdover — it is running on its "
                    "own oscillator."
                )
            case SmartClockMode.RECOVERY:
                return "The receiver has lost GPS lock and is trying to reacquire."
            case SmartClockMode.POWER_UP:
                return "The receiver is warming up after power was applied, and is not locked."
            case _:
                return "The receiver is no longer locked to GPS."
