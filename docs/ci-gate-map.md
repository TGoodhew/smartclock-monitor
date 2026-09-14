# Where WinZ3805A's CI gates went

WinZ3805A's `build/` carries **eighteen** `Test-*.ps1` gates. This table says, for each one, what
enforces the same rule here — or that nothing does.

> **Corrected 14 Sep 2026 (#97).** This said *twelve*, and listed twelve. Six gates had no row at
> all — so the document whose whole purpose is accounting for them was silently short by a third,
> which is the failure it warns about two paragraphs down, committed by the warning itself. The six
> are the last six rows below.

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
| `Test-GuideCoverage.ps1` | Every option the user can act on is named in the guide | `test_guide.py` — the guide's coverage of the options; and `test_guide_against_the_interface.py` (#99) — every card and control the guide names exists on that page, and every card on a page is named in the guide. The second direction found §10.9's *GPS receiver* card built and never documented |
| `Test-DocumentReferences.ps1` | Every cross-reference a document makes resolves | `test_document_references.py` — markdown links resolve, and every test function a document names exists. Paths named in *prose* are deliberately not checked; the module says why |
| `Test-FocusVisualCoverage.ps1` | A11Y-2 / §9.12: the focus visual clears 3:1 on any surface | `test_accessibility.py` — `test_the_focus_visual_clears_three_to_one_on_every_surface_it_lands_on` measures the stroke against all five surfaces in both themes (4.85–8.12:1), and `test_no_focusable_control_is_filled_with_the_focus_colour` checks §9.12's accent-filled case structurally |
| `Test-NoCachedDispatcherHandlers.ps1` | #403: no `DispatcherQueueHandler` cached in a field and handed to `TryEnqueue` — every call mints a COM callable wrapper and the runtime keeps each one | **Not applicable.** There is no `DispatcherQueue`: Qt marshals to the GUI thread by signal connection, and a connection is not re-created per emission. The analogous rule — a page that subscribes must let go — is the row above |
| `Test-NoPushedAutomationNames.ps1` | A custom control computes its automation name in a peer rather than pushing it with `AutomationProperties.SetName`, which hands the control across to WinRT | **Not applicable, and inverted.** `setAccessibleName` is a plain Qt property with no interop cost, so this port's own gate *requires* what that one forbids: `test_accessibility.py`'s `test_every_control_without_visible_text_is_named_or_tipped` |
| `Test-ResourceKeysResolve.ps1` | Every `{ThemeResource Wz…}` names a token that exists | **Not applicable, and moot for a better reason than absence.** QSS has no resource dictionaries — the stylesheet is generated from the token table by `themes/qss.py`, so a misspelled token is an attribute that does not exist and `mypy --strict` refuses it before anything runs. A missing key cannot reach a running window |
| `Test-SpacingScale.ps1` | §9.13 item 2: only §9.6's spacing scale and §9.3's three radii | `test_design_tokens.py` — `test_the_stylesheet_uses_only_the_spacing_scale` covers the generated QSS, and `test_no_layout_call_uses_an_off_scale_value` covers the imperative half: `setContentsMargins`, `setSpacing` and the two grid spacings, by AST scan. **The second was added by #97's audit** — the first covered the stylesheet only, and most spacing in a Qt application is set in code rather than in the stylesheet |
| `Test-ThemeDictionaryParity.ps1` | §9.4 / A11Y-8: every theme defines the same keys, of the same type | `test_design_tokens.py` — `test_every_theme_defines_every_token`, and `test_there_are_two_themes_per_decision_d3` pins how many themes there are to a decision rather than to a habit. The high-contrast third is D3's *not shipped* |
| `Test-NoClosingKeywords.ps1` | A GitHub closing keyword stands only where the author means to close the issue | `test_closing_keywords.py` for the commit messages this branch adds to `main`, and `ci.yml`'s **Closing keywords** job for the pull request body, which is not in the tree at all. One module (`tools/closing_keywords.py`) behind both, so the two halves of the rule cannot drift apart (#131) |
| `Test-PageTeardown.ps1` | A page that subscribes must let go when navigated away | **Not applicable, and pinned as such.** `test_page_lifecycle.py` asserts the two facts that make it moot: pages are built once into a `QStackedWidget` and shown by index, and every `.connect()` in `pages.py` is to a signal the page owns. Either changing would make WinUI's rule live here |

## What this leaves open

**Nothing, as of 14 Sep 2026.** Every one of the eighteen is either ported, or asserted not to
apply in a form that stays true on its own — which is the only kind of *not applicable* worth
writing down. `Test-NoClosingKeywords.ps1` was the last open row and closed the same day the audit
that found it (#97) was written up.

> **Corrected 14 Sep 2026 (#97).** This section said `Test-GuideCoverage.ps1` had *"nothing on
> `main`"* and that its counterpart sat unpushed on a branch. **It was merged**: `tests/test_guide.py`
> and `docs/how-to-use.md` are both on `main`, the guide is what `F1` opens, and #99's part 4 added
> a second gate that checks the guide against the interface in both directions. A gate map that
> reports a gate as missing when it is present is the same defect as the reverse, and harder to
> notice: nobody goes looking for a gate the map says is already there.

## The other direction

Gates here with no WinZ3805A counterpart, because they enforce rules that only exist in this port:

| Here | Enforces |
|---|---|
| `test_layering.py` | `smartclock_device/` imports no Qt and no application code, by AST scan. The boundary that makes the port testable without a display or hardware |
| `test_versioning.py` | The version is derived, is `A.B.C.D`, and CI checks out enough history to derive it |
| `test_fixtures.py` | The captured screens keep their exact bytes, CRLF endings included |
| `test_requirements_coverage.py` | Every P0 and P1 in §13 is named by a test or recorded with the decision that removed it |
| `test_catalogue_covers_the_spec.py` | Every command §8.2 and §8.3 list is on the allowlist, at §8.3's tier and with §8.3's sentence. It reads the specification itself, so it fails when the document and the catalogue disagree whichever of them moved |
| `test_registers_against_screen.py` | The status registers and the status screen, captured in one sitting, say the same thing — and no register has a bit set that the map cannot name |
| `test_guide_against_the_interface.py` | The guide and the interface agree about what is on each page, in both directions |
| `test_screen_against_bytes.py` | A page's text, against a status built by the real driver from bytes a real receiver sent |
