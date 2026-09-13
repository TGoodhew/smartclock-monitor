"""A driver for any NMEA 0183 GNSS talker — the second family, and the one that proves the seam.

**A talker is the opposite shape to the SmartClock.** It speaks unprompted, it is never written to,
and it has no command parser to write to — so this driver's allowlist is empty, its link style is
broadcast, and it is recognised by what it *said* rather than by an answer to a question it would
not understand.

**It fills only what NMEA carries, and invents nothing.** There is no 1 PPS time interval, no
oscillator EFC, no TFOM, no holdover — those are disciplined-oscillator concepts and a GNSS
receiver has none of them. §11.1's discipline is what makes this safe rather than broken: every
consumer already handles ``None``, so the Timing page shows dashes and §12's capability gate greys
every control this family cannot drive. A driver that filled those fields with plausible numbers
would be worse than one that leaves them empty, because nothing downstream could tell.

**The mode is this driver's interpretation, and it is one line.** §12's #304 item 3 moved that
decision into the driver for exactly this reason: "locked" means a disciplined oscillator to a
SmartClock and a position fix to a talker, and §9's half — the severity, the shape, the word — is
no driver's business.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from smartclock_device.clock import Clock
from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import WHOLE_CYCLE, Cadence, LinkStyle, PollPlan
from smartclock_device.drivers.capability import Capability, CommandGroup
from smartclock_device.drivers.nmea import sentences
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.position import GeoPosition, HeightDatum, PositionMode
from smartclock_device.models.receiver_status import (
    OutputValidity,
    ReceiverStatus,
    SignalStrengthKind,
    SmartClockMode,
    TimeScale,
)
from smartclock_device.models.satellite import (
    Constellation,
    PredictedSatellite,
    SatelliteId,
    TrackedSatellite,
)
from smartclock_device.transport.settings import Parity, SerialSettings, StopBits
from smartclock_device.transport.transaction import Transaction

#: A talker's cycle. One a second is the near-universal rate, and both tiers are the same read —
#: a broadcast family has no separate "full" query to spend wire time on, because its full read is
#: the cycle it was going to send anyway.
CADENCE: Final = Cadence(fast=timedelta(seconds=1), full=timedelta(seconds=1))

#: How many recognised sentences it takes to claim a stream.
#:
#: **Two, not one.** A single valid sentence can arrive from another device on a shared bus, and
#: claiming a stream on one would let this driver take over a link that belongs to something else.
#: Two of them, one of which is the fix sentence, is a talker.
CLAIM_THRESHOLD: Final = 2


def _key_command(key: str) -> ScpiCommand:
    """A plan entry for a broadcast family.

    §12: *"on a broadcast link a plan entry is a key, not a query."* It is still a ``ScpiCommand``
    because the plan is one type for both link styles — a second plan type would double every
    signature that touches one, to describe a difference the listener already knows about.
    """
    from smartclock_device.commands.scpi_command import ResponseFormat

    return ScpiCommand(
        mnemonic=key,
        summary=f"NMEA {key} sentences from the last complete cycle",
        response=ResponseFormat.MULTI_LINE,
    )


#: **The boundaries are declared rather than implied.** §12's default is the first fast-tier entry,
#: which is the same thing as naming GGA only while a family has one spelling of its fix sentence.
#: This one has two — see `sentences.FIX_KINDS` — and a receiver sending the other read as silence.
PLAN: Final = PollPlan(
    fast=tuple(_key_command(key) for key in sentences.KEYS),
    full=_key_command(WHOLE_CYCLE),
    boundaries=sentences.FIX_KINDS,
)


@dataclass
class NmeaDriver:
    """Any NMEA 0183 GNSS talker."""

    clock: Clock

    name: str = "NMEA 0183 talker"

    _identified: str | None = field(default=None, init=False)

    # -- What kind of family this is -------------------------------------------------------------

    @property
    def link(self) -> LinkStyle:
        return LinkStyle.BROADCAST

    @property
    def cadence(self) -> Cadence:
        return CADENCE

    @property
    def plan(self) -> PollPlan:
        return PLAN

    # -- Recognition -----------------------------------------------------------------------------

    def recognises(self, identity: DeviceIdentity | None) -> bool:
        """Never by identity. A talker has no ``*IDN?`` and would not answer one."""
        del identity
        return False

    def overhear(self, lines: object) -> bool:
        """Whether what arrived before anything was asked is a talker's.

        Claimed on **two** recognised sentences including a fix sentence, not one: a single valid
        line can come from another device sharing the bus, and claiming on it would take over a
        link that belongs to something else.
        """
        if not isinstance(lines, list | tuple):
            return False

        seen = 0
        fix = False
        for line in lines:
            parsed = sentences.parse(str(line))
            if parsed is None or parsed.kind not in sentences.KEYS:
                continue
            seen += 1
            # Either spelling claims the link. Requiring GGA meant a GNS talker was never claimed
            # at all, so auto-detect walked past a working receiver (#58).
            if parsed.kind in sentences.FIX_KINDS:
                fix = True
                self._identified = parsed.talker

        return fix and seen >= CLAIM_THRESHOLD

    def classify(self, line: str) -> str | None:
        parsed = sentences.parse(line)
        if parsed is None or parsed.kind not in sentences.KEYS:
            return None
        return parsed.kind

    # -- Nothing may be sent ---------------------------------------------------------------------

    def is_allowed(self, mnemonic: str | None) -> bool:
        """**Nothing.** A talker is never written to, so there is no allowlist to be on.

        This is not a stub: §8.1's check asks whether a command is catalogued *for this family*,
        and the honest answer for a family with no command parser is no. §12's capability gate
        turns that into greyed controls with a sentence, rather than buttons that fail on click.
        """
        del mnemonic
        return False

    def is_blocked(self, mnemonic: str | None) -> bool:
        """Nothing is excluded, because nothing can be sent. §8.4 has nothing to bite on here."""
        del mnemonic
        return False

    @property
    def auto_detect_sequence(self) -> tuple[SerialSettings, ...]:
        """NMEA 0183's own rates, and only the ones it specifies.

        4800-8-N-1 is the standard's, and 38400 its high-speed variant; both are 8-N-1, because the
        standard says so and no talker in service departs from it. 9600 is deliberately **absent**:
        the SmartClock names it first, the union de-duplicates, and adding it here would claim
        credit for a combination that is already tried before this family is reached.

        Every entry costs one probe timeout on a port that is not a talker, so this is three rates
        rather than the six the connection dialog offers.
        """
        return (
            SerialSettings(4800, 8, Parity.NONE, StopBits.ONE),
            SerialSettings(38400, 8, Parity.NONE, StopBits.ONE),
        )

    def command(self, capability: Capability) -> ScpiCommand | None:
        """**Nothing, for every capability.** A talker is never written to and has no command
        parser, so there is no command it uses for any of them — and §9.11's gate turns that into a
        disabled control naming this family rather than a button that fails on click."""
        del capability
        return None

    def commands_for(self, group: CommandGroup) -> tuple[ScpiCommand, ...]:
        del group
        return ()

    @property
    def register_fields(self) -> tuple[tuple[str, str], ...]:
        """None. A talker has no status registers, and §10.10 draws nothing rather than five empty
        columns implying registers that were not read."""
        return ()

    def register_query(self, node: str, field: str) -> ScpiCommand | None:
        del node, field
        return None

    def register_setter(self, node: str, field: str) -> ScpiCommand | None:
        del node, field
        return None

    @property
    def commands(self) -> tuple[ScpiCommand, ...]:
        """**Empty**, and §10.11's picker shows it empty. A talker has no command parser, so there
        is no allowlist to be on — and a console that fell back to another family's catalog would
        be offering ninety-eight commands to a device that would read every one of them as noise
        in the middle of its own stream."""
        return ()

    def supports(self, command: ScpiCommand) -> bool:
        del command
        return False

    # -- Reading ---------------------------------------------------------------------------------

    def parse_full(
        self, transaction: Transaction, previous: ReceiverStatus | None
    ) -> ReceiverStatus:
        """Turn one complete cycle into a status. **Never raises** (§11.1)."""
        by_kind: dict[str, list[sentences.Sentence]] = {}
        for line in transaction.lines:
            parsed = sentences.parse(line)
            if parsed is not None and parsed.kind in sentences.KEYS:
                by_kind.setdefault(parsed.kind, []).append(parsed)

        fix = _fix_sentence(by_kind)
        used = _satellites_in_use(by_kind.get(sentences.GSA, []))
        visible = _visible(by_kind.get(sentences.GSV, []))

        tracked = tuple(
            sat for identity, sat in sorted(visible.items()) if _is_used(identity, used)
        )
        not_tracked = tuple(
            PredictedSatellite(
                prn=identity.prn,
                elevation_degrees=sat.elevation_degrees,
                azimuth_degrees=sat.azimuth_degrees,
                attempting_to_track=False,
                constellation=identity.constellation,
            )
            for identity, sat in sorted(visible.items())
            if not _is_used(identity, used)
        )

        moment = _timestamp(by_kind.get(sentences.RMC, []), fix)

        return ReceiverStatus(
            captured_at=self.clock.utc_now(),
            mode=_mode(fix),
            outputs=OutputValidity.VALID if _has_fix(fix) else OutputValidity.UNKNOWN,
            gps_one_pps_valid=_has_fix(fix),
            tracked=tracked,
            not_tracked=not_tracked,
            # GSV reports carrier-to-noise density in dB-Hz, which is the C/N scale §11.1 names —
            # so the sky plot's ramp and the strength bar are both correct without conversion.
            signal_strength_kind=SignalStrengthKind.CARRIER_TO_NOISE,
            # A talker reports UTC. It is not on the GPS time scale and saying so matters: §10.14
            # renders the scale because UTC and GPS differ by the accumulated leap seconds.
            time_scale=TimeScale.UTC,
            device_date_time=moment,
            corrected_date_time=moment,
            position=_position(fix),
            position_mode=PositionMode.UNKNOWN,
            # GGA's altitude is above mean sea level and the sentence carries the geoid separation
            # separately, so the datum is knowable rather than assumed — which is the same care
            # §10.6 records for the SmartClock's own height field.
            height_datum=HeightDatum.MSL if _position(fix) is not None else HeightDatum.UNKNOWN,
            health_ok=_has_fix(fix),
        )

    def apply_fast(self, status: ReceiverStatus, results: dict[str, Transaction]) -> ReceiverStatus:
        """A broadcast family's tiers read the same cycle, so the full parse has already done it.

        Returned unchanged rather than re-parsed: the fast sweep and the full read are the same
        sentences here, and folding them twice would be arithmetic for its own sake.
        """
        del results
        return status


# ---- The mapping decisions, each one this driver's --------------------------------------------


#: The GNS mode character for a constellation that contributed nothing.
#:
#: The field is **one character per constellation**, not a fixed code — `DN` from a VK-162 with two
#: and `ANNN` from a forM8N with four. So the question "is there a fix" is *"is any character not
#: this one"*, and a reader expecting a fixed-width code would get the wrong answer on one of the
#: two receivers in the corpus.
NO_CONSTELLATION_FIX: Final = "N"


def _fix_sentence(by_kind: dict[str, list[sentences.Sentence]]) -> sentences.Sentence | None:
    """Whichever fix sentence this talker sends, in the order `FIX_KINDS` gives them.

    A receiver sends GGA or GNS, and twelve captures say never both. Where both did arrive this
    prefers GGA, because its quality field is an integer with a defined meaning and GNS's mode
    string has to be interpreted — given a choice, take the reading that needs no interpreting.
    """
    for kind in sentences.FIX_KINDS:
        found = by_kind.get(kind, ())
        if found:
            return found[0]
    return None


def _has_fix(fix: sentences.Sentence | None) -> bool:
    """Whether the fix sentence reports one, in whichever way its spelling reports it."""
    if fix is None:
        return False

    if fix.kind == sentences.GNS:
        mode = fix.field(5)
        return mode is not None and any(c != NO_CONSTELLATION_FIX for c in mode)

    quality = sentences.parse_int(fix.field(5))
    return quality is not None and quality > 0


def _mode(fix: sentences.Sentence | None) -> SmartClockMode:
    """§12's #304 item 3: the mode is the driver's.

    "Locked" means a disciplined oscillator to a SmartClock and a position fix to a talker, and
    mapping one onto the other is a claim only the driver is in a position to make. A talker with
    no fix is *searching*, which is RECOVERY's shape — it is not in holdover, because it has no
    oscillator to hold over on.
    """
    if fix is None:
        return SmartClockMode.UNKNOWN
    return SmartClockMode.LOCKED if _has_fix(fix) else SmartClockMode.RECOVERY


def _position(fix: sentences.Sentence | None) -> GeoPosition | None:
    """Latitude, longitude and height, from either spelling.

    The three fields sit at the same indices in both sentences, which is why this needs no branch
    where :func:`_has_fix` does. What differs is the field *after* the height: GGA puts the unit
    there and GNS the geoid separation — neither of which is read here, so neither matters yet.
    """
    if fix is None:
        return None

    latitude = sentences.parse_degrees(fix.field(1), fix.field(2))
    longitude = sentences.parse_degrees(fix.field(3), fix.field(4))
    if latitude is None or longitude is None:
        return None

    return GeoPosition(
        latitude_degrees=latitude,
        longitude_degrees=longitude,
        height_metres=sentences.parse_float(fix.field(8)),
    )


#: Where GSA puts NMEA 4.11's GNSS system id, when it carries one at all.
GSA_SYSTEM_ID: Final = 17


def _gsa_constellation(sentence: sentences.Sentence, prn: int) -> Constellation:
    """Which system one of a GSA sentence's slots belongs to.

    Two sources, and the corpus says exactly which applies when: a ``GN`` GSA always carries
    NMEA 4.11's system id in its last field (7,976 of them across the fixtures, none missing), and a
    single-constellation GSA never does but names the system in its talker instead. Neither case is
    a guess.

    **Per slot rather than per sentence**, and the number is passed through, because the talker is
    not always the whole answer: NMEA numbers satellite-based augmentation 33–64 *inside* the GPS
    talker, so one ``$GPGSA`` can hold both GPS and SBAS. Deciding once per sentence made every
    WAAS satellite a GPS one here and an SBAS one in GSV, so the two never matched and the tracked
    list quietly lost them — 12 tracked down to 10 in ``vk162-steady-state``, which is the very
    symptom #57 exists to remove rather than introduce.
    """
    system = sentence.field(GSA_SYSTEM_ID)
    if system is not None and system in sentences.SYSTEM_IDS:
        return sentences.SYSTEM_IDS[system]
    return sentences.constellation_for(sentence.talker, prn)


def _satellites_in_use(gsa: list[sentences.Sentence]) -> set[SatelliteId]:
    """GSA's twelve slots, as identities. Empty slots are empty fields, not zeros."""
    used: set[SatelliteId] = set()
    for sentence in gsa:
        for index in range(2, 14):
            prn = sentences.parse_int(sentence.field(index))
            if prn:
                used.add(SatelliteId(prn=prn, constellation=_gsa_constellation(sentence, prn)))
    return used


