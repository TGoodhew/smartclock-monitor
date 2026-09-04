# What is different from WinZ3805A

For someone who knows the Windows application and is meeting this one. It lists what this port
does **differently**, why, and — where the difference is a reduction — says so in those words.

The two repositories share a specification, a set of captured fixtures and a colour derivation, and
none of those has been edited to fit the port ([`provenance.md`](provenance.md) records what was
copied and what must not drift). So the differences here are not drift. Each one is a decision with
its reasoning in [`platform-decisions.md`](platform-decisions.md) and its argument in an issue.

---

## At a glance

| | WinZ3805A | Here | |
|---|---|---|---|
| **High contrast** | Resolves to your Windows system colours | **Not shipped** | *Reduction* — D3 |
| **Lock-loss alert (P1-9)** | Desktop notification | **Not shipped** | *Reduction* — D5 |
| **Close to notification area** | Hides, keeps polling | Closes, stops polling | *Reduction* — D5 |
| **Taskbar overlay badge (P1-13)** | Yes | No | *Reduction* — D5 |
| **UI typeface** | Segoe UI Variable | Noto Sans | Neutral — D4 |
| **Device-literal typeface** | Cascadia Mono | Cascadia Mono | **Same** — D4 |
| **Packaging** | MSIX, Microsoft Store | **AppImage**, built from PyInstaller | Different — D2, #27 |
| **Platforms** | Windows | Linux, Windows, macOS | *Addition* |
| **Receiver families** | SmartClock | SmartClock **and NMEA 0183** | *Addition* |
| **How pages name commands** | SCPI mnemonics | `Capability` enum | Different — see below |
| **System accent colour (P1-11)** | Opt-in | Not offered | Neutral — nothing to read |
| **Sequential ramp on Dark** | One ramp, both themes | Derived per surface | *Fix* — see below |
| **Diverging ramp** | One ramp, both themes | Derived per surface | *Fix* — see below |
| **Main window minimum width** | 380 px (§9.6.2) | **415 px**, measured | Different — see below |
| **Main window minimum height** | 240 px (§9.6.2) | **285 px**, measured | Different — see below |
| **Compact mode, in and out** | Double-click the medallion, or `Ctrl+Shift+M` | `Ctrl+Shift+M` and `Esc` only | *Reduction* — see below |
| **The user's guide** | One document | **Forked** — same receiver half, rewritten window half | Different — see below |
| **Multiple receivers (P2-1)** | Not built | Not built | Same |

---

## The reductions, in full

These are the ones worth reading before deciding whether this port suits you.

### There is no high-contrast theme

WinZ3805A resolves its high-contrast tokens to the colours **you** chose in Windows. No desktop
this port targets offers an equivalent contract, and the alternative — a hand-authored set of
colours we picked — is a different service wearing the same name. For someone who configured a
specific scheme because of a specific impairment, "we chose good colours" is not a weaker version
of "we use yours".

Shipping it would have been worse than not, because a menu entry reading *High contrast* is a claim
you have no reason to doubt until it fails you. So there is Light and Dark, and this sentence.

Everything else in §9.12's accessibility criteria is unchanged: severity is always colour **and**
shape **and** text, every text token clears 4.5:1 on every surface it is drawn on, the sky plot is
reachable entirely from the keyboard, and its tables carry the same data at a 40 px row height.

**What it withdraws from §13**, precisely, so the table can be read against this port:

| Row | Effect |
|---|---|
| **A11Y-8** — "high contrast is a first-class theme" | Withdrawn entirely. There is no such theme to be first-class. |
| **A11Y-4** — contrast floors in Light, Dark *and HighContrast* | The Light and Dark half stands and is gated at 4.5:1, which is the stricter floor. The HighContrast half is withdrawn. |
| **P0-17** — token set with "Light, Dark, and HighContrast dictionaries" | The parity half stands and is gated — every token defined in every theme. The third dictionary is withdrawn. |

The `Test-HighContrastLegibility.ps1` gate retires with the theme it checked;
`Test-ThemeDictionaryParity.ps1`'s job survives as `test_every_theme_defines_every_token`, over
two themes rather than three.

### Nothing tells you when lock is lost

