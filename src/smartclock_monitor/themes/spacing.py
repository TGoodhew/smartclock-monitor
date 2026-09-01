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

#: §9.10.2's one recorded exception to the floor above, for sky-plot markers only.
#:
#: **A marker's position is the data.** It is the satellite's actual place in the sky and cannot be
#: moved to make room, so growing the target past a point stops helping and starts hurting: two
#: targets that overlap mean one marker silently takes the other's clicks, which is worse than a
#: small target because a missed click is obvious and a wrong selection is not.
#:
#: The number is not a preference. Of the 424 satellite pairs the ten captures place on a plot at
#: its own 240 px minimum, **thirteen are closer than 32 px and none is closer than 24** — the
#: tightest being PRN 17 and PRN 22 at 26.8 px. So 32 px targets overlap on real captured sky and
#: 24 px ones do not. §9.10.2 predicted exactly that and named the compliant path with it: the
#: keyboard model reaches every satellite regardless of size, and the tracked/not-tracked tables
#: carry the same data at ≥ 40 px with selection shared both ways.
SKY_PLOT_POINTER_TARGET: Final = 24

#: The floor for a table row that is itself a selection or interaction target.
#:
#: **40, and §9.10.2 argues for the stronger number deliberately.** A11Y-5's pointer floor is 32 and
#: its touch floor is 40; the specification takes 40 here because the tracked/not-tracked tables are
#: *the compliant alternate* to a control that can meet neither — the sky plot, whose markers cannot
#: be moved to make room. An argument that rests on an alternate should rest on the stronger figure
#: rather than on the weaker one it happens to need.
#:
#: §9.10.2 carries a warning about exactly this, because it already went wrong once: WinZ3805A's
#: dense list style set the row minimum to 0 to escape Qt's stock 40, the rows measured 26–28 px,
#: and the sky plot's exception was resting on an alternate no more compliant than the thing it was
#: excusing. **This port reproduced it at 30 px** — found while writing `divergences.md`, whose
#: draft claimed the 40 the specification requires.
#:
#: A floor, not a fixed height: rows still grow with scaled text (A11Y-6).
TABLE_ROW_TARGET: Final = 40

#: §9.12's touch floor, for the modes this application does not have (#186). Named because §10.5's
#: tables meet it deliberately: they are the compliant alternate to a control that can meet neither
#: floor, so that argument should rest on the stronger number rather than the one it needs.
MINIMUM_TOUCH_TARGET: Final = 40