def _is_used(identity: SatelliteId, used: set[SatelliteId]) -> bool:
    """Whether GSA offered this satellite to the solution.

    Matched on the full identity, which is the point of #57. **The fallback matters more than the
    match**: where GSA could not say which system its slots belong to — a ``GN`` talker with no
    system id, which no receiver in the corpus is but the standard permits — the identity is
    ``UNKNOWN`` and an exact match would find nothing, emptying the tracked list for a receiver
    that had been working. So an unknown-constellation entry matches on the number alone, which is
    the behaviour this had before and is strictly better than dropping every satellite.
    """
    if identity in used:
        return True
    return any(
        other.constellation is Constellation.UNKNOWN and other.prn == identity.prn for other in used
    )


def _visible(gsv: list[sentences.Sentence]) -> dict[SatelliteId, TrackedSatellite]:
    """GSV's four-satellite groups, across however many sentences the talker paged them into.

    **Keyed by identity, not by number.** Keyed by number, the second claimant of a number was
    silently dropped: every one of the 632 cycles in ``form8n-wsl-bench.nmea``, where GPS 4 and
    BeiDou 4 are in view together.
    """
    found: dict[SatelliteId, TrackedSatellite] = {}
    for sentence in gsv:
        for group in range(4):
            base = 3 + group * 4
            prn = sentences.parse_int(sentence.field(base))
            if prn is None:
                continue
            constellation = sentences.constellation_for(sentence.talker, prn)
            identity = SatelliteId(prn=prn, constellation=constellation)
            found[identity] = TrackedSatellite(
                prn=prn,
                elevation_degrees=sentences.parse_int(sentence.field(base + 1)),
                azimuth_degrees=sentences.parse_int(sentence.field(base + 2)),
                # Absent where the talker sees a satellite it is not tracking, which is precisely
                # the distinction §10.5's table draws — so it stays None rather than becoming 0.
                signal_strength=sentences.parse_int(sentence.field(base + 3)),
                constellation=constellation,
            )
    return found


def _timestamp(rmc: list[sentences.Sentence], gga: sentences.Sentence | None) -> datetime | None:
    """RMC carries the date; GGA carries only the time of day.

    **No date is inferred from the host clock.** A talker that has not yet decoded the almanac
    sends a time and no date, and pairing it with today's date here would produce a timestamp that
    looked authoritative and came half from this machine — which is the §7.4 mistake in a
    different costume.
    """
    if not rmc:
        return None

    sentence = rmc[0]
    clock_field = sentence.field(0)
    date_field = sentence.field(8)
    if clock_field is None or date_field is None or len(date_field) < 6:
        return None

    try:
        hour, minute = int(clock_field[0:2]), int(clock_field[2:4])
        second = int(clock_field[4:6])
        day, month, year = (
            int(date_field[0:2]),
            int(date_field[2:4]),
            int(date_field[4:6]),
        )
        # RMC's two-digit year. The sentence has carried it since 1983 and there is no more of it
        # to read, so the century is a convention rather than data — 2000-based, which every
        # talker in service assumes and which this records as an assumption rather than a fact.
        return datetime(2000 + year, month, day, hour, minute, second, tzinfo=UTC)
    except ValueError:
        return None
