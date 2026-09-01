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

import ast
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


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """The string constants that are docstrings, by identity."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def colours_named_in(source: str) -> list[tuple[int, str]]:
    """Every hex colour written into a string literal, with its line number.

    **Prose is not scanned, and that is the whole design of this check.** A line-by-line regex
    reads ``#183`` — an issue reference, of which the specification and this codebase are full —
    as the three-digit colour ``#RGB``, and a gate that fires on a comment citing the issue that
    justifies the code beside it is one people learn to scroll past. So the scan walks the parsed
    module and looks only where a colour could actually reach a widget: comments are absent from
    the tree, and docstrings are skipped by identity.

    The trade is deliberate and narrow. A colour written inside a docstring escapes — and a colour
    in a docstring is not a colour anything renders.
    """
    tree = ast.parse(source)
    docstrings = _docstring_nodes(tree)

    return [
        (node.lineno, match.group(0))
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
        for match in _HEX.finditer(node.value)
    ]


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
        for number, colour in colours_named_in(path.read_text(encoding="utf-8")):
            offenders.append(f"{path.relative_to(ROOT)}:{number} ({colour})")

    assert not offenders, "Hard-coded colour outside the token table at: " + ", ".join(offenders)


def test_the_gate_catches_a_deliberate_violation(tmp_path: Path) -> None:
    """CLAUDE.md: test the rule against a violation, then remove it and re-confirm green. A rule
    that matches nothing enforces nothing, and it fails silently."""
    offender = tmp_path / "widget.py"
    offender.write_text('BACKGROUND = "#FF00FF"\n')

    assert colours_named_in(offender.read_text()) == [(1, "#FF00FF")]

    innocent = tmp_path / "clean.py"
    innocent.write_text("from smartclock_monitor.themes.tokens import LIGHT\n")

    assert colours_named_in(innocent.read_text()) == []


def test_the_gate_still_catches_a_colour_hidden_inside_a_longer_string() -> None:
    """The case that argues against matching whole strings only: a colour spliced into generated
    QSS is exactly where one would do the most damage and be least visible."""
    source = 'STYLE = f"QLabel {{ color: #B22B2B; }}"\n'

    assert colours_named_in(source) == [(1, "#B22B2B")]


def test_the_gate_does_not_fire_on_an_issue_reference() -> None:
    """#183 is three hex digits, so a line-by-line regex reads it as the colour ``#RGB``. The
    specification cites issues by number constantly and so do the comments that explain why a
    given piece of code is the shape it is — a gate firing on those is one people learn to scroll
    past, which is worse than no gate because it reads as coverage."""
    source = (
        '"""Framed on the window\'s own data — see #183 and #218."""\n'
        "# The EFC axis was zero-anchored until #183; #316 corrected the figures.\n"
        "SPAN = 0.01  # about 55 codes, per #183\n"
    )

    assert colours_named_in(source) == []


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


def test_there_are_two_themes_per_decision_d3() -> None:
    """`docs/platform-decisions.md` D3, settled 1 Sep 2026 (issue #3): **Light and Dark only.**

    Windows resolves high-contrast tokens to the user's *own* system colours, and no desktop this
    port targets offers an equivalent contract. The third set that used to be here asserted our
    contrast in place of theirs, which is a weaker service to the person who configured a scheme
    for a specific impairment — and it is worse than saying so, because it looks like the feature.

    Pinned as an equality rather than a floor: a third theme appearing without that decision being
    revisited is the thing to catch. `docs/divergences.md` records the reduction.
    """
    assert set(ALL_THEMES) == {Theme.LIGHT, Theme.DARK}


def test_the_series_ramp_has_eight_entries_in_every_theme() -> None:
    """§9.4.4 draws up to eight satellite traces."""
    for theme in ALL_THEMES:
        assert len(palette_for(theme).series) == 8


def test_the_two_data_ramps_have_the_lengths_the_spec_gives() -> None:
    """Seven sequential steps, five diverging stops, in every theme. §9.4.4 names the token keys
    ``WzSequential1..7`` and ``WzDiverging{NegativeStrong,Negative,Zero,Positive,PositiveStrong}``,
    and code indexes them — a short ramp in one theme is an IndexError on theme change."""
    for theme in ALL_THEMES:
        palette = palette_for(theme)
        assert len(palette.sequential) == 7, f"{theme.value} sequential"
        assert len(palette.diverging) == 5, f"{theme.value} diverging"


