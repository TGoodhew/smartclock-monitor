# What is different from WinZ3805A

For someone who knows the Windows application and is meeting this one. It lists what this port
does **differently**, why, and — where the difference is a reduction — says so in those words.

The two repositories share a specification, a set of captured fixtures and a colour derivation, and
none of those has been edited to fit the port ([`provenance.md`](provenance.md) records what was
copied and what must not drift). So the differences here are not drift. Each one is a decision with
its reasoning in [`platform-decisions.md`](platform-decisions.md) and its argument in an issue.

---

## At a glance

| | WinZ3805A | Here | |
|---|---|---|---|
| **High contrast** | Resolves to your Windows system colours | **Not shipped** | *Reduction* — D3 |
| **Lock-loss alert (P1-9)** | Desktop notification | **Not shipped** | *Reduction* — D5 |
| **Close to notification area** | Hides, keeps polling | Closes, stops polling | *Reduction* — D5 |
| **Taskbar overlay badge (P1-13)** | Yes | No | *Reduction* — D5 |
| **UI typeface** | Segoe UI Variable | Noto Sans | Neutral — D4 |
| **Device-literal typeface** | Cascadia Mono | Cascadia Mono | **Same** — D4 |
| **Packaging** | MSIX, Microsoft Store | Flatpak / AppImage / PyInstaller planned | Different — D2 |
| **Platforms** | Windows | Linux, Windows, macOS | *Addition* |
| **Receiver families** | SmartClock | SmartClock **and NMEA 0183** | *Addition* |
| **System accent colour (P1-11)** | Opt-in | Not offered | Neutral — nothing to read |
| **Multiple receivers (P2-1)** | Not built | Not built | Same |

---

## The reductions, in full

These are the ones worth reading before deciding whether this port suits you.

### There is no high-contrast theme

WinZ3805A resolves its high-contrast tokens to the colours **you** chose in Windows. No desktop
this port targets offers an equivalent contract, and the alternative — a hand-authored set of
colours we picked — is a different service wearing the same name. For someone who configured a
specific scheme because of a specific impairment, "we chose good colours" is not a weaker version
of "we use yours".

Shipping it would have been worse than not, because a menu entry reading *High contrast* is a claim
you have no reason to doubt until it fails you. So there is Light and Dark, and this sentence.

Everything else in §9.12's accessibility criteria is unchanged: severity is always colour **and**
shape **and** text, every text token clears 4.5:1 on every surface it is drawn on, the sky plot is
reachable entirely from the keyboard, and its tables carry the same data at a 40 px row height.

### Nothing tells you when lock is lost

P1-9 is a desktop notification in WinZ3805A, on by default, and it exists — in §10.13's own words —
"precisely for the user who is *not* looking". This port ships no notification channel, and a
message shown only inside a window you are not looking at does not do that job. Rather than keep
the switch over a weaker promise, it is gone.

The window still shows the state at all times: the medallion's ring, the mode pill and the outputs
pill all change together. What is missing is the interruption.

### Closing the window stops the application

§10.3.1 hides the window to the notification area and keeps polling. With no notification area,
§10.3.1's own argument decides it: a hidden window with no icon "cannot be reached by any means the
user has", so hiding would not be an inconvenience but a loss of the application.

Close means close, and the poll stops. Leave the window open — minimised is fine — to keep the
trend filling.

---

## The additions

### A second receiver family, and a seam that is actually exercised

WinZ3805A's driver model is designed for more than one family and ships with one. Here there are
two: the SmartClock and any **NMEA 0183 talker**, the latter being the opposite shape at every
point the contract has an opinion — broadcast rather than query/response, an empty allowlist because
it is never written to, recognised by what it said before anything was asked.

That is not a feature so much as a proof: a contract satisfied by one implementation is a contract
nobody has tested. Registering the second found four defects in the first — see
[`driver-contract.md`](driver-contract.md).

### Three platforms

The whole reason the repository exists. WinUI 3 is Windows-only by definition.

---

## What is deliberately identical

Listed because sameness here is load-bearing, not incidental.

- **The §8.4 exclusion list.** Non-negotiable, synchronised in both directions, and the one thing
  on this page that may never diverge. A receiver bricked by one of those commands is bricked
  either way. See D6.
- **The specification.** Byte-exact, unedited, and describing a WinUI 3 application shipped to the
  Microsoft Store — deliberately, so the two repositories stay comparable.
- **The captured fixtures**, to the byte, line endings included.
- **The colour derivation** in `build/palette/`, which runs unchanged and is excluded from this
  project's linting so the two copies stay identical.
- **The command catalog's shape**: an allowlist, checked at the point of send, with the exclusions
  absent as data rather than present with a flag.
- **Cascadia Mono** for every string the receiver emits, which is the half of §9.5's typographic
  split that carries the meaning.

---

## What is not decided by this document

The Microsoft Store (G5) is not a goal here and remains a live goal of WinZ3805A, which ships it
today (D2). Packaging for the three platforms is Phase 8 work and nothing above depends on it.
