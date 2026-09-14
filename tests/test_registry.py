"""§12's composition root: which driver serves the receiver that answered.

**The probe phase belongs to no driver.** The session opens the port, absorbs the banner and asks
`*IDN?` neutrally; only then is a family chosen. Choosing first would mean asking one family's
questions of a receiver that may be another's.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.nmea import NmeaDriver
from smartclock_device.drivers.registry import Registry
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.drivers.uccm.driver import UccmDriver
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.transport.fake import FakeTransport
from smartclock_device.transport.settings import (
    AUTO_DETECT_SEQUENCE,
    DOCUMENTED_SETTINGS,
    Parity,
    SerialSettings,
    StopBits,
)
from smartclock_monitor.services.session import DeviceSession
from test_capability import TalkerDriver

PROBE = timedelta(milliseconds=20)
Z3805A = "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A"


def clock() -> FixedClock:
    return FixedClock(NOW)


def smartclock() -> SmartClockDriver:
    return SmartClockDriver(clock=clock())


# ---- Selection ---------------------------------------------------------------------------------


def test_an_empty_registry_is_refused() -> None:
    """There would be nothing to fall back to, and the fallback is the whole design."""
    with pytest.raises(ValueError, match="at least one"):
        Registry([])


def test_the_first_driver_that_claims_the_identity_wins() -> None:
    """Registration order is priority order."""
    registry = Registry([TalkerDriver(), smartclock()])

    selection = registry.select(DeviceIdentity.parse(Z3805A))

    assert isinstance(selection.driver, SmartClockDriver)
    assert selection.recognised is True


def test_a_family_that_claims_nothing_never_displaces_one_that_does() -> None:
    registry = Registry([smartclock(), TalkerDriver()])

    assert isinstance(registry.select(DeviceIdentity.parse(Z3805A)).driver, SmartClockDriver)


def test_nothing_claiming_falls_back_to_the_first_registered() -> None:
    """`None` — nothing answered `*IDN?` — is not a reason to fail: a receiver that says nothing
    is the ordinary state of most of §7.1's combinations during auto-detect, and the walk needs a
    driver to keep asking with."""
    talker = TalkerDriver()
    registry = Registry([talker, smartclock()])

    selection = registry.select(None)

    assert selection.driver is talker
    assert selection.recognised is False


def test_an_unrecognised_identity_falls_back_too() -> None:
    unknown = DeviceIdentity.parse("ACME,WIDGET-9,1,1")
    registry = Registry([smartclock()])

    selection = registry.select(unknown)

    assert selection.recognised is False
    assert isinstance(selection.driver, SmartClockDriver)


def test_one_registered_driver_is_never_ambiguous() -> None:
    """The fallback *is* the driver that would have served it regardless, so a warning would be
    noise on every connection an unidentified receiver ever makes."""
    assert Registry([smartclock()]).is_ambiguous is False
    assert Registry([smartclock(), TalkerDriver()]).is_ambiguous is True


def test_the_smartclock_claims_its_own_family_and_not_a_stranger() -> None:
    """Keyed on the parsed model rather than the manufacturer string: UNKNOWN means the identity
    did not name a member this build knows, which is a receiver this driver should not claim so a
    later-registered family gets its turn."""
    driver = smartclock()

    assert driver.recognises(DeviceIdentity.parse(Z3805A)) is True
    assert driver.recognises(DeviceIdentity.parse("ACME,WIDGET-9,1,1")) is False
    assert driver.recognises(None) is False


def test_a_family_that_claims_nothing_says_so_explicitly() -> None:
    """Making `recognises` optional was the first design and was worse: an absent method says the
    author forgot, where an explicit False says "I claim nothing" and the fallback is reached on
    purpose."""
    assert TalkerDriver().recognises(DeviceIdentity.parse(Z3805A)) is False


# ---- Through the session -----------------------------------------------------------------------


def _open(registry: Registry, responses: dict[str, str]) -> DeviceSession:
    async def run() -> DeviceSession:
        transport = FakeTransport({"*CLS": "", **responses}, default_response="")
        session = DeviceSession(transport, registry.drivers[0], clock(), registry=registry)
        await session.open(probe=PROBE)
        return session

    return asyncio.run(run())


def test_the_session_selects_the_family_that_claims_the_receiver() -> None:
    """The talker is registered first and would have served it; the SmartClock claims it."""
    registry = Registry([TalkerDriver(), smartclock()])

    session = _open(registry, {"*IDN?": Z3805A})

    assert isinstance(session.driver, SmartClockDriver)
    assert session.driver_was_recognised is True


def test_the_session_keeps_the_fallback_when_nothing_claims() -> None:
    talker = TalkerDriver()
    registry = Registry([talker, smartclock()])

    session = _open(registry, {"*IDN?": "ACME,WIDGET-9,1,1"})

    assert session.driver is talker
    assert session.driver_was_recognised is False, "and somebody should be able to find that out"


def test_a_single_family_build_never_reports_an_unrecognised_receiver() -> None:
    """With one driver the fallback is the answer, so there is nothing to report."""
    session = _open(Registry([smartclock()]), {"*IDN?": "ACME,WIDGET-9,1,1"})

    assert session.driver_was_recognised is True


def test_re_selection_happens_on_every_connect() -> None:
    """§12: the receiver on the port can have been swapped while the link was down, and a session
    that kept the driver it chose an hour ago would parse one family's answers with another's
    rules."""
    registry = Registry([TalkerDriver(), smartclock()])

    async def run() -> tuple[object, object]:
        transport = FakeTransport({"*CLS": "", "*IDN?": Z3805A}, default_response="")
        session = DeviceSession(transport, registry.drivers[0], clock(), registry=registry)
        await session.open(probe=PROBE)
        first = session.driver

        # The receiver is swapped for something this build does not recognise.
        transport.script("*IDN?", "ACME,WIDGET-9,1,1")
        await session.open(probe=PROBE)
        return first, session.driver

    first, second = asyncio.run(run())

    assert isinstance(first, SmartClockDriver)
    assert isinstance(second, TalkerDriver), "it kept a driver the receiver no longer justifies"


def test_a_session_without_a_registry_keeps_the_driver_it_was_given() -> None:
    """A single-family build handed its driver directly is unchanged — the registry is additive."""

    async def run() -> object:
        transport = FakeTransport({"*CLS": "", "*IDN?": Z3805A}, default_response="")
        driver = smartclock()
        session = DeviceSession(transport, driver, clock())
        await session.open(probe=PROBE)
        return session.driver is driver

    assert asyncio.run(run()) is True


# ---- §10.12's union ----------------------------------------------------------------------------


def a_registry() -> Registry:
    tick = FixedClock(NOW)
    return Registry([SmartClockDriver(clock=tick), NmeaDriver(clock=tick)])


def test_the_walk_is_the_union_of_every_family_s_rates() -> None:
    """§10.12. This is what makes a second family *reachable*: a talker runs at 4800, and the walk
    knew only one receiver's rates — so the driver was registered and could not be found."""
    walk = a_registry().auto_detect_sequence

    assert SerialSettings(4800, 8, Parity.NONE, StopBits.ONE) in walk
    assert SerialSettings(38400, 8, Parity.NONE, StopBits.ONE) in walk


