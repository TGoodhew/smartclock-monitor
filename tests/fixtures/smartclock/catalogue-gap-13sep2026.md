# catalogue-gap-13sep2026

**Everything this application may ask the receiver, asked once.** Eighty-six argument-free queries
from §8.1's allowlist, in catalogue order, swept in a single pass:

```
python tools/capture_registers.py --port /dev/ttyUSB0 --every-query --label <name>
```

| | |
|---|---|
| Receiver | `SYMMETRICOM,Z3805A,3625A02931,1.01.03-A` |
| Port | `/dev/ttyUSB0` at 9600-8-N-1, Prolific PL2303 through `usbipd-win` into WSL |
| Taken | 14 Sep 2026 04:11 UTC (13 Sep, 14:11 +10:00) |
| Asked | 86 |
| Answered | 81 |
| Asserted by | `tests/test_catalogue_gap.py` |

Locked to GPS, position `MODE Hold`, health `[ OK ]`. The sweep is taken from the catalogue rather
than from a list in the harness, so **a query added to §8.1 is covered by the next sitting without
anyone editing this file's harness**.

## Why it was taken

#118: thirty of §8.2's entries had no catalogue entry here, and §10.11's console is a picker over
the allowlist — so those thirty were commands this application could not send at all, by anyone.
This is the evidence that each of them answers on real hardware rather than only in a manual.

## The five that answered nothing

Each has nothing to say in this state, and each is #114's `E-230` class — the firmware has the
query and no data for it — rather than a query the receiver lacks:

| | |
|---|---|
| `:DIAG:TEST:RES?` | no self-test has been run this session |
| `:SYNC:HOLD:TUNC:PRES?` | the *present* holdover uncertainty, and it is not in holdover |
| `:PTIM:LEAP:DATE?` | §10.14: answers only while an announcement stands |
| `:PTIM:LEAP:DUR?` | the same |
| `:GPS:POS:SURV:PROG?` | no survey is running |

## Three summaries the receiver corrected

Carried differently here from `WinZ3805A.Device/Commands/CommandCatalog.cs`, in each case because
this sitting or the hand probe beside it says so:

- **`:SYST:COMM?` names a port, not a configuration.** It answers `SER1`. The configuration lives
  under `:SYST:COMM:SER1:` and every one of those is a tier C setter.
- **`:SYNC:HOLD:WAIT?` answers a keyword, not a boolean.** It answers `NONE`, which `parse_boolean`
  would read as *absent* — the same answer it gives for a receiver that never replied.
- **`:DIAG:QUER:RESP?` repeats the previous query's answer.** Upstream carries it as *"reads a fixed
  response, used to prove the link is alive"*. A hand probe on this bench, immediately before the
  sweep:

  ```
  :SYNC:TFOM?              +3
  :DIAG:QUER:RESP?         +3
  :DIAG:QUER:RESP?         +3      <- twice in a row, same answer
  *CLS                     (no response)
  :DIAG:QUER:RESP?         +3      <- a setter in between does not disturb it
  ```

  and earlier, `1` after `:LED:GPSL?` and `+10` after `:GPS:SAT:VIS:PRED:COUN?`. Four values, four
  matches. It is still a link test — but a user told it returns a *fixed* response would read a
  stale value as the response and conclude the link was fine.

## Two things worth knowing when reading the file

**`*ESR?` reads `+16` here and read `+48` an hour earlier.** Reading the standard event status
register clears it, which is IEEE 488.2's own contract: the probe read it, and what is left is what
accumulated between the two.

**The satellite lists move between sittings.** `:GPS:SAT:TRAC?` names eight here and nine in the
sitting an hour before. That is the constellation, not the receiver.

## What it cannot settle

**One state.** Every reading here is from a receiver locked, steady and up for hours — so the five
declines above are evidence about *those five in this state* and nothing more, and no fault bit,
survey, holdover or announcement appears anywhere in the file. The queries that report those are
catalogued on the strength of answering at all.
