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
| `docs/how-to-use.md` and `docs/images/how-to-use/` | same | Verbatim. The guide is correct about *what the application does*; every screenshot in it is a Windows capture and is wrong for this port until retaken. |
| `docs/adding-a-receiver.md` | same | Verbatim. Describes the C# driver model. Kept because the *architecture* it teaches is what this port reproduces, not because the code samples compile here. **`docs/driver-contract.md` is this port's member-by-member mapping** — written here rather than by editing the inherited file, which would fork it. |
| `tests/fixtures/` | `tests/WinZ3805A.Tests/Fixtures/` | Verbatim, including `capture-log.md`. Marked `-text`: these are device output and their exact bytes, line endings included, are the point. |
| `build/palette/` | same | Verbatim, and already Python. Runs unchanged — **plus one file added here**, `sequential.py`. See below. |

Nothing else was taken. No C# was translated mechanically; the source tree here is new.

## The one file added to a carried directory

`build/palette/sequential.py`. Every file copied from WinZ3805A is still byte-identical; the
*directory* is not, because this one is new.

It derives §9.4.4's sequential ramp for a dark surface, which the specification does not provide —
it gives one column of seven values and no per-theme variant, and a sequential ramp is read by
lightness, so used verbatim on the Dark card the encoding is exactly inverted. Issue
[#9](https://github.com/TGoodhew/smartclock-monitor/issues/9) here.

**The same defect is expected upstream**, where the same values are resolved from one dictionary
for both themes, and it is filed as
[TGoodhew/WinZ3805A#1](https://github.com/TGoodhew/WinZ3805A/issues/1). Copying this file there
restores the directory to identical. It is written in that repository's style, not this one's, so
that the copy is a copy.

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
