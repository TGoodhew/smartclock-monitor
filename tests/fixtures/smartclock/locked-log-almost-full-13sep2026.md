# locked-log-almost-full-13sep2026

**The first capture that asks the receiver the same question twice by two routes.** Every other
artefact in this tree is one account of an instant — a status screen, or a stream of sentences.
This one holds a screen and the five status registers taken in the same breath, so a claim about
what a bit means can be checked against what the screen said at the moment it was set.

| | |
|---|---|
| Receiver | `SYMMETRICOM,Z3805A,3625A02931,1.01.03-A` — the unit the whole SmartClock corpus comes from |
| Port | `/dev/ttyUSB0` at 9600-8-N-1, Prolific PL2303 through `usbipd-win` into WSL |
| Taken | 14 Sep 2026 00:52:38 UTC (13 Sep, 10:52 +10:00) |
| Harness | `tools/capture_registers.py --label locked-log-almost-full-13sep2026` |
| Asserted by | `tests/test_registers_against_screen.py` |

## What the receiver was doing

Locked to GPS, outputs valid, TFOM 3, FFOM 0, nine satellites tracked and two not, health monitor
`[ OK ]` on all six labels, position `MODE Hold`. An ordinary steady state, which is the point:
**the registers are worth capturing in a state the screen also describes**, because that is the
only state in which the two can be checked against each other.

## Why it is a transcript and not raw bytes

`tools/capture_talker.py` writes bytes because the NMEA parser's job is to survive what is on the
wire. This harness writes lines, because what is under test is *agreement between two answers*
rather than the framing of either. The ten status screens in `captured/` remain the byte-exact
oracle for `StatusScreenParser`; nothing here replaces them, and the parser is handed this
screen too.

`>>> ` opens a command. Everything else is verbatim, CRLF endings intact, `-text` like the rest.

## What it settled

- **The map is right where the bench can check it.** Every bit set in all five registers is a bit
  `status_register_map.py` names, and the Operation, Hardware, Power-up, Holdover and Questionable
  values each say what the screen says.
- **The diagnostic log is almost full and no surface says so** (#110). Operation bit 6 is set;
  `:DIAG:LOG:COUN?` answers `+222`. §10.9's card reports the count and never the bit. That the
  receiver sets the bit at 222 entries is the only evidence this port has for what *almost* means
  on this firmware — the figure is not documented anywhere it can cite.
- **`:SYNC:HOLD:DUR?` answers two fields while locked** (#111): `+1.44800E+003,0` — twenty-four
  minutes of a holdover that has ended, and a flag saying it has. The screen prints no duration at
  all in this state, so `ReceiverStatus.holdover_duration` is `None` while the receiver is holding
  the figure ready to be asked for.

## What it cannot settle

**Every fault bit is clear, and a healthy receiver is the only kind this bench has.** The twelve
Hardware bits are the states §10.4's health card exists to draw, and the only one this capture
exercises is *none of them*. Two of the twelve — *time interval measurement failed* and *EEPROM
write failed* — have no label on the health block at all (#112), and that is a reading of the
screen's six labels rather than of a capture: no sitting has ever produced either.
