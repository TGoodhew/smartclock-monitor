"""The injected clock.

There is no ``datetime.now()`` in this codebase, and the ban is enforced by ruff's ``TID251``
rather than by review — see the banned-api table in ``pyproject.toml``. This is the thing that
gets called instead.

The reason is §7.4. The GPS week rollover is detected by comparing the date the receiver printed
against the host's idea of now, so "what time is it" is an *input* to parsing, not an ambient
fact. A fixture captured in August 2026 has to parse the same way in 2031, and the only way to
write that test is to hand the parser a clock that says August 2026. Poll scheduling (§7.3) and
staleness display have the same shape.

This is the port of C#'s ``TimeProvider``, cut down to the one member this project uses.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    """Something that can say what time it is."""

    def utc_now(self) -> datetime:
        """The current instant, timezone-aware and in UTC.

        Timezone-aware without exception: a naive datetime compared against an aware one raises
        ``TypeError``, and §11.1 forbids the parser from raising.
        """
        ...


class SystemClock:
    """The real clock. The one place in the codebase permitted to ask the operating system."""

    def utc_now(self) -> datetime:
        # ruff: noqa: TID251 - this is the single sanctioned call site, and the reason the rule
        # names a symbol rather than a module: everywhere else, the fix is to take a Clock.
        return datetime.now(UTC)


class FixedClock:
    """A clock that reports a pinned instant, advanced only when a test says so.

    Lives beside the real one rather than in ``tests/`` because the fixture replay in Phase 4 and
    the NMEA simulator both need it, and a test helper that two non-test callers import is not a
    test helper.
    """

    def __init__(self, now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError(
                "A FixedClock needs an aware datetime; a naive one cannot be compared."
            )
        self._now = now.astimezone(UTC)

    def utc_now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        """Move the clock forward.

        Backwards is allowed; the receiver's date can go backwards too.
        """
        self._now += delta
