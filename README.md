# smartclock-monitor

A cross-platform monitor and controller for HP/Symmetricom **SmartClock** GPS-disciplined
oscillators — the Z3805A and its siblings (Z3801A, 58503A/B, 59551A, Z3816A) — over RS-232.
Python 3 and Qt, so it runs on Linux, Windows and macOS.

> **Status: early. Nothing works yet.**
> This repository currently holds the specification, the parser fixtures, the colour
> derivation and the project scaffolding. The application is being built from them.
> See [the port plan](https://github.com/TGoodhew/WinZ3805A/blob/main/docs/porting-to-python-qt.md)
> for what is being built and in what order.

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
| [`build/palette/`](build/palette/) | verbatim, already Python | The §9.4.4 colour derivation and its self-check. Needs no porting at all. |
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

## Building

Nothing to build yet. The scaffolding runs:

```bash
python -m venv .venv && . .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
ruff check . && mypy && pytest
python build/palette/validate.py
```

## Licence

MIT, as WinZ3805A is. See [LICENSE](LICENSE).

`docs/` and `tests/fixtures/` are reproduced from WinZ3805A under the same licence.
Cascadia Mono, if bundled later, is under the SIL Open Font License.
