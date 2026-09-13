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

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from smartclock_device.clock import Clock
from smartclock_device.commands.scpi_command import ResponseFormat, ScpiCommand
from smartclock_device.drivers.base import WHOLE_CYCLE, Cadence, LinkStyle, PollPlan
from smartclock_device.drivers.capability import Capability, CommandGroup, ReceiverReading
from smartclock_device.drivers.nmea import sentences
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.fix_quality import (
    GGA_QUALITIES,
    GNS_MODES,
    ConstellationIntegrity,
    FixQuality,
    PositionUncertainty,
    best_of,
)
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
    return ScpiCommand(
        mnemonic=key,
        summary=f"NMEA {key} sentences from the last complete cycle",
        response=ResponseFormat.MULTI_LINE,
    )


#: §8.1's catalogue for this family: **one entry**, and it is a key rather than wire text (D8).
#:
#: Given its own summary rather than `_key_command`'s, which describes a *read* — "sentences from
#: the last complete cycle" — and would be the one entry in the catalogue where that is false. This
#: is the one thing this family sends, and §10.11's picker shows the summary to whoever is about to
#: send it.
TIME_POLL_COMMAND: Final = ScpiCommand(
    mnemonic=sentences.TIME_POLL_KEY,
    summary="Time and clock poll — GPS − UTC, answered only by a u-blox module",
    response=ResponseFormat.MULTI_LINE,
)


#: **The boundaries are declared rather than implied.** §12's default is the first fast-tier entry,
#: which is the same thing as naming GGA only while a family has one spelling of its fix sentence.
#: This one has two — see `sentences.FIX_KINDS` — and a receiver sending the other read as silence.
PLAN: Final = PollPlan(
    fast=tuple(_key_command(key) for key in sentences.KEYS),
    full=_key_command(WHOLE_CYCLE),
    boundaries=sentences.FIX_KINDS,
    # **Nothing**, and that is the honest answer rather than an omission (#61). Both of this
    # family's tiers read the same cycle, so the fast sweep is answerable for nothing the full
    # read has not already done — which is exactly why `apply_fast` returns the status unchanged.
    fast_readings=(),
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
        """**Exactly one entry** (D8, §7.2 gate 1).

        This answered *nothing* until #64, on the reasoning that a talker has no command parser.
        That is still true of everything but one sentence: `$PUBX,04` is a *poll*, answered by a
        u-blox module, and it carries GPS − UTC which no standard sentence does.

        §8.1's property is preserved rather than weakened — **no text can be sent for which there
        is no catalogue entry** — and on this link the entry is a key rather than the text itself,
        which is why `outgoing_text_for` exists to map one to the other.
        """
        return mnemonic == sentences.TIME_POLL_KEY

    def is_blocked(self, text: str | None) -> bool:
        """Every proprietary sentence but the one poll (D8, §7.2 gate 3).

        **This answered `False` for everything, which is now a defect rather than a
        simplification.**
        It was correct while nothing could be sent; with a send path it is the gate that has to
        refuse a port-reconfiguring sentence, and a predicate that permits everything gates nothing.

        NMEA reserves `$P` for vendors, which makes a prefix rule sound here rather than a guess
        about names. Standard sentences are not this predicate's business: they are broadcast,
        nothing here ever sends one, and §10.11's picker offers only the catalogue.

        **The permitted case is an equality test, not a prefix**, which is stricter than the
        sibling's rule and deliberately so — see `sentences.is_the_time_poll`.
        """
        if text is None:
            return False
        candidate = text.strip()
        if not candidate.upper().startswith(sentences.PROPRIETARY_PREFIX):
            return False
        return not sentences.is_the_time_poll(candidate)

    def outgoing_text_for(self, mnemonic: str | None) -> str | None:
        """The one sentence this family sends, and nothing else (D8, §7.2 gate 2).

        Built from `sentences.TIME_POLL` rather than written out here, so the text this offers and
        the text :meth:`is_blocked` permits cannot drift apart — they are the same constant. A
        caller asking for anything else gets ``None`` and nothing goes out.
        """
        if mnemonic != sentences.TIME_POLL_KEY:
            return None
        return sentences.TIME_POLL

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
        """**One**, and §10.11's picker shows exactly that one (D8).

        This was empty, on the reasoning that a talker has no command parser. It has no command
        parser still; what it has is a *poll* that a u-blox module answers, and §8.1's guarantee is
        that anything sendable is catalogued — so the entry has to be here rather than hidden in
        the send path. A console that fell back to another family's catalogue would still be
        offering ninety-eight commands to a device that would read every one as noise, which is
        what the emptiness was really protecting against and is unchanged.
        """
        return (TIME_POLL_COMMAND,)

    def supports(self, command: ScpiCommand) -> bool:
        return command.mnemonic == sentences.TIME_POLL_KEY

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
        gst = by_kind.get(sentences.GST, ())
        gbs = by_kind.get(sentences.GBS, ())
        banner = _banner(by_kind.get(sentences.TXT, ())) or (
            previous.banner if previous is not None else ()
        )

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
            fix_quality=_fix_quality(fix),
            banner=banner,
            uncertainty=_uncertainty(gst[0] if gst else None),
            integrity=_integrity(gbs[0] if gbs else None),
        )

    #: What a GNSS talker has no way of ever supplying (§11, #60).
    #:
    #: **This list was in the class docstring and nowhere else.** It said "no oscillator EFC, no
    #: TFOM or FFOM, no holdover — those are disciplined-oscillator concepts and a GNSS talker has
    #: none of them", which was true, unreachable, and therefore rendered as a row of em dashes
    #: that a user could not distinguish from a slow read.
    #:
    #: Everything here follows from one fact: **a talker has no disciplined oscillator and no
    #: command parser.** It reports where it is and what it can hear, once a second, unprompted.
    NEVER_REPORTS: Final[frozenset[ReceiverReading]] = frozenset(
        {
            # No oscillator, so nothing that measures or steers one.
            ReceiverReading.TFOM,
            ReceiverReading.FFOM,
            ReceiverReading.ONE_PPS_INTERVAL,
            ReceiverReading.OSCILLATOR_CONTROL,
            ReceiverReading.HOLDOVER,
            ReceiverReading.ANTENNA_DELAY,
            ReceiverReading.OUTPUT_VALIDITY,
            # No command parser, so nothing that has to be asked for.
            ReceiverReading.DEVICE_IDENTITY,
            ReceiverReading.LEAP_SECOND,
            ReceiverReading.TIME_CODE_FORMAT,
            ReceiverReading.POWER_ON_HOURS,
            ReceiverReading.HEALTH_MONITOR,
            ReceiverReading.STATUS_REGISTERS,
            ReceiverReading.DIAGNOSTIC_LOG,
            ReceiverReading.ERROR_QUEUE,
            ReceiverReading.ELEVATION_MASK,
            # A talker IS the GPS receiver. There is no second one inside it to describe, which is
            # a different fact from "it declines to say".
            ReceiverReading.GPS_ENGINE_IDENTITY,
            ReceiverReading.POSITION_HOLD,
            # And no status screen, so §11.1's parse-health line is about nothing.
            ReceiverReading.STATUS_SCREEN,
        }
    )

    def reports(self, reading: ReceiverReading) -> bool:
        """§11: what a talker can never supply is declined, not dashed."""
        return reading not in self.NEVER_REPORTS

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


