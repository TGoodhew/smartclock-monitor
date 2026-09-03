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
| 7 — strongest signal | `#08474D` | **1.36 : 1** |

<!-- Corrected: this row read 1.13:1, which is a *Light*-card figure — `#DFF1F3` against `#FBFBFB`,
     the weakest step on the surface the ramp was drawn for. On Dark the strongest step is 1.36:1.
     The defect it describes is unchanged; only the number was from the wrong column. -->

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
| strongest step on the card | 1.36 : 1 | 12.15 : 1 | 10.70 : 1 |
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

## §9.4.4's diverging ramp, on both cards

Derived by [`build/palette/diverging.py`](../build/palette/diverging.py). Same defect as the
sequential ramp above and found the same way — one column in the specification, two surfaces in the
application — but with a second failure the sequential ramp did not have, and a worse one.

Filed as [#19](https://github.com/TGoodhew/smartclock-monitor/issues/19) here and
[TGoodhew/WinZ3805A#371](https://github.com/TGoodhew/WinZ3805A/issues/371) upstream, where it was
found.

### The defect

These five are the 1 PPS chart's per-column whiskers — `TrendChart` draws each column's departure
from zero with a **1 px pen** in one of them — so §9.4.5's 3:1 floor for meaningful non-text applies
to every stop, not just to the ends.

| Token | Value | Light card | Dark card |
|---|---|---|---|
| negative, strong | `#08474D` | 10.05 : 1 | **1.36 : 1** |
| negative | `#3FB8C4` | **2.29 : 1** | 5.98 : 1 |
| zero | `#DDE4E5` | **1.24 : 1** | 10.99 : 1 |
| positive | `#F0A882` | **1.91 : 1** | 7.17 : 1 |
| positive, strong | `#B23A00` | 5.80 : 1 | **2.36 : 1** |

Five of the ten under the floor. Two separate problems:

1. **On Dark the ordering inverts**, exactly as the sequential ramp's did — the pale neutral is the
   boldest mark on the card at 10.99:1 while a large excursion fades to 1.36:1. A diverging ramp
   puts its neutral *near* the surface and its extremes *away* from it, and "away" is darker on a
   light card and lighter on a dark one. One column cannot do both.
2. **On Light three live strokes are illegible**, and this is not an ordering problem — it is on the
   theme the ramp was drawn for. `#DDE4E5` at **1.24:1** on a white card is not a line anyone can
   follow.

Measured against §9.4.1's reference cards, `#FBFBFB` and `#2B2B2B`. This port's Light card is
`#FFFFFF`, which moves each Light figure by under 0.15 and changes nothing.

### The derived ramps

| Step | Light | on card | Dark | on card |
|---|---|---|---|---|
| negative, strong | `#1D5D64` | 7.24 : 1 | `#90DEE7` | 9.31 : 1 |
| negative | `#2A7D85` | 4.66 : 1 | `#75B6BD` | 6.17 : 1 |
| zero | `#8B9293` | 3.06 : 1 | `#818788` | 3.90 : 1 |
| positive | `#C24D19` | 4.66 : 1 | `#EB976A` | 6.17 : 1 |
| positive, strong | `#93370F` | 7.24 : 1 | `#F3C9B4` | 9.31 : 1 |

Against this port's own cards the Light column measures 7.49 / 4.80 / 3.17 / 4.81 / 7.52 and the
Dark 9.30 / 6.19 / 3.88 / 6.18 / 9.32 — every stop clear of the floor on both, the neutral quietest,
and prominence rising outward along both arms.

| | spec, verbatim | derived |
|---|---|---|
| weakest stop, Light | 1.24 : 1 | **3.06 : 1** |
| weakest stop, Dark | 1.36 : 1 | **3.90 : 1** |
| stops under 3:1, both cards | 5 of 10 | **none** |
| prominence rises outward | Light only | **both cards** |
| arms apart at matching magnitude | — | 28.6 ΔE₀₀ Light, 20.3 Dark |

The arm separation is the worst of three vision models — normal, deuteranopia, protanopia — so the
*sign* of an excursion survives dichromacy even where its magnitude is harder to judge. That matters
more here than on the sequential ramp: early or late is a different fault from a large or small
error, and colour is the only thing carrying it.

### What was solved for

**"Change as little as possible."** The objective is the nearest legal ramp to the five §9.4.4
already had, not an optimum. Minimising ΔE₀₀ step evenness — `sequential.py`'s objective — is the
wrong one for a two-armed ramp: evenness across a ramp read *outward from its middle* would pull the
two arms toward each other and cost the separation that carries the sign.

### The one constant in `diverging.py` that is not shared

`SEMANTIC` in that file is **WinZ3805A's §9.4.3, not this port's**, and the file says so in place
(added by [TGoodhew/WinZ3805A#373](https://github.com/TGoodhew/WinZ3805A/pull/373)). Their accent and
info are the brand teal; here both are blue — `#0F6CBD` on Light, `#4CC2FF` on Dark. So the
clearance line `diverging.py` prints, 5.35 ΔE₀₀ on Light and 5.51 on Dark, is measured against the
wrong palette when the script is run in this repository, while looking perfectly correct.

Measured against **this port's** §9.4.3 colours, the derived ramps clear them by **11.2 ΔE₀₀ on
Light** (positive-strong vs `critical`) and **7.5 on Dark** (zero vs `neutral`) — comfortably above
the 5.0 the file asserts, so the ramps are safe here as they stand. The same caveat applies to
`sequential.py`'s `SEMANTIC_DARK`, whose 3.18 figure is likewise upstream's.

Reproduce with:

```bash
python - <<'EOF'
import sys; sys.path[:0] = ['build/palette', 'src']
import cvd
from smartclock_monitor.themes.tokens import LIGHT, DARK
h2r = lambda h: tuple(int(h[i:i+2], 16) for i in (1, 3, 5))
for pal, name in ((LIGHT, 'Light'), (DARK, 'Dark')):
    sem = {k: getattr(pal, k) for k in
           ('accent', 'success', 'caution', 'critical', 'info', 'neutral')}
    print(name, min(cvd.de00(h2r(d), h2r(c)) for d in pal.diverging for c in sem.values()))
EOF
```

**Upstream's copy must stay as it is.** `build/palette/` is byte-identical between the two
repositories and that is the whole of its value; correcting `SEMANTIC` to this port's colours would
fork the directory to fix a comment.

### One thing this got wrong on the way

`in_gamut` asked whether `lab2rgb`'s returned bytes were inside 0–255. They always are, because
`vec.unlin` clips — so the bisection that "clamps to the gamut" clamped nothing and answered yes for
every colour in the plane. It changed nothing in `sequential.py`, whose chroma curve never asks for
an impossible colour and whose ramp re-derives byte for byte either way; it produced immediate
nonsense in `diverging.py`, which asks constantly. Corrected in both, and both files are carried
between the two repositories with the fix.

---

## §9.4.4's categorical ramp

Carried from WinZ3805A #87 and unchanged here. `validate.py`'s first block reproduces that issue's
four collapsed pairs and its adjacent-minima table; see `build/palette/derive.py` for the
derivation and `evaluate.py` for the full report.