def test_the_smartclock_still_answers_on_the_first_attempt() -> None:
    """Registration order is priority order, and adding a family must not cost the first one a
    single probe. Fourteen seconds was what getting this ordering wrong cost last time.

    **The two the SmartClock is documented to ship at keep positions 1 and 2**, which is the half
    of §10.12's ordering that is load-bearing: the Z3805A's factory 9600-8-N-1 and the Z3801A's
    19200-7-O-1, the latter being exactly what #64's correction moved up from eighth. The banding
    re-groups the walk behind them; it must never reach over them.
    """
    walk = a_registry().auto_detect_sequence

    assert walk[:2] == DOCUMENTED_SETTINGS
    assert str(walk[0]) == "9600-8-N-1"
    assert str(walk[1]) == "19200-7-O-1"


def test_a_shared_combination_is_tried_once_at_the_earlier_position() -> None:
    """Two entries for one combination would mean two probe timeouts on every port that is neither.

    Written against the real pair first, where it asserted nothing: the NMEA driver deliberately
    omits 9600 *because* the union de-duplicates, so there was no duplicate to remove and the test
    passed against a registry with the de-duplication deleted. It takes a family that genuinely
    overlaps to test the thing.
    """
    shared = SerialSettings(9600, 8, Parity.NONE, StopBits.ONE)
    mine = SerialSettings(57600, 8, Parity.NONE, StopBits.ONE)
    tick = FixedClock(NOW)
    registry = Registry([SmartClockDriver(clock=tick), TalkerDriver(walk=(shared, mine))])

    walk = registry.auto_detect_sequence

    assert len(walk) == len(set(walk)), "the union is de-duplicated"
    assert walk.count(shared) == 1
    assert walk.index(shared) == 0, "tried at the earlier family's position, not appended"
    assert mine in walk, "and what is new is still added"


