# smartclock-monitor — agent conventions

smartclock-monitor monitors and controls HP/Symmetricom **SmartClock** GPS-disciplined
oscillators — the Z3805A and its siblings (Z3801A, 58503A/B, 59551A, Z3816A) — over RS-232.
Python 3.12 and Qt, so it runs on Linux, Windows and macOS.

It is a reimplementation of [WinZ3805A](https://github.com/TGoodhew/WinZ3805A), a finished
WinUI 3 application for the same hardware by the same author. **No code is shared, because
none of it can be** — WinUI 3 is Windows-only by definition, which is the whole reason this
repository exists. What *is* shared is everything that was never Windows-specific: the
specification, the captured fixtures, the colour derivation, and the guide.

**The application does not exist yet.** At the time of writing this repository holds the
specification, the fixtures, the palette derivation and the scaffolding. If you are reading
this in a session that is about to write code, your first job is to find out how much of
that is still true — read the tree, not this paragraph.

---

## The specification

**The specification is `docs/requirements.md`. Read it before implementing anything.
§-numbers in this file, in commits, and in code comments all resolve against it.**

It is the authority. Where this file, a prompt, a skill, or a plausible convention disagrees
with it, the document wins — and the conflict gets **surfaced, not silently resolved**.

Two things about it that will look like mistakes and are not:

1. **It describes a WinUI 3 application shipped to the Microsoft Store.** That is
   deliberate. It was carried across unedited so the two repositories stay comparable;
   editing it to match this port would fork the specification on day one and lose the
   ability to tell what diverged. **Do not edit it.** It is byte-identical to the copy in
   WinZ3805A, `.gitattributes` marks it `-text` so no checkout rewrites it, and
   `docs/provenance.md` records the commit it came from.

2. **"SmartClock" is HP's terminology, not a leftover.** `SmartClock Mode` is a field the
   receiver prints, and the specification uses *SmartClock family*, *SmartClock firmware*
   and *SmartClock oscillator learning* throughout §7, §10 and §11. Appendix B says
   explicitly that these are not to be renamed. Renaming them would make the parser
   specification wrong.

Where the specification is genuinely wrong **for this platform** — Mica, high contrast,
MSIX, Segoe UI Variable, the taskbar badge — part 7 of the port plan names every case. The
decisions this repository still owes its own answers to are part 12 of the same document.
**Those answers belong in a new document here**, not in edits to the inherited one and not
in a pull request description. Write them down before the code assumes them.

## The plan

[The port plan](https://github.com/TGoodhew/WinZ3805A/blob/main/docs/porting-to-python-qt.md)
lives in the sibling repository. Eight phases, each with a done-condition; work them in
order and do not start one before its predecessor's condition holds.

**Work out which phase we are on from the tree, not from the plan.** The plan is a map, and
the tree is the territory.

It uses `winz3805a_device` and `winz3805a` as package names. Here they are
**`smartclock_device`** and **`smartclock_monitor`** — carrying `Win` into a cross-platform
port makes no sense, and the application has always served the whole family rather than one
model. The mapping is otherwise exact.

---

## Safety — non-negotiable

**The commands listed in §8.4 are never implemented, displayed, logged, or referenced. Do
not add them to any catalog, list, comment, test fixture or docstring.**

This extends to commit messages, branch names and TODOs. The receiver accepts commands that
can render it unusable, and §8.1 excludes them by making the command catalog an
**allowlist**: they are not entries carrying a warning flag, **they do not exist as data**.
When the catalog is built, the only place those patterns may appear is
`src/smartclock_device/commands/blocked.py`, and the only way out is an
`is_blocked(candidate) -> bool` predicate that answers one question about one candidate and
cannot be enumerated, iterated or bound to.

There is no free-text command path, and there must never be one. §10.11's Advanced Console
is a picker over the allowlist.

**When `blocked.py` is written, port `Test-NoBlockedCommands.ps1` in the same change.** Over
in WinZ3805A that gate reads its tokens out of the one file that holds them and scans the
tree, which is what keeps that file the only place they occur. Until it exists here,
`docs/provenance.md` is the only thing saying the two lists must not diverge.

---

## Architecture boundaries

- **`src/smartclock_device/` imports no Qt and no application code, ever.** Not
  `PySide6`, not `smartclock_monitor`, not in a function body. This is the boundary that
  makes the port tractable at all: it is why the parser, the command classifier and the
  transport are testable with no display and no hardware, against captured status screens.
  `tests/test_layering.py` enforces it by AST scan — read it before adding an import.
- **Keep the device layer's dependencies to the standard library and `pyserial`.** The C#
  original ships three references and has stayed that way; the same discipline applies here.
  A dependency in the device layer is a dependency in every test.
- **No `datetime.now()`, `datetime.utcnow()`, `time.time()` or `time.monotonic()`, anywhere.**
  Inject a `Clock` and call it. This is not stylistic: the GPS week-rollover logic (§7.4),
  staleness display and poll scheduling are all clock-dependent, and the fixture tests must
  be able to pin the clock. **ruff enforces it** through `TID251` and the banned-api table in
  `pyproject.toml` — add a symbol there rather than relying on review, and test the addition
  against a deliberate violation.
- **The parser never raises** (§11.1). Not `ValueError`, not `KeyError`, not
  `AttributeError`. An unparseable field becomes `None` on the model and renders as `—`.
  Every consumer handles `None`; `mypy --strict` is what makes that checkable rather than
  aspirational, which is why it is on from the first commit rather than added later.
- **The session object is per-device, never a singleton.** v1 connects to one receiver. §12
  requires that this not be baked in — no module-level state for connection or identity.
- **Every receiver-specific fact sits behind a driver.** The application never reaches the
  SmartClock driver or the NMEA driver directly; it asks the driver the session selected.

### The fixtures

`tests/fixtures/` holds ten status screens captured from real hardware across two bench
sittings. The states they record — power-up, acquisition, holdover, recovery — happen only
while the receiver is being moved or restarted. **They cannot be regenerated on demand, and
a parsing bug found after they are lost cannot be retried without moving the hardware.**

Never reformat, regenerate or tidy them. They are device output and their exact bytes,
trailing whitespace and CRLF endings included, are the point; `.gitattributes` marks the
directory `-text` and `tests/test_fixtures.py` notices if that ever stops working.

They are the parser's oracle. **Write the fixture assertion before the parsing code.**

### `build/palette/`

Carried across from WinZ3805A verbatim, already Python, and runs unchanged. It is the
derivation behind §9.4.4's categorical palette, and `validate.py` checks the colour maths
against published figures before anything trusts it.

**It is excluded from ruff and from formatting on purpose.** The two copies being
byte-identical is what lets either repository trust the other's colours; reformatting it to
this project's house style would buy nothing and cost that.

**`sequential.py` is the one addition**, and it is written in that repository's style rather
than this one's, so the copy back is a copy. Every carried file is still byte-identical; the
*directory* is not, and that is tracked as
[TGoodhew/WinZ3805A#367](https://github.com/TGoodhew/WinZ3805A/issues/367). It derives §9.4.4's
sequential ramp for a dark surface, which the specification does not provide. Figures in
`docs/palette-figures.md`, re-checked by `validate.py`.

---

## Design system

§9 is the design system, and it is largely platform-neutral: the token set, the type ramp,
the spacing scale, the severity shapes, the categorical palette and the accessibility
criteria all survive the move to Qt. **Reach for §9 before reaching for a Qt or Fluent
default.**

Three §9.13 prohibitions worth keeping in view from the start, because retrofitting any of
them is where design systems die: no hard-coded colours outside the token table; only the
4 / 8 / circle corner radii and the §9.6 spacing scale; and **severity always renders as
colour + shape + text**, never colour alone.

What changes under Qt, and why:

- **QSS has no theme dictionaries and no live resource resolution.** Generate the stylesheet
  from the token table at startup and on theme change, and re-apply it. Keep the token table
  as *data* in one file, so that "no colour outside the token file" stays checkable.
- **Custom widgets do not take their colours from QSS at all.** Give them a palette object
  and repaint on theme change.
- **Light and Dark port directly. High contrast does not** — Windows resolves those tokens
  to the user's own system colours and Linux has no equivalent contract. That is part 12's
  decision, not an implementation choice; do not settle it by writing a theme file.

§15 is an ordering constraint, not a suggestion: **the token layer exists before any page is
built.**

---

## Build and verify

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

Run all four before pushing. They are what CI runs, they take seconds, and CI runs them in
separate jobs so a lint or typing regression fails without waiting for the tests:

```bash
ruff check .
ruff format --check .
mypy
pytest
```

Plus, if you touched anything about colour:

```bash
python build/palette/validate.py
```

That one reports rather than exiting non-zero, so the failure marker `!!` in its output is
the gate — CI greps for it.

`mypy --strict` is on. So is `ruff format`. Neither is negotiable per-file.

### Adding a guard

Several rules here are enforced by a check rather than by review, and more will be as the
port proceeds. When you add one:

**Test it against a deliberate violation, then remove the violation and re-confirm green.**
A rule that matches nothing is a rule that enforces nothing, and it fails silently — which
is worse than no rule, because it reads as coverage. `tests/test_layering.py` tests *itself*
this way for exactly that reason: it scans a nearly-empty tree and would otherwise pass
while broken.

The corollary: **a gate that cries wolf is one people learn to scroll past.** Prefer a
precise check that finds nothing today over a loose one that produces noise.

---

## Branches and merges

Never work on `main`, not even for a one-line fix. Branch off an up-to-date `main`, named
for the work — `feat/parser-status-screen`, `fix/prompt-straddles-read`,
`docs/platform-decisions` — commit in separately revertable pieces where the work has
separable parts, and open a pull request so CI runs.

Merge when it is green (rebase merge, so `main` stays linear), then leave the local
repository matching the remote: delete the branch on both sides
(`gh pr merge --rebase --delete-branch` does both), fast-forward local `main`, and
`git remote prune origin`.

---

## Repository layout

```
docs/requirements.md          the specification — inherited, byte-exact, never edited
docs/provenance.md            what was copied, and what must not drift
docs/how-to-use.md            the guide; its screenshots are Windows captures, to be retaken
src/smartclock_device/        the receiver. NO Qt, NO application imports, ever.
  transport/ commands/ parsing/ models/ drivers/ (and drivers/nmea/)
src/smartclock_monitor/       the application
  services/ viewmodels/ widgets/ views/ themes/ platform/
tests/fixtures/               ten captured status screens — irreplaceable
build/palette/                the colour derivation, carried verbatim (+ sequential.py), no lint
.github/workflows/ci.yml      lint, types, palette self-test, then tests on Linux and Windows
```

`platform/` is where anything that differs between desktops goes — tray, notifications,
badges — behind a per-OS implementation with a no-op fallback. Nothing outside it should ask
what operating system it is running on.
