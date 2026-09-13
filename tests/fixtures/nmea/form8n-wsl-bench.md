# form8n-wsl-bench

- **Captured** 2026-09-13T18:12Z, 10 minutes, alongside `vk162-wsl-bench` on the same bench
- **Receiver** RCmall forM8N — u-blox `HW UBX-M8130`, ROM CORE 3.01 (107888), FWVER SPG 3.01,
  PROTVER 18.00. `GNSS OTP=GPS;BDS`, with `GPS;GLO;BDS` and `QZSS` as the supported set
- **Port** `/dev/ttyACM1` in WSL, through `usbipd attach --wsl --busid 11-3`
- **Antenna** the module's own patch, indoors
- **Bytes** 488,448 — 633 cycles, 632 closed, every one with a fix

## What this is for

**The satellite-number collision, at 100 %.** Every one of the 632 closed cycles has at least one
number reported by both the `GP` and the `GB` talker — 14 GPS numbers and 10 BeiDou numbers over
the sitting, overlapping in every cycle. `form8n-gps-beidou-outdoors` shows the same defect in
1,217 of its 1,800 cycles; this one shows it in all of them, which makes it the cheaper fixture to
assert against for #57. `TrackedSatellite` is keyed on the number alone, so `_visible` collapses
each colliding pair and the tracked count is short by however many collided.

**The two modules disagree about the last RMC field.** The VK-162 sends `A` and this module sends
`V` in all 632 — the NMEA 4.1 navigational-status indicator, which this firmware carries and does
not implement. A parser that read the last field of RMC as the mode indicator would conclude this
receiver has no valid fix while GGA quality says `1` and the position is good. Worth having as a
fixture precisely because it is a field that *looks* like a fix flag and is not.

**The banner, with the distinction that matters.** Twelve `$GNTXT` lines at power-on, including
both `GPS;GLO;BDS` — what the firmware *supports* — and `GNSS OTP=GPS;BDS`, what this unit is
one-time-programmed for. Read only the first and you would expect GLONASS sentences that never
come; there is not one `GLGSV` in the capture. Whatever fills #62's health card has to quote the
OTP line, not the supported one.

**What it does not have:** no outage, no `GNS`, no `GST`, no midnight crossing. The carried
captures hold all four.
