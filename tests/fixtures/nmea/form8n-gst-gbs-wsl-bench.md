# form8n-gst-gbs-wsl-bench

- **Captured** 2026-09-13T23:55Z, 5 min, on this bench
- **Receiver** RCmall forM8N — u-blox `HW UBX-M8130`, ROM CORE 3.01 (107888), PROTVER 18.00
- **Port** `/dev/ttyACM1` in WSL through `usbipd`
- **Bytes** 236,790 — **301 `GST` and 301 `GBS`**
- **Sentences switched on** `GST`, `GBS`, by `UBX-CFG-MSG` **to RAM**, with the owner's say-so

> **This receiver does not send these by default**, and the write was made from a script outside the
> application on purpose: D8 permits exactly one outgoing sentence from the driver and this is not
> it. RAM only — no `CFG-CFG` save followed — so a power cycle reverts it, and the set was restored
> afterwards with the result **read back** rather than assumed from the write.

## Why take this when the corpus already had one

`form8n-gst-gbs` came from WinZ3805A on 12 September. This is the same *family* of module on a
different bench, a different day and a different position — and the point of taking it was to find
out which of that sitting's findings are about **the firmware** and which were about that afternoon.

All three carried over, which is worth more than a second capture of the same numbers:

**The error ellipse is empty here too — 0 of 301.** Fields 2, 3 and 4 blank in every sentence,
exactly as in the 12 Sep sitting. Two independent sittings say this module declines to publish an
ellipse; it is not a truncation and not a property of one afternoon.

**The `GBS` fault fields are empty in all 301.** No satellite flagged, again. The faulted branch of
`ConstellationIntegrity` has now failed to occur in **601 cycles across two sittings**, which is
why the test that covers it is still labelled synthetic.

**The range RMS is unusable, and this sitting says something new about *how*.** The 12 Sep note
described it as running "from 17 to 3,179,277 — six orders of magnitude", which reads as noise.
It is not noise. Both sittings contain the **same two exact values**:

| | 12 Sep | here |
|---|---|---|
| `3179277` | 11 times | 4 times |
| `3071473` | 12 times | 5 times |
| anything else above 10⁶ | none | none |

Two discrete values, repeating exactly, a day apart on different hardware placement. That is a
**sentinel or a saturated computation**, not a wild reading — and it makes the decision not to
display the field stronger rather than merely cautious. Nothing in the application reads it, and
`parsing`'s comment says why.

## What differs, and is supposed to

The deviations are larger here — 2.7–3.1 m latitude against 1.7–1.9 on 12 Sep, giving a horizontal
error near **3.9 m** against 2.7 — because this is a different indoor position. That is the reading
doing its job: same firmware, worse sky, bigger number.
