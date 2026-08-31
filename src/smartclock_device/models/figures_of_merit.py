"""What the receiver's two figures of merit mean.

From the *58503A/59551A Operating and Programming Guide*, Command Reference 5-23 and 5-24
(``:SYNChronization:FFOMerit?`` and ``:SYNChronization:TFOMerit?``). Recorded here rather than
looked up again: the guide is not redistributable and the tables are the whole reason a bare
"TFOM 3" is worth showing at all — the number alone tells a user nothing, and the range behind it
is the thing they came to find out.

**Lower is better for both.** That is the opposite of most instrument scales, which is why §9.4.3
forbids conveying either by colour alone.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

#: The 1 PPS output's time error for a given TFOM.
#:
#: Values 0, 1 and 2 are documented but "not presently used in the 58503A and 59551A products",
#: which "display TFOM values ranging from 9 to 3". They are carried anyway: a receiver reporting
#: one is not a parse failure, and the Z3805A's firmware is a sibling rather than the exact
#: product the guide describes.
_TIME_ERROR: Final[MappingProxyType[int, str]] = MappingProxyType(
    {
        0: "less than 1 ns",
        1: "1 \N{EN DASH} 10 ns",
        2: "10 \N{EN DASH} 100 ns",
        3: "100 ns \N{EN DASH} 1 \N{MICRO SIGN}s",
        4: "1 \N{EN DASH} 10 \N{MICRO SIGN}s",
        5: "10 \N{EN DASH} 100 \N{MICRO SIGN}s",
        6: "100 \N{MICRO SIGN}s \N{EN DASH} 1 ms",
        7: "1 \N{EN DASH} 10 ms",
        8: "10 \N{EN DASH} 100 ms",
        9: "more than 100 ms",
    }
)

#: What a given FFOM says about the 10 MHz output.
#:
#: FFOM 2 and 3 are both "PLL unlocked" and are not interchangeable: 2 is holdover, where the
#: output starts within specification and drifts out, and 3 is unlocked while *not* in holdover,
#: which the guide answers with "do not use the output".
_PLL_STATE: Final[MappingProxyType[int, str]] = MappingProxyType(
    {
        0: "PLL stabilized",
        1: "PLL stabilizing",
        2: "PLL unlocked, in holdover",
        3: "PLL unlocked \N{EM DASH} do not use the output",
    }
)

#: The longer form of :data:`_PLL_STATE`, for a tooltip.
_PLL_DETAIL: Final[MappingProxyType[int, str]] = MappingProxyType(
    {
        0: "The 10 MHz output is within specification.",
        1: (
            "The phase-locked loop is still settling. The 10 MHz output is not yet within "
            "specification."
        ),
        2: (
            "The phase-locked loop is unlocked and the receiver is in holdover. The 10 MHz "
            "output starts within specification and drifts out as holdover continues."
        ),
        3: (
            "The phase-locked loop is unlocked and the receiver is not in holdover. Do not use "
            "the 10 MHz output."
        ),
    }
)


def time_error(tfom: int | None) -> str | None:
    """The 1 PPS output's time error for a given TFOM, or ``None`` if out of range."""
    return None if tfom is None else _TIME_ERROR.get(tfom)


def pll_state(ffom: int | None) -> str | None:
    """What a given FFOM says about the 10 MHz output, or ``None`` if out of range."""
    return None if ffom is None else _PLL_STATE.get(ffom)


def pll_detail(ffom: int | None) -> str | None:
    """The longer form of :func:`pll_state`, for a tooltip."""
    return None if ffom is None else _PLL_DETAIL.get(ffom)
