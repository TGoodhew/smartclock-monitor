# The driver contract, in this port

[`adding-a-receiver.md`](adding-a-receiver.md) is the walkthrough and it is **carried over
verbatim** from WinZ3805A. `provenance.md` records why: the *architecture* it teaches is what this
port reproduces, not the code samples. Its member table is C#, its file paths are C#, and every
signature in it is a `IReceiverDriver` method rather than a Python one.

This document is the mapping. It says what the contract looks like here, which members exist, which
do not yet, and where the difference is a decision rather than a gap.

**Six members postdate the walkthrough entirely** — `reports`, `outgoing_text_for`, `prompt_words`,
`plan.fast_readings`, `plan.cycle_boundaries` and `is_verified`. A driver author who reads only the
inherited walkthrough will meet none of them, which is why they have a section of their own below
rather than a row in a table.

**Read the inherited walkthrough for the reasoning and this for the names.** Nothing here supersedes
it; where they disagree about *why*, it is right.

---

## The contract as it stands

`src/smartclock_device/drivers/base.py`, a `typing.Protocol`. A driver is anything that satisfies
it — there is no base class to inherit and nothing to register a subclass with, which is why
`tests/test_capability.py`'s reads-only talker is twenty lines and is a real driver.

| C# member | Here | Notes |
|---|---|---|
| `Family` | `name` | A property, not a field. |
| `Recognises(identity)` | `recognises(identity)` | **Required**, and a family that claims nothing returns `False`. See below. |
| `Commands` + `Find(mnemonic)` | `is_allowed(mnemonic)` | The allowlist is asked a question rather than enumerated. §8.4's rule that a verdict is exposed and never a list is what shapes this. |
| — | `supports(command)` | New here. Takes a command *object* and answers whether this family can send it, which is what §9.11's capability gate needs before it offers a control. |
| `IsBlocked(header)` | `is_blocked(mnemonic)` | Unchanged in substance. |
| `Cadence` | `cadence` | A property returning `Cadence(fast, full)`. |
| `Plan` | `plan` | A property returning `PollPlan(fast, full, refusable, state_query)`. |
| `Parse(response)` | `parse_full(transaction, previous)` | Takes the previous status, so an incremental family can build on it. The SmartClock ignores it. |
| `InterpretSweep(answers)` | `apply_fast(status, results)` | Folds the fast tier into the status the full tier produced, rather than returning a separate readings object. |
| `Link` | `link` | `LinkStyle.QUERY_RESPONSE` or `LinkStyle.BROADCAST`. |
| `Overhear(lines)` | `overhear(lines)` | Offered the synchronise step's lines, **before** `*IDN?` is asked. A claim here means the probe is never sent. |
| `ClassifyLine(line)` | `classify(line)` | Which plan key a broadcast line belongs to, or `None`. |
| `Reports(reading)` | `reports(reading)` | **Required.** Whether this family can *ever* supply a reading. `False` is a structural claim, not a report on this poll — see below. |
| `OutgoingTextFor(mnemonic)` | `outgoing_text_for(mnemonic)` | **Required**, where the specification defaults it to null. §7.2's write rule, gate 2. |
| — | `prompt_words` | New here. §7.2's prompt as a grammar rather than a constant: `scpi > ` and `UCCM-P >` differ in the word *and* the spacing. |
| — | `plan.fast_readings` | New here. Which readings the fast tier is answerable for, so §7.3's tier rule is checkable and a page can be aged by the tier that fills it. |
| — | `plan.cycle_boundaries` | New here. Which plan keys close a cycle on a broadcast link. §12's default is `fast[0]`, which is one spelling; a talker has two. |
| — | `is_verified` | New here, and read by the interface. D7: whether this driver has ever met the receiver it claims to drive. |

Query/response families get the three broadcast members from the `QueryResponseDefaults` mixin and
write none of them. **`reports` and `outgoing_text_for` are not among them**, and that is
deliberate: a `Protocol` cannot default anything for a structural implementer — which is the whole
reason that mixin exists — so making these required is what forces a new family to *answer* rather
than inherit. The considered `return None` is written out, not assumed.

### Not here yet

| C# member | Why not, and what it blocks |
|---|---|
| `TimeoutFor(mnemonic)` | §7.2's classes live in `transport/timeouts.py` and are not yet per-driver. Broadcast does not need them — it never waits on a reply — so nothing forces the issue yet. |

`AutoDetectSequence` **is** here now, as `auto_detect_sequence` on each driver with the union built
by `Registry`. §10.12's eleven combinations are eleven because three families contribute: the
SmartClock's eight, a talker's two, and a UCCM's one.

---

## The second family

`drivers/nmea/` — any NMEA 0183 GNSS talker. It exists because **a contract satisfied by one
implementation is a contract nobody has tested**, and it is registered in `__main__` rather than
kept in the test suite, because a driver that only tests can reach is a driver nothing has proved.

