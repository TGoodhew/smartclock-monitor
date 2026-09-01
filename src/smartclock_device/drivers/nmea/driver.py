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
from smartclock_device.models.satellite import PredictedSatellite, TrackedSatellite
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


#: GGA first, because §12 requires the plan's first fast-tier entry to delimit a cycle and GGA is
#: the sentence every talker emits exactly once per cycle.
PLAN: Final = PollPlan(
    fast=tuple(_key_command(key) for key in sentences.KEYS),
    full=_key_command(WHOLE_CYCLE),
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
            if parsed.kind == sentences.GGA:
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

        found = by_kind.get(sentences.GGA, ())
        gga = found[0] if found else None
        used = _satellites_in_use(by_kind.get(sentences.GSA, []))
        visible = _visible(by_kind.get(sentences.GSV, []))

        tracked = tuple(sat for prn, sat in sorted(visible.items()) if prn in used)
        not_tracked = tuple(
            PredictedSatellite(
                prn=prn,
                elevation_degrees=sat.elevation_degrees,
                azimuth_degrees=sat.azimuth_degrees,
                attempting_to_track=False,
            )
            for prn, sat in sorted(visible.items())
            if prn not in used
        )

        moment = _timestamp(by_kind.get(sentences.RMC, []), gga)

        return ReceiverStatus(
            captured_at=self.clock.utc_now(),
            mode=_mode(gga),
            outputs=OutputValidity.VALID if _has_fix(gga) else OutputValidity.UNKNOWN,
            gps_one_pps_valid=_has_fix(gga),
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
            position=_position(gga),
            position_mode=PositionMode.UNKNOWN,
            # GGA's altitude is above mean sea level and the sentence carries the geoid separation
            # separately, so the datum is knowable rather than assumed — which is the same care
            # §10.6 records for the SmartClock's own height field.
            height_datum=HeightDatum.MSL if _position(gga) is not None else HeightDatum.UNKNOWN,
            health_ok=_has_fix(gga),
        )

    def apply_fast(self, status: ReceiverStatus, results: dict[str, Transaction]) -> ReceiverStatus:
        """A broadcast family's tiers read the same cycle, so the full parse has already done it.

        Returned unchanged rather than re-parsed: the fast sweep and the full read are the same
        sentences here, and folding them twice would be arithmetic for its own sake.
        """
        del results
        return status


# ---- The mapping decisions, each one this driver's --------------------------------------------


def _has_fix(gga: sentences.Sentence | None) -> bool:
    quality = sentences.parse_int(gga.field(5)) if gga is not None else None
    return quality is not None and quality > 0


def _mode(gga: sentences.Sentence | None) -> SmartClockMode:
    """§12's #304 item 3: the mode is the driver's.

    "Locked" means a disciplined oscillator to a SmartClock and a position fix to a talker, and
    mapping one onto the other is a claim only the driver is in a position to make. A talker with
    no fix is *searching*, which is RECOVERY's shape — it is not in holdover, because it has no
    oscillator to hold over on.
    """
    if gga is None:
        return SmartClockMode.UNKNOWN
    return SmartClockMode.LOCKED if _has_fix(gga) else SmartClockMode.RECOVERY


def _position(gga: sentences.Sentence | None) -> GeoPosition | None:
    if gga is None:
        return None

    latitude = sentences.parse_degrees(gga.field(1), gga.field(2))
    longitude = sentences.parse_degrees(gga.field(3), gga.field(4))
    if latitude is None or longitude is None:
        return None

    return GeoPosition(
        latitude_degrees=latitude,
        longitude_degrees=longitude,
        height_metres=sentences.parse_float(gga.field(8)),
    )


def _satellites_in_use(gsa: list[sentences.Sentence]) -> set[int]:
    """GSA's twelve PRN slots. Empty slots are empty fields, not zeros."""
    used: set[int] = set()
    for sentence in gsa:
        for index in range(2, 14):
            prn = sentences.parse_int(sentence.field(index))
            if prn:
                used.add(prn)
    return used


def _visible(gsv: list[sentences.Sentence]) -> dict[int, TrackedSatellite]:
    """GSV's four-satellite groups, across however many sentences the talker paged them into."""
    found: dict[int, TrackedSatellite] = {}
    for sentence in gsv:
        for group in range(4):
            base = 3 + group * 4
            prn = sentences.parse_int(sentence.field(base))
            if prn is None:
                continue
            found[prn] = TrackedSatellite(
                prn=prn,
                elevation_degrees=sentences.parse_int(sentence.field(base + 1)),
                azimuth_degrees=sentences.parse_int(sentence.field(base + 2)),
                # Absent where the talker sees a satellite it is not tracking, which is precisely
                # the distinction §10.5's table draws — so it stays None rather than becoming 0.
                signal_strength=sentences.parse_int(sentence.field(base + 3)),
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
