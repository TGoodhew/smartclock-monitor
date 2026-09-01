# smartclock-monitor

A cross-platform monitor and controller for HP/Symmetricom **SmartClock** GPS-disciplined
oscillators — the Z3805A and its siblings (Z3801A, 58503A/B, 59551A, Z3816A) — over RS-232.
Python 3 and Qt, so it runs on Linux, Windows and macOS.

> **Status: it works against real hardware.** Phases 1 to 7 of
> [the port plan](https://github.com/TGoodhew/WinZ3805A/blob/main/docs/porting-to-python-qt.md)
> are in — the models, the status-screen parser, the line protocol, the §8.4 safety model, the
> command allowlist, the session and poll loop, the design tokens, the custom widgets, and every
> one of §10's twelve surfaces — the main window, the ten Details pages, and the connection
> dialog.
>
> **You can look at it without a receiver** — `smartclock-monitor --demo` replays the ten
> captured status screens through the real protocol and poll loop. See *Running it* below.
>
> **Two receiver families**, not one: the SmartClock, and any NMEA 0183 talker. The second is
> there because a driver seam with one implementation is a seam nobody has tested — see
> [`docs/driver-contract.md`](docs/driver-contract.md).
>
> **Phase 8 is mostly decided rather than pending.** Its shell-integration half — tray icon,
> notifications, taskbar badge — is settled as *not shipped* on these desktops
> ([D5](docs/platform-decisions.md)), and the window closing behaviour follows from that. What
> remains of it is the guide: every screenshot in
> [`docs/how-to-use.md`](docs/how-to-use.md) is a Windows capture and has still to be retaken.
>
> **If you know the Windows application**, [`docs/divergences.md`](docs/divergences.md) is the
> page to read: what is different here, what is a reduction, and what is deliberately identical.

---

## What this is, and what it came from

This is a **reimplementation in Python and Qt of
[WinZ3805A](https://github.com/TGoodhew/WinZ3805A)**, a WinUI 3 application for the same
hardware, by the same author. It is a sibling rather than a fork: no code is shared, because
none of it can be — WinUI 3 is Windows-only by definition, which is why this repository
exists at all.

What *is* shared is everything that was never Windows-specific in the first place:

| Carried across | From | Why it ports |
|---|---|---|
| [`docs/requirements.md`](docs/requirements.md) | verbatim | The specification. Receiver behaviour, the safety model and the design system, almost all of it platform-neutral in substance even where it is Windows-specific in wording. |
| [`tests/fixtures/`](tests/fixtures/) | verbatim | Ten captured status screens from real hardware. They are the parser's pass/fail oracle. |
| [`build/palette/`](build/palette/) | verbatim, already Python | The §9.4.4 colour derivation and its self-check. Needs no porting at all. One file is **added** here — `sequential.py`, deriving the signal-strength ramp for a dark surface, which the specification does not provide. Figures in [`docs/palette-figures.md`](docs/palette-figures.md); filed upstream as [WinZ3805A#367](https://github.com/TGoodhew/WinZ3805A/issues/367). |
| [`docs/how-to-use.md`](docs/how-to-use.md) | verbatim | The user guide, which is also the application's F1 help. Its screenshots are Windows captures and must all be retaken. |

Taken from WinZ3805A at commit
[`73d5962`](https://github.com/TGoodhew/WinZ3805A/commit/73d5962a0ae43e7f9a2c0963d7edd3b109c32787).
[`docs/provenance.md`](docs/provenance.md) records what was copied and what has to stay in
step; read it before changing anything in the table above.

## Why not just run the Windows one under Wine

Because the interesting half of this application is a serial-port conversation with a piece
of laboratory equipment, and the useful place to have that conversation is often a Linux
machine sitting next to the equipment. The Windows application is finished and supported;
this one exists so the same receiver can be monitored from the same bench without a Windows
box on it.

## Safety

**§8's safety model is not optional, and it is not a matter of style.** The receiver accepts
commands that can render it unusable. The specification excludes them by making the command
catalog an **allowlist** (§8.1): the excluded commands are not entries with a warning flag,
they do not exist as data, and no free-text path can emit them. §8.4 says which and why.

Any port that expects to be pointed at real hardware inherits that design whole. If you fork
this, keep it.

## Running it

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

**Without hardware.** The ten captured status screens, replayed through the real line protocol,
session and poll loop — the same code path a receiver drives, with only the source of the bytes
changed. It walks power-up, acquisition, lock, survey, three depths of holdover and recovery, so
the whole state matrix goes past in a couple of minutes.

```bash
smartclock-monitor --demo
```

**With a receiver.** §7.1's line parameters are all settable, because the family is not consistent
about them: a Z3805A ships 9600-8-N-1 and a Z3801A leaves the factory at 19200-7-O-1.

```bash
smartclock-monitor --list-ports
smartclock-monitor --port /dev/ttyUSB0                       # Z3805A defaults
smartclock-monitor --port /dev/ttyUSB0 --baud 19200 --data-bits 7 --parity O
```

`--theme light|dark` picks the token set to start in; the window has a picker too.

**There is no high-contrast theme.** WinZ3805A resolves its high-contrast tokens to your own
Windows system colours; no desktop this port targets offers an equivalent contract, and rather than
assert colours of our own under that name there is none here. If you rely on a high-contrast
scheme, that is a real reduction against the Windows application — see
[`docs/divergences.md`](docs/divergences.md).

> **Linux serial access** is the first thing that will go wrong. Your user needs to be in the
> `dialout` group (`sudo usermod -aG dialout $USER`, then log out and back in). Under WSL, a USB
> adapter needs `usbipd attach` from an elevated Windows prompt before it appears at all — only
> real motherboard ports show up as `/dev/ttyS*` without it.

## Building

```bash
ruff check . && ruff format --check . && mypy && pytest
python build/palette/validate.py
```

The palette self-test **reports rather than exiting non-zero** — the failure marker `!!` in its
output is the gate, and CI greps for it. It reproduces the published figures for both ramps:
WinZ3805A #87's categorical derivation, and this port's own sequential one.

§13's priority table is walked by CI too. `tests/test_requirements_coverage.py` parses it out of
the specification and asks the suite to account for every P0 — each names the test that gates it,
or is listed with the reason it needs a person instead. An audit nobody re-runs is a snapshot;
this one fails when it stops being true.

## Adding another receiver

Every receiver-specific fact sits behind a driver, so a second family is a new file rather than a
scatter of conditionals.

- [`docs/adding-a-receiver.md`](docs/adding-a-receiver.md) is the walkthrough. It is carried over
  from WinZ3805A verbatim and is C# throughout — read it for the reasoning.
- [`docs/driver-contract.md`](docs/driver-contract.md) is this port's member-by-member mapping:
  what the Protocol looks like here, what is not built yet, and what the second family found in
  the first.

A page never names a command. It asks for a **capability** and the connected family answers with
its own command or with nothing, so adding a receiver does not touch a page —
`tests/test_layering.py` enforces that no view reaches the command catalog. The NMEA driver is the
worked example, and `tools/nmea_simulator.py` will drive one without hardware.

## Licence

MIT, as WinZ3805A is. See [LICENSE](LICENSE).

`docs/` and `tests/fixtures/` are reproduced from WinZ3805A under the same licence.

Type is **Noto Sans** for the interface and **Cascadia Mono** for every string the receiver emits —
§9.5's split is what tells "what the machine said" from "what the app says about it". Both are SIL
Open Font License; neither is bundled yet, so both fall back to whatever the desktop has.
