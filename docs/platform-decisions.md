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

**Status: Provisional** ([#5](https://github.com/TGoodhew/smartclock-monitor/issues/5)). Dropped
as a goal of this repository.

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

**Status: Provisional** ([#3](https://github.com/TGoodhew/smartclock-monitor/issues/3)) — option
**(a)**, with (c)'s trigger deferred to Phase 8.

**This is the one to be most careful about.** It was taken provisionally rather than left open
only because Phase 5 could not start otherwise; of everything on this page it is the decision
most worth a second opinion.

It is an accessibility promise, the current one is stronger than a hand-authored theme can be,
and the difference is invisible to anyone not relying on it.

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

**(a)**, with (c)'s trigger deferred. The plan says (a) is the better answer for this audience,
with the qualifier that it be made deliberately and the weaker promise written down where a user
can read it — so:

> **This application asserts its own high-contrast colours. It does not use yours.** On Windows,
> WinZ3805A resolves them to your system colour choices; this port cannot, because the desktop
> offers no equivalent contract. If you rely on a specific high-contrast scheme, this is a real
> difference and not a cosmetic one.

That paragraph belongs in the README and the guide, not only here.

The token set is identical under (a) and (c), so adding the trigger in Phase 8 reworks nothing in
Phase 5. **Reversing to (b) is cheap** — delete a token column and two gates. Reversing *to* (a)
later would not have been, which is why it was taken this way round.

---

## D4 — The typeface, and the contrast re-derivation that follows

**Status: Provisional** ([#4](https://github.com/TGoodhew/smartclock-monitor/issues/4)). System UI
font for prose, Cascadia Mono bundled for device-literal text, contrast figures re-derived before
Phase 5 closes.

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

The prose half therefore needs a face. Either the system UI font (Qt's default resolves to
Cantarell, Noto Sans, DejaVu Sans or whatever the desktop configures), or a bundled variable face
chosen once. The system font is proposed: it is what every other application on the desktop uses,
which is the same instinct §9.5.1 followed in picking the Windows system face, and it avoids
shipping a second font with a second licence for no gain in identity.

**The part that is not optional.** §9.4.5's contrast figures and §9.5.2's type ramp were measured
against Segoe UI Variable at specific optical sizes. Changing the face **silently invalidates
them** — that is part 12's own warning. Whatever is chosen:

1. Re-derive the §9.4.5 contrast figures against the chosen face and Qt's palette. §9.4.1's stock
   Fluent values were measured from a running Windows app and are not a valid baseline here.
2. Re-check §9.5.2's ramp — x-height and optical sizing differ, and a ramp that reads correctly in
   Segoe UI Variable Text at 12 px may not in a face with a larger x-height.
3. Only then port `Test-ContrastFloor.ps1`. Its maths is reusable; **its input table is not.**

---

## D5 — Tray and notifications on desktops that have neither

**Status: Provisional** ([#6](https://github.com/TGoodhew/smartclock-monitor/issues/6)). Behind
`platform/`, with a no-op fallback and a visible degradation.

§10.3.1's close-to-tray design assumes a tray exists. `QSystemTrayIcon` works, but GNOME has no
tray without a shell extension, and some desktops have none at all.

- **Tray:** probe `QSystemTrayIcon.isSystemTrayAvailable()` at startup. Where there is no tray,
  **close means close** and the keep-running preference is disabled with a reason shown, rather
  than the window vanishing to nowhere. A window that disappears with no way back is the worst
  available outcome and is what the naive port produces.
- **Notifications:** the D-Bus `org.freedesktop.Notifications` interface, or `notify-send`.
  Straightforward — but note the history: the App SDK notification path in WinZ3805A never worked
  and was fixed by *removing* it. **Keep the `IToastSink` seam and its no-op fallback**; that seam
  is the thing that made removal possible without touching callers.
- **Taskbar overlay badge:** dropped. No cross-desktop equivalent; the Unity launcher D-Bus API
  works on some desktops and not others.

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
| D2 | G5 / Microsoft Store | Provisional | [#5](https://github.com/TGoodhew/smartclock-monitor/issues/5) | Phase 8 packaging work only |
| D3 | High contrast | Provisional | [#3](https://github.com/TGoodhew/smartclock-monitor/issues/3) | One token column and two gates |
| D4 | Typeface + contrast re-derivation | Provisional | [#4](https://github.com/TGoodhew/smartclock-monitor/issues/4) | One constant, plus re-running the figures |
| D5 | Tray and notifications | Provisional | [#6](https://github.com/TGoodhew/smartclock-monitor/issues/6) | Confined to `platform/` |
| D6 | Relationship — §8.4 sync | **Settled** (safety half) | — | Not reversible. See above. |

**Every provisional row was chosen to be cheap to reverse**, which is the only honest way to take
a decision on someone else's behalf. D3 is the one to look at first.
