# Where WinZ3805A's CI gates went

WinZ3805A's `build/` carries twelve `Test-*.ps1` gates. This table says, for each one, what enforces
the same rule here — or that nothing does.

**Written because "we have a test with a similar name" was doing the work of "the rule is
enforced".** The #22 audit found three rules with no counterpart at all, and none of them announced
itself: a missing gate is indistinguishable from a passing one.

`CLAUDE.md`'s rule applies to this table as much as to the gates it lists — *a rule that matches
nothing is a rule that enforces nothing, and it fails silently, which is worse than no rule because
it reads as coverage.*

| WinZ3805A | Enforces | Here |
|---|---|---|
| `Test-ContrastFloor.ps1` | A11Y-4 / §9.4.5: every token pair meets its floor in both themes | `test_design_tokens.py` — `test_primary_text_meets_the_contrast_floor`, `test_secondary_and_tertiary_text_meet_the_floor`, `test_every_severity_colour_is_legible_on_a_card`, `test_every_diverging_stop_clears_the_contrast_floor` |
| `Test-NoHexLiterals.ps1` | §9.13 item 2: no literal colour outside the token file | `test_design_tokens.py` — `test_no_hex_literal_outside_the_token_file`, with three tests of the gate itself |
| `Test-NoColourOnlyStates.ps1` | A11Y-12 / §9.4.3: no state distinguished by colour alone | `test_design_tokens.py` — `test_success_and_critical_are_not_distinguished_by_colour_alone`; `test_accessibility.py` — `test_only_the_sanctioned_renderers_resolve_a_severity_to_a_colour` |
| `Test-IconOnlyButtons.ps1` | A11Y-3, A11Y-5, §9.9: every icon-only control is named | `test_accessibility.py` — `test_every_control_without_visible_text_is_named_or_tipped`, tested against a deliberate violation |
| `Test-PointerTargets.ps1` | A11Y-5: a non-button pointer target is still 32 px | `test_accessibility.py` — `test_every_interactive_control_meets_the_pointer_floor`, `test_the_sky_plot_marker_keeps_its_documented_hit_area` |
| `Test-NoBlockedCommands.ps1` | P0-7 / §8.4: no excluded command named outside the one file | `test_no_blocked_commands.py` — the port named in `CLAUDE.md`, scanning the whole tree |
| `Test-SeriesSeparation.ps1` | §9.4.4 / A11Y-12: chart series stay distinguishable under CVD | **`build/palette/validate.py`**, run as its own CI job — it reproduces the published ΔE₀₀ figures under deutan and protan simulation. Not a pytest, and correctly so: the derivation and its check are carried from WinZ3805A verbatim |
| `Test-HighContrastLegibility.ps1` | A11Y-8 / §9.2: nothing illegible in the high-contrast theme | **Not applicable.** D3 — there is no high-contrast theme; Windows resolves those tokens to the user's system colours and Linux has no equivalent contract. `docs/divergences.md` |
| `Test-GuideCoverage.ps1` | Every option the user can act on is named in the guide | **Nothing on `main`.** A counterpart exists as `tests/test_guide.py` on the unpushed branch `docs/guide-for-this-port`, together with the guide it checks |
| `Test-DocumentReferences.ps1` | Every cross-reference a document makes resolves | **Nothing.** The repository has ten documents that reference each other and the code |
| `Test-FocusVisualCoverage.ps1` | A11Y-2 / §9.12: the focus visual clears 3:1 on any surface | **Nothing.** `themes/qss.py` draws `:focus` on buttons, line edits, tool buttons and combo boxes, and no test measures any of them |
| `Test-PageTeardown.ps1` | A page that subscribes must let go when navigated away | **Nothing.** Whether the rule even applies under Qt is the first question — it was written against WinUI navigation |

## What this leaves open

Three rows say *nothing*, and they are tracked as
[#41](https://github.com/TGoodhew/smartclock-monitor/issues/41) rather than left in a table nobody
re-reads. The guide row is not a missing gate so much as a missing merge — the work exists on
`docs/guide-for-this-port` and has never been pushed.

## The other direction

Gates here with no WinZ3805A counterpart, because they enforce rules that only exist in this port:

| Here | Enforces |
|---|---|
| `test_layering.py` | `smartclock_device/` imports no Qt and no application code, by AST scan. The boundary that makes the port testable without a display or hardware |
| `test_versioning.py` | The version is derived, is `A.B.C.D`, and CI checks out enough history to derive it |
| `test_fixtures.py` | The captured screens keep their exact bytes, CRLF endings included |
| `test_requirements_coverage.py` | Every P0 and P1 in §13 is named by a test or recorded with the decision that removed it |
