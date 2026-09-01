# The driver contract, in this port

[`adding-a-receiver.md`](adding-a-receiver.md) is the walkthrough and it is **carried over
verbatim** from WinZ3805A. `provenance.md` records why: the *architecture* it teaches is what this
port reproduces, not the code samples. Its member table is C#, its file paths are C#, and every
signature in it is a `IReceiverDriver` method rather than a Python one.

This document is the mapping. It says what the contract looks like here, which members exist, which
do not yet, and where the difference is a decision rather than a gap.

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

### Not here yet

| C# member | Why not, and what it blocks |
|---|---|
| `Link` (`QueryResponse` / `Broadcast`) | No broadcast family exists here, so there is nothing for the flag to switch between. Blocks: the NMEA driver. |
| `Overhear(lines)` | Same. The synchronise step's lines are absorbed and parsed for an identity, but no driver is offered them. |
| `ClassifyLine(line)` | Same, and the `BroadcastListener` that would consume it. |
| `TimeoutFor(mnemonic)` | §7.2's classes live in `transport/timeouts.py` and are not yet per-driver. One family, one set. |
| `AutoDetectSequence` | Lives in `transport/settings.py` as one sequence. §10.12's "union of every registered driver's sequence" needs a second driver to be a union of. |

All of it is [issue #13](https://github.com/TGoodhew/smartclock-monitor/issues/13).

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

## What a new driver has to do

1. Satisfy the Protocol. `isinstance(YourDriver(), ReceiverDriver)` is a real check — the Protocol
   is `runtime_checkable` — and a contract test should assert it.
2. Return `False` from `recognises` for anything that is not yours, including `None`.
3. Answer `supports` honestly. A family that cannot set the antenna delay says so, and the page
   greys the control with your family's name in the tooltip.
4. Never raise from `parse_full` or `apply_fast`. §11.1 is not scoped to one family.
5. Register in `__main__`'s `Registry([...])`, in priority order.

The exclusions rule is the one that binds hardest and is already enforced against the interface:
§8.4's patterns live in one file, reach the application only as an `is_blocked` verdict, and
`tests/test_no_blocked_commands.py` scans the tree for any that leaked. That test binds every
future driver, not only the existing one.
