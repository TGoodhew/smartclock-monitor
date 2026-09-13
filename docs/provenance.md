# Provenance, and what must not drift

This repository is a Python and Qt reimplementation of
[WinZ3805A](https://github.com/TGoodhew/WinZ3805A). Four things were copied from it rather
than written here, and two of those can go wrong silently if the two repositories diverge.

**Source commit:** `d892779` (13 Sep 2026, WinZ3805A 1.2.0). Re-pinned from `73d5962` (31 Aug) on
13 Sep 2026 — 200 commits of drift, of which fourteen touched the specification. See *What the
re-pin brought across*, below.

---

## What was copied

| Path here | Path there | State |
|---|---|---|
| `docs/requirements.md` | `docs/requirements.md` | **Byte-exact.** Marked `-text` in `.gitattributes` so no checkout converts its line endings — the file's byte count, hashes and column positions are referenced elsewhere and must stay stable. |
| `docs/how-to-use.md` and `docs/images/how-to-use/` | same | **Forked.** It was carried verbatim and is not any more — see *The one document that had to fork*, below. Do not diff the two expecting them to agree. |
| `docs/adding-a-receiver.md` | same | Verbatim, refreshed to `d892779` on 13 Sep 2026. Describes the C# driver model. Kept because the *architecture* it teaches is what this port reproduces, not because the code samples compile here. **`docs/driver-contract.md` is this port's member-by-member mapping** — written here rather than by editing the inherited file, which would fork it, and it now carries six members the walkthrough does not mention at all. |
| `tests/fixtures/` | `tests/WinZ3805A.Tests/Fixtures/` | Verbatim, including `capture-log.md`. Marked `-text`: these are device output and their exact bytes, line endings included, are the point. |
| `tests/fixtures/uccm/` | `tests/WinZ3805A.Tests/Uccm/Captures/` | **Verbatim, all seven sittings and their notes**, carried 13 Sep 2026 for D7 — every blob hash matches. Nobody here has a UCCM, so this corpus is the *only* evidence the driver in Phase 5 is written against. |
| `tests/fixtures/nmea/` | `tests/WinZ3805A.Tests/Nmea/Captures/` | **Verbatim, all ten sittings and their notes** (#56), carried 13 Sep 2026 — every blob hash matches. Two captures taken on this bench sit beside them; see below. |
| `build/palette/` | same | **Byte-identical, directory included.** Already Python, runs unchanged. Two files were added since the fork — `sequential.py` here, `diverging.py` upstream — and both have been carried the other way, so the copies agree again. See below. |

Nothing else was taken. No C# was translated mechanically; the source tree here is new.

Of the five, **three are still verbatim and one is forked**; the fifth, `build/palette/`, is
byte-identical again in both directions. Both departures are written down below rather than
left to a diff.

## The one document that had to fork

`docs/how-to-use.md`, and the pictures in `docs/images/how-to-use/` with it.

It was carried across on the reasoning that the guide is "correct about *what the application
does*, and only its screenshots are wrong". That was true when it was written and is not now.
**D3, D4 and D5 changed what the application does**, and the layout was never the same in the
first place: this port's main window has no clock line, no time-zone flyout and no footer; its
details window has a command bar rather than a title bar with a status pill; its navigation pane is
in a different order, which moves every accelerator and puts Settings on `Ctrl+9`; §10.5 has one
table where that one has two; and the Settings page offers three switches where that one offers
six, of which three describe a notification area this port does not ship.

**It is also the application's `F1` help.** That is what settled it. Every other inherited document
is read beside the code by somebody who can hold two repositories in mind; this one is read by a
user who is looking at the window while it describes a different window. A wrong sentence here
costs more than a wrong sentence anywhere else in the repository, and the comparability the other
carried files buy is worth nothing to that reader.

So the two guides now diverge, deliberately and permanently. What survives word for word is
everything about the **receiver** rather than the application — the two holdover thresholds and why
only one is settable, the unverified power-up time, the week rollover, the signal-strength scales —
because those paragraphs are right in both repositories and their value is that somebody worked out
how to say them once. What was rewritten is everything about the **windows**.

The pictures are rendered by `tools/capture_guide_images.py` from the captured fixtures, and
`tests/test_guide.py` keeps the guide and the application in step: every picture named exists, no
picture exists that is no longer named, every picture carries alt text, and every page the details
window has is written about. That gate is what replaces the comparability that was lost.

**A fix to the receiver half is still worth carrying both ways by hand.** Nothing enforces that,
and nothing can now; this paragraph is the whole of the arrangement.

## `build/palette/` — identical again, and now shared in both directions

**Every file is byte-identical to WinZ3805A's copy, the directory included.** That was not true
between 31 Aug and today, and the two files that made it untrue are the reason this section exists.

`sequential.py` was written **here**, where the defect was found: §9.4.4 gives one column of seven
values and no per-theme variant, and a sequential ramp is read by lightness, so used verbatim on the
Dark card the encoding is exactly inverted
([#9](https://github.com/TGoodhew/smartclock-monitor/issues/9) here,
[TGoodhew/WinZ3805A#367](https://github.com/TGoodhew/WinZ3805A/issues/367) there). It was written in
that repository's style rather than this one's precisely so the copy back would be a copy, and it
has since been copied back.

`diverging.py` came the other way. The same reasoning applied to §9.4.4's *other* ramp turned up a
second and worse defect — on Dark the ordering inverts as the sequential one's did, and on **Light**
three of the five stops are under §9.4.5's 3:1 floor on the theme the ramp was drawn for. Derived
upstream in [TGoodhew/WinZ3805A#372](https://github.com/TGoodhew/WinZ3805A/pull/372), filed here as
[#19](https://github.com/TGoodhew/smartclock-monitor/issues/19), carried across verbatim with the
`sequential.py` and `validate.py` changes that went with it.

So the direction of travel is now both ways, and the property to protect is unchanged: **the two
copies being identical is what lets either repository trust the other's colours.** A fix to any file
in this directory belongs in both, byte for byte, in whichever repository finds it.

**One constant in it is not actually shared**, and both files say so in place: `SEMANTIC` is
WinZ3805A's §9.4.3, whose accent and info are the brand teal where this port's are blue. The
clearance figures those scripts print are therefore measured against the wrong palette when run
here. Measured against this port's own colours the ramps clear by 11.2 ΔE₀₀ on Light and 7.5 on
Dark, well above the 5.0 asserted — recorded, with the command to reproduce it, in
[`palette-figures.md`](palette-figures.md). Correcting the constant would fork the directory to fix
a comment, so it stays.

Figures in [`palette-figures.md`](palette-figures.md); `validate.py` reproduces them and prints
`!!` beside any it cannot.

## What the re-pin brought across

`docs/requirements.md` sat at `73d5962` for a fortnight while WinZ3805A moved 200 commits. It is
byte-exact again — `git hash-object` gives `6ed0af4f` in both repositories — and the refresh brought
five amendments worth naming, because three of them describe behaviour this port does not have:

| Amended | What changed | Where this port stands |
|---|---|---|
| **§9.4.4** | Both data ramps belong to a **surface**, not to the application. Closes WinZ3805A#367 and #372. | **Already matches.** `themes/tokens.py` derives both per theme; the sequential derivation went *upstream* from here. |
| **§7.1 / §10.12** | The auto-detect union is **eleven** combinations, the eleventh being 57600-8-N-1 for a UCCM. | Walks **ten**. The eleventh arrives with the UCCM driver (D7). |
| **§7.2** | A broadcast family **may be written to**, under three gates, replacing the flat prohibition. | **Undecided** — [#64](https://github.com/TGoodhew/smartclock-monitor/issues/64). The driver here still says "never written to". |
| **§8.1 / §8.4** | Correction: the exclusion predicate **has a production caller** upstream, and logs. | Still true here that it has none, *because* there is no send path. Follows #64. |
| **§11** | A reading a family can never supply is **declined outright** rather than dashed; a navigation destination it cannot fill is **dimmed rather than disabled**. | Not built — [#60](https://github.com/TGoodhew/smartclock-monitor/issues/60), whose open design question this settles. |

Every one of the 73 distinct § references in this tree was re-checked against the new numbering and
all 73 resolve; §7.1 and §7.2 are the pair to watch, because upstream's own amendment notes it cited
the scope note as §7.1 throughout and it is in §7.2.

**The specification is the authority, so where the table above says "not built", the specification is
right and this port is behind** — not the other way round. `divergences.md` records each as a gap
with an issue, rather than as a decision, until it is one.

---

## The talker corpus, and why it came across whole

`tests/fixtures/nmea/` is ten sittings from two receivers — a VK-162 (u-blox 7) and an RCmall
forM8N (u-blox M8) — captured in WinZ3805A between 7 and 11 September 2026. Until they arrived
here, **everything this port's NMEA driver had ever been tested against came from
`tools/nmea_simulator.py`**, which can only produce what we already believed a talker sends.

The rule for the status screens applies unchanged: *a capture belongs in both repositories.* It
applies more cheaply here — NMEA is text, the files are a few megabytes, and replaying one needs
no hardware — and it applies more urgently, because four of the ten record a receiver doing
something no one had predicted: sending `GNS` and never `GGA`, advertising a constellation it
cannot see, losing a fix and regaining it, and crossing UTC midnight.

**Three captures were taken here**, with `tools/capture_talker.py` — the port of upstream's
`Capture-Talker.ps1` — from the same two module families on this bench, reached through
`usbipd`. They are not carried from anywhere and belong upstream if that repository wants them.
Their value is the cross-check: the same silicon, a different harness, five days later.

**One of the three is unlike everything else in this repository: it contains something this
application sent.** `form8n-time-poll.nmea` is six `$PUBX,04` polls and six replies, and every
other capture here — in every corpus — is a receiver talking unprompted. D8 traded away the
structural guarantee that made that true, and that file is the evidence for the reading it was
traded for: GPS − UTC, answered as **18** by both bench modules, a firmware generation apart, in
the same second.

The replay is `tests/test_nmea_captures.py`, and **three of its assertions are expected failures
by design** — the fixture assertions for #57 and #58, written before the parsing that will fix
them. They are `strict`, so the markers cannot outlive the defects.

---

## The UCCM corpus, which is the whole of the evidence

`tests/fixtures/uccm/` is seven sittings with a Trimble UCCM-P, taken in WinZ3805A between 10 and
13 September 2026. **D7 takes this family without a receiver to test it against**, so unlike every
other corpus here these captures are not a cross-check on hardware we have — they *are* the
hardware, as far as this repository is concerned.

That makes the rule stricter rather than looser. Every assertion the UCCM driver makes must trace
to a line in this directory or it is not made, and the two states upstream's driver cannot tell
apart stay untold-apart here — reproducing a known limitation is correct where quietly resolving
it would be the guess D7 exists to prevent.

**The format is not the NMEA corpus's.** These are annotated transcripts rather than raw byte
streams: a header, then one block per command with the reply as a hex dump *and* as decoded lines.
The hex is what makes them usable as a byte-level oracle — `frames-13sep2026.txt` is 150 binary
time-code frames written one per line as hex, which is what `transport/frames.py` is tested on.

---

---

## The two that must not drift

### 1. The §8.4 exclusion list

Two implementations of the safety model is two places for it to go wrong, and a receiver
bricked by this one is bricked either way.

When either repository changes its exclusion list, **diff both**. The mechanism that makes
this checkable rather than a matter of memory is the gate: over there,
`build/Test-NoBlockedCommands.ps1` reads its tokens out of the single file that holds them
and scans the tree, so the list exists in exactly one place. Reproduce that here as soon as
`smartclock_device/commands/blocked.py` exists — it is Phase 3 of the port plan, and it is
the highest-value gate in the set.

Until then, this file is the only thing saying so.

### 2. The captured fixtures

The ten status screens in `tests/fixtures/` were captured from real hardware over two bench
sittings, and the states they record — power-up, acquisition, holdover, recovery — happen
only while the receiver is being moved or restarted. They cost a sitting to obtain and
cannot be regenerated on demand.

One state is still missing and is now recorded as **not capturable**: a failing health monitor.
The line reads `[ OK ]` because the receiver is healthy, and nothing short of the hardware actually
failing will change that — every other state in the corpus was reached by *doing* something, and
this one has no such action behind it. **We cannot simulate dying hardware**, and a synthetic
eleventh screen filed beside ten that are device output would quietly falsify the one claim this
directory makes about itself.

If a receiver ever does start failing its own self-test, that is the moment to capture — and **it
belongs in both repositories.** `captured/capture-log.md` is the shared record; keep it that
way rather than letting each repository grow its own.

## Naming

The port plan written over there uses `winz3805a_device` and `winz3805a` as the package
names. This repository uses **`smartclock_device`** and **`smartclock_monitor`**, because
carrying `Win` into a cross-platform port makes no sense and the application has always
served the whole SmartClock family rather than one model. The mapping is otherwise exact:
wherever the plan says `winz3805a_device`, read `smartclock_device`.

"SmartClock" is HP's own terminology, not a leftover — the specification uses *SmartClock
family*, *SmartClock firmware* and *SmartClock oscillator learning* throughout §7, §10 and
§11, and Appendix B says explicitly that these are not to be renamed.

## Reading the specification here

`docs/requirements.md` is carried across unedited, which means **it still describes a WinUI 3
application shipped to the Microsoft Store**. That is deliberate: editing it to match this
port would fork the specification on day one and lose the ability to tell the two apart.

Instead:

- Part 7 of the port plan names every place the specification is wrong for Linux — Mica, high
  contrast, MSIX, Segoe UI Variable, the taskbar badge.
- Part 12 lists the decisions this repository owes its own answers to. **Those answers belong
  in a document here**, not in edits to the inherited one, and not in a pull request
  description. Write them down before the code assumes them.

Until that document exists, `requirements.md` is authoritative on the receiver, the safety
model and the design intent, and silent on this port's platform.
