# form8n-time-poll

- **Captured** 2026-09-13T21:38Z, 60 s, on this bench
- **Receiver** RCmall forM8N — u-blox `HW UBX-M8130`, ROM CORE 3.01 (107888), PROTVER 18.00
- **Port** `/dev/ttyACM1` in WSL through `usbipd`
- **Harness** `tools/capture_talker.py`'s transport, driven by a script that also **sent** the poll

## What this is for

**The first capture in this repository that contains something this application sent.** Everything
else here is a receiver talking unprompted. D8 traded away the structural guarantee that made that
true — there was no send path — and this is the evidence for the reading it was traded for.

`$PUBX,04*37` was written six times, ten seconds apart. Each write went through the same three
gates the session applies: catalogued, offered by the driver, and not refused by the driver's own
exclusion rule. Six polls, six replies, no losses.

## What the reply says

```
$PUBX,04,213801.00,130926,77880.99,2436,18,-574488,-808.578,21*2E
```

| Field | Value | |
|---|---|---|
| 1 | `213801.00` | UTC time of day |
| 2 | `130926` | date, `ddmmyy` |
| 3 | `77880.99` | UTC time of week, seconds |
| 4 | `2436` | UTC week number |
| **5** | **`18`** | **GPS − UTC, in seconds** — the reading this whole path exists for |
| 6 | `-574488` | receiver clock bias, ns |
| 7 | `-808.578` | receiver clock drift, ns/s |
| 8 | `21` | time-pulse granularity, ns |

**18 is correct for 2026** and is what both bench receivers answered independently — the u-blox 7
on `/dev/ttyACM0` gave the same figure in the same second. Two modules, two firmware generations,
one number.

**Field 5 can carry a `D` suffix** — `18D` — meaning the firmware's built-in default rather than a
value decoded from the satellites. Neither receiver here produced one, because both had been
tracking for hours. The parser tells the two apart and the model records which it got, because a
default is a guess the receiver is making and a user of a timing application should be told so.
Nothing in this capture exercises that branch, and the test that covers it says it is synthetic.

## What no standard sentence carries

This is the point. GPS − UTC appears in no standard NMEA sentence. §10.14 renders the time scale
because UTC and GPS differ by exactly this, and without the poll the talker family answers it with
a dash for ever.
