"""One entry from the receiver's diagnostic log.

The log is the receiver's own account of what has happened to it — power cycles, mode changes,
faults — and is the only history that survives the app not running. §10.9 puts it on the
Diagnostics page with a filter and an export.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DiagnosticLogEntry:
    """One log line, decomposed as far as it honestly can be."""

    #: Exactly what the receiver returned, before any interpretation.
    #:
    #: Kept whole so an entry this version cannot decompose is still exportable and still readable.
    #: §11.1's rule that the parser never raises is only useful if what it could not parse survives.
    raw_text: str

    #: What the receiver logged.
    message: str

    #: The entry number, or ``None`` if the prefix did not parse.
    number: int | None = None

    #: When the entry was recorded, or ``None`` if the timestamp did not parse.
    #:
    #: **On the receiver's own time scale, whichever it is set to** — the GPS or UTC that §11.2's
    #: :attr:`ReceiverStatus.time_scale` reports — and with no offset attached, because the log does
    #: not carry one. It is also subject to the §7.4 week rollover, so an entry from a receiver that
    #: has not been corrected may be 1024 weeks adrift.
    #:
    #: **Tagged UTC even so, which diverges from the C# original.** There a ``DateTime`` of
    #: unspecified kind carries the same caveat harmlessly; in Python a naive value cannot be
    #: compared or differenced against the aware instants the status screen parser produces without
    #: raising ``TypeError``, and §11.1 forbids raising. The two callers of
    #: :func:`~smartclock_device.models.gps_week_rollover.correct` — the parser and the log export —
    #: must therefore agree on one kind. The tag records no claim about the receiver's scale.
    timestamp: datetime | None = None

    @property
    def is_structured(self) -> bool:
        """Whether the prefix parsed into a number and a timestamp."""
        return self.number is not None and self.timestamp is not None
