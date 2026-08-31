"""The design token table (§9.4), as data, in one file.

**Nothing outside this module names a colour.** §9.13's first prohibition, and the one that is
hardest to retrofit, so it is enforced by a gate (``tests/test_no_hex_literals.py``) rather than by
review. Custom widgets take a :class:`Palette` and repaint on theme change; QSS is generated from
these tokens at startup and re-applied when the theme changes, because QSS has no theme
dictionaries and no live resource resolution.

Three themes, per `docs/platform-decisions.md` D3 (issue #3). Light and Dark port directly from
§9.4.1. **High contrast does not.** On Windows those tokens resolve to the user's own
``SystemColor*`` choices; Linux offers no equivalent contract, so this ships a hand-authored set —
which asserts *our* contrast rather than honouring theirs. That is a weaker promise and it is
recorded as one. It was taken provisionally so Phase 5 could start; reversing to Light and Dark
alone is deleting one column here.

Values are the specification's own where §9.4 gives a literal. Where §9.4 maps a token to a stock
Fluent brush, the resolved Fluent value is written out, because there is no Fluent to inherit from
here — and §9.4.1's rationale for mapping (inheriting future refinements for free) does not survive
the platform move, while its rationale for the custom names (one place for a later change) does.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class Theme(Enum):
    """The three token sets."""

    LIGHT = "light"
    DARK = "dark"
    #: Hand-authored, and a weaker promise than Windows'. See the module docstring and issue #3.
    HIGH_CONTRAST = "high-contrast"


@dataclass(frozen=True, slots=True)
class Palette:
    """Every colour the application may draw with, resolved for one theme.

    Handed to custom widgets directly: they do not take their colours from QSS at all, because QSS
    cannot re-resolve on a theme change and a widget that painted from a stylesheet would keep the
    old theme's colours until it was recreated.
    """

    #: Solid backdrop. §9.2's Mica has no Linux equivalent, so the fallback is the only path — a
    #: case the design already handled correctly.
    page_background: str

    #: L1 page region.
    layer_fill: str

    #: L2 card.
    card_fill: str

    #: L2 card, recessed row.
    card_fill_secondary: str

    #: L3 transient surface.
    overlay_fill: str

    #: Card hairline.
    stroke_subtle: str

    #: Input borders and dividers.
    stroke_default: str

    #: Readouts and headings.
    text_primary: str

    #: Labels, units, captions.
    text_secondary: str

    #: Footers, timestamps, staleness.
    text_tertiary: str

    #: Disabled text.
    text_disabled: str

    #: The brand accent.
    accent: str

    #: Text drawn on an accent fill.
    accent_foreground: str

    # -- §9.4.3 severity. Never the only channel: colour + shape + text, always. ----------------

    #: Locked, valid, test passed.
    success: str

    #: Recovering, waiting, reduced accuracy, stale data.
    caution: str

    #: Holdover, hardware failure, disconnected with error.
    critical: str

    #: Neutral advisory, rollover notice.
    info: str

    #: Unknown, power-up, not applicable.
    neutral: str

    #: The §9.4.4 categorical ramp, eight series, for satellite traces.
    series: tuple[str, ...]

    #: §9.4.4's sequential ramp, seven steps, low to high. Signal strength, and nothing else —
    #: it encodes a magnitude, so it may not be used for a categorical distinction.
    sequential: tuple[str, ...]

    #: §9.4.4's diverging ramp, five stops, negative-strong → zero → positive-strong.
    #:
    #: **Only for an axis that contains zero**, which today means the 1 PPS chart alone. The
    #: middle stop maps to exactly 0, never to the data midpoint: a colour break that drifted
    #: with the window would mean "the receiver is on time" on one chart and "near where it has
    #: lately been" on another.
    diverging: tuple[str, ...]

    #: Which theme this is, for anything that must ask.
    theme: Theme


#: §9.4.4's categorical ramp, re-derived to fix four pairs that collapsed under simulated
#: deuteranopia and protanopia. ``build/palette/validate.py`` checks the colour maths against the
#: published figures, and is the reason these eight values are trustworthy rather than plausible.
_SERIES_LIGHT: Final[tuple[str, ...]] = (
    "#BD5572",  # rose
    "#B4684E",  # terracotta
    "#766110",  # olive
    "#455530",  # moss
    "#109180",  # teal
    "#45849F",  # steel
    "#085AA6",  # blue
    "#4A4A4A",  # graphite
)

_SERIES_DARK: Final[tuple[str, ...]] = (
    "#DD7F97",
    "#E97E59",
    "#EAC96A",
    "#B5C79C",
    "#07AE9A",
    "#7CB9D6",
    "#719BEA",
    "#C4C4C4",
)

#: §9.4.4's sequential ramp, verbatim, ordered for a **light** surface: low strength pale, high
#: strength dark teal.
#:
#: Its adjacent steps measure low under simulated protanopia (4.4 ΔE₀₀) and §9.4.4 says that is
#: correct rather than a defect — neighbouring steps of a ramp are meant to be similar, and the
#: simulated ramp stays monotonic.
#:
#: **§9.4.4 gives one ramp and no second column, and that is a defect in Dark** (issue filed).
#: A sequential ramp is read by lightness, so which end recedes depends on the surface it is drawn
#: on. Used verbatim in Dark, the *strongest* signal draws #08474D on the #2B2B2B card — 1.13:1,
#: below anything §9.4.5 permits and invisible in practice — while the *weakest* draws the
#: brightest mark on the plot. The encoding is exactly inverted, on the theme that ships by default.
#:
#: This port therefore orders the same seven values per surface rather than deriving a second ramp:
#: no new colour is introduced, the hue and the step spacing are the specification's, and the
#: property §9.4.4 actually asks for — prominence rising with the value — holds in both themes.
_SEQUENTIAL: Final[tuple[str, ...]] = (
    "#DFF1F3",
    "#A8DDE3",
    "#6FC5CE",
    "#3FB8C4",
    "#189AA6",
    "#0B6C74",
    "#08474D",
)

#: The same seven values for a dark surface. See the note above: reversed, not re-derived.
_SEQUENTIAL_DARK: Final[tuple[str, ...]] = tuple(reversed(_SEQUENTIAL))

#: §9.4.4's diverging ramp, verbatim, ordered negative-strong → zero → positive-strong. One ramp
#: for Light and Dark, for the same reason as the sequential one.
_DIVERGING: Final[tuple[str, ...]] = (
    "#08474D",
    "#3FB8C4",
    "#DDE4E5",
    "#F0A882",
    "#B23A00",
)

LIGHT: Final = Palette(
    page_background="#F3F3F3",
    layer_fill="#FFFFFF",
    card_fill="#FFFFFF",
    card_fill_secondary="#F6F6F6",
    overlay_fill="#FFFFFF",
    stroke_subtle="#E5E5E5",
    stroke_default="#D1D1D1",
    text_primary="#1B1B1B",
    text_secondary="#5D5D5D",
    # Owned rather than inherited: stock tertiary is 45% black in Light and measures 3.28:1 on the
    # layer fill, under §9.4.5's floor. 54.9% black is the value §9.4.1 settled on.
    #
    # **Written as the opaque composite rather than as §9.4.1's literal**, and the difference is
    # not cosmetic. There the token is #8C000000 — 54.9% black with an alpha channel — which
    # resolves differently over each surface it is drawn on. These tokens are opaque, so the value
    # has to be the one that holds on the *tightest* surface: 54.9% black over the recessed row is
    # #6F6F6F, which measures 4.65:1 there and 5.02:1 on a card. Compositing over white instead
    # gives #737373, which is what this was first written as and measures 4.39:1 on the recessed
    # row — under the floor, on the one surface nobody checks.
    text_tertiary="#6F6F6F",
    text_disabled="#9D9D9D",
    accent="#0F6CBD",
    accent_foreground="#FFFFFF",
    success="#0F7B3C",
    caution="#8A5300",
    critical="#B22B2B",
    info="#0F6CBD",
    neutral="#616161",
    series=_SERIES_LIGHT,
    sequential=_SEQUENTIAL,
    diverging=_DIVERGING,
    theme=Theme.LIGHT,
)

DARK: Final = Palette(
    page_background="#202020",
    layer_fill="#272727",
    card_fill="#2B2B2B",
    card_fill_secondary="#323232",
    overlay_fill="#2C2C2C",
    # Lighter than the fill, and that is correct rather than a bug to be "fixed" by inverting it:
    # §9.4.1 says so explicitly, because in dark theme a stroke reads by being lighter.
    stroke_subtle="#3D3D3D",
    stroke_default="#4A4A4A",
    text_primary="#FFFFFF",
    text_secondary="#C7C7C7",
    # 4.73:1 on the recessed row, the tightest of the three surfaces it is drawn on.
    # #8F8F8F was the first choice and measured 4.38:1 on a card — under §9.4.5's floor, and the
    # same defect §9.4.1 records for stock tertiary in Light. The gate caught it.
    text_tertiary="#9D9D9D",
    text_disabled="#6E6E6E",
    accent="#4CC2FF",
    accent_foreground="#000000",
    success="#4CC38A",
    caution="#F2B155",
    critical="#FF6B6B",
    info="#4CC2FF",
    neutral="#9A9A9A",
    series=_SERIES_DARK,
    sequential=_SEQUENTIAL_DARK,
    diverging=_DIVERGING,
    theme=Theme.DARK,
)

#: Hand-authored, and a **weaker promise** than the Windows original (issue #3).
#:
#: On Windows these resolve to the user's own system colours. Here they are ours. The values are
#: chosen to be unambiguous rather than tasteful: pure black and white surfaces, a single yellow
#: accent, and severity colours that stay distinguishable at maximum contrast.
#:
#: The series ramp does **not** flatten to the text colour, which is what the Windows high-contrast
#: dictionary does. That flattening exists there because the system colours are outside the app's
#: control and a chart line could otherwise resolve to the page background — the defect that gate
#: was written for. Here the values are ours, so the ramp can stay distinguishable, and each entry
#: is checked against the background rather than assumed.
HIGH_CONTRAST: Final = Palette(
    page_background="#000000",
    layer_fill="#000000",
    card_fill="#000000",
    card_fill_secondary="#1A1A1A",
    overlay_fill="#000000",
    stroke_subtle="#FFFFFF",
    stroke_default="#FFFFFF",
    text_primary="#FFFFFF",
    text_secondary="#FFFFFF",
    text_tertiary="#D6D6D6",
    text_disabled="#A6A6A6",
    accent="#FFFF00",
    accent_foreground="#000000",
    success="#3FF23F",
    caution="#FFD700",
    critical="#FF5C5C",
    info="#66D9FF",
    neutral="#D6D6D6",
    series=(
        "#FFFFFF",
        "#FFFF00",
        "#00FFFF",
        "#FF80FF",
        "#80FF80",
        "#FFB060",
        "#8CB4FF",
        "#D6D6D6",
    ),
    # Neither ramp flattens, for the reason given above: §9.4.4 flattens the sequential ramp to
    # SystemColorWindowTextColor because on Windows the steps are the user's colours and steps 1
    # and 2 resolved to the page background (#218). Here they are ours, so the ramp can stay
    # readable — and a flattened sequential ramp would draw every satellite the same colour, which
    # is what the strength encoding is for.
    #
    # Ordered by lightness rather than by hue. Under high contrast lightness is the channel that
    # survives, and every step clears §9.4.5's 3:1 against the black surfaces.
    sequential=(
        "#8C8C8C",
        "#A0A0A0",
        "#B4B4B4",
        "#C8C8C8",
        "#DCDCDC",
        "#EEEEEE",
        "#FFFFFF",
    ),
    # Sign is carried by hue and strength by saturation, because on black the normal ramp's
    # device — dark for strongly negative — would put the strongest readings in the background.
    diverging=(
        "#00E5E5",
        "#7FD4FF",
        "#FFFFFF",
        "#FFC08A",
        "#FF8A3D",
    ),
    theme=Theme.HIGH_CONTRAST,
)

_BY_THEME: Final[dict[Theme, Palette]] = {
    Theme.LIGHT: LIGHT,
    Theme.DARK: DARK,
    Theme.HIGH_CONTRAST: HIGH_CONTRAST,
}


def palette_for(theme: Theme) -> Palette:
    """The token set for a theme."""
    return _BY_THEME[theme]


#: Every theme, for the swatch page and for the parity gate.
ALL_THEMES: Final[tuple[Theme, ...]] = tuple(_BY_THEME)
