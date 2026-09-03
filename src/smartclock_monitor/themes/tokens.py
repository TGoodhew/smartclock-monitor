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
    """The two token sets.

    **There is no high-contrast theme, deliberately** — D3, settled 1 Sep 2026 (#3). Windows
    resolves those tokens to the user's *own* system colours, and no desktop this port targets
    offers an equivalent contract. A hand-authored third set would have asserted our contrast in
    place of theirs, which is a different and weaker service to someone who has configured a
    specific scheme for a specific impairment. Saying so plainly is the honest answer; shipping a
    lookalike and calling it high contrast is not. `docs/divergences.md` records it as the
    reduction against WinZ3805A that it is.
    """

    LIGHT = "light"
    DARK = "dark"


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
#: **§9.4.4 gives one ramp and no second column, and that is a defect in Dark** — issue #9 here and
#: TGoodhew/WinZ3805A#367, since the same values are resolved from one dictionary there.
#: A sequential ramp is read by lightness, so which end recedes depends on the surface it is drawn
#: on. Used verbatim in Dark, the *strongest* signal draws #08474D on the #2B2B2B card — 1.13:1,
#: below anything §9.4.5 permits and invisible in practice — while the *weakest* draws the
#: brightest mark on the plot. The encoding is exactly inverted, on the theme that ships by default.
_SEQUENTIAL: Final[tuple[str, ...]] = (
    "#DFF1F3",
    "#A8DDE3",
    "#6FC5CE",
    "#3FB8C4",
    "#189AA6",
    "#0B6C74",
    "#08474D",
)

#: A ramp **derived for the dark surface**, by `build/palette/sequential.py`. Figures published in
#: `docs/palette-figures.md`; `build/palette/validate.py` re-checks them.
#:
#: Reversing the seven Light values was the first fix and is not enough. It cures the inversion, but
#: the spec ramp is not perceptually uniform — adjacent steps run 5.1 to 17.1 ΔE₀₀, a 3.33-fold
#: spread — and reversing cannot change that ratio, since max/min does not care about order. What
#: it changes is **where the coarse steps land**: the dark, strong-signal end on Light, and the
#: weak end once reversed onto Dark. The ramp then spends its resolution where the data matters
#: least and leaves the strong end its finest steps. Telling 45 dB-Hz from 50 is the job, and that
#: is the comparison the reversal makes hardest.
#:
#: It also carries a collision the specification did not intend for this surface: spec step 4 is
#: `#3FB8C4`, which **is** Dark's info colour, 0.0 ΔE₀₀ apart. A mid-strength satellite drew
#: exactly the info indicator.
#:
#: Derived: hue held at the specification's 208.5°, chroma following the spec's own curve (it peaks
#: mid-ramp and desaturates toward white — a first run maximised chroma instead, met every number
#: and produced a neon cyan that was the wrong colour beside §9.4.4's teal), L* evenly spaced.
#:
#: | | reversed | derived |
#: |---|---|---|
#: | step evenness, ΔE₀₀ max/min | 3.33x | **1.20x** |
#: | coarsest step lands at | the weak end | evenly spread |
#: | nearest §9.4.3 colour | 0.00 ΔE₀₀ | **3.2 ΔE₀₀** |
#: | weakest step on the card | 1.36:1 | **2.36:1** |
#: | strongest step on the card | 12.15:1 | 10.68:1 |
#:
#: Monotone under simulated deuteranopia and protanopia both. §9.4.4 is explicit that a sequential
#: ramp's neighbours measuring low under dichromacy is correct rather than a defect — they encode a
#: magnitude and are read by lightness — so that is checked, not maximised.
_SEQUENTIAL_DARK: Final[tuple[str, ...]] = (
    "#216D74",
    "#2A828A",
    "#3398A1",
    "#48ADB7",
    "#70C1C9",
    "#9BD3D9",
    "#C5E6E9",
)

#: §9.4.4's diverging ramp, ordered negative-strong → zero → positive-strong, **derived per
#: surface** — `build/palette/diverging.py`, figures in `docs/palette-figures.md`.
#:
#: The specification gives one column, as it does for the sequential ramp, and one column cannot
#: serve both cards for the same reason (#19, and TGoodhew/WinZ3805A#371 where it was found). A
#: diverging ramp puts its neutral **near** the surface and its extremes **away** from it, so that
#: magnitude reads as prominence — and "away" means darker on a light card and lighter on a dark
#: one. Used verbatim the ordering inverts on Dark: the pale neutral `#DDE4E5` is the boldest mark
#: on the card at 10.99:1 while a large excursion fades to 1.36:1.
#:
#: **The Light column was the more urgent half, and it was not an ordering problem.** These are the
#: 1 PPS chart's per-column whiskers, drawn as a 1 px pen (`widgets/trend_chart.py`), so §9.4.5's
#: 3:1 floor for meaningful non-text applies to every one of them. Three of the five were under it
#: on the theme the ramp was drawn for, `#DDE4E5` worst at **1.24:1** — not a line anyone can
#: follow.
#:
#: | | spec, verbatim | derived |
#: |---|---|---|
#: | weakest stop, Light | 1.24:1 | **3.06:1** |
#: | weakest stop, Dark | 1.36:1 | **3.90:1** |
#: | stops under 3:1, both cards | 5 of 10 | **none** |
#: | prominence rises outward | Light only | **both cards** |
#:
#: Derived to **change as little as possible** rather than to optimise: the nearest legal ramp to
#: the five §9.4.4 already had. Minimising step evenness the way `sequential.py` does is the wrong
#: objective for a two-armed ramp, and `diverging.py`'s docstring says why. Arms stay 28.6 ΔE₀₀
#: (Light) and 20.3 (Dark) apart at matching magnitude under normal vision, deuteranopia and
#: protanopia, so the sign of an excursion survives dichromacy.
_DIVERGING_LIGHT: Final[tuple[str, ...]] = (
    "#1D5D64",
    "#2A7D85",
    "#8B9293",
    "#C24D19",
    "#93370F",
)

#: The same ramp derived for the Dark card. See `_DIVERGING_LIGHT` for why there are two.
_DIVERGING_DARK: Final[tuple[str, ...]] = (
    "#90DEE7",
    "#75B6BD",
    "#818788",
    "#EB976A",
    "#F3C9B4",
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
    diverging=_DIVERGING_LIGHT,
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
    diverging=_DIVERGING_DARK,
    theme=Theme.DARK,
)


_BY_THEME: Final[dict[Theme, Palette]] = {
    Theme.LIGHT: LIGHT,
    Theme.DARK: DARK,
}


def palette_for(theme: Theme) -> Palette:
    """The token set for a theme."""
    return _BY_THEME[theme]


#: Every theme, for the swatch page and for the parity gate.
ALL_THEMES: Final[tuple[Theme, ...]] = tuple(_BY_THEME)
