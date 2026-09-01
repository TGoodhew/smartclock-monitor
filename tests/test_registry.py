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
from smartclock_device.drivers.registry import Registry
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.transport.fake import FakeTransport
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
