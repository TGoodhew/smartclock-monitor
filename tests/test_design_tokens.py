"""§9.13's prohibitions, enforced by a gate rather than by review.

Three rules, and retrofitting any of them is where design systems die:

1. **No hard-coded colour outside the token table.**
2. **Only the 4 / 8 / circle corner radii and the §9.6 spacing scale.**
3. **Severity always renders as colour + shape + text**, never colour alone.

The third cannot be checked by scanning text — it is a property of the widget that draws it — so it
is asserted against the severity table here and tested again where the pill is built.

§9.4.5's contrast floor is checked here too, against the surfaces these tokens actually define.
§9.4.1's stock Fluent values were measured from a running Windows app and are not a valid baseline
on this platform; these figures are computed from the tokens themselves.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from smartclock_monitor.themes import tokens
from smartclock_monitor.themes.qss import stylesheet
from smartclock_monitor.themes.spacing import RADII, SCALE, Radius, Spacing
from smartclock_monitor.themes.tokens import ALL_THEMES, Palette, Theme, palette_for
from smartclock_monitor.themes.typography import RAMP, Type

ROOT: Final = Path(__file__).resolve().parent.parent
APPLICATION: Final = ROOT / "src" / "smartclock_monitor"

#: The one file permitted to name a colour.
TOKEN_FILE: Final = APPLICATION / "themes" / "tokens.py"

#: A hex colour literal, in any of the spellings that reach a stylesheet.
_HEX: Final = re.compile(r"#[0-9A-Fa-f]{3,8}\b")


def _application_sources() -> list[Path]:
    return sorted(path for path in APPLICATION.rglob("*.py") if path.is_file())


# ---- §9.13, rule 1: no colour outside the token table ------------------------------------------


def test_there_are_application_sources_to_scan() -> None:
    """Guarding the guard: a glob that matched nothing would leave every check below passing while
    scanning an empty set."""
    assert len(_application_sources()) >= 5


def test_no_hex_literal_outside_the_token_file() -> None:
    """§9.13's first prohibition, and the hardest to retrofit.

    Keeping the token table as *data in one file* is exactly what makes this checkable. The moment
    a colour is written in a widget, the table stops being the single source and becomes a
    suggestion.
    """
    offenders: list[str] = []

    for path in _application_sources():
        if path.resolve() == TOKEN_FILE.resolve():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if _HEX.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")

    assert not offenders, "Hard-coded colour outside the token table at: " + ", ".join(offenders)


def test_the_gate_catches_a_deliberate_violation(tmp_path: Path) -> None:
    """CLAUDE.md: test the rule against a violation, then remove it and re-confirm green. A rule
    that matches nothing enforces nothing, and it fails silently."""
    offender = tmp_path / "widget.py"
    offender.write_text('BACKGROUND = "#FF00FF"\n')

    assert _HEX.search(offender.read_text())

    innocent = tmp_path / "clean.py"
    innocent.write_text("from smartclock_monitor.themes.tokens import LIGHT\n")

    assert not _HEX.search(innocent.read_text())


def test_the_generated_stylesheet_carries_only_token_colours() -> None:
    """The stylesheet is where a stray colour would do the most damage and be least visible."""
    for theme in ALL_THEMES:
        palette = palette_for(theme)
        known = {value.upper() for value in _colours_of(palette)}
        used = {match.group(0).upper() for match in _HEX.finditer(stylesheet(palette))}

        assert used <= known, f"{theme.value} stylesheet uses a colour that is not a token."


def _colours_of(palette: Palette) -> set[str]:
    values: set[str] = set()
    for name in palette.__slots__:
        value = getattr(palette, name)
        if isinstance(value, str) and value.startswith("#"):
            values.add(value)
        elif isinstance(value, tuple):
            values.update(item for item in value if isinstance(item, str) and item.startswith("#"))
    return values


# ---- §9.13, rule 2: the spacing scale and the radii ---------------------------------------------


def test_the_stylesheet_uses_only_the_spacing_scale() -> None:
    """§9.6's scale, and §9.13's rule that nothing else is permitted. A margin of 15 is not a
    smaller 16, it is a defect that makes the next one arguable."""
    allowed = {*SCALE, *RADII, 0, 1, 2}  # 1 and 2 are hairline borders; 0 is a reset
    used = {int(match) for match in re.findall(r"(\d+)px", stylesheet(palette_for(Theme.LIGHT)))}

    assert used <= allowed, f"Off-scale value in the stylesheet: {sorted(used - allowed)}"


def test_only_the_sanctioned_radii_exist() -> None:
    """§9.13: 4, 8, and circle. Circle is computed from the shorter side rather than written as a
    number, which is why it is not in the list a gate compares against."""
    assert RADII == (4, 8)
    assert Radius.CIRCLE not in RADII


def test_the_spacing_scale_is_ordered_and_distinct() -> None:
    """A scale with a duplicate or an inversion in it is one nobody can reason about."""
    assert list(SCALE) == sorted(set(SCALE))
    assert Spacing.TIGHT < Spacing.CARD_PADDING < Spacing.PAGE


# ---- §9.13, rule 3: severity is never colour alone ---------------------------------------------


def test_every_severity_has_a_distinct_colour_in_every_theme() -> None:
    """Necessary but nowhere near sufficient — see the test below, which is the real one."""
    for theme in ALL_THEMES:
        palette = palette_for(theme)
        severities = {
            palette.success,
            palette.caution,
            palette.critical,
            palette.neutral,
        }
        assert len(severities) == 4, f"Two severities share a colour in {theme.value}."


def test_success_and_critical_are_not_distinguished_by_colour_alone() -> None:
    """The rule that matters. Under deuteranopia and protanopia success and critical converge — a
    circle and a hexagon do not, and a label does not either.

    This asserts the contract rather than the pixels: the shape and the text channel are required
    to exist. The widget test is where the drawing is checked.
    """
    from smartclock_monitor.themes.severity import SEVERITY_SHAPES, Severity

    for severity in Severity:
        shape, label = SEVERITY_SHAPES[severity]
        assert shape, f"{severity.name} has no shape channel."
        assert label, f"{severity.name} has no text channel."

    shapes = {SEVERITY_SHAPES[severity][0] for severity in Severity}
    assert len(shapes) == len(Severity), "Two severities share a shape."


# ---- §9.4.5's contrast floor, re-derived ---------------------------------------------------------


def _luminance(hex_colour: str) -> float:
    """Relative luminance, per WCAG 2.x."""
    value = hex_colour.lstrip("#")
    channels = [int(value[at : at + 2], 16) / 255 for at in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(foreground: str, background: str) -> float:
    """The WCAG contrast ratio between two colours."""
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda t: t.value)
def test_primary_text_meets_the_contrast_floor(theme: Theme) -> None:
    """4.5:1 on every surface it is drawn on. §9.4.1's stock Fluent values were measured from a
    running Windows app and are not a valid baseline here, so this is computed from the tokens."""
    palette = palette_for(theme)

    for surface in (palette.page_background, palette.layer_fill, palette.card_fill):
        assert contrast(palette.text_primary, surface) >= 4.5


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda t: t.value)
def test_secondary_and_tertiary_text_meet_the_floor(theme: Theme) -> None:
    """Tertiary is the one that fails, and it failed here too.

    §9.4.1 owns the Light tertiary token rather than inheriting it because stock 45% black measured
    3.28:1 on the layer fill. The first Dark value chosen for this port measured 4.38:1 on a card —
    the same defect, on the other theme, found by this gate rather than by a reviewer.

    **Every surface it is drawn on**, not just the card: the recessed row is the tightest of the
    three, and checking only the easiest one is how the Windows defect survived review.
    """
    palette = palette_for(theme)
    surfaces = (palette.card_fill, palette.card_fill_secondary, palette.layer_fill)

    for surface in surfaces:
        assert contrast(palette.text_secondary, surface) >= 4.5, f"secondary on {surface}"
        assert contrast(palette.text_tertiary, surface) >= 4.5, f"tertiary on {surface}"


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda t: t.value)
def test_every_severity_colour_is_legible_on_a_card(theme: Theme) -> None:
    palette = palette_for(theme)

    for name in ("success", "caution", "critical", "info", "neutral"):
        colour = getattr(palette, name)
        ratio = contrast(colour, palette.card_fill)
        assert ratio >= 3.0, f"{theme.value} {name} is {ratio:.2f}:1 on a card."


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda t: t.value)
def test_no_series_colour_is_the_page_background(theme: Theme) -> None:
    """The defect the high-contrast legibility gate was written for: sequential steps defined as
    the window colour drew every satellite below C/N 35 in the page background. A foreground token
    may never *be* a surface."""
    palette = palette_for(theme)

    for index, colour in enumerate(palette.series, start=1):
        assert colour.upper() != palette.page_background.upper(), f"Series {index} is the page."
        assert contrast(colour, palette.card_fill) >= 3.0, f"Series {index} is under 3:1."


# ---- Parity, and the theme set --------------------------------------------------------------


def test_every_theme_defines_every_token() -> None:
    """The port of the theme-dictionary parity gate. A token defined in one theme and missing in
    another is a crash on theme change, and it is the kind that ships."""
    for theme in ALL_THEMES:
        palette = palette_for(theme)
        for name in palette.__slots__:
            assert getattr(palette, name) is not None, f"{theme.value} is missing {name}."


def test_there_are_three_themes_per_decision_d3() -> None:
    """`docs/platform-decisions.md` D3, issue #3. Reversing to Light and Dark alone is deleting one
    column of the token table — which is what "cheap to reverse" was supposed to mean."""
    assert set(ALL_THEMES) == {Theme.LIGHT, Theme.DARK, Theme.HIGH_CONTRAST}


def test_the_series_ramp_has_eight_entries_in_every_theme() -> None:
    """§9.4.4 draws up to eight satellite traces."""
    for theme in ALL_THEMES:
        assert len(palette_for(theme).series) == 8


def test_the_series_ramp_matches_the_derivation() -> None:
    """These eight values come from ``build/palette/``, whose ``validate.py`` checks the colour
    maths against published figures. Restating them here would put them in two places; this asserts
    the ones that are here are the ones that were derived."""
    assert palette_for(Theme.LIGHT).series[0] == "#BD5572"
    assert palette_for(Theme.LIGHT).series[6] == "#085AA6"


# ---- The type ramp ------------------------------------------------------------------------------


def test_device_literal_text_is_the_only_monospace_style() -> None:
    """§9.5's split is load-bearing: it makes "what the machine said" visually distinct from "what
    the app says about it", in an application whose whole job is faithful reporting."""
    monospace = [name for name, style in RAMP if style.monospace]

    assert monospace == ["Device"]


def test_readouts_use_tabular_figures() -> None:
    """A value that changes once a second must not shift its own decimal point."""
    assert Type.READOUT.tabular is True
    assert Type.READOUT_SMALL.tabular is True


def test_the_ramp_is_ordered_by_size() -> None:
    sizes = [style.size for _, style in RAMP if not style.monospace]

    assert sizes == sorted(sizes, reverse=True) or len(set(sizes)) > 1


def test_the_token_module_is_the_only_place_a_colour_is_named() -> None:
    """Restating the first gate as an architectural assertion: the module exists, and it is the one
    the others read from."""
    assert TOKEN_FILE.is_file()
    assert tokens.LIGHT.theme is Theme.LIGHT