def test_a_family_with_no_rates_of_its_own_lengthens_nothing() -> None:
    """Every entry costs one probe timeout on a port that is not it, so a driver naming rates it
    does not use spends other people's seconds."""
    tick = FixedClock(NOW)
    with_talker = Registry([SmartClockDriver(clock=tick), TalkerDriver()])

    assert sorted(map(str, with_talker.auto_detect_sequence)) == sorted(
        map(str, AUTO_DETECT_SEQUENCE)
    ), "a family with no rates added or removed one"
    assert len(with_talker.auto_detect_sequence) == len(AUTO_DETECT_SEQUENCE)


# ---- The three bands the walk is ordered in ----------------------------------------------------


def test_the_walk_is_ordered_documented_then_8n1_then_the_rest() -> None:
    """The whole ordering, spelled out, because every position in it was argued for.

    §10.12 appends each family's sequence whole. With three families registered that put the
    SmartClock's three **unsourced** 7-bit spellings at 3, 4 and 8 — ahead of NMEA 0183's own
    4800, which a talker is specified to use. A talker was found on the ninth attempt, behind four
    combinations no talker has ever run at, which is about fourteen seconds at §7.2's 2 s probe.
    """
    tick = FixedClock(NOW)
    walk = Registry(
        [SmartClockDriver(clock=tick), NmeaDriver(clock=tick), UccmDriver(clock=tick)]
    ).auto_detect_sequence

    assert [str(candidate) for candidate in walk] == [
        # Band 1 — documented. A manual's factory default, a standard's rate, a measured figure.
        "9600-8-N-1",  # Z3805A, factory
        "19200-7-O-1",  # Z3801A, factory — #64's correction, still second
        "4800-8-N-1",  # NMEA 0183
        "38400-8-N-1",  # NMEA 0183, high speed
        "57600-8-N-1",  # UCCM-P, measured (#470)
        # Band 2 — 8-N-1. A rate is cheap to be wrong about; framing is near-universal.
        "19200-8-N-1",
        "2400-8-N-1",
        "1200-8-N-1",
        # Band 3 — the rest, which is where the unsourced spellings end up.
        "19200-7-E-1",
        "9600-7-E-1",
        "9600-7-O-1",
    ]


def test_a_documented_rate_never_sits_behind_an_unsourced_one() -> None:
    """The property the bands exist for, stated without naming a single combination.

    The list above would still pass if somebody re-derived it from a walk that had drifted. This
    one fails on the drift itself, and it is the sentence the change was made to make true.
    """
    tick = FixedClock(NOW)
    drivers: list[ReceiverDriver] = [
        SmartClockDriver(clock=tick),
        NmeaDriver(clock=tick),
        UccmDriver(clock=tick),
    ]
    walk = Registry(drivers).auto_detect_sequence
    documented = {candidate for driver in drivers for candidate in driver.documented_settings}

    last_documented = max(index for index, c in enumerate(walk) if c in documented)
    first_unsourced = min(index for index, c in enumerate(walk) if c not in documented)

    assert last_documented < first_unsourced, (
        "an unsourced combination is being probed before a documented one"
    )