It is the opposite shape to the SmartClock at every point the contract has an opinion:

| | SmartClock | NMEA talker |
|---|---|---|
| Link | query/response | broadcast |
| Recognised by | `*IDN?` and the banner | `overhear`, before anything is asked |
| Allowlist | 98 commands | **empty** — it is never written to |
| Plan entry | a query | a key |
| Full read | one status screen | the whole cycle |
| Oscillator fields | all of them | **none**, left `None` |

Four things it forced into the open, none of which a single-family build would have found:

1. **The probe had to become neutral.** Registering a reads-only family ahead of the SmartClock
   made every connection fall back, because `*IDN?` went through the allowlist of whichever driver
   was first. It is now sent outside any allowlist, as a constant.
2. **Recognition by listening has to come first.** Probing a talker costs a full timeout and is a
   *write* to a link whose driver says it is never written to.
3. **`ResponseBuffer` needed a stream mode.** It looks for a terminating prompt and keeps every line
   forever — correct for a transaction, a freeze and a slow leak for a device that talks for weeks.
   `detect_prompt=False` and `drain_lines()`.
4. **Silence has to reuse the timeout vocabulary.** A talker that has gone quiet reports
   `TIMED_OUT`, so §7.2's three-consecutive-failures rule, the supervisor and the status bar all
   apply unchanged rather than each learning a second failure mode.

What it deliberately does *not* do: invent an oscillator. There is no 1 PPS interval, no EFC, no
TFOM, no holdover in NMEA, and those fields stay `None`. §11.1's rule is what makes that safe —
every consumer already renders `None` as an em dash — and a driver that filled them with plausible
numbers would be worse than one that leaves them empty, because nothing downstream could tell.

`tools/nmea_simulator.py` is a talker on a pty. It is outside `src/`, nothing imports it, and
`tests/test_nmea.py` drives the driver from its output rather than from sentences pasted into the
test — so the sentences under test are ones something actually emitted.

---

## Three things this port learned that the walkthrough does not say

### `recognises` is required, and returning `False` is the point

The first design made it optional, on the reasoning that a single registered family has nothing to
distinguish itself from. That was worse. An absent method says *the author forgot*; an explicit
`return False` says *I claim nothing*, and the registry's fallback is then reached on purpose rather
than by accident.

`None` — nothing answered `*IDN?` — is not a claim either. A receiver that says nothing is the
ordinary state of most of §7.1's serial combinations during auto-detect, and the walk still needs a
driver to keep asking with.

### The probe belongs to no driver, and that has to be enforced rather than intended

§12 says *"the session probes `*IDN?` neutrally — the probe phase belongs to no driver"*. That is
easy to write and easy to violate: routing the probe through the session's ordinary `execute()`
gates it on **whichever driver happens to be registered first**, so a family registered ahead of the
one that actually serves the receiver refuses the identity query, nothing is ever recognised, and
the fallback becomes the only possible outcome.

Found by registering a reads-only talker first and watching a Z3805A go unclaimed. The probe is now
sent outside any allowlist — the one command that is, and a constant rather than a path: nothing
supplies the mnemonic and no argument is appended.

The alternative would have been to require every driver's allowlist to contain `*IDN?`, which puts a
requirement on the contract in order to make the probe work — the coupling the neutrality rule
exists to avoid.

### A page asks the driver before it offers a control

§12's #304 records the defect: every Details page asked for its tier C commands in a form that
throws, *"correct while one family shipped, and a crash on navigation the day a reads-only talker
arrived"*.

`views/capability.py` is the gate, and §9.11's rule is that **absent means disabled and explained,
never hidden**. A missing control reads as a feature the application does not have; a greyed one
naming the family reads as a feature *this receiver* does not have. Those are different facts and
the second is the true one.

It asks for **every** command a control would send, not any: a control whose action sends three and
can send two would do half of what it says, and half of a destructive operation is what §8.3's
confirmations exist to prevent.

---

## The five members the contract grew, and what each one is for

Everything in this section postdates the walkthrough. A driver author reading
[`adding-a-receiver.md`](adding-a-receiver.md) alone will not meet any of it.

### `reports(reading)` — what this family can never know

The read-side counterpart of the command catalogue. That one answers *what may I send*; this
answers *what may I ever know*.

It exists because a field a family cannot carry rendered as an em dash — which §11.1 defines as
*did not parse* and §9.11 as *has not arrived yet*. Structural absence and a slow read were drawn
identically, so a user could not tell *"this receiver will never tell you"* from *"this has not
come in"*. §11 settles it: a reading a family can never supply is **declined outright rather than
dashed**, *"because the em dash means not yet and using it for never promises something that will
not arrive"*.

**An entry in `ReceiverReading` is a question a page asks, not a field of the status model.** One
entry covers the 1 PPS interval, its trend, the Allan deviation and the drift fit, because a family
that cannot measure the interval cannot produce any of them.

