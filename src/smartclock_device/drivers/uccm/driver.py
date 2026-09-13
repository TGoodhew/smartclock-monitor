"""The UCCM family: recognition, identity, and an honest label (D7, #63).

**This driver has never met a receiver.** Every line of it is written against
[`tests/fixtures/uccm/`](../../../../tests/fixtures/uccm) — seven sittings with a Trimble UCCM-P,
captured in WinZ3805A between 10 and 13 September 2026 — and there is no UCCM within reach of this
bench to check any of it against.

D7 takes the family anyway, on the grounds that a driver which *says* it is unverified serves the
one person who owns a UCCM better than no driver. The rules that decision set are not decoration:

- **Every assertion traces to a capture, or it is not made.** Where the corpus is silent this
  driver is silent too, rather than inferring from a datasheet nobody here has read.
- **The two states upstream's driver cannot tell apart stay untold-apart.** Reproducing a known
  limitation is correct; resolving it without a receiver would be the guess D7 exists to prevent.
- **The label is user-visible**, not a docstring. :attr:`is_verified` is what the connection dialog
  and the identity card read.

What this file does *not* do yet is parse a status screen. That is a separate change against the
same captures; recognising the receiver, connecting to it and saying plainly what it is comes
first, because a driver that connects and shows nothing is honest where one that shows a guess is
not.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Final

from smartclock_device.clock import Clock
from smartclock_device.commands.scpi_command import ResponseFormat, ScpiCommand
from smartclock_device.drivers.base import Cadence, LinkStyle, PollPlan, QueryResponseDefaults
from smartclock_device.drivers.capability import Capability, CommandGroup, ReceiverReading
from smartclock_device.drivers.uccm import time_code
from smartclock_device.drivers.uccm.profile import (
    PROMPTS,
    VENDOR_TOKENS,
    UccmProfile,
    UccmVariant,
    UccmVendor,
)
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode, TimeScale
from smartclock_device.parsing.uccm_screen import UccmScreenParser
from smartclock_device.transport.settings import Parity, SerialSettings, StopBits
from smartclock_device.transport.transaction import Transaction

#: §10.12's eleventh auto-detect combination, and the only one this family answers on.
#:
#: Measured rather than assumed: the sibling's #470 established it by walking the others first, and
#: every capture in the corpus carries `Port COM3 at 57600-8-N-1` in its header.
LINE_SETTINGS: Final = SerialSettings(
    baud_rate=57600, data_bits=8, parity=Parity.NONE, stop_bits=StopBits.ONE
)

#: The status screen, which is spelled without a leading colon on this family.
#:
#: `SYST:STAT?`, not `:SYST:STAT?` — that is what the captures record as sent and answered, and it
#: is exactly the kind of difference the sibling's *"ask the drifted queries the way the driver
#: spells them"* exists to stop anybody guessing at.
STATUS_SCREEN: Final = ScpiCommand(
    mnemonic="SYST:STAT?",
    summary="The UCCM status screen",
    response=ResponseFormat.MULTI_LINE,
)

#: The identity query, which this family answers in the SmartClock's own form.
IDENTITY: Final = ScpiCommand(
    mnemonic="*IDN?",
    summary="Manufacturer, model, serial number and firmware revision",
    response=ResponseFormat.TEXT,
)

#: §8.1's catalogue for this family, as far as the corpus establishes it.
#:
#: **Two entries, not eight.** `catalog-spellings-12sep2026` records which of the sibling's
#: catalogued spellings this firmware actually answers, and porting the rest belongs with the
#: status parser rather than here — a catalogue entry that has never been sent is a claim, and D7
#: says claims trace to captures.
COMMANDS: Final[tuple[ScpiCommand, ...]] = (IDENTITY, STATUS_SCREEN)

#: §7.3's two tiers. The full read is the screen; there is no scalar sweep in the corpus to model a
#: fast tier on, so both tiers read the same thing until one is captured.
CADENCE: Final = Cadence(fast=timedelta(seconds=2), full=timedelta(seconds=10))

PLAN: Final = PollPlan(fast=(STATUS_SCREEN,), full=STATUS_SCREEN)


#: What each decoded state means in §11.2's vocabulary.
#:
#: `COLD` and `ACQUIRING` both map to RECOVERY — a module searching for a fix is what that shape
#: describes — and they are kept apart in :class:`UccmState` rather than here, because the
#: distinction is real on the wire even where §11.2 has one word for both.
_MODES: Final[dict[time_code.UccmState, SmartClockMode]] = {
    time_code.UccmState.LOCKED: SmartClockMode.LOCKED,
    time_code.UccmState.HOLDOVER: SmartClockMode.HOLDOVER,
    time_code.UccmState.ACQUIRING: SmartClockMode.RECOVERY,
    time_code.UccmState.COLD: SmartClockMode.RECOVERY,
    time_code.UccmState.UNKNOWN: SmartClockMode.UNKNOWN,
}


@dataclass(slots=True)
class UccmDriver(QueryResponseDefaults):
    """A UCCM, of whichever vendor and variant the link turns out to hold."""

    clock: Clock

    _profile: UccmProfile = field(default=UccmProfile(), init=False)

    # -- What kind of family this is -------------------------------------------------------------

    @property
    def name(self) -> str:
        """Named for what was established, and never for what was assumed.

        Before an identity is read this is the bare "UCCM"; afterwards it carries whichever of the
        vendor and the variant the link actually said.
        """
        return self._profile.name

    @property
    def is_verified(self) -> bool:
        """**False, and it is meant to be read** (D7).

        Not a docstring and not a comment: the connection dialog and §10.4's identity card show
        this to a user, because a driver written entirely from somebody else's captures is a
        different thing from one that has met the receiver it claims to drive, and only the person
        in front of it can decide what to do about that.
        """
        return False

    @property
    def cadence(self) -> Cadence:
        return CADENCE

    @property
    def plan(self) -> PollPlan:
        return PLAN

    @property
    def link(self) -> LinkStyle:
        return LinkStyle.QUERY_RESPONSE

    @property
    def prompt_words(self) -> tuple[str, ...]:
        """`UCCM-P >` and `UCCM >`, as §7.2's grammar rather than as a literal.

        The corpus carries `UCCM-P >` 162 times. `UCCM` is here because the plain variant exists
        and its prompt is the obvious shorter form — **which is an inference, and is the one place
        in this file that is**. It is a prompt word rather than a reading, so being wrong about it
        costs a family that will not connect rather than a figure that is quietly false.
        """
        return tuple(PROMPTS)

    # -- Recognition -----------------------------------------------------------------------------

    def recognises(self, identity: DeviceIdentity | None) -> bool:
        """Whether `*IDN?` says this is a UCCM.

        `TRIMBLE,57964-80,40896646,V2.0.1.6-01` is the whole of the evidence — one vendor, one
        part number. Matching on the **vendor token** rather than the part number is deliberate:
        a part number identifies one module and the corpus has exactly one, so keying on it would
        make this driver serve precisely the unit nobody here owns.

        A SmartClock also answers `SYMMETRICOM,...`, so vendor alone cannot be the whole test; the
        model is checked against the SmartClock's own names first by the registry, which asks that
        family first.
        """
        if identity is None:
            return False
        return self._vendor_of(identity) is not UccmVendor.UNKNOWN

    def adopt(self, identity: DeviceIdentity | None, prompt: str | None) -> None:
        """Record what the link established, from the identity and the prompt.

        **The variant comes from the prompt, not from `*IDN?`** — the sibling's `08c62c1`,
        *"Take the UCCM variant from the prompt, because asking does not work"*. The identity gives
        a part number that says nothing about the variant; the prompt says it outright.
        """
        vendor = self._vendor_of(identity) if identity is not None else UccmVendor.UNKNOWN
        variant = UccmVariant.UNKNOWN
        if prompt is not None:
            token = prompt.strip().rstrip(">").strip()
            variant = PROMPTS.get(token.upper(), UccmVariant.UNKNOWN)
        self._profile = UccmProfile(vendor=vendor, variant=variant)

    @property
    def profile(self) -> UccmProfile:
        return self._profile

    @staticmethod
    def _vendor_of(identity: DeviceIdentity) -> UccmVendor:
        maker = (identity.manufacturer or "").strip().upper()
        return VENDOR_TOKENS.get(maker, UccmVendor.UNKNOWN)

    @property
    def auto_detect_sequence(self) -> tuple[SerialSettings, ...]:
        """§10.12's eleventh combination, and this family's only one."""
        return (LINE_SETTINGS,)

    # -- What may be sent ------------------------------------------------------------------------

    def is_allowed(self, mnemonic: str | None) -> bool:
        return any(command.mnemonic == mnemonic for command in COMMANDS)

    def is_blocked(self, mnemonic: str | None) -> bool:
        """§8.4 binds every family. The predicate is the shared one, asked through this seam."""
        from smartclock_device.commands.blocked import is_blocked

        return is_blocked(mnemonic)

    def outgoing_text_for(self, mnemonic: str | None) -> str | None:
        """Nothing. A query/response family's mnemonic *is* its wire text (D8)."""
        del mnemonic
        return None

    @property
    def commands(self) -> tuple[ScpiCommand, ...]:
        return COMMANDS

    def supports(self, command: ScpiCommand) -> bool:
        return command in COMMANDS

    def command(self, capability: Capability) -> ScpiCommand | None:
        """**Nothing yet.** No capability in the corpus has been exercised against this family.

        §9.11 turns that into greyed controls with a sentence naming the family, which is the right
        answer for a driver that has never met its receiver: offering a control that has never been
        sent would be a claim D7 forbids.
        """
        del capability
        return None

    def commands_for(self, group: CommandGroup) -> tuple[ScpiCommand, ...]:
        del group
        return ()

    @property
    def register_fields(self) -> tuple[tuple[str, str], ...]:
        return ()

    def register_query(self, node: str, field_name: str) -> ScpiCommand | None:
        del node, field_name
        return None

    def register_setter(self, node: str, field_name: str) -> ScpiCommand | None:
        del node, field_name
        return None

    # -- What it can never know ------------------------------------------------------------------

    #: What the corpus establishes this family does not report (#483, via D7).
    #:
    #: Read off the captured screen rather than guessed: it carries no diagnostic log, no error
    #: queue, no status registers and no holdover figures. It **does** carry TFOM, FFOM, an antenna
    #: delay, an elevation mask and a position mode, so those are not declined.
    #:
    #: **The oscillator control was in this set and has been taken out** (#98). It was declined on
    #: the grounds that no capture shows one, with a comment admitting that rested on seven
    #: sittings *not showing a field* rather than on a receiver saying it has none. Lady Heather
    #: 5.00 queries `DIAG:ROSC:EFC:DATA?` on this family, so the reading exists — it is simply not
    #: on the status screen, which is a different fact. A **decline is a strictly stronger claim
    #: than a dash**, so a claim contradicted by a citation goes back to the dash §11.1 means by
    #: *not yet*. Softening needs no new evidence; asserting would.
    NEVER_REPORTS: Final[frozenset[ReceiverReading]] = frozenset(
        {
            ReceiverReading.DIAGNOSTIC_LOG,
            ReceiverReading.ERROR_QUEUE,
            ReceiverReading.STATUS_REGISTERS,
            ReceiverReading.POWER_ON_HOURS,
            ReceiverReading.GPS_ENGINE_IDENTITY,
            ReceiverReading.HEALTH_MONITOR,
            ReceiverReading.LEAP_SECOND,
            ReceiverReading.TIME_CODE_FORMAT,
            ReceiverReading.POSITION_UNCERTAINTY,
            ReceiverReading.CONSTELLATION_INTEGRITY,
            ReceiverReading.FIX_QUALITY,
            ReceiverReading.GPS_UTC_OFFSET,
        }
    )

    def reports(self, reading: ReceiverReading) -> bool:
        return reading not in self.NEVER_REPORTS

    # -- Reading ---------------------------------------------------------------------------------

    def parse_full(
        self, transaction: Transaction, previous: ReceiverStatus | None
    ) -> ReceiverStatus:
        """One status screen, read by `parsing/uccm_screen.py`. **Never raises** (§11.1)."""
        del previous
        return UccmScreenParser(self.clock).parse(transaction.text)

    def apply_time_code(self, status: ReceiverStatus, frame: bytes) -> ReceiverStatus:
        """Fold one broadcast time code into the status the screen produced.

        **This is where holdover comes from**, and it comes from nowhere else. The text screen is
        silent about it: through fourteen minutes with no antenna the module never degraded TFOM or
        FFOM past 2 and never moved off `UCCM A Status[ACTIVE]`. The five state bytes say it
        outright, which is why `parse_full` alone leaves the mode `UNKNOWN` and this fills it in.
        """
        code = time_code.decode(frame)
        if code is None:
            return status

        return dataclasses.replace(
            status,
            mode=_MODES[code.state],
            gps_one_pps_valid=code.state is time_code.UccmState.LOCKED,
            device_date_time=code.utc_time,
            corrected_date_time=code.utc_time,
            time_scale=TimeScale.UTC if code.utc_time is not None else status.time_scale,
        )

    def apply_fast(self, status: ReceiverStatus, results: dict[str, Transaction]) -> ReceiverStatus:
        del results
        return status

    def overhear(self, lines: Sequence[str]) -> bool:
        """Never. A UCCM is asked, not overheard."""
        del lines
        return False

    def classify(self, line: str) -> str | None:
        del line
        return None