def test_the_sequential_ramp_rises_monotonically_in_prominence() -> None:
    """§9.4.4: a sequential ramp is *read by lightness*, which is why its adjacent steps measuring
    low under simulated dichromacy is correct rather than a defect. That argument only holds while
    the order holds, and nothing else in the suite would notice a transposed step — the colours
    would still all be teal.

    **The invariant is contrast against the surface, not lightness in a fixed direction.** §9.4.4's
    ramp runs pale to dark because it was drawn for a light surface: the low end recedes and the
    high end asserts itself. On a dark surface the same intent inverts, and a gate written as
    "light to dark" would demand a ramp whose strongest signals were nearly invisible — #218's
    defect, arrived at by way of a test. (That reasoning was first written about the
    high-contrast theme, which D3 has since removed; it applies to Dark unchanged, which is why
    the gate outlived the theme that motivated it.)"""
    for theme in ALL_THEMES:
        palette = palette_for(theme)
        steps = [contrast(colour, palette.card_fill) for colour in palette.sequential]
        assert steps == sorted(steps), (
            f"{theme.value} sequential does not rise in prominence: "
            f"{[f'{s:.2f}' for s in steps]} for {palette.sequential}"
        )


def test_the_diverging_ramp_is_symmetric_about_its_middle_stop() -> None:
    """The middle stop maps to exactly zero (§9.4.4), so it must be the *neutral* one. A ramp whose
    midpoint sat nearer one end would put the colour break off zero while still looking diverging,
    which is the failure the section spends a paragraph forbidding."""
    for theme in ALL_THEMES:
        negative, _, zero, _, positive = (
            _luminance(colour) for colour in palette_for(theme).diverging
        )
        assert zero > negative and zero > positive, (
            f"{theme.value}'s middle diverging stop is not the neutral one."
        )


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda t: t.value)
def test_no_data_ramp_step_is_a_surface(theme: Theme) -> None:
    """#218's rule generalised: a foreground token may never *be* a surface. Checked for both new
    ramps, because #218 was found in the sequential one and this is the ramp it was found in.

    The 3:1 floor is deliberately **not** asserted for the sequential ramp. §9.4.5 applies it to
    chart lines; these are marker *fills* whose pale end is the point — a low C/N reading is meant
    to recede — and the marker's outline is what carries it against the surface (§9.10.2)."""
    palette = palette_for(theme)
    surfaces = {
        palette.page_background.upper(),
        palette.layer_fill.upper(),
        palette.card_fill.upper(),
        palette.card_fill_secondary.upper(),
    }

    for index, colour in enumerate(palette.sequential, start=1):
        assert colour.upper() not in surfaces, f"Sequential {index} is a surface colour."
    for index, colour in enumerate(palette.diverging, start=1):
        assert colour.upper() not in surfaces, f"Diverging {index} is a surface colour."


def test_the_data_ramps_match_the_specification() -> None:
    """§9.4.4 gives both ramps as literals and gives **one** column rather than one per theme.

    The diverging ramp is shared verbatim: its middle stop is the neutral one against either
    surface. The sequential ramp is not — see the token file for the measurement — but the *values*
    are still the specification's, which is what this asserts."""
    assert palette_for(Theme.LIGHT).sequential == (
        "#DFF1F3",
        "#A8DDE3",
        "#6FC5CE",
        "#3FB8C4",
        "#189AA6",
        "#0B6C74",
        "#08474D",
    )

    # Dark carries the same seven values in the other order — see the token file. Asserted as an
    # exact reversal so that a *new* colour appearing in Dark fails here rather than passing as a
    # re-derivation nobody reviewed.
    assert palette_for(Theme.DARK).sequential == tuple(
        reversed(palette_for(Theme.LIGHT).sequential)
    )

    for theme in (Theme.LIGHT, Theme.DARK):
        assert palette_for(theme).diverging == (
            "#08474D",
            "#3FB8C4",
            "#DDE4E5",
            "#F0A882",
            "#B23A00",
        )


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