**It runs both ways.** A talker has no disciplined oscillator; a status screen has no dilution of
precision, no position error and no fix quality. Neither family is the default.

**Declining is a claim, and some claims are weaker than others.** The UCCM declines the oscillator
control on the strength of seven sittings not showing a field, which is a different kind of
evidence from a receiver saying it has none — and the code says so where it does it.

### `outgoing_text_for(mnemonic)` — §7.2's write rule

A broadcast family may be written to **only** through this member. Three gates, independent by
design, all of which must hold before a byte leaves:

1. the mnemonic is a catalogued §8.1 entry for that family;
2. this member returns non-`None` for it;
3. the returned text passes that driver's own `is_blocked` **at the point of send**.

Gates 1 and 3 are asked again by `DeviceSession`, because a driver checking its own homework is not
a gate. A driver whose two methods disagree is a programming error: not sent, and logged.

A **fourth** precondition — will *this particular module* understand the sentence — is deliberately
not the driver's. It belongs to whatever holds the evidence, which for a talker is the power-on
banner, and a driver is a singleton that would otherwise carry one receiver's answer to the next.

D8 in [`platform-decisions.md`](platform-decisions.md) carries the argument, including the
recommendation that was overruled, because this trades a structural guarantee for a rule.

### `prompt_words` — the prompt as a grammar

§7.2's prompt was a constant. Two families made that untenable: `scpi > ` and `UCCM-P >` differ in
the word **and** the spacing, so no single literal matches both.

The **probe phase takes the union**, because §12 says that phase belongs to no driver — the prompt
has to be recognisable before a family is chosen. The session narrows it to the selected driver's
afterwards, so one family cannot end a transaction on another's prompt.

### `plan.fast_readings` — which tier owns which reading

§7.3 splits the poll in two and §7.3.1 governs refusals, but nothing said which readings the fast
half is *answerable for*. Two things needed that stated rather than inferred: the tier rule is only
checkable against a declaration, and a page cannot be aged by the tier that fills it until
something says which tier that is.

**Empty is the honest answer for a broadcast family** — both its tiers read the same cycle.

A subtlety worth knowing: the SmartClock's plan claims `OSCILLATOR_CONTROL` although `apply_fast`
does not fold it. The tier *reads* it and the poller folds it, because the control voltage has no
field on a status screen's model. The tuple records **responsibility**, not mechanism.

### `plan.cycle_boundaries` — which lines close a cycle

§12's default is the plan's first fast-tier entry, which is the same thing as naming one sentence
while a family has one spelling of its boundary. A talker has two — `GGA` and `GNS` — and against
a receiver sending the second this port read **nothing at all**.

The listener closes when a boundary key repeats **its own** key, so a talker sending both still
closes one cycle a second.

### `is_verified` — whether this driver has met a receiver

D7's condition, and a property the interface reads rather than a docstring. The UCCM driver answers
`False`: it is written entirely against captures taken elsewhere, and §10.4's identity card says so
in words a user can act on.

---

## What a new driver has to do

1. Satisfy the Protocol. `isinstance(YourDriver(), ReceiverDriver)` is a real check — the Protocol
   is `runtime_checkable` — and a contract test should assert it.
2. Return `False` from `recognises` for anything that is not yours, including `None`.
3. Answer `supports` honestly. A family that cannot set the antenna delay says so, and the page
   greys the control with your family's name in the tooltip.
4. **Answer `reports` for every reading.** Decline what your family can never supply, and *only*
   that — an over-eager decline says a receiver cannot do something it does once a second, which
   is worse than the dash it replaced.
5. **Return `None` from `outgoing_text_for` unless your family genuinely transmits.** If it does,
   read D8 first: the three gates are not negotiable and the fourth is not yours.
6. **Declare `prompt_words`** if your prompt is not the SmartClock's, and `plan.cycle_boundaries`
   if your link is broadcast and your cycle is delimited by more than one spelling.
7. **Declare `plan.fast_readings`** — empty is a real answer for a family whose tiers read the
   same thing.
8. Never raise from `parse_full` or `apply_fast`. §11.1 is not scoped to one family.
9. **Say whether you have met a receiver.** `is_verified` is `True` by omission, so a driver
   written from somebody else's captures has to say so — see D7.
10. Register in `__main__`'s `Registry([...])`, in priority order. **Order matters**: the UCCM is
    registered last because `SYMMETRICOM` is a vendor token the SmartClock also answers with, and
    the family that has met hardware gets first refusal.

The exclusions rule is the one that binds hardest and is already enforced against the interface:
§8.4's patterns live in one file, reach the application only as an `is_blocked` verdict, and
`tests/test_no_blocked_commands.py` scans the tree for any that leaked. That test binds every
future driver, not only the existing one.
