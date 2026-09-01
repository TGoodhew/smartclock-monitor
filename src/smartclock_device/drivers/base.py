"""The driver seam: every receiver-specific fact sits behind one of these.

The application never reaches the SmartClock driver or the NMEA driver directly; it asks the driver
the session selected. That is what makes a second family a new file rather than a scatter of
conditionals, and it is why the poll cadence and the sweep are properties of the **driver** rather
than of the application — §7.3's schedule is the SmartClock family's, and a broadcast talker has a
different one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import Final, Protocol, runtime_checkable

from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.capability import Capability, CommandGroup
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.receiver_status import ReceiverStatus
from smartclock_device.transport.settings import SerialSettings
from smartclock_device.transport.transaction import Transaction


class LinkStyle(Enum):
    """Whether a family answers what it is asked, or talks.

    The distinction is not cosmetic: it decides whether the session may *send* at all. A talker is
    the opposite shape to the SmartClock — it speaks unprompted and is never written to after
    recognition — so §7.2's error queue and §8.3's confirmations bind query/response families only.
    There is nothing to confirm about a receiver you cannot address.
    """

    #: Asks and is answered. The default, and the SmartClock's.
    QUERY_RESPONSE = "query-response"

    #: Speaks unprompted. Read by listening, never by asking.
    BROADCAST = "broadcast"


#: §12's whole-cycle key: the full-status "command" for a broadcast family, whose full read is the
#: whole of its last complete cycle rather than any one sentence.
WHOLE_CYCLE: Final = "*"


@dataclass(frozen=True, slots=True)
class Cadence:
    """How often a driver wants its two tiers polled (§7.3).

    Fixed rather than user-settable: §10.13 decided the cadences are deliberately not offered, and
    the scheduler takes them from here.
    """

    #: The scalar sweep that drives the main window and the trend charts.
    fast: timedelta

    #: The full read that drives the satellite table, position and health.
    full: timedelta


@dataclass(frozen=True, slots=True)
class PollPlan:
    """What a driver asks for on each tier.

    ``full`` is a single command for the SmartClock family — the status screen — but need not be:
    a broadcast family's full read is the whole of its last complete cycle, which is why this is a
    plan rather than a hard-coded pair of commands.
    """

    #: The fast tier, in order. The first entry is asked before the rest, so a driver whose rule
    #: depends on knowing a state first (§7.3.1) puts that query at the front.
    fast: tuple[ScpiCommand, ...]

    #: The full read.
    full: ScpiCommand

    #: The fast-tier reading the receiver may legitimately refuse, or ``None``.
    #:
    #: §7.3.1: when a receiver refuses this, it is not asked again until the state query reports a
    #: different state. Keyed on the state rather than on a list of states, because nothing in the
    #: application decides which states support which reading — the receiver is asked once and
    #: believed. A family whose plan has no refusable query leaves this ``None`` and §7.3.1 does
    #: not arise for it.
    refusable: ScpiCommand | None = None

    #: The query whose answer keys the §7.3.1 suppression, or ``None``.
    state_query: ScpiCommand | None = None


@runtime_checkable
class ReceiverDriver(Protocol):
    """Everything the application needs to know about one family of receiver."""

    @property
    def name(self) -> str:
        """What the family is called, for the connection UI and the logs."""
        ...

    @property
    def cadence(self) -> Cadence:
        """How often to poll."""
        ...

    @property
    def plan(self) -> PollPlan:
        """What to ask for."""
        ...

    def is_allowed(self, mnemonic: str | None) -> bool:
        """Whether this command is on **this driver's** allowlist.

        The point-of-send check (§8.1). A reads-only family legitimately allows no setter at all.
        """
        ...

    @property
    def auto_detect_sequence(self) -> tuple[SerialSettings, ...]:
        """The line settings **this family** is worth trying, most-likely-first.

        §10.12's walk is the union of every registered driver's sequence, in registration order and
        de-duplicated — which is only a union once there is a second family with different rates.
        NMEA specifies 4800, and a talker at the standard's own rate was unreachable by auto-detect
        while the sequence was one list belonging to one receiver.

        A family with nothing of its own returns ``()`` and adds nothing to the walk. Every entry
        costs one probe timeout on a port that is not it, so a driver naming rates it does not use
        spends other people's seconds.
        """
        ...

    def command(self, capability: Capability) -> ScpiCommand | None:
        """The command this family uses for one capability, or ``None`` if it has none.

        **This is how a page asks.** It names what it wants done — ``Capability.RUN_SELF_TEST`` —
        and the family answers with its own command or with nothing, so the page never holds
        another family's mnemonic. A talker answers ``None`` to every capability, which is the
        honest answer for a receiver that is never written to.

        ``None`` rather than an error, because §9.11's rule is that an absent command is disabled
        and explained. The page has a control to grey out, not an exception to handle.
        """
        ...

    def commands_for(self, group: CommandGroup) -> tuple[ScpiCommand, ...]:
        """Every command in a set the page offers together, in the order it should show them.

        Separate from :meth:`command` because the *count* is the family's business: §8.5 has six
        experimental queries for the SmartClock and might have none elsewhere. A page renders one
        control per member and must not assume how many there are.
        """
        ...

    @property
    def register_fields(self) -> tuple[tuple[str, str], ...]:
        """§10.10's register fields — the node suffix and what to call it — or empty.

        The register *model* is family-specific structure rather than a capability: a family may
        have five fields per register, or none, and §10.10 renders one column per field. A family
        with no status registers answers ``()`` and the page has nothing to draw.
        """
        ...

    def register_query(self, node: str, field: str) -> ScpiCommand | None:
        """The command that reads one field of one register, or ``None``.

        Composing ``f":STAT:{node}:{field}?"`` at the call site is exactly the coupling §12 is
        about — it is this family's spelling, in a page. The family composes it.
        """
        ...

    def register_setter(self, node: str, field: str) -> ScpiCommand | None:
        """The command that writes one mask field of one register, or ``None``."""
        ...

    @property
    def commands(self) -> tuple[ScpiCommand, ...]:
        """**This family's allowlist, made visible.** §10.11's console picker is exactly this.

        Enumerable on purpose, and the asymmetry with :meth:`is_blocked` is §8.1's whole design:
        an allowlist is a list of what may be sent and showing it is the point, while the §8.4
        exclusions are never a list at all — they are not entries carrying a flag, they do not
        exist as data, and the only thing exposed about them is a verdict on one candidate.

        A family with no command parser returns ``()``, and the console then shows an empty picker
        with an explanation rather than offering another family's ninety-eight.
        """
        ...

    def supports(self, command: ScpiCommand) -> bool:
        """Whether **this family** can send this command at all.

        Asked by a page before it offers a control, so a family that has no such command gets a
        disabled control with an explanation rather than a button that fails on click — or, worse,
        a crash on navigation. §12's #304 records that exact defect in the original: every Details
        page asked for its tier C commands with a form that throws, which was "correct while one
        family shipped, and a crash on navigation the day a reads-only talker arrived".

        Distinct from :meth:`is_allowed`, which takes a mnemonic and answers the *point-of-send*
        question. This takes a command object and answers a question about the family, before
        anything is sent and often before anything is connected.
        """
        ...

    def is_blocked(self, mnemonic: str | None) -> bool:
        """Whether §8.4 excludes this command for this family.

        Routed through the driver so the application never imports the exclusion module itself. A
        family with nothing it can write legitimately answers ``False`` for everything, there being
        nothing to exclude.
        """
        ...

    @property
    def link(self) -> LinkStyle:
        """How this family is read. Defaults to query/response for anything that does not say."""
        ...

    def overhear(self, lines: Sequence[str]) -> bool:
        """Whether the lines heard **before anything was asked** are this family's.

        The session hands every driver what the synchronise step absorbed, and the first to claim
        them is selected — so a talker is recognised here and ``*IDN?`` is never sent to it. That
        matters beyond tidiness: a talker has no command parser, and a question put to one is
        noise in the middle of its stream.

        A query/response family answers ``False`` and is recognised by its identity instead.
        """
        ...

    def classify(self, line: str) -> str | None:
        """Which plan key a heard line belongs to, or ``None`` if it is not this family's.

        Only a broadcast family needs this. The key is what a listener files the line under, and
        the plan's first fast-tier entry is the one that delimits a cycle.
        """
        ...

    def recognises(self, identity: DeviceIdentity | None) -> bool:
        """Whether this family claims the receiver that answered ``*IDN?``.

        **Required, and a family that claims nothing returns ``False``.** Making it optional was
        the first design and it was worse: an absent method says "the author forgot" where an
        explicit ``False`` says "I claim nothing", and the registry's fallback then reaches the
        second on purpose rather than by accident.

        ``None`` — nothing answered — is not a claim either. A receiver that says nothing is the
        ordinary state of most of §7.1's combinations during auto-detect.
        """
        ...

    def parse_full(
        self, transaction: Transaction, previous: ReceiverStatus | None
    ) -> ReceiverStatus:
        """Turn the full-tier response into a status.

        :param previous: The last status, so a driver whose full read is incremental can build on
            it. The SmartClock driver ignores it — a status screen is complete in itself.
        """
        ...

    def apply_fast(self, status: ReceiverStatus, results: dict[str, Transaction]) -> ReceiverStatus:
        """Fold the fast-tier answers into the status the full tier last produced."""
        ...


class QueryResponseDefaults:
    """The three broadcast members, answered the way a family that asks questions answers them.

    §12 records that the C# contract *"gained three defaulted members"* when the second family
    arrived. A Python ``Protocol`` cannot default anything for its implementers, so this carries
    them: a query/response driver inherits it and says nothing about listening, and a broadcast one
    overrides all three.

    Deliberately **not** part of the Protocol's own definition. A driver is anything that satisfies
    the contract, and requiring a base class would make the twenty-line test double in
    ``test_capability.py`` inherit from the library it is standing in for.
    """

    @property
    def link(self) -> LinkStyle:
        return LinkStyle.QUERY_RESPONSE

    def overhear(self, lines: Sequence[str]) -> bool:
        """A family that is asked is recognised by its identity, not by what it said first."""
        del lines
        return False

    def classify(self, line: str) -> str | None:
        """Nothing is filed by line: every answer belongs to the question that provoked it."""
        del line
        return None