def _fix_quality(fix: sentences.Sentence | None) -> FixQuality:
    """What kind of fix, from whichever sentence reported it.

    `GGA`'s field 5 is an integer code; `GNS`'s is **one character per constellation**, and the fix
    as a whole is the best any of them managed — a receiver contributing a differential solution on
    GPS and nothing on GLONASS has produced a differential fix.

    An unrecognised code is `UNKNOWN` rather than `NONE`. The two are different claims: *"this
    receiver told us something we do not understand"* and *"this receiver has no fix"* would both
    be drawn as a problem, and only one of them is.
    """
    if fix is None:
        return FixQuality.UNKNOWN

    if fix.kind == sentences.GNS:
        mode = fix.field(5)
        if mode is None:
            return FixQuality.UNKNOWN
        return best_of(GNS_MODES[c] for c in mode if c in GNS_MODES)

    code = sentences.parse_int(fix.field(5))
    return FixQuality.UNKNOWN if code is None else GGA_QUALITIES.get(code, FixQuality.UNKNOWN)


def _banner(txt: Sequence[sentences.Sentence]) -> tuple[str, ...]:
    """The text of each `TXT` sentence in this cycle, in order.

    Field 3 is the message; the three before it are the sentence count, the sentence number and a
    severity. **Empty is the ordinary case** — a talker prints its banner once, in its first
    second, and never again — so an empty answer means *nothing new this cycle*, not *no banner*,
    and the caller carries the previous one forward.
    """
    return tuple(text for sentence in txt if (text := sentence.field(3)) is not None)


def _uncertainty(gst: sentences.Sentence | None) -> PositionUncertainty | None:
    """``GST``'s three per-axis standard deviations, in metres.

    **Fields 5, 6 and 7, and nothing before them.** Field 1 is the total range residual RMS and is
    deliberately unread: on the only receiver in the corpus that sends it, it runs from 17 to
    3,179,277 across 300 sentences from a module sitting still on one unbroken fix, while the three
    deviations in those very same sentences stay between 1.6 and 4.1 m. Reading it would put a
    six-order-of-magnitude number on §10.6 once every dozen seconds.

    ``None`` when the sentence is absent — the family was not asked, or cannot answer. An instance
    with every field ``None`` cannot arise from a valid sentence, because a `GST` with no
    deviations at all still parses to one and renders as §11.1's dashes, which is the right answer
    for a receiver that sent the sentence and filled nothing in.
    """
    if gst is None:
        return None
    return PositionUncertainty(
        latitude_metres=sentences.parse_float(gst.field(5)),
        longitude_metres=sentences.parse_float(gst.field(6)),
        altitude_metres=sentences.parse_float(gst.field(7)),
    )


def _integrity(gbs: sentences.Sentence | None) -> ConstellationIntegrity | None:
    """``GBS``'s integrity check — which satellite the receiver would exclude, if any.

    The satellite id is in field 4 and is **blank in every cycle of the corpus**, which is the
    clean case rather than a missing one: the sentence arrived and the receiver flagged nothing.
    That is why this returns an instance with no faulted satellite rather than ``None`` — ``None``
    is reserved for a family that was never asked, and the two are different facts.

    The system id in field 8 names the constellation the faulted number belongs to, on a receiver
    that fills it. Where it is absent the number stands alone, which is the same honest
    `UNKNOWN` a `$GNGSV` page gets.
    """
    if gbs is None:
        return None

    number = sentences.parse_int(gbs.field(4))
    system = gbs.field(8)
    faulted = (
        SatelliteId(
            prn=number,
            constellation=sentences.SYSTEM_IDS.get(system or "", Constellation.UNKNOWN),
        )
        if number is not None
        else None
    )
    return ConstellationIntegrity(
        faulted=faulted,
        miss_probability=sentences.parse_float(gbs.field(5)),
        bias_metres=sentences.parse_float(gbs.field(6)),
        bias_deviation_metres=sentences.parse_float(gbs.field(7)),
    )


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
