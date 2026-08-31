"""One subsystem ``:DIAG:TEST?`` will test, and the keyword it is asked for by (P1-5, #53).

**Probed, not guessed.** The Z3801A guide does not document ``:DIAG:TEST?``'s parameter at all —
there the command appears only in the error list for ``-330``. The 58503A/59551A guide does, and
disagrees with itself: its Quick Reference (4-9) lists twelve keywords and its Command Reference
(5-54) eleven, omitting ``IREFerence``, and §10.9's eleven names had no stated source. Each was
sent to the live receiver on 28 Aug 2026 and all twelve were accepted, which is what turned this
from a plausible list into a fact.

The control that made the result mean something was an invalid keyword sent first:
``:DIAG:TEST? ZZNOSUCH`` returned ``-224,"Illegal parameter value"`` immediately and ran nothing.
Without it, a keyword that was silently ignored would have looked exactly like one that worked.

:data:`ALL` is the receiver's own sweep rather than this application running the other eleven in
turn. It is one command, took 12.4 s where eleven sequential runs would cost close to a minute of
testing, and — the part that matters — it is what the hardware offers rather than something
invented on top of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class SelfTestSubsystem:
    """A subsystem the receiver can be asked to test."""

    #: The keyword sent to the receiver — ``DISP``, ``GPS``, ``ALL`` and so on.
    keyword: str

    #: The §10.9 name, for the selector and the result row.
    display_name: str


#: Every keyword the receiver accepts, in §10.9's order.
KNOWN: Final[tuple[SelfTestSubsystem, ...]] = (
    SelfTestSubsystem("ALL", "All subsystems"),
    SelfTestSubsystem("DISP", "Display"),
    SelfTestSubsystem("PROC", "Processor"),
    SelfTestSubsystem("RAM", "RAM"),
    SelfTestSubsystem("EEPR", "EEPROM"),
    SelfTestSubsystem("UART", "UART"),
    SelfTestSubsystem("QSPI", "QSPI"),
    SelfTestSubsystem("FPGA", "FPGA"),
    SelfTestSubsystem("INT", "Interpolator"),
    SelfTestSubsystem("IREF", "Internal reference"),
    SelfTestSubsystem("GPS", "GPS"),
    SelfTestSubsystem("POW", "Power"),
)

#: The sweep the receiver performs itself — the first entry of :data:`KNOWN`, not the whole list.
ALL: Final = KNOWN[0]


def by_keyword(keyword: str | None) -> SelfTestSubsystem | None:
    """Find a subsystem by the keyword the receiver reports, or ``None``.

    Used to match ``:DIAG:TEST:RES?``'s answer back to a row. The comparison is case-insensitive
    because the receiver's own echo is not guaranteed to match the case sent.
    """
    if keyword is None or not keyword.strip():
        return None

    wanted = keyword.strip().upper()
    return next((s for s in KNOWN if s.keyword.upper() == wanted), None)