P1-9 is a desktop notification in WinZ3805A, on by default, and it exists — in §10.13's own words —
"precisely for the user who is *not* looking". This port ships no notification channel, and a
message shown only inside a window you are not looking at does not do that job. Rather than keep
the switch over a weaker promise, it is gone.

The window still shows the state at all times: the medallion's ring, the mode pill and the outputs
pill all change together. What is missing is the interruption.

### Closing the window stops the application

§10.3.1 hides the window to the notification area and keeps polling. With no notification area,
§10.3.1's own argument decides it: a hidden window with no icon "cannot be reached by any means the
user has", so hiding would not be an inconvenience but a loss of the application.

Close means close, and the poll stops. Leave the window open — minimised is fine — to keep the
trend filling.

**What D5 withdraws from §13**, so the table can be read against this port. All four are rows §13
lists as *shipped* in WinZ3805A:

| Row | Effect |
|---|---|
| **P1-9** — notification on holdover entry / lock loss | Not shipped. There is no notification channel, and a message inside a window nobody is looking at does not serve a requirement that exists for the user who is not looking. |
| **P1-10** — system tray icon reflecting lock state | Not shipped. |
| **P1-13** — taskbar overlay badge | Not shipped. Already dropped in the provisional answer for want of a cross-desktop equivalent. |
| **P1-14** — close-to-tray, start minimised, exit that does not need the tray | The last clause stands — the Settings *Exit* button — and is the only part that survives without a tray. |

**P1-11** — system accent opt-in — is also absent, for a different and unrelated reason: there is
nothing to read on these desktops, and §9.4.2's guarantee is that the brand accent is chosen for
hue separation from the severity colours. The Settings page says so on screen rather than offering
a switch that cannot work.

### Compact mode has two ways out, not three

§9.6.2 gives a double-click on the medallion alongside `Ctrl+Shift+M`. That gesture is **not built
here** — the two keys are the whole of it, and the guide says so rather than promising it. Nothing
is unreachable as a result: both keys are bound to the window rather than to a control, which is
what §9.7.5's amendment asks for so that a collapse cannot strand a keyboard user.

---

## The guide describes this application, not that one

`docs/how-to-use.md` was carried across verbatim and has been rewritten. Everything it says about
the **receiver** is word for word what it always said; everything it says about the **windows** is
new, because the windows are not the same ones.

It is the `F1` help as well as a document, which is what made this the one inherited file that had
to fork: its reader is looking at the window while it describes a window. `provenance.md` has the
full reasoning and the arrangement that replaces the lost comparability.

---

## A defect fixed here, and expected upstream

§9.4.4 gives the sequential ramp — signal strength on the sky plot — as **one** column of seven
values with no per-theme variant. A sequential ramp is read by lightness, so used verbatim on the
Dark card the encoding is exactly inverted: the strongest satellite draws the least visible mark
at 1.36:1 and the weakest draws the brightest.

This port derives a ramp for the dark surface instead. Figures in
[`palette-figures.md`](palette-figures.md).

