"""The §9.6 spacing scale and the §9.13 corner radii, as data.

Two of §9.13's three prohibitions live here: **only the 4 / 8 / circle corner radii**, and **only
the §9.6 spacing scale**. Both are enforced by a gate rather than by review, because retrofitting
either is where design systems die.

Named rather than numbered at the call site: ``Spacing.CARD_PADDING`` says why the number is what
it is, where ``16`` says only what it is.
"""

from __future__ import annotations

from typing import Final


class Spacing:
    """The §9.6 scale. Every margin, padding and gap is one of these."""

    #: Hairline separation, between a glyph and its label.
    TIGHT: Final = 4

    #: Between related controls in a row.
    SMALL: Final = 8

    #: Between rows within a card.
    MEDIUM: Final = 12

    #: Card padding, and the gap between cards.
    CARD_PADDING: Final = 16

    #: Between sections of a page.
    LARGE: Final = 24

    #: Page margin.
    PAGE: Final = 32


class Radius:
    """§9.13: only these. A radius that is not on this list is a defect, not a preference."""

    #: Controls, inputs, small chips.
    CONTROL: Final = 4

    #: Cards and surfaces.
    CARD: Final = 8

    #: A circle. Rendered as half the shorter side rather than as a literal.
    CIRCLE: Final = -1


#: Every value the spacing gate accepts.
SCALE: Final[tuple[int, ...]] = (
    Spacing.TIGHT,
    Spacing.SMALL,
    Spacing.MEDIUM,
    Spacing.CARD_PADDING,
    Spacing.LARGE,
    Spacing.PAGE,
)

#: Every value the radius gate accepts.
RADII: Final[tuple[int, ...]] = (Radius.CONTROL, Radius.CARD)

#: §9.12's pointer-target floor, in logical pixels.
#:
#: **Declared, not inherited.** The gate that guards it exists because a stock style happening to
#: supply enough height is not the same as the application promising it — and the defect it was
#: written for was in a non-button widget, which is why the floor is a number here rather than a
#: property of one control.
MINIMUM_POINTER_TARGET: Final = 32