def test_eight_n_one_is_tried_before_any_other_framing() -> None:
    """The user-facing half: every rate at the near-universal framing, before any 7-bit or parity
    variant is tried at all."""
    tick = FixedClock(NOW)
    walk = Registry(
        [SmartClockDriver(clock=tick), NmeaDriver(clock=tick), UccmDriver(clock=tick)]
    ).auto_detect_sequence

    def is_8n1(candidate: SerialSettings) -> bool:
        return (
            candidate.data_bits == 8
            and candidate.parity is Parity.NONE
            and candidate.stop_bits is StopBits.ONE
        )

    others = [index for index, c in enumerate(walk) if not is_8n1(c)]
    eights = [index for index, c in enumerate(walk) if is_8n1(c)]

    # The one deliberate exception, and the only one: the Z3801A's documented factory setting.
    exception = walk.index(SerialSettings(19200, 7, Parity.ODD, StopBits.ONE))
    assert max(eights) < min(index for index in others if index != exception)


def test_every_documented_combination_is_one_the_walk_actually_tries() -> None:
    """A `documented_settings` entry that is not in `auto_detect_sequence` is never probed.

    It would sort nothing, change nothing and look like a claim that had been made — the quietest
    way for this seam to stop meaning anything. Held against every real family.
    """
    tick = FixedClock(NOW)
    for driver in (SmartClockDriver(clock=tick), NmeaDriver(clock=tick), UccmDriver(clock=tick)):
        extra = set(driver.documented_settings) - set(driver.auto_detect_sequence)
        assert not extra, f"{driver.name} documents {extra}, which its walk never tries"


# ---- Claiming a talker on the second listen ----------------------------------------------------


def test_a_talker_is_claimed_from_what_the_probe_heard_when_the_banner_was_not_enough() -> None:
    """The claim is a race against the probe window, and it used to lose about half of them.

    `overhear` needs two recognised sentences including a fix sentence. A 1 Hz talker whose burst
    straddles the edge of the 2 s window delivers one clean cycle or none — measured on a VK-162,
    four connections at identical settings claimed the link twice, and the two that missed adopted
    the fallback family, asked SCPI of a device with no command parser and dropped the link.

    So the question is asked again on what the ``*IDN?`` probe heard. **It costs nothing**: the
    probe has just spent its own timeout and a talker does not stop talking while it elapses.

    Here the banner carries one sentence — not enough — and the rest arrives during the probe.
    """
    talker = NmeaDriver(clock=clock())
    registry = Registry([smartclock(), talker])

    async def run() -> DeviceSession:
        transport = FakeTransport(
            {
                "*CLS": "",
                # What a talker "answers" `*IDN?` with: more of the stream, because it has no
                # command parser and was never listening for a question.
                "*IDN?": (
                    "$GPGGA,000821.00,4731.31126,N,12212.37609,W,2,12,0.73,29.2,M,-18.8,M,,0000*5B"
                    "\r\n$GPGSA,A,3,10,27,32,48,23,08,,,,,,,4.03,1.44,3.76*06\r\n"
                ),
            },
            # One sentence, and not a fix sentence: `overhear` cannot claim on this.
            banner="$GPGSA,A,3,10,27,32,48,23,08,,,,,,,4.03,1.44,3.76*06\r\n",
            prompt="",
        )
        session = DeviceSession(transport, registry.drivers[0], clock(), registry=registry)
        await session.open(probe=PROBE)
        return session

    session = asyncio.run(run())

    assert session.driver is talker, "the banner alone lost the claim and nothing asked again"
    assert session.identity is None, "a talker has no identity, and none may be invented for it"
