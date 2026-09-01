# Published palette figures

Numbers that colour decisions were taken on, written down so they can be re-checked rather than
re-argued. `build/palette/validate.py` reproduces every one of them and prints `!!` beside any it
cannot; CI greps for that marker, which is the gate.

The convention is WinZ3805A's, from #87: **publish the figures, then check the tool still produces
them.** A derivation nobody can reproduce is an assertion.

---

## §9.4.4's sequential ramp, on the Dark card

Issue [#9](https://github.com/TGoodhew/smartclock-monitor/issues/9), and
[TGoodhew/WinZ3805A#367](https://github.com/TGoodhew/WinZ3805A/issues/367) — the same values are
resolved from one dictionary there, so the same defect is expected.

§9.4.4 gives the ramp as **one** column of seven values, pale → dark teal, with no per-theme
variant. A sequential ramp is read by lightness, so which end recedes depends on the surface.

### The defect

| Step | Value | Contrast on the Dark card |
|---|---|---|
| 1 — weakest signal | `#DFF1F3` | 12.15 : 1 |
| 7 — strongest signal | `#08474D` | **1.13 : 1** |

The strongest satellite drew the least visible mark and the weakest drew the brightest. Exactly
inverted, on the theme that ships by default.

### Why reversing the same seven values is not enough

It was the first fix and it cures the inversion. It cannot cure the rest.

The specification ramp is not perceptually uniform. Its six adjacent steps measure:

```
10.7   8.6   5.1   9.1   17.1   12.2      ΔE₀₀, light end → dark end
```

— a **3.33-fold** spread between coarsest and finest. Reversing cannot change that ratio, because
max/min does not care about order. What it changes is *where the coarse steps land*: on Light they
sit at the dark, strong-signal end, and reversed onto Dark they sit at the weak end. The ramp then
spends its resolution where the data matters least and leaves the strong end its finest steps —
and telling 45 dB-Hz from 50 is the job.

The reversal also carries a collision the specification did not intend for this surface. Spec step
4 is `#3FB8C4`, which **is** Dark's info colour — 0.00 ΔE₀₀. A mid-strength satellite drew exactly
the info indicator.

### The derived ramp

`build/palette/sequential.py`. Hue held at the specification's 208.5°, chroma following the spec's
own curve — it peaks mid-ramp at C 33.2 and desaturates toward white, which is what makes it read
as one family — and L\* evenly spaced.

| Step | Value | Contrast on the Dark card |
|---|---|---|
| 1 — weakest | `#216D74` | 2.36 : 1 |
| 2 | `#2A828A` | 3.14 : 1 |
| 3 | `#3398A1` | 4.13 : 1 |
| 4 | `#48ADB7` | 5.35 : 1 |
| 5 | `#70C1C9` | 6.83 : 1 |
| 6 | `#9BD3D9` | 8.60 : 1 |
| 7 — strongest | `#C5E6E9` | 10.68 : 1 |

| | verbatim | reversed | **derived** |
|---|---|---|---|
| prominence rises with the value | no — inverted | yes | **yes** |
| step evenness, ΔE₀₀ max / min | 3.33× | 3.33× | **1.20×** |
| coarsest step lands at | — | the weak end | evenly spread |
| nearest §9.4.3 colour | 0.00 ΔE₀₀ | 0.00 ΔE₀₀ | **3.18 ΔE₀₀** |
| weakest step on the card | 12.15 : 1 | 1.36 : 1 | **2.36 : 1** |
| strongest step on the card | 1.13 : 1 | 12.15 : 1 | 10.70 : 1 |
| monotone under deuteranopia | — | yes | yes |
| monotone under protanopia | — | yes | yes |

The derived ramp gives up some top-end contrast (10.70 against the reversal's 12.15) to buy even
steps and clearance from the info colour. That is the trade the numbers were chosen on.

### What was solved for, and what was not

Five constraints, in `sequential.py`'s own words: monotone prominence, even perceptual steps, a
visible floor at the weak end (1.8:1 — the low end recedes, it does not disappear), one hue family
shared with Light including the chroma trajectory, and 3.0 ΔE₀₀ clearance from every §9.4.3 colour.

**Dichromat separability between adjacent steps is deliberately not maximised.** §9.4.4 is explicit
that a sequential ramp's neighbours measuring low under simulated protanopia is correct rather than
a defect — they encode a magnitude, they are read by lightness, and the simulated ramp stays
monotonic. That is checked, not optimised.

### Two things this got wrong on the way

Recorded because both were caught by a tool disagreeing with another tool, not by review.

1. **A first derivation maximised chroma at every L\*.** It met every numeric constraint and
   produced a top end of `#64F9FF` — a neon cyan, the wrong colour beside §9.4.4's teal. Hue alone
   does not carry family; the chroma trajectory does, and the spec's *desaturates* toward white.
2. **`cvd.de00()` takes RGB and converts internally.** Passing it Lab double-converts and
   under-reports by roughly threefold, silently. That is how the spec ramp's spread was first
   "measured" as 2.23× when it is 3.33×, and the wrong figure reached two docstrings before
   `validate.py` disagreed with `sequential.py`.

---

## §9.4.4's categorical ramp

Carried from WinZ3805A #87 and unchanged here. `validate.py`'s first block reproduces that issue's
four collapsed pairs and its adjacent-minima table; see `build/palette/derive.py` for the
derivation and `evaluate.py` for the full report.
