# locked-with-time-code-13sep2026

**Three accounts of one instant.** The status screen prints the figures of merit; the five status
registers carry the conditions behind them; and `:PTIM:TCOD?` carries both figures again — with the
time of the next 1 PPS and three flags — in twenty-three characters, by a route that touches
neither. Taken in one pass, which is what makes *they agree* assertable.

| | |
|---|---|
| Receiver | `SYMMETRICOM,Z3805A,3625A02931,1.01.03-A` |
| Port | `/dev/ttyUSB0` at 9600-8-N-1, Prolific PL2303 through `usbipd-win` into WSL |
| Taken | 14 Sep 2026 01:46 UTC (13 Sep, 11:46 +10:00) |
| Harness | `tools/capture_registers.py --label locked-with-time-code-13sep2026` |
| Asserted by | `tests/test_time_code.py` |

Locked to GPS, outputs valid, TFOM 3, FFOM 0, nine satellites tracked and four not, health monitor
`[ OK ]`, position `MODE Hold`. The same steady state as the sitting beside it, an hour later.

## Why there are eight time codes and not one

One message proves a decode. A **run** proves the checksum, and only if the run crosses a carry.

Consecutive messages usually differ in a single digit, so a trailing pair that advanced by one
would be equally consistent with a counter. This run crosses `…49` → `…50`: two digits change, the
character sum falls by eight, and the trailing pair goes `47` → `3F`. **A counter cannot do that.**

The rule is the sum of the twenty-one preceding characters modulo 256 — #37 verified it on 103 of
103 messages in Aug 2026, and this sitting is 8 of 8 more.

## What it settles

- **The message decodes**, and its two figures of merit equal the screen's and the scalar queries'
  taken seconds earlier. Three routes, one pair of numbers.
- **It carries the same rolled-over date as the screen** — 29 Jan 2007 — which is the first time
  §7.4's correction has been checked against a source other than the status screen it was written
  for.
- **The receiver answers on demand**, contrary to nothing: §10.14 already recorded that a request
  lands in the receiver's next 1 Hz emission slot. Measured here at 0.4 to 1.0 s, against 0.2 s for
  a scalar query on the same link in the same minute. That is why nothing polls it (#113).

## What it cannot settle

**Every flag is in its quiet state.** Time valid, no leap second, no service requested — so the
decode of those three fields rests on Lady Heather's layout (#98) and on the message length
agreeing, not on having seen any of them change. The one that could be captured is time validity: a
receiver reads invalid for the first minutes after a power cycle, which is the same state the
screen marks with `(?)`.

**T1 has never been seen.** This unit is in T2, and the setter that would change it is deliberately
not catalogued (§10.14.1).
