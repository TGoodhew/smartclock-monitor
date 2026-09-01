"""§12's broadcast listener: reading a receiver that talks instead of answering.

A talker sends the same set of sentences over and over. There is no request to correlate a reply
with, so the listener does the correlating: every line the driver claims is filed under the plan key
the driver names, and the keys are read back **from the last complete cycle**.

**Cycles are delimited by the plan's first fast-tier entry.** That entry must therefore be a line
the talker sends exactly once per cycle, *every* cycle — a cycle whose boundary never arrives never
closes and is never answered. That is a requirement on the driver, and it is the same entry §7.3.1
calls the discriminator for a query/response family, which is why it is one field rather than two.

**Answers come from the last complete cycle, never the one in progress.** A sentence that arrives
in three parts is a sentence that is wrong twice before it is right, and a reader who saw the
half-arrived state would see a satellite count drop and recover every second.

**A talker that has gone quiet is reported as a timeout**, not as a distinct state. §7.2's reconnect
policy already knows what to do about a link that stops answering, and giving broadcast its own
failure vocabulary would mean teaching the supervisor a second one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from smartclock_device.clock import Clock


@dataclass
class BroadcastListener:
    """Sorts a talker's lines into cycles and answers plan keys from the last complete one."""

    clock: Clock

    #: The plan key that delimits a cycle — the driver's first fast-tier entry.
    boundary: str

    #: How long a talker may be silent before the listener reports a timeout. Generous relative to
    #: a 1 Hz talker: a missed sentence is ordinary and a missed *second* is not.
    quiet_after: timedelta = timedelta(seconds=5)

    _current: dict[str, list[str]] = field(default_factory=dict, init=False)
    _complete: dict[str, list[str]] = field(default_factory=dict, init=False)
    _last_line_at: datetime | None = field(default=None, init=False)
    _cycles: int = field(default=0, init=False)

    def feed(self, key: str | None, line: str) -> None:
        """Take one line the driver has classified.

        ``None`` — a line this family does not claim — still counts as **traffic**: a talker
        sharing a bus with something else is alive, and treating another device's sentence as
        silence would report a link that is plainly working as gone.
        """
        self._last_line_at = self.clock.utc_now()
        if key is None:
            return

        if key == self.boundary and self.boundary in self._current:
            # The boundary has come round again: what we have is a complete cycle.
            self._close()

        self._current.setdefault(key, []).append(line)

    def _close(self) -> None:
        self._complete = self._current
        self._current = {}
        self._cycles += 1

    def answer(self, key: str) -> tuple[str, ...]:
        """What the last complete cycle said for this key, or empty.

        Empty rather than the in-progress cycle's lines: a key that has not been heard yet and a
        key heard half a cycle ago are both "nothing to report", and §11.1's consumers already
        render nothing as a dash.
        """
        return tuple(self._complete.get(key, ()))

    def whole_cycle(self) -> tuple[str, ...]:
        """Every line of the last complete cycle, in the order it arrived.

        §12's ``WHOLE_CYCLE`` key: a broadcast family's full read is the cycle entire, because its
        "status screen" is spread across a dozen sentences rather than printed as one.
        """
        lines: list[str] = []
        for key_lines in self._complete.values():
            lines.extend(key_lines)
        return tuple(lines)

    @property
    def cycles(self) -> int:
        """How many complete cycles have been seen. Zero means nothing can be answered yet."""
        return self._cycles

    @property
    def has_answered(self) -> bool:
        return self._cycles > 0

    def is_quiet(self) -> bool:
        """Whether the talker has stopped, in the terms §7.2's reconnect policy already uses.

        A listener that has heard **nothing at all** is quiet from the moment it is asked: a port
        opened onto a device that never speaks is exactly the case auto-detect walks past, and
        waiting five seconds to say so would cost five seconds per combination.
        """
        if self._last_line_at is None:
            return True
        return self.clock.utc_now() - self._last_line_at >= self.quiet_after

    def take(self, lines: Sequence[tuple[str | None, str]]) -> None:
        """Feed several at once, for a reader that hands over a chunk."""
        for key, line in lines:
            self.feed(key, line)
