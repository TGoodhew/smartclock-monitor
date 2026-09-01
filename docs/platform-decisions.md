# Platform decisions

**The decisions this port owes its own answers to, and where each one stands.**

`docs/requirements.md` is carried across from
[WinZ3805A](https://github.com/TGoodhew/WinZ3805A) unedited and still describes a WinUI 3
application shipped to the Microsoft Store. That is deliberate — editing it to match this port
would fork the specification on day one and lose the ability to tell what diverged — so it is
silent on this platform by design, and **this file is where that silence gets filled in**.

Part 7 of [the port plan](https://github.com/TGoodhew/WinZ3805A/blob/main/docs/porting-to-python-qt.md)
names every place the specification is wrong for Linux. Part 12 lists the decisions that must not
be made by accident. This document answers part 12, in order, and records part 7's mechanical
consequences underneath.

**Each of these changes what the application promises a user**, and each has a default that looks
harmless from inside a single pull request. That is the whole reason the list exists. The plan
puts it plainly: none of them should be settled by whoever reaches the file first.

## How to read the status column

| Status | Means |
|---|---|
| **Settled** | Decided, with the evidence recorded here. Code may rely on it. |
| **Provisional** | Decided so the work can proceed, with the reasoning and the alternatives in a tracking issue. Code relies on it; **it is expected to be reviewed, and reversing it is budgeted for.** |

Every `Provisional` row carries an issue number. That is where the argument lives, and it is the
place to disagree — the row here records only what was chosen and what it costs.

**Provisional is not a synonym for settled.** §15 orders the token layer ahead of every page
because retrofitting it is where design systems die, and D3 and D4 both feed that layer. They
were taken provisionally rather than left open so that Phase 5 could start; each names, in its
issue, what reversing it would cost.

---

## D1 — Which route this is

**Status: Settled.** An independent port.

The plan's part 0 offers two routes: an independent port, which needs no amendment to anything
in WinZ3805A because it is not bound by that project's goals; or a port that project adopts,
which requires §2, §3 and §6.1 to be amended there first, since that is where the goals and the
stack are written down.

This is the first. The evidence is already in the tree rather than in anyone's memory:

- `README.md` states it is "a sibling rather than a fork", and records the commit it was taken
  from — [`73d5962`](https://github.com/TGoodhew/WinZ3805A/commit/73d5962a0ae43e7f9a2c0963d7edd3b109c32787).
  That is exactly what the plan's Phase 0 asks an independent port to write down, and the reason
  it asks: a fork that cannot say what it diverged from cannot pick up a later parser fix.
- `docs/provenance.md` records what was copied and what must not drift.
- `docs/requirements.md` is carried byte-exact and unedited, which is route (a)'s behaviour.
  Route (b) would have required amending §2, §3 and §6.1 over there *before* anything else.

**Consequence:** the remaining decisions on this page are this repository's own to make. They do
not need permission from WinZ3805A, and D6 governs what flows back.

*Same author is not the same thing as same project.* The two repositories have different goals
and different platforms; that they share a maintainer is why D6 matters, not why D1 is in doubt.

---

## D2 — G5, the Microsoft Store

**Status: Settled** (confirmed 1 Sep 2026, [#5](https://github.com/TGoodhew/smartclock-monitor/issues/5)).
Dropped as a goal of this repository.

§2's G5 is "Ships to the Microsoft Store as an MSIX package", measured by passing the Windows App
Certification Kit. MSIX is a Windows packaging format and the Store is a Windows channel; neither
has a Linux equivalent, and the plan notes that packaging a Python Qt app for the Store is
materially harder than packaging the current MSIX — a real cost of this port rather than a
detail.

G5 remains a live goal **of WinZ3805A**, which ships it today. Nothing here changes that.

The reason to state this rather than let it lapse: §6.3's rule against hard-coding the
application name exists because `Package.Current.DisplayName` supplied it. With no package
identity there is no such source, and the rule still has to be honoured — see P4 below.

**Proposed replacement targets:** Flatpak for Linux (bundles Qt, sandboxed, and serial access is
a declared device permission), with AppImage a reasonable second; PyInstaller plus an installer
for Windows. macOS falls out nearly free from PySide6, but nothing here has been thought through
for it and support should not be claimed without a machine to test on.

---

## D3 — High contrast

**Status: Settled** (1 Sep 2026, [#3](https://github.com/TGoodhew/smartclock-monitor/issues/3)) —
option **(b)**. Light and Dark only, and the reduction is written down where a user can read it.

This was taken provisionally as **(a)** so that Phase 5 could start, flagged here as the decision
most worth a second opinion, and reviewed. The second opinion went the other way.

### What Windows does today

`Themes/Colors.xaml` is the one file with `Light`, `Dark` and `HighContrast` dictionaries, and
under high contrast the tokens resolve to the user's **own** `SystemColor*` choices — not to
values this application picked. That is a materially stronger promise than "we chose colours that
contrast well": it defers to whatever the person at the keyboard has configured.

Two CI gates exist because that deferral can still go wrong. `Test-ThemeDictionaryParity.ps1`
checks every token is defined in all three dictionaries; `Test-HighContrastLegibility.ps1` forbids
a foreground token from *being* a surface. The second was written after a real defect (#218) where
sequential ramp steps 1 and 2 were defined as the window colour, drawing every satellite below
C/N 35 in the page background. A token that is merely *defined* can still be illegible.

### What Linux offers

No equivalent system-wide contract. GNOME has a high-contrast preference; it is not a per-token
API, and it is not universal across desktops. There is nothing to defer *to*.

### The options

**(a) Ship a hand-authored high-contrast theme** as a third token set the application owns.

- Both gates keep working, against this repository's own values rather than the user's.
- §9.13's prohibitions and the §9.11 state matrix stay expressible in three themes.
- **But the promise weakens**, and that has to be written down as such: the app asserts its own
  contrast instead of honouring the user's configuration. For someone who has set a specific
  high-contrast scheme because of a specific visual impairment, "we picked good colours" is not
  the same service as "we use yours".
- Cost: a third token set to author, maintain and gate, with no user configuration behind it.

**(b) Ship Light and Dark only**, and say so plainly in the README and the guide.

- Honest, and cheap. `Test-ThemeDictionaryParity.ps1` becomes meaningless with two themes both
  exercised daily, and `Test-HighContrastLegibility.ps1` retires with it.
- **But it is a straightforward reduction in accessibility** against the Windows sibling, on an
  axis §9.12 treats as an acceptance criterion rather than a nicety.

**(c) Not in the plan, worth naming:** follow the desktop's own preference where one exists —
read `org.gnome.desktop.a11y.interface high-contrast` or the `prefers-contrast` equivalent — and
select a hand-authored high-contrast token set from it. This is (a) plus a trigger, not a third
answer: the values are still ours. It buys automatic activation for the users most likely to
need it, at the cost of a per-desktop probe in `platform/`, which is where anything that asks
what desktop it is running on belongs anyway.

### What was decided, and what it costs

**(b).** Light and Dark, and no high-contrast theme.

The argument that settled it is the one (a) had to answer and could not: a hand-authored theme
**asserts our contrast in place of the user's**. For someone who has configured a specific scheme
because of a specific impairment, that is not a weaker version of the Windows behaviour — it is a
different thing wearing its name. And it is worse than having nothing, because a menu entry
reading *High contrast* is a claim the user has no reason to doubt until it fails them.

> **This port ships Light and Dark only.** WinZ3805A resolves its high-contrast tokens to your own
> Windows system colours; no desktop this port targets offers an equivalent contract, and rather
> than assert colours of our own under that name, there is no high-contrast theme here. If you
> rely on one, this is a real reduction against the Windows application and not a cosmetic one.

That paragraph belongs in the README and the guide, not only here, and the difference is recorded
in [`divergences.md`](divergences.md) with the others.

**What it cost to reverse, as predicted:** one token column, one gate rewritten from three themes
to two, and nine parametrised cases that went away with it. The prediction was accurate, which is
the only reason taking it provisionally was defensible.

**(c) is not reopened by this.** Reading the desktop's own high-contrast preference would only
select a hand-authored set, and the objection above is to the set, not to the trigger.

---

## D4 — The typeface, and the contrast re-derivation that follows

**Status: Settled** (1 Sep 2026, [#4](https://github.com/TGoodhew/smartclock-monitor/issues/4)).
**Noto Sans** for prose, Cascadia Mono for device-literal text, contrast figures re-derived and
gated.

§9.5.1 specifies Segoe UI Variable Text for UI, Segoe UI Variable Display for headings and
numeric readouts, and **Cascadia Mono for every string the receiver actually emits** — SCPI
mnemonics, raw register values, log entries, the transcript, the `*IDN?` string. §9.5's typographic
split is load-bearing, not decorative: it makes "what the machine said" visually distinct from
"what the app says about it", in an application whose whole job is faithful reporting.

- **Cascadia Mono ports as-is.** It is SIL OFL 1.1, already bundled in WinZ3805A with its licence
  notice, and licensed for redistribution. Bundle it here the same way rather than assuming it is
  present — it is not inbox on most Linux distributions. **The device-literal half of the split
  survives unchanged**, which is the half that matters most.
- **Segoe UI Variable does not port.** It is not present on Linux and is not redistributable.

The prose half therefore needs a face, and it is **Noto Sans**, named.

The provisional answer was the system UI font — whatever the desktop configures — on the reasoning
that this is what every other application uses, and it is the same instinct §9.5.1 followed in
picking the Windows system face. That reasoning is sound for an application with slack in its
layout. **This one does not have much**, and the cost showed up as a CI failure: a page measured to
fit on the development machine overflowed on a runner that resolved a wider face at the same point
size. A face is a set of glyph widths, so deferring the face defers the widths to a machine nobody
has measured, and no local run can see it.

Noto Sans rather than DejaVu Sans, the other candidate present nearly everywhere: DejaVu is
materially wider at the same point size, and the widest page here already sets the Details window's
minimum. A specimen of both across the §9.5.2 ramp is what settled it. Noto is SIL OFL 1.1, so
bundling it later needs no new licence conversation — the same door Cascadia Mono leaves open, and
bundling is what would make the metrics identical everywhere rather than merely likely.

**The part that was not optional, and what became of it.** §9.4.5's contrast figures and §9.5.2's
type ramp were measured against Segoe UI Variable at specific optical sizes, and changing the face
silently invalidates them — part 12's own warning.

1. **Contrast: re-derived, and it no longer depends on the face.** `test_design_tokens.py` asserts
   **4.5:1 for every text token on every surface it is drawn on**. That is the stricter floor,
   taken deliberately: none of it rests on WCAG's large-text exemption, which is the only part a
   change of face could have invalidated. §9.4.1's stock Fluent values are not a baseline here and
   are not used as one.
2. **The ramp: re-checked against a rendered specimen** of Noto Sans, DejaVu Sans and Ubuntu across
   all six steps, comparing x-heights. Noto's progression (15 / 10 / 8 / 7 px at Title / Subtitle /
   Body / Caption) keeps every step distinguishable from its neighbours, which is what the ramp is
   for. `test_typography.py` gates the distinctness and the named face.
3. `Test-ContrastFloor.ps1` was not ported. Its maths is inline in the gate above; **its input
   table was the part that did not transfer**, and it is this port's palette that is asserted.

---

## D5 — Tray and notifications on desktops that have neither

**Status: Settled** (1 Sep 2026, [#6](https://github.com/TGoodhew/smartclock-monitor/issues/6)).
**Neither is shipped.** No tray, no desktop notifications, no taskbar badge.

§10.3.1's close-to-tray design assumes a tray exists. `QSystemTrayIcon` works, but GNOME has none
without a shell extension and some desktops have none at all — so the provisional answer was to
probe for one and degrade visibly. That answer was built, and reviewing it turned up the objection
it could not meet: **every fallback path was the only path.** The development desktop reports no
tray, the CI runners have none, and a feature exercised on nobody's machine that appears on
somebody's is worse than one that never appears at all.

So the seam went with the feature, rather than being kept for a caller that no longer exists.

- **Tray:** removed. Close means close, and the poll stops with it. §10.3.1's own argument settles
  what to do without an icon: a hidden window with no icon "cannot be reached by any means the
  user has", so hiding would be a loss of the application rather than an inconvenience.
- **Notifications:** removed, and the history rhymes. The App SDK notification path in WinZ3805A
  never worked and was fixed by *removing* it; the seam that made that possible is here honoured
  by taking the same decision earlier rather than by keeping an unused abstraction.
- **Taskbar overlay badge:** dropped, as it already was. No cross-desktop equivalent.

### What went with them

**P1-9, the lock-loss alert.** §13 makes it a P1 and §10.13 defaults it *on*, because it exists
"precisely for the user who is *not* looking". A message shown only inside the window they are not
looking at does not serve that, so the honest move is to remove it rather than keep a switch that
promises less than its name. This is a **reduction against WinZ3805A** and is recorded as one.

**§10.3.1's keep-running-when-closed**, and **start-in-the-notification-area**. Both were switches
that only a notification area could honour. A switch that cannot do what it says is worse than an
absent one, because the user sets it and then believes it.

The Settings *Exit* button stays. §10.3.1 wants the application quittable from its own surface, and
that argument survives the removal of the surface it was written against.

---

## D6 — The relationship between the two implementations

**Status: Settled on the safety half. Proposed on the rest.**

**Settled, and non-negotiable: the §8.4 exclusion list is kept synchronised, in both directions.**

§8's safety model now exists twice, and two implementations is two places for it to go wrong. A
receiver bricked by one of those commands is bricked either way, so the allowlist architecture in
§8.1 is the part that must not diverge: the excluded commands are not entries carrying a warning
flag, **they do not exist as data**.

The mechanism, not the intention, is what makes this hold:

- `src/smartclock_device/commands/blocked.py` will be the only file in this repository where
  those patterns appear, reached solely through `is_blocked(candidate) -> bool` — a predicate that
  answers one question about one candidate and cannot be enumerated, iterated or bound to.
- `Test-NoBlockedCommands.ps1` is ported **in the same change as `blocked.py`**, not after. Over
  in WinZ3805A that gate reads its tokens out of the one file that holds them and scans the tree,
  which is what keeps that file the only place they occur.
- When either repository changes its list, **diff both.** Until the gate exists here,
  `docs/provenance.md` is the only thing saying so, which is not enough.

This is Phase 3 of the plan and the highest-value gate in the set.

**Provisional for everything else:** this port tracks WinZ3805A for receiver behaviour — parser
fixes, command semantics, newly captured fixtures — and diverges freely on presentation and
platform. A fixture captured on either bench belongs in both repositories;
`tests/fixtures/captured/capture-log.md` is the shared record and should stay one record rather
than growing two. A parser fix found here is worth reporting there, and vice versa.

---

## Part 7's mechanical consequences

These follow from the platform rather than from a judgement, and are recorded so nobody
re-litigates them mid-implementation. They are not part 12 decisions.

| Windows feature | Where | What happens here |
|---|---|---|
| **Mica Alt backdrop** | §9.2 | No equivalent. The existing solid-colour fallback becomes the only path, which the design already handles correctly. |
| **`Package.Current.DisplayName`** | §6.3 | No package identity. Read the name from **one** module-level constant — see P4 below. |
| **Stock Fluent colours** | §9.4.1, `build/fluent-stock-colours.txt` | Measured from a running Windows app. Not a valid baseline; re-derive per D4. |
| **Windows accent colour** | §9.4.2 | No single equivalent. §9.4.2's guard against using the accent as brand becomes unnecessary; the brand ramp stays. |
| **MSIX / Store** | §6.3, G5 | Per D2. |
| **Taskbar overlay badge** | shell surfaces | Dropped, per D5. |
| **`SerialPort.GetPortNames` + registry crawl** | `SerialPortEnumerator` | `serial.tools.list_ports.comports()`, which gives description and hwid on all three platforms. A clear simplification. |

**P4 — the application name.** §6.3 forbids hard-coding it, and the reason survives the loss of
the API that supplied it: the name appears in title bars, the about surface and the guide, and a
rename that has to be made in nine places gets made in eight. One module-level constant, read
everywhere, no literal anywhere else.

**A11Y tooling.** §9.12's criteria port — accessible names, focus visuals, keyboard traversal,
live regions, pointer target floors, and the rule that colour is never the only channel. The
*harness* does not: the Windows UIA rig has no Linux equivalent, so AT-SPI via Accerciser or
dogtail has to be written from scratch. Budget for it. Several existing gates exist because a
criterion was signed off as passing while breaches sat in the primary window, and what found them
was someone trying to use the application.

---

## What is still owed

| # | Decision | Status | Issue | Reversing it costs |
|---|---|---|---|---|
| D1 | Route — independent port | **Settled** | — | — |
| D2 | G5 / Microsoft Store | **Settled** | [#5](https://github.com/TGoodhew/smartclock-monitor/issues/5) | — |
| D3 | High contrast — **not shipped** | **Settled** | [#3](https://github.com/TGoodhew/smartclock-monitor/issues/3) | — |
| D4 | Typeface — **Noto Sans** + Cascadia Mono | **Settled** | [#4](https://github.com/TGoodhew/smartclock-monitor/issues/4) | — |
| D5 | Tray and notifications — **not shipped** | **Settled** | [#6](https://github.com/TGoodhew/smartclock-monitor/issues/6) | — |
| D6 | Relationship — §8.4 sync | **Settled** (safety half) | — | Not reversible. See above. |

**Every provisional row was chosen to be cheap to reverse**, which is the only honest way to take a
decision on someone else's behalf — and all five were reviewed on 1 Sep 2026. Two were reversed
(D3 and D5), one was tightened from a deferral into a name (D4), and one was confirmed (D2). The
reversals cost what they were predicted to cost, which is the only reason taking them provisionally
was defensible.

Nothing on this page is provisional now. The differences those decisions create against the Windows
sibling are collected in [`divergences.md`](divergences.md), which is the document to hand someone
who knows WinZ3805A and is meeting this port for the first time.
