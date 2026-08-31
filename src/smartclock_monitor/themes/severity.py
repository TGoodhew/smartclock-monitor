"""§9.4.3's severity vocabulary: colour **and** shape **and** text, always.

**Meaning is never carried by colour alone.** Every severity indication is a triple. The shape
channel is what makes the application usable under deuteranopia and protanopia, where success and
critical converge — a circle and a hexagon do not, and a word does not either.

Deliberately Qt-free, and in ``themes/`` rather than ``widgets/``. The vocabulary is design-system
data: which shape belongs to which severity is a §9 decision, not a drawing detail, and keeping it
importable without a display is what lets the §9.13 gate assert the rule without starting a Qt
application.
"""

from __future__ import annotations

from enum import Enum
from typing import Final


class Severity(Enum):
    """The five, and only five."""

    #: Locked, valid, test passed.
    SUCCESS = "success"

    #: Recovering, waiting, reduced accuracy, stale data.
    CAUTION = "caution"

    #: Holdover, hardware failure, disconnected with error.
    CRITICAL = "critical"

    #: Neutral advisory, rollover notice.
    INFO = "info"

    #: Unknown, power-up, not applicable.
    NEUTRAL = "neutral"


class Shape(Enum):
    """The five shapes, drawn as geometry rather than as glyphs from a font.

    §9.4.3 draws them as paths on purpose: a glyph depends on a font being present and on the
    renderer picking the right face, and under high contrast a path resolves to an outline while a
    glyph may not resolve at all.
    """

    CIRCLE = "circle"
    TRIANGLE = "triangle"
    HEXAGON = "hexagon"
    INFO = "info"
    RING = "ring"


#: The triple, minus the colour — which lives in the palette, because it changes with the theme and
#: the shape and the word do not.
#:
#: The default label is what a caller shows when it has nothing more specific. It is never omitted:
#: the text channel is as required as the shape one.
SEVERITY_SHAPES: Final[dict[Severity, tuple[Shape, str]]] = {
    Severity.SUCCESS: (Shape.CIRCLE, "OK"),
    Severity.CAUTION: (Shape.TRIANGLE, "Caution"),
    Severity.CRITICAL: (Shape.HEXAGON, "Critical"),
    Severity.INFO: (Shape.INFO, "Info"),
    Severity.NEUTRAL: (Shape.RING, "Unknown"),
}

#: The box every shape is drawn on, per §9.4.3.
SHAPE_BOX: Final = 12


def colour_for(severity: Severity, palette: object) -> str:
    """The palette colour for a severity.

    Takes the palette as an object and reads the attribute named by the severity, so that adding a
    severity means adding a token with the matching name rather than editing a mapping here — one
    fewer place for the two to disagree.
    """
    colour = getattr(palette, severity.value, None)
    if not isinstance(colour, str):  # pragma: no cover - a palette missing a severity is a bug
        raise AttributeError(f"The palette has no colour for severity {severity.value!r}.")
    return colour
