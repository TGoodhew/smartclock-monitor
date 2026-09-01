"""§12's capability seam: what a page asks for, and what each family answers.

Issue #13. The pages name a :class:`Capability` and the driver answers with its own command or
with nothing, so no page holds one family's mnemonic. `test_layering.py` enforces the absence;
this checks the seam itself works.
"""

from __future__ import annotations

import pytest

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.drivers.capability import Capability, CommandGroup
from smartclock_device.drivers.nmea import NmeaDriver
from smartclock_device.drivers.smartclock import SmartClockDriver


def smartclock() -> SmartClockDriver:
    return SmartClockDriver(clock=FixedClock(NOW))


def talker() -> NmeaDriver:
    return NmeaDriver(clock=FixedClock(NOW))


@pytest.mark.parametrize("capability", list(Capability), ids=lambda c: c.name)
def test_the_smartclock_answers_every_capability(capability: Capability) -> None:
    """The table is **total** for this family, and that is the thing to catch.

    A capability nothing maps would leave a control permanently greyed with no indication that the
    receiver in front of you can in fact do it — the failure would be silent and would look like a
    limitation of the hardware.
    """
    command = smartclock().command(capability)

    assert command is not None, f"nothing maps {capability.name}"
    assert catalog.is_allowed(command.mnemonic), (
        f"{capability.name} maps to {command.mnemonic}, which is not on the allowlist"
    )


@pytest.mark.parametrize("capability", list(Capability), ids=lambda c: c.name)
def test_a_talker_answers_none_to_every_capability(capability: Capability) -> None:
    """A receiver that is never written to has no command for any of them, and §9.11's gate turns
    that into a disabled control naming the family rather than a button that fails on click."""
    assert talker().command(capability) is None


def test_no_two_capabilities_map_to_the_same_command() -> None:
    """Two names for one command means one of them is a synonym nobody will keep in step — and a
    page gated on the wrong one would be disabled for a receiver that supports it."""
    driver = smartclock()
    seen: dict[str, Capability] = {}
    for capability in Capability:
        command = driver.command(capability)
        assert command is not None
        clash = seen.get(command.mnemonic)
        assert clash is None, f"{capability.name} and {clash.name} both map to {command.mnemonic}"
        seen[command.mnemonic] = capability


def test_the_groups_are_the_families_own() -> None:
    """§8.5's six and §10.10's setters belong to the family, not to a page. A page renders one
    control per member and must not assume a count."""
    assert smartclock().commands_for(CommandGroup.EXPERIMENTAL) == catalog.EXPERIMENTAL
    assert smartclock().commands_for(CommandGroup.REGISTER_SETTERS) == catalog.REGISTER_SETTERS

    for group in CommandGroup:
        assert talker().commands_for(group) == ()


def test_the_register_structure_comes_from_the_family() -> None:
    """§10.10's columns and its per-register queries. Composing ``f":STAT:{node}:{field}?"`` in a
    page was this receiver's spelling written into the application."""
    driver = smartclock()

    assert driver.register_fields == catalog.REGISTER_FIELDS
    assert driver.register_query("OPER", "COND") is not None
    assert driver.register_setter("OPER", "ENAB") is not None
    assert driver.register_query("OPER", "NOT_A_FIELD") is None

    assert talker().register_fields == ()
    assert talker().register_query("OPER", "COND") is None


def test_a_capability_is_named_for_the_want_not_the_spelling() -> None:
    """The point of the enum. A member named for SCPI would put the coupling back inside the name
    and leave the seam looking closed."""
    for capability in Capability:
        assert ":" not in capability.name, f"{capability.name} looks like a mnemonic"
        assert capability.value.islower() or " " in capability.value
