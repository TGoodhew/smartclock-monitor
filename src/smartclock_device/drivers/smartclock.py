"""The SmartClock family driver: the Z3805A and its siblings.

§7.3's schedule is this family's, which is why it lives here and not in the polling service.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from smartclock_device.clock import Clock
from smartclock_device.commands import catalog
from smartclock_device.commands.blocked import is_blocked as _is_blocked
from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import Cadence, PollPlan, QueryResponseDefaults
from smartclock_device.drivers.capability import Capability, CommandGroup
from smartclock_device.models.device_identity import DeviceIdentity, ReceiverModel
from smartclock_device.models.receiver_status import ReceiverStatus
from smartclock_device.parsing.scalars import (
    parse_decimal,
    parse_integer,
    parse_seconds_as_nanoseconds,
)
from smartclock_device.parsing.status_screen import StatusScreenParser
from smartclock_device.transport.settings import AUTO_DETECT_SEQUENCE, SerialSettings
from smartclock_device.transport.transaction import Transaction

#: §7.3: 1 s for the scalar sweep, 10 s for the screen.
#:
#: The full screen consumes 3,521 ms measured of its 10 s window at 9600 baud. The scheduler must
#: never let the two tiers overlap — they share one command channel, so the fast tier stalls behind
#: a screen fetch. That is acceptable; interleaving them is not.
CADENCE: Final = Cadence(fast=timedelta(seconds=1), full=timedelta(seconds=10))

#: §7.3's sweep, with the state query first so §7.3.1's rule can key on it.
PLAN: Final = PollPlan(
    fast=catalog.FAST_TIER,
    full=catalog.STATUS_SCREEN,
    refusable=catalog.REFUSABLE,
    state_query=catalog.SYNC_STATE,
)


@dataclass(slots=True)
class SmartClockDriver(QueryResponseDefaults):
    """The Z3805A, Z3801A, Z3816A, 58503A/B and 59551A."""

    clock: Clock

    name: str = "SmartClock (HP/Symmetricom)"

    @property
    def cadence(self) -> Cadence:
        return CADENCE

    @property
    def plan(self) -> PollPlan:
        return PLAN

    def is_allowed(self, mnemonic: str | None) -> bool:
        """The point-of-send allowlist check (§8.1)."""
        return catalog.is_allowed(mnemonic)

    def recognises(self, identity: DeviceIdentity | None) -> bool:
        """Whether this is a SmartClock-family receiver.

        Keyed on the parsed model rather than on the manufacturer string: §8.6's profile already
        decides which member of the family answered, and ``UNKNOWN`` means the identity did not
        name one this build knows — which is a receiver this driver should not claim, so that a
        later-registered family gets its turn.
        """
        return identity is not None and identity.receiver is not ReceiverModel.UNKNOWN

    @property
    def auto_detect_sequence(self) -> tuple[SerialSettings, ...]:
        """§7.1's eight combinations. The note on the constant records why odd parity sits
        second, and what an even-parity spelling with no source behind it cost."""
        return AUTO_DETECT_SEQUENCE

    def command(self, capability: Capability) -> ScpiCommand | None:
        """This family's command for a capability. Every one of them is offered."""
        return _BY_CAPABILITY.get(capability)

    def commands_for(self, group: CommandGroup) -> tuple[ScpiCommand, ...]:
        return _BY_GROUP.get(group, ())

    @property
    def register_fields(self) -> tuple[tuple[str, str], ...]:
        return catalog.REGISTER_FIELDS

    def register_query(self, node: str, field: str) -> ScpiCommand | None:
        return catalog.register_query(f":STAT:{node}", field)

    def register_setter(self, node: str, field: str) -> ScpiCommand | None:
        return catalog.register_setter(f":STAT:{node}", field)

    @property
    def commands(self) -> tuple[ScpiCommand, ...]:
        """This family's allowlist. §8.4's exclusions are not in it, because they are not in it —
        the catalog has no entry for them to be filtered out of."""
        return catalog.ALL

    def supports(self, command: ScpiCommand) -> bool:
        """This family's catalog **is** the SmartClock catalog, so membership is the answer.

        Compared by mnemonic rather than by identity: a command object built elsewhere that names
        a catalogued mnemonic is the same command, and one that does not is not this family's
        however it was constructed.
        """
        return catalog.is_allowed(command.mnemonic)

    def is_blocked(self, mnemonic: str | None) -> bool:
        """§8.4, routed through the driver so the application never imports the module itself."""
        return _is_blocked(mnemonic)

    def parse_full(
        self, transaction: Transaction, previous: ReceiverStatus | None = None
    ) -> ReceiverStatus:
        """Parse the status screen.

        ``previous`` is ignored: a status screen is complete in itself, and folding an old one in
        would let a field that has *stopped* being reported keep its stale value. A family whose
        full read is incremental would use it.
        """
        return StatusScreenParser(self.clock).parse(transaction.text)

    def apply_fast(self, status: ReceiverStatus, results: dict[str, Transaction]) -> ReceiverStatus:
        """Fold the fast-tier answers into the status the full tier last produced.

        Every field is taken only when its transaction **succeeded and returned something**. A
        refused query answers with the prompt alone (§7.2), and writing ``None`` over a good value
        because of one refusal would make the main window flicker between a reading and a dash once
        a second — which is what §7.3.1 exists to prevent the cause of.
        """
        changes: dict[str, object] = {}

        tfom = _scalar(results, catalog.TIME_FIGURE_OF_MERIT.mnemonic, parse_integer)
        if tfom is not None:
            changes["tfom"] = tfom

        ffom = _scalar(results, catalog.FREQUENCY_FIGURE_OF_MERIT.mnemonic, parse_integer)
        if ffom is not None:
            changes["ffom"] = ffom

        interval = _scalar(results, catalog.TIME_INTERVAL.mnemonic, parse_seconds_as_nanoseconds)
        if interval is not None:
            changes["one_pps_ti_nanoseconds"] = interval

        if not changes:
            return status

        return dataclasses.replace(status, **changes)  # type: ignore[arg-type]


