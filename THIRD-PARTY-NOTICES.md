# Third-party notices

smartclock-monitor is distributed under the MIT licence (see `LICENSE`). It depends on, and in some
channels redistributes, the components below.

> **Every component listed here remains the property of its own authors and is licensed to you
> under the terms of its original provider, not under this project's.** Nothing in this file, and
> nothing about being carried inside a smartclock-monitor wheel or bundle, changes, relaxes or
> replaces those terms. Where a component's licence and this project's disagree, the component's
> governs that component. The MIT licence in `LICENSE` covers the code written for this project
> and nothing else.
>
> Each licence text is reproduced or carried alongside the software it covers, and the rights it
> grants — including any right to the corresponding source, or to relink against your own build of
> a library — are granted by that provider and are exercised against them, not against this
> project.

**Scope: what actually ships, per channel.** The three differ, and the obligations differ with them.

| Channel | What it carries |
|---|---|
| a checkout, or `pip install` | The application only. Dependencies are *declared* and fetched by pip, which is not redistribution — **except the two fonts**, which are files in the source tree |
| the wheel | The application and both fonts, with each font's licence beside it. Verified: `smartclock_monitor/themes/fonts/NotoSans-LICENSE.txt` and `CascadiaMono-LICENSE.txt` are in the built wheel |
| the PyInstaller bundle | **Everything below.** Qt, PySide6, every dependency and both fonts, as one directory. This is the channel the notices exist for |

Packages used only to build or test — pytest, mypy, ruff, numpy, PyInstaller — ship nothing and are
not the subject of a notice.

---

## Components

| Component | Version | Licence | Redistributed |
|---|---|---|---|
| **Qt** (via PySide6) | 6.11.2 | LGPL-3.0-only, or GPL-2.0-only / GPL-3.0-only | In the PyInstaller bundle: the Qt shared libraries and plugins, which are the bulk of it |
| **PySide6**, with `PySide6_Essentials`, `PySide6_Addons` and `shiboken6` | 6.11.2 | LGPL-3.0-only, or GPL-2.0-only / GPL-3.0-only | In the PyInstaller bundle |
| **qasync** | 0.28.0 | BSD-2-Clause | In the PyInstaller bundle |
| **pyserial** | 3.5 | BSD-3-Clause | In the PyInstaller bundle |
| **pyserial-asyncio** | 0.6 | BSD-3-Clause | In the PyInstaller bundle |
| **markdown-it-py** | 4.2.0 | MIT | In the PyInstaller bundle |
| **mdurl** (via markdown-it-py) | 0.1.2 | MIT | In the PyInstaller bundle |
| **Noto Sans** | — | SIL Open Font License 1.1 | **Every channel.** `themes/fonts/NotoSans-Regular.ttf`, `NotoSans-SemiBold.ttf`, licence beside them |
| **Cascadia Mono** | — | SIL Open Font License 1.1 | **Every channel.** `themes/fonts/CascadiaMono-Regular.ttf`, licence beside it |

The fonts are the reason this file matters even before anything is packaged: the OFL requires its
text to travel with the font, and they are in the source tree and in the wheel today. Both licence
texts are already shipped beside the files they cover, which is what the OFL asks for.

---

## What is met, and what is still #27's to close

**~~Qt, PySide6 and pyserial ship no licence text.~~ Carried here instead.** Checked against the
installed packages: there is no file with `licen` in its name anywhere under `PySide6/`, and
neither its distributions nor pyserial's list one. Rather than leave a bundle redistributing
several hundred megabytes of LGPL-3.0 code without the licence permitting it, the texts are in
[`licenses/`](licenses/) and ship with every artefact. **This part is now met.**

**What is still open is the LGPL's other requirement, and it asks for more than a text.** Distributing Qt in a bundle carries a relinking
obligation — the recipient must be able to replace the Qt libraries with their own build. A
PyInstaller directory happens to satisfy this reasonably well, because the `.so` files sit beside
the executable and can be swapped, and that is worth stating in the packaging rather than assumed.
Flatpak, where Qt may come from the runtime instead, is a different answer again.

None of this is a problem with what exists today: the only artefacts published so far are a git tag
and a source release. It becomes real with the first binary.

---

## Licence texts

The SIL Open Font License 1.1 covering both fonts is reproduced in full beside them, in
[`src/smartclock_monitor/themes/fonts/`](src/smartclock_monitor/themes/fonts/).

`qasync`, `pyserial-asyncio`, `markdown-it-py` and `mdurl` each carry a licence inside their
installed distribution, and the PyInstaller spec now collects it for each of them with
`copy_metadata`.

<!-- Corrected. This paragraph said a bundle "picks them up" from a working environment. It does
     not: PyInstaller collects a distribution's .dist-info only when asked, which is what
     copy_metadata is for, and the spec asked only for smartclock-monitor's own. The four licences
     were named in this file and shipped in nothing. -->

**Qt, PySide6 and pyserial ship no licence text at all**, so theirs are carried in this repository
under [`licenses/`](licenses/) and go into the wheel and the bundle:

| File | Covers | Source |
|---|---|---|
| `licenses/LGPL-3.0.txt` | Qt, PySide6, shiboken6 | gnu.org |
| `licenses/GPL-3.0.txt` | the above — LGPL-3.0 incorporates GPL-3.0 by reference and is not complete without it | gnu.org |
| `licenses/pyserial-LICENSE.txt` | pyserial | the pyserial repository, with its `(C) 2001-2020 Chris Liechti` notice intact |

## Keeping this file true

`tests/test_third_party_notices.py` asserts that every runtime dependency declared in
`pyproject.toml` is named here. A dependency added later and not mentioned is the case this file
would otherwise fail at silently, and it is the way a notices file usually goes wrong: not by being
written badly, but by not being updated when the thing it describes changes.

Versions above are those the file was written against. They are deliberately not asserted by the
gate — a version bump is not a licence change, and a test that failed on every upgrade would be
edited rather than read.
