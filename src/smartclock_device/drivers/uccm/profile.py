"""Who made this UCCM, and which variant it is (D7).

**Vendor and variant are kept apart on purpose.** A UCCM is a form factor rather than a product:
Symmetricom and Trimble both make one, they answer `*IDN?` differently, and the `-P` variant is a
different module from the plain one. Folding the two into a single enum would make "a Trimble" and
"a UCCM-P" the same kind of fact, and the corpus already shows they are not — the bench module is
both.

Nobody here has a UCCM. Everything below is read out of
[`tests/fixtures/uccm/`](../../../../tests/fixtures/uccm), which is somebody else's receiver, and
D7's rule applies: an assertion that does not trace to a line in that directory is not made.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Final


class UccmVendor(enum.Enum):
    """Who built it."""

    #: Not established. The honest answer before an identity is read, and after one that says
    #: something nobody here has seen.
    UNKNOWN = "unknown"

    SYMMETRICOM = "Symmetricom"
    TRIMBLE = "Trimble"


class UccmVariant(enum.Enum):
    """Which module. `-P` is a different receiver, not a decoration on the same one."""

    UNKNOWN = "unknown"
    UCCM = "UCCM"
    UCCM_P = "UCCM-P"


@dataclass(frozen=True, slots=True)
class UccmProfile:
    """The pair, and how it was established."""

    vendor: UccmVendor = UccmVendor.UNKNOWN
    variant: UccmVariant = UccmVariant.UNKNOWN

    @property
    def name(self) -> str:
        """What to call it on a surface, given whichever halves are known."""
        if self.vendor is UccmVendor.UNKNOWN and self.variant is UccmVariant.UNKNOWN:
            return "UCCM"
        if self.vendor is UccmVendor.UNKNOWN:
            return self.variant.value
        if self.variant is UccmVariant.UNKNOWN:
            return f"{self.vendor.value} UCCM"
        return f"{self.vendor.value} {self.variant.value}"


#: The manufacturer tokens seen at the front of a UCCM's ``*IDN?``.
#:
#: Only `TRIMBLE` is in the corpus — `TRIMBLE,57964-80,40896646,V2.0.1.6-01`. `SYMMETRICOM` is here
#: because the SmartClock family already uses that token and a UCCM must not be mistaken for one;
#: the entry exists to be *distinguished from*, not because a Symmetricom UCCM has been seen.
VENDOR_TOKENS: Final[dict[str, UccmVendor]] = {
    "TRIMBLE": UccmVendor.TRIMBLE,
    "SYMMETRICOM": UccmVendor.SYMMETRICOM,
}

#: The prompt each variant prints, which is also how the variant is established.
#:
#: **Taken from the prompt rather than from `*IDN?`**, and that is the sibling's finding rather
#: than a preference: `08c62c1` — *"Take the UCCM variant from the prompt, because asking does not
#: work"*. The identity gives the part number `57964-80`, which says nothing about the variant;
#: the prompt says `UCCM-P >` outright, 162 times across the corpus.
PROMPTS: Final[dict[str, UccmVariant]] = {
    "UCCM-P": UccmVariant.UCCM_P,
    "UCCM": UccmVariant.UCCM,
}
