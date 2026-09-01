"""The §9.5 type ramp, and the Segoe/Cascadia split that survives the platform move.

**The split is load-bearing, not decorative.** Every string the receiver actually emits — SCPI
mnemonics, raw register values, log entries, the transcript, the ``*IDN?`` string — is set in a
monospace face, and everything the *application* says is set in the UI face. In an application
whose whole job is faithful reporting, that is what makes "what the machine said" visually distinct
from "what the app says about it".

Per `docs/platform-decisions.md` D4 (issue #4, settled 1 Sep 2026): the device-literal half ports
unchanged, because Cascadia Mono is SIL OFL 1.1 and redistributable. Segoe UI Variable does not —
it is absent from Linux and is not redistributable — so the prose half is **Noto Sans**, named.

**Named, rather than deferred to the desktop.** The first answer here was an empty first entry
meaning "whatever Qt resolves as the system UI font", on the reasoning that this is what every
other application does. That reasoning is sound for an application whose layout has slack, and this
one does not have much: a face is a set of glyph widths, and deferring the face defers the widths.
It cost a CI failure — a page measured to fit here overflowed on a runner that resolved a wider
face at the same point size — and it would have gone on costing them, because no local run can see
another machine's fontconfig.

Noto Sans rather than DejaVu Sans, which was the other candidate present nearly everywhere: DejaVu
is materially wider at the same point size, and this application's widest page is already the thing
setting the Details window's minimum. Noto is also SIL OFL 1.1, so bundling it later needs no new
licence conversation — the same door Cascadia Mono left open.

**§9.4.5's contrast figures do not depend on the face.** They were re-derived for this port against
its own palette, and `test_design_tokens.py` asserts 4.5:1 for every text token on every surface it
is drawn on — the *stricter* floor, taken deliberately so that none of it rests on WCAG's
large-text exemption, which is the only part a change of face could have invalidated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: The UI face, with fallbacks. **Named first, not the system default** — see the module docstring
#: for what deferring it cost. The fallbacks are ordered so that a machine without Noto Sans lands
#: on something close in width before it lands on something merely present.
UI_FAMILY: Final[tuple[str, ...]] = ("Noto Sans", "Cantarell", "DejaVu Sans", "sans-serif")

#: The device-literal face. Cascadia Mono ports as-is; the rest are fallbacks for a machine that
#: does not have it yet, since bundling is Phase 8's packaging work.
MONO_FAMILY: Final[tuple[str, ...]] = (
    "Cascadia Mono",
    "Cascadia Code",
    "DejaVu Sans Mono",
    "Consolas",
    "monospace",
)


@dataclass(frozen=True, slots=True)
class TypeStyle:
    """One step of the §9.5.2 ramp."""

    #: Point size.
    size: int

    #: 400 normal, 600 semibold.
    weight: int

    #: Whether this is device-literal text and therefore monospace.
    monospace: bool = False

    #: Whether figures should be tabular, so a changing readout does not jitter horizontally.
    tabular: bool = False

    @property
    def family(self) -> tuple[str, ...]:
        return MONO_FAMILY if self.monospace else UI_FAMILY


class Type:
    """The ramp. Nothing sets a font size that is not one of these."""

    #: Page and window titles.
    TITLE = TypeStyle(size=20, weight=600)

    #: Card headings.
    SUBTITLE = TypeStyle(size=14, weight=600)

    #: Ordinary prose and control labels.
    BODY = TypeStyle(size=11, weight=400)

    #: Field labels, units, captions.
    CAPTION = TypeStyle(size=10, weight=400)

    #: The big numeric readouts. Tabular figures, because a value that changes once a second must
    #: not shift its own decimal point.
    READOUT = TypeStyle(size=28, weight=600, tabular=True)

    #: A smaller readout, for a card that carries several.
    READOUT_SMALL = TypeStyle(size=18, weight=600, tabular=True)

    #: **Device-literal text.** Anything the receiver itself emitted.
    DEVICE = TypeStyle(size=11, weight=400, monospace=True)


#: Every style, for the swatch page and the ramp gate.
RAMP: Final[tuple[tuple[str, TypeStyle], ...]] = (
    ("Title", Type.TITLE),
    ("Subtitle", Type.SUBTITLE),
    ("Body", Type.BODY),
    ("Caption", Type.CAPTION),
    ("Readout", Type.READOUT),
    ("Readout small", Type.READOUT_SMALL),
    ("Device", Type.DEVICE),
)
