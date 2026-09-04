# Third-party notices

smartclock-monitor is distributed under the MIT licence (see `LICENSE`). It depends on, and in some
channels redistributes, the components below, each under its own terms.

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

## Two obligations that are not met yet, and are #27's to close

**Qt and PySide6 ship no licence text.** Checked against the installed packages: there is no file
with `licen` in its name anywhere under `PySide6/`, and the distributions list none. So a
PyInstaller bundle today redistributes several hundred megabytes of LGPL-3.0 code **without the
licence that permits it**. Whoever builds a distributable has to place the LGPL-3.0 text in it; a
notices file that only names the licence does not discharge that.

**pyserial ships no licence file either**, and its BSD-3-Clause terms require the copyright notice
and disclaimer to accompany a binary redistribution. Same conclusion, smaller scale.

**The LGPL also asks for more than a text.** Distributing Qt in a bundle carries a relinking
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

`qasync`, `pyserial-asyncio`, `markdown-it-py` and `mdurl` each carry their licence inside their
installed distribution, so a bundle built from a working environment picks them up. `pyserial`,
PySide6 and Qt do not — see above.

## Keeping this file true

`tests/test_third_party_notices.py` asserts that every runtime dependency declared in
`pyproject.toml` is named here. A dependency added later and not mentioned is the case this file
would otherwise fail at silently, and it is the way a notices file usually goes wrong: not by being
written badly, but by not being updated when the thing it describes changes.

Versions above are those the file was written against. They are deliberately not asserted by the
gate — a version bump is not a licence change, and a test that failed on every upgrade would be
edited rather than read.
