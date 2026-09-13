2026-08-27T20:24:22.4884570-07:00  locked-to-gps-stabilizing-frequency.txt  mode="Locked to GPS: stabilizing frequency" sync="Outputs Valid/Reduced Accuracy" acquisition="GPS 1PPS Valid" health="OK" tracking=8
2026-08-27T20:40:34.4612433-07:00  locked-to-gps-stabilizing-frequency-2.txt  mode="Locked to GPS: stabilizing frequency" sync="Outputs Valid/Reduced Accuracy" acquisition="GPS 1PPS Valid" health="OK" tracking=7
2026-08-27T20:44:17.5055572-07:00  locked-to-gps-stabilizing-frequency-2.txt  mode="Locked to GPS: stabilizing frequency" sync="Outputs Valid/Reduced Accuracy" acquisition="GPS 1PPS Valid" health="OK" tracking=8
2026-08-27T20:52:23.4097525-07:00  locked-to-gps.txt  mode="Locked to GPS" sync="Outputs Valid" acquisition="GPS 1PPS Valid" health="OK" tracking=9
2026-08-27T20:56:50.4649438-07:00  locked-to-gps-2.txt  mode="Locked to GPS" sync="Outputs Valid" acquisition="GPS 1PPS Valid" health="OK" tracking=9
2026-08-27T21:03:43.4917710-07:00  locked-to-gps-2.txt  mode="Locked to GPS" sync="Outputs Valid" acquisition="GPS 1PPS Valid" health="OK" tracking=8
2026-08-27T21:46:56.4289432-07:00  locked-to-gps-2.txt  mode="Locked to GPS" sync="Outputs Valid" acquisition="GPS 1PPS Valid" health="OK" tracking=9
2026-08-27T22:09:48.9451094-07:00  power-up-gps-acquisition.txt  mode="Power-up: GPS acquisition" sync="Outputs Invalid" acquisition="GPS 1PPS Invalid" health="OK" tracking=0
2026-08-27T22:10:29.3236078-07:00  power-up-fine-freq-adj.txt  mode="Power-up: fine freq adj" sync="Outputs Invalid" acquisition="GPS 1PPS Valid" health="OK" tracking=8
2026-08-27T22:12:23.3801746-07:00  locked-to-gps-stabilizing-frequency-2.txt  mode="Locked to GPS: stabilizing frequency" sync="Outputs Valid/Reduced Accuracy" acquisition="GPS 1PPS Valid" health="OK" tracking=8
2026-08-27T22:20:00.0000000-07:00  surveying-locked-to-gps-stabilizing-frequency.txt  mode="Locked to GPS: stabilizing frequency" sync="Outputs Valid/Reduced Accuracy" acquisition="GPS 1PPS Valid" health="OK" tracking=8  [RECONSTRUCTED - this screen was captured by hand, because until #242 the harness could not see the survey state and reported it as one already seen. The facts were re-read from the file with the harness's own Get-ScreenFacts; the timestamp is when it was committed, not when it was taken.]
2026-08-28T08:52:56.8206604-07:00  holdover-gps-1pps-invalid.txt  mode="Holdover: GPS 1PPS invalid" sync="Outputs Valid/Reduced Accuracy" acquisition="GPS 1PPS Invalid" health="OK" tracking=0
2026-08-28T09:04:27.0000000-07:00  holdover-gps-1pps-invalid-deep.txt  mode="Holdover: GPS 1PPS invalid" sync="Outputs Valid/Reduced Accuracy" acquisition="GPS 1PPS Invalid" health="OK" tracking=0  [DELIBERATE SECOND SAMPLE - same signature as the file above, so the harness would never take it. Captured by hand 11m34s into the same holdover, into a scratch directory with an empty seen-set, to pin the two-digit minute format that a 0m03s screen cannot show. Kept because it is the only evidence the minutes field is unpadded rather than fixed-width. Named outside the numeric sequence so it cannot be confused with the harness suffixes, which number genuinely distinct states.]
2026-08-28T09:09:45.7355421-07:00  holdover-gps-1pps-invalid-3.txt  mode="Holdover: GPS 1PPS invalid" sync="Outputs Valid/Reduced Accuracy" acquisition="GPS 1PPS Valid" health="OK" tracking=6
2026-08-28T09:09:59.8280414-07:00  recovery-fine-freq-adj.txt  mode="Recovery: fine freq adj" sync="Outputs Valid/Reduced Accuracy" acquisition="GPS 1PPS Valid" health="OK" tracking=7


---

## 13 September 2026 — one query, no screen capture

Not a fixture sitting: the Z3805A was asked a single documented query and the answer written into
`commands/catalog.py` and `tests/test_diagnostic_log.py` rather than into a file here. Recorded in
this log anyway, because the next person to wonder where that string came from will look here.

**Unit:** `SYMMETRICOM,Z3805A,3625A02931,1.01.03-A` — the same one every capture above came from,
reached from WSL over `usbipd` on `/dev/ttyUSB0` at 9600-8-N-1.

**Asked:** `:DIAG:IDEN:GPS?`, and its long form `:DIAGnostic:IDENtification:GPSystem?`. Both were
checked against the §8.4 exclusion predicate before a byte was sent; both are queries; both answer
identically, which is SCPI's abbreviation rule behaving as documented.

**Answered:**

```
"--","SFTW P/N # 4850266","SOFTWARE VER # 005","--","--","MODEL # FURUNO GT-80","--","--","--","--"
```

**Why it was asked rather than assumed.** Upstream records three queries in that repository whose
spelling had drifted from what the hardware answers, so guessing here would have been repeating a
mistake somebody had already paid for. It was worth the five minutes: the answer's *shape* turned
out to be the finding. Ten fields, seven of them `--`, and **the serial number the Z3801A User's
Guide is most specific about is among the empty ones** — so nothing may assign meaning to position,
and the card shows the populated fields in receiver order, in the receiver's own words.

The instrument's own firmware is `1.01.03-A`; the engine inside it is a Furuno GT-80 running
software version 005. Two revision schedules, which is the whole reason the reading exists.