**§9.4.4's *diverging* ramp had the same defect and a worse one**, found by applying the same
reasoning to the ramp next door: on Dark its ordering inverts too, and on **Light** three of its
five stops sit under §9.4.5's 3:1 floor on the theme it was drawn for. Those five are drawn as 1 px
chart lines, so the floor applies to every one of them
([#19](https://github.com/TGoodhew/smartclock-monitor/issues/19)).

**Neither is a difference between the repositories any more.** Both were filed upstream, both were
fixed there, and `build/palette/` is byte-identical again in both directions —
[#367](https://github.com/TGoodhew/WinZ3805A/issues/367) for the sequential ramp,
[#372](https://github.com/TGoodhew/WinZ3805A/pull/372) for the diverging one, whose derivation was
written upstream and carried here. The colours agree; what this section now records is where two
defects were found rather than where two repositories differ.

---

## §9.6.2's minimums are 415 by 285 here, not 380 by 240

§9.6.2 gives the main window a minimum of **380 by 240**. This port enforces **240 high and as wide
as the button row measures**, which is 415 px on the bundled typefaces.

**The 380 was never wrong; it was computed for a layout this port does not have.** That section's
"behaviour at minimum" collapses *the footer*, and in WinZ3805A the buttons are in one — so at
380 px there are no buttons on screen and 380 only ever had to hold the medallion and two lines of
text. This port has no footer, and §10.3's buttons sit in the header instead, where nothing
collapses them. Applied literally, the number left the row 35 px over its space and Qt clipped it:
`Connect…` lost its first character, `Retry now` its last, and the theme picker rendered as `Dar`
([#20](https://github.com/TGoodhew/smartclock-monitor/issues/20)).

That is the one outcome §9.6.2 explicitly forbids — *"**collapsed** — not clipped, not scrolled"* —
and a clipped button stays focusable and hit-testable while unreadable, which A11Y-1 and A11Y-6
forbid in turn. So the choice was to break the number or to break the rule the number serves.

**G1's box is what makes this safe.** Its acceptance criterion is a main window of *420 by 260 or
smaller* — an upper bound, because the window is meant to be left open on a second monitor all day.
415 fits inside it with 5 px to spare, so the floor moved without the goal moving. A gate asserts
that, and would fail if a wider typeface ever pushed the row past 420.

**Measured, not pinned.** The width comes from the controls' own reported sizes after the
stylesheet is applied, for the reason `_size_theme_picker` gives at length: a literal that is right
on one desktop is wrong on the next, and this repository has already been caught by that once — the
theme picker measured 28 px against 36 after polishing, and 18 against 75 on CI's Windows runner.
The two typefaces are bundled so the metrics are pinned rather than inherited, which is why 415 is
expected to hold everywhere rather than being this machine's number.

**The height moved for the same reason, and later** ([#21](https://github.com/TGoodhew/smartclock-monitor/issues/21)).
§9.6.2's 240 assumes the readout row is collapsed at the minimum, which it is here — but this port's
main window carries the header row that the 380 discussion above is about, and the collapsed layout
still measures 285. Below that there is nothing further the section permits to collapse, so the
alternative to a floor is the overlap the collapse exists to prevent: the state pills drawn over
each other and the medallion flattened out of shape.

**Compact is not affected and is not reached by dragging.** §9.6.2 is explicit — *"compact cannot be
entered by dragging, and that is the application's floor rather than the display's"* — so it remains
a state the user chooses with `Ctrl+Shift+M`, at §9.6.2's own `380 x 144`. That state has its own
defect, tracked separately as
[#30](https://github.com/TGoodhew/smartclock-monitor/issues/30).

**Both figures are measured at runtime, not written down.** 415 and 285 are what this machine's
bundled typefaces produce; the code asks the layout rather than carrying the numbers, so a desktop
whose metrics differ gets its own answer. They are quoted here to say how far from §9.6.2 the port
sits, not as constants to maintain.

**The specification is not edited.** [`requirements.md`](requirements.md) stays byte-identical to
WinZ3805A's copy, as [`provenance.md`](provenance.md) requires; this document is the authority for
the difference. §9.6.2's 380 by 240 is therefore knowingly stale for this port, and deliberately so.

---

## The additions

### A second receiver family, and a seam that is actually exercised

WinZ3805A's driver model is designed for more than one family and ships with one. Here there are
two: the SmartClock and any **NMEA 0183 talker**, the latter being the opposite shape at every
point the contract has an opinion — broadcast rather than query/response, an empty allowlist because
it is never written to, recognised by what it said before anything was asked.

That is not a feature so much as a proof: a contract satisfied by one implementation is a contract
nobody has tested. Registering the second found four defects in the first — see
[`driver-contract.md`](driver-contract.md).

### Pages ask for a capability, not a mnemonic

WinZ3805A's pages name SCPI mnemonics and gate on them (`Views/Capability.cs`, #304). The gate is
the same here, and it does the same job — §9.11's *disabled and explained*. What is added is that a
page names **what it wants done** and the connected family answers with its own command or with
nothing, so no page holds one family's spelling.

The old shape worked, and that was the problem: `driver.supports(catalog.RUN_SELF_TEST)` hands the
SmartClock's command object to whichever driver is connected, and reads as decoupled only because
the other one answers `False`. `tests/test_layering.py` now forbids a view importing the command
catalog at all.

### Three platforms

The whole reason the repository exists. WinUI 3 is Windows-only by definition.

---

## What is deliberately identical

Listed because sameness here is load-bearing, not incidental.

- **The §8.4 exclusion list.** Non-negotiable, synchronised in both directions, and the one thing
  on this page that may never diverge. A receiver bricked by one of those commands is bricked
  either way. See D6.
- **The specification.** Byte-exact, unedited, and describing a WinUI 3 application shipped to the
  Microsoft Store — deliberately, so the two repositories stay comparable.
- **The captured fixtures**, to the byte, line endings included.
- **The colour derivation** in `build/palette/`, which runs unchanged and is excluded from this
  project's linting so the two copies stay identical.
- **The command catalog's shape**: an allowlist, checked at the point of send, with the exclusions
  absent as data rather than present with a flag.
- **Cascadia Mono** for every string the receiver emits, which is the half of §9.5's typographic
  split that carries the meaning.

---

## What the #22 audit found

Run 3 Sep 2026, across three axes: the application, the repository's documentation, and the CI
gates. Its output is this section, [`ci-gate-map.md`](ci-gate-map.md), and the issues named below —
**not a list in a closed issue**, which is the form an audit takes when it is worth doing once and
worthless afterwards.

### The gates

Twelve `Test-*.ps1` gates upstream. Eight have a counterpart here, one is correctly not applicable
(D3, no high-contrast theme), and three enforced nothing here — document cross-references, the
focus visual's contrast, and page teardown — and
[#41](https://github.com/TGoodhew/smartclock-monitor/issues/41) closed all three: two as gates, the
third as an assertion that the rule does not apply under Qt. One more, guide coverage, exists but
only on an unpushed branch. The full mapping, in both directions, is in
[`ci-gate-map.md`](ci-gate-map.md).

### The requirements table

`tests/test_requirements_coverage.py` came from #14 and walked **P0 only** — it stopped at the
`### P1` heading. The tier below was unwatched, and of fourteen P1 rows exactly two were named by a
test, while most of the features are built, tested and shipped. So "no test names it" carried no
information at P1, and the four rows D5 removed were indistinguishable from four nobody had reached.

The gate now walks P1 as well. Each row is either named by the test that covers it, or listed in
`NOT_SHIPPED` with the decision that removed it — and a third test refuses an exemption that cites
no document. A test asserting a feature is *absent* counts as covering it, which is what gates a
divergence rather than contradicting one.

`P1-12` gained an actual assertion in the process: A11Y-11 wants a non-spatial alternate to the sky
plot, this port pairs the plot with a table, and nothing had ever checked that the table was there.

### The documentation

Present upstream and absent here, with what each is worth:

| | |
|---|---|
| `THIRD-PARTY-NOTICES.md` | **A licence obligation, not a preference.** This port bundles two typefaces and pulls five dependencies where the original ships three references. [#40](https://github.com/TGoodhew/smartclock-monitor/issues/40) |
| `docs/tutorial-nmea-driver.md` | Exists only in the repository that does **not** ship an NMEA driver. This one does |
| `docs/manual-qa.md` | `test_requirements_coverage.py` keeps a `MANUAL` dict of criteria needing a person, a desktop or hardware. That list is the script this document would be |
| `docs/lady-heather-comparison.md`, `docs/privacy.md`, `docs/index.md`, `docs/_config.yml` | Positioning and the GitHub Pages site. Judged upstream-only unless this port publishes a site |
| `docs/store-listing.md` | Correctly absent — D2, no Microsoft Store |
| `docs/review/` | 320 files of per-change review notes. Not a document to port |

Present here and not upstream — `divergences.md`, `driver-contract.md`, `platform-decisions.md`,
`provenance.md`, `palette-figures.md`, `kickoff-prompt.md`, `ci-gate-map.md` — all deliberate, and
all of them exist because this port owes an answer the inherited documents do not give.

### The application

No functional gap found. Every P1 feature §13 lists is either built here or recorded above as a
decision, and §10's pages are all present — Time, Satellites, Position, Timing, Status registers,
Diagnostics, Holdover, Console, Settings. The layout differences are the ones already recorded in
this document and in `provenance.md`; the behavioural ones are D2 through D5.

That is a narrower claim than it sounds. It says every requirement is accounted for, not that every
one is correctly implemented — #20, #21, #29 and #30 were all found by *using* the application on
real hardware in the same week, and none of them would have been caught by reading §13.

---

## What is not decided by this document

The Microsoft Store (G5) is not a goal here and remains a live goal of WinZ3805A, which ships it
today (D2). Packaging for the three platforms is Phase 8 work and nothing above depends on it.