def _scalar[T](
    results: dict[str, Transaction],
    mnemonic: str,
    parse: Callable[[str | None], T | None],
) -> T | None:
    """Parse one fast-tier answer, or ``None`` if it did not arrive.

    ``None`` covers three different things on purpose — the command was not asked, it faulted, or
    the receiver refused it — because the caller does the same thing with all three: keep what it
    had. §7.3.1 is what distinguishes a refusal, and it does so from the prompt rather than here.
    """
    transaction = results.get(mnemonic)
    if transaction is None or not transaction.succeeded:
        return None
    return parse(transaction.first_line)


#: The oscillator EFC and the tracked count are read by the fast tier and carried on the view
#: model rather than on :class:`ReceiverStatus`, which §11.2 defines as what the *screen* reports.
#: Kept here so the poll loop has one place to look for the parsers.
EFC_PARSER: Final = parse_decimal
TRACKED_COUNT_PARSER: Final = parse_integer


#: What this family does for each :class:`Capability`.
#:
#: **Written out rather than resolved by name.** The capability names match the catalog's constants
#: — deliberately, since both are named for intent — so ``getattr(catalog, capability.name)`` would
#: work and would also silently map a renamed capability onto nothing. Spelled in full, a mismatch
#: is a NameError at import and ``test_capability_map.py`` asserts the table is total.
_BY_CAPABILITY: Final[dict[Capability, ScpiCommand]] = {
    Capability.ANTENNA_DELAY: catalog.ANTENNA_DELAY,
    Capability.ELEVATION_MASK: catalog.ELEVATION_MASK,
    Capability.EXCLUDED_SATELLITES: catalog.EXCLUDED_SATELLITES,
    Capability.SURVEY_ON_POWER_UP: catalog.SURVEY_ON_POWER_UP,
    Capability.HOLDOVER_DURATION_THRESHOLD: catalog.HOLDOVER_DURATION_THRESHOLD,
    Capability.DIAGNOSTIC_LOG: catalog.DIAGNOSTIC_LOG,
    Capability.LOG_COUNT: catalog.LOG_COUNT,
    Capability.LIFETIME_HOURS: catalog.LIFETIME_HOURS,
    Capability.ERROR_QUEUE: catalog.ERROR_QUEUE,
    Capability.HARDWARE_CONDITION: catalog.HARDWARE_CONDITION,
    Capability.TIME_CODE_FORMAT: catalog.TIME_CODE_FORMAT,
    Capability.LEAP_ACCUMULATED: catalog.LEAP_ACCUMULATED,
    Capability.LEAP_DATE: catalog.LEAP_DATE,
    Capability.LEAP_DURATION: catalog.LEAP_DURATION,
    Capability.LEAP_STATE: catalog.LEAP_STATE,
    Capability.SET_ANTENNA_DELAY: catalog.SET_ANTENNA_DELAY,
    Capability.SET_ELEVATION_MASK: catalog.SET_ELEVATION_MASK,
    Capability.SET_HOLDOVER_DURATION_THRESHOLD: catalog.SET_HOLDOVER_DURATION_THRESHOLD,
    Capability.SET_SURVEY_ON_POWER_UP: catalog.SET_SURVEY_ON_POWER_UP,
    Capability.SET_POSITION: catalog.SET_POSITION,
    Capability.EXCLUDE_SATELLITES: catalog.EXCLUDE_SATELLITES,
    Capability.EXCLUDE_ALL_SATELLITES: catalog.EXCLUDE_ALL_SATELLITES,
    Capability.CLEAR_EXCLUSIONS: catalog.CLEAR_EXCLUSIONS,
    Capability.START_SURVEY: catalog.START_SURVEY,
    Capability.ADOPT_SURVEYED_POSITION: catalog.ADOPT_SURVEYED_POSITION,
    Capability.RESTORE_LAST_POSITION: catalog.RESTORE_LAST_POSITION,
    Capability.HOLDOVER_FORCE: catalog.HOLDOVER_FORCE,
    Capability.HOLDOVER_RECOVER: catalog.HOLDOVER_RECOVER,
    Capability.HOLDOVER_IGNORE_RECOVERY_LIMIT: catalog.HOLDOVER_IGNORE_RECOVERY_LIMIT,
    Capability.RUN_SELF_TEST: catalog.RUN_SELF_TEST,
    Capability.CLEAR_DIAGNOSTIC_LOG: catalog.CLEAR_DIAGNOSTIC_LOG,
}

#: The sets §10.9 and §10.10 render one control per member of.
_BY_GROUP: Final[dict[CommandGroup, tuple[ScpiCommand, ...]]] = {
    CommandGroup.EXPERIMENTAL: catalog.EXPERIMENTAL,
    CommandGroup.REGISTER_SETTERS: catalog.REGISTER_SETTERS,
}
