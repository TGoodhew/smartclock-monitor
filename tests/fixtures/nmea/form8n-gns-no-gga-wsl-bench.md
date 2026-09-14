# form8n-gns-no-gga-wsl-bench

- **Captured** 2026-09-14T00:04Z, 4 min, on this bench
- **Receiver** RCmall forM8N — u-blox `HW UBX-M8130`, PROTVER 18.00
- **Port** `/dev/ttyACM1` in WSL through `usbipd`
- **Bytes** 174,088 — **240 `GNS`, and not one `GGA`**
- **Configured** `GNS` on and `GGA` off by `UBX-CFG-MSG` **to RAM**, with the owner's say-so, and
  restored afterwards with the result read back over eight seconds rather than assumed

## Why take this when the corpus already had two

`vk162-gns-no-gga` and `form8n-gns-without-gga` came from WinZ3805A, and between them they found
the defect that mattered most in this port's whole audit: **against a talker sending `GNS` instead
of `GGA`, this application read nothing at all** — 720 and 130 cycles, zero cycles closed, because
the listener's boundary never came round (#58).

This is that configuration produced deliberately on our own hardware, and it reads: **239 cycles,
every one carrying a position.** The fix holds against a receiver we own rather than only against
somebody else's recording.

## The new finding: `ANNA`, not `ANNN`

`GNS`'s mode field is **one character per constellation**, and the two sittings disagree about
which constellations answer:

| | mode | reading |
|---|---|---|
| WinZ3805A, 11 Sep | `ANNN` | autonomous on the first system, nothing on three others |
| VK-162, upstream | `DN` | **two** characters — differential on the first, nothing on the second |
| here | **`ANNA`** | autonomous on the **first and fourth** |

Three distinct shapes across three sittings, and the field is not a fixed-width code in any of
them. A reader that took `ANNN`'s length as the format, or matched the string, would be wrong on
the other two — which is exactly why the parser asks *"is any character not `N`"* and takes the
**best** of what it finds rather than reading a position.

`ANNA` is the first value in either repository where a constellation **other than the first**
contributes, so it is the first one that would catch a parser looking only at character zero. Ours
reads `autonomous` in all 240, which is right: the best of `A`, `N`, `N`, `A`.

## What it does not add

Nothing about the fix ladder — the module held an autonomous fix throughout, so there is no
acquisition sequence here. `vk162-cold-start` remains the only capture that walks all three
qualities in order.
