# vk162-wsl-bench

- **Captured** 2026-09-13T18:12Z, 10 minutes
- **Receiver** VK-162 USB GPS puck — u-blox `HW UBX-G70xx`, ROM CORE 1.00 (59842), PROTVER 14.00
- **Port** `/dev/ttyACM0` in WSL, reached through `usbipd attach --wsl --busid 1-8`
- **Antenna** the puck's own, indoors on a windowsill
- **Harness** `tools/capture_talker.py` — the first capture this repository has taken itself
- **Bytes** 343,730 — 633 cycles, 632 closed by the listener, every one with a fix

## What this is for

**It is not a new state, and it is not pretending to be.** The corpus already holds thirty minutes
of this module from WinZ3805A. This is the same silicon, five days later, on a different continent
of the stack: a Python harness, a Linux host, and a USB/IP link with a Windows machine in the
middle of it.

Three things it is good for.

**The harness produces the same artefact.** 4,903 CRLF pairs, no conversion in either direction,
and `NmeaDriver` reads it to the same shape it reads the carried captures. That is what makes
`tools/capture_talker.py` trustworthy for the sittings that *will* hold a state nothing else does.

**A standalone fix, at length.** GGA quality is `1` in all 633 cycles and the RMC mode indicator is
`A`. `vk162-steady-state` is a **differential** fix in all 1,800 of its cycles, so between the two
the ordinary and the augmented cases are both covered at length rather than only the better one.

**The power-on banner, because `usbipd attach` re-enumerates the device.** Seven `$GPTXT` lines
arrive in the first second and never again — the hardware, the ROM version, the protocol version
and `ANTSTATUS=OK`. That is #62's banner reading, and this capture has it by construction rather
than by luck: every attach from Windows restarts the talker.

**What it does not have:** one constellation, one talker, no outage, no `GNS`, no `GST`. For any
of those, read the carried captures.
