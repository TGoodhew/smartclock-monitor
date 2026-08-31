"""The §9.5 type ramp, and the Segoe/Cascadia split that survives the platform move.

**The split is load-bearing, not decorative.** Every string the receiver actually emits — SCPI
mnemonics, raw register values, log entries, the transcript, the ``*IDN?`` string — is set in a
monospace face, and everything the *application* says is set in the UI face. In an application
whose whole job is faithful reporting, that is what makes "what the machine said" visually distinct
from "what the app says about it".

Per `docs/platform-decisions.md` D4 (issue #4): the device-literal half ports unchanged, because
Cascadia Mono is SIL OFL 1.1 and redistributable. The prose half does not — Segoe UI Variable is
not present on Linux and is not redistributable — so the system UI font is used, which is what
every other application on the desktop uses and the same instinct §9.5.1 followed in picking the
Windows system face.

**§9.4.5's contrast figures and §9.5.2's ramp were measured against Segoe UI Variable.** Changing
the face silently invalidates them. Re-deriving both is issue #4's outstanding work and is required
before Phase 5 can be called finished.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

#: The UI face, with fallbacks. Empty first entry means "whatever Qt resolves as the system UI
#: font", which is the deliberate choice — see the module docstring.
UI_FAMILY: Final[tuple[str, ...]] = ("", "Cantarell", "Noto Sans", "DejaVu Sans", "sans-serif")

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
