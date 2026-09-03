# Provenance, and what must not drift

This repository is a Python and Qt reimplementation of
[WinZ3805A](https://github.com/TGoodhew/WinZ3805A). Four things were copied from it rather
than written here, and two of those can go wrong silently if the two repositories diverge.

**Source commit:** `73d5962a0ae43e7f9a2c0963d7edd3b109c32787` (`73d5962`, 31 Aug 2026).

---

## What was copied

| Path here | Path there | State |
|---|---|---|
| `docs/requirements.md` | `docs/requirements.md` | **Byte-exact.** Marked `-text` in `.gitattributes` so no checkout converts its line endings — the file's byte count, hashes and column positions are referenced elsewhere and must stay stable. |
| `docs/how-to-use.md` and `docs/images/how-to-use/` | same | **Forked.** It was carried verbatim and is not any more — see *The one document that had to fork*, below. Do not diff the two expecting them to agree. |
| `docs/adding-a-receiver.md` | same | Verbatim. Describes the C# driver model. Kept because the *architecture* it teaches is what this port reproduces, not because the code samples compile here. **`docs/driver-contract.md` is this port's member-by-member mapping** — written here rather than by editing the inherited file, which would fork it. |
| `tests/fixtures/` | `tests/WinZ3805A.Tests/Fixtures/` | Verbatim, including `capture-log.md`. Marked `-text`: these are device output and their exact bytes, line endings included, are the point. |
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

One state is still missing: a failing health monitor. If a future sitting captures it, **it
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
