"""§7.2's write rule: three gates, each tested on its own (D8, #64).

**Each gate gets its own test rather than one end-to-end case**, because they fail independently
and an end-to-end test passes as soon as *any* of them holds. That is §7.2's own verification note,
and it is the difference between three gates and one gate with two decorations.

What is being protected is worth restating where it can be read: before #64 there was no send path
anywhere in this application, so a port-reconfiguring proprietary sentence was excluded by there
being nowhere to express one. D8 traded that structural guarantee for these three checks. If they
are weak, nothing else is holding.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.drivers.nmea import sentences
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.drivers.registry import Registry
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.transport.fake import FakeTransport
from smartclock_monitor.services.session import DeviceSession


def talker() -> NmeaDriver:
    return NmeaDriver(clock=FixedClock(NOW))


# ---- Gate 1: the mnemonic is catalogued ---------------------------------------------------------


def test_only_the_one_key_is_catalogued() -> None:
    driver = talker()

    assert driver.is_allowed(sentences.TIME_POLL_KEY) is True
    assert [c.mnemonic for c in driver.commands] == [sentences.TIME_POLL_KEY]


@pytest.mark.parametrize(
    "mnemonic", [None, "", "GGA", "*IDN?", catalog.STATUS_SCREEN.mnemonic, "ubx", "UBX "]
)
def test_nothing_else_is_catalogued(mnemonic: str | None) -> None:
    """Including the case-different and whitespace-padded spellings of the one that is.

    §8.1's check is an exact match on the header for exactly this reason: a loose comparison here
    would be a prefix rule wearing a different coat.
    """
    assert talker().is_allowed(mnemonic) is False


# ---- Gate 2: the driver offers text, and defaults to none ---------------------------------------


def test_text_is_offered_for_the_catalogued_key_and_nothing_else() -> None:
    driver = talker()

    assert driver.outgoing_text_for(sentences.TIME_POLL_KEY) == sentences.TIME_POLL
    for other in (None, "GGA", "GSV", "*IDN?", "UBX,04"):
        assert driver.outgoing_text_for(other) is None


def test_a_query_response_family_offers_nothing_through_this_member() -> None:
    """Its mnemonic *is* its wire text and goes out the ordinary way.

    Answering anything here would create a **second** path to the wire for a family that already
    has one, which is the shape D8's gates exist to prevent.
    """
    driver = SmartClockDriver(clock=FixedClock(NOW))

    for command in driver.commands:
        assert driver.outgoing_text_for(command.mnemonic) is None


# ---- Gate 3: the text passes the driver's own exclusion rule ------------------------------------


def test_the_offered_text_is_not_refused_by_the_driver_s_own_rule() -> None:
    """The two methods must agree. A driver that contradicts itself is a programming error."""
    driver = talker()
    text = driver.outgoing_text_for(sentences.TIME_POLL_KEY)

    assert text is not None
    assert driver.is_blocked(text) is False


@pytest.mark.parametrize(
    "sentence",
    [
        "$PUBX,41,1,0007,0003,9600,0",  # the port-reconfiguring one, which is the whole point
        "$PUBX,40,GLL,0,0,0,0",
        "$PUBX,00",
        "$PUBX,04,EXTRA",  # right prefix, wrong sentence
        "$PUBX,0",  # truncated
        "$PUBX,04*00",  # right shape, wrong checksum
        "$PSRF100,0,9600,8,1,0",
        "$PMTK314,0,1,0,1,0,0,0",
    ],
)
def test_every_other_proprietary_sentence_is_refused(sentence: str) -> None:
    """Including a **truncation** and an **extension** of the permitted one.

    §7.2 warns that *"a prefix rule that accepted a truncation would accept far more than one
    sentence"*. This port answers that with an equality test rather than a prefix, which closes the
    hole in both directions — `$PUBX,04,EXTRA` is refused as firmly as `$PUBX,0`.
    """
    assert talker().is_blocked(sentence) is True


@pytest.mark.parametrize("sentence", ["$GPGGA,1,2,3", "$GNRMC,1", "", None, "not a sentence"])
def test_standard_sentences_are_not_this_predicate_s_business(sentence: str | None) -> None:
    """They are broadcast, nothing here ever sends one, and the picker offers only the catalogue."""
    assert talker().is_blocked(sentence) is False


# ---- The gates at the point of send -------------------------------------------------------------


#: Two real sentences from `vk162-steady-state.nmea`, which is what makes the session recognise a
#: talker and enter broadcast mode at all. Without them `open` finds nothing to claim the link, no
#: listener is started, and the send path under test is never reached — which is how the first
#: draft of `test_the_poll_reaches_the_wire` managed to fail for a reason unrelated to the gates.
OVERHEARD = (
    "$GPGGA,000821.00,4731.31126,N,12212.37609,W,2,12,0.73,29.2,M,-18.8,M,,0000*5B\r\n"
    "$GPGSA,A,3,10,27,32,48,23,08,,,,,,,4.03,1.44,3.76*06\r\n"
)


def _session(driver: object) -> tuple[DeviceSession, FakeTransport]:
    clock = FixedClock(NOW)
    # `prompt=""` because a talker has none. With the fake's default a SCPI prompt is appended to
    # the banner, the sentences stop being recognisable, the session never claims the link, and the
    # send path under test is never reached.
    transport = FakeTransport({}, banner=OVERHEARD, prompt="")
    # **With a registry**, because claiming a family by what it said is the registry's job — a
    # session without one never calls `overhear`, never starts a listener, and falls through to the
    # query/response path. The first draft of this helper had no registry and the send path under
    # test was never reached.
    session = DeviceSession(
        transport,
        driver,  # type: ignore[arg-type]
        clock,
        registry=Registry([driver]),  # type: ignore[list-item]
    )
    return session, transport


def test_the_poll_reaches_the_wire() -> None:
    """The gates are only worth testing if the permitted case actually goes out."""

    async def run() -> None:
        session, transport = _session(talker())
        await session.open(probe=timedelta(seconds=1))
        await session.execute(sentences.TIME_POLL_KEY)

        assert any(sentences.TIME_POLL in w for w in transport.written)

    asyncio.run(run())


def test_a_driver_that_contradicts_itself_sends_nothing() -> None:
    """Gate 3 at the point of send, against a driver whose two methods disagree.

    This is the case that cannot be produced by any real driver in the tree, which is exactly why
    it needs a deliberate one: the gate exists for the driver somebody writes next.
    """

    class Contradicts(NmeaDriver):
        def is_blocked(self, text: str | None) -> bool:
            return True

    async def run() -> None:
        session, transport = _session(Contradicts(clock=FixedClock(NOW)))
        await session.open(probe=timedelta(seconds=1))
        await session.execute(sentences.TIME_POLL_KEY)

        assert not any(sentences.TIME_POLL in w for w in transport.written)

    asyncio.run(run())


def test_a_driver_offering_text_for_an_uncatalogued_key_sends_nothing() -> None:
    """Gate 1 at the point of send. The catalogue is asked again *here*, not trusted from the plan.

    A driver checking its own homework is not a gate.
    """

    class OffersTooMuch(NmeaDriver):
        def outgoing_text_for(self, mnemonic: str | None) -> str | None:
            return sentences.TIME_POLL

        def is_allowed(self, mnemonic: str | None) -> bool:
            return False

    async def run() -> None:
        session, transport = _session(OffersTooMuch(clock=FixedClock(NOW)))
        await session.open(probe=timedelta(seconds=1))
        await session.execute("GGA")

        assert not any(sentences.TIME_POLL in w for w in transport.written)

    asyncio.run(run())
