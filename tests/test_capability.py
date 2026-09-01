"""§12's capability gate, and §9.11's rule for a control the family cannot drive.

**Absent means disabled and explained, never hidden.** §12's #304 records why this is a rule: every
Details page asked for its tier C commands in a form that throws, which was *"correct while one
family shipped, and a crash on navigation the day a reads-only talker arrived"*.

The driver here is a **reads-only talker** — the shape §12 says the seam has to survive — so these
run against something that is not the SmartClock, which is the only way the seam is exercised at
all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton

from smartclock_device.commands import catalog
from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import Cadence, PollPlan, ReceiverDriver
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.receiver_status import ReceiverStatus
from smartclock_device.transport.transaction import Transaction
from smartclock_monitor.views.capability import explain, gate
from smartclock_monitor.views.holdover_page import HoldoverPage
from smartclock_monitor.views.pages import PositionPage, SatellitesPage
from test_operational_pages import FakeRunner


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@dataclass
class TalkerDriver:
    """A reads-only family: it speaks and is never written to.

    Deliberately not a subset of the SmartClock's catalog — it supports **nothing** the pages want
    to send, which is the case a gate that quietly passed would let straight through to a crash.
    """

    name: str = "NMEA 0183 talker"
    supported: frozenset[str] = field(default_factory=frozenset)

    @property
    def cadence(self) -> Cadence:
        return Cadence(fast=timedelta(seconds=1), full=timedelta(seconds=1))

    @property
    def plan(self) -> PollPlan:
        return PollPlan(fast=(), full=catalog.STATUS_SCREEN)

    def is_allowed(self, mnemonic: str | None) -> bool:
        return mnemonic in self.supported

    def is_blocked(self, mnemonic: str | None) -> bool:
        return False

    def supports(self, command: ScpiCommand) -> bool:
        return command.mnemonic in self.supported

    def recognises(self, identity: DeviceIdentity | None) -> bool:
        """Claims nothing: this stand-in exists to be the family that is *not* selected."""
        del identity
        return False

    def parse_full(
        self, transaction: Transaction, previous: ReceiverStatus | None
    ) -> ReceiverStatus:
        raise NotImplementedError

    def apply_fast(self, status: ReceiverStatus, results: dict[str, Transaction]) -> ReceiverStatus:
        return status


def talking(**supported: bool) -> FakeRunner:
    del supported
    return FakeRunner({}, driver_for=TalkerDriver())


# ---- The gate itself ---------------------------------------------------------------------------


def test_it_satisfies_the_driver_seam() -> None:
    """The stand-in has to be a real driver, or these tests prove nothing about the contract."""
    assert isinstance(TalkerDriver(), ReceiverDriver)


def test_an_unsupported_command_disables_and_explains() -> None:
    """§9.11: the control stays where it is, greyed, with one sentence naming the family."""
    button = QPushButton("Force holdover")
    driver = TalkerDriver()

    assert gate(button, driver, catalog.HOLDOVER_FORCE) is False
    assert button.isEnabled() is False
    assert "NMEA 0183 talker" in button.toolTip()
    assert "no command for this" in button.toolTip()


def test_it_is_disabled_rather_than_hidden() -> None:
    """A missing control reads as a feature the application does not have; a greyed one with a
    sentence reads as a feature *this receiver* does not have. Those are different facts, and the
    second is the true one."""
    button = QPushButton("Force holdover")
    button.show()

    gate(button, TalkerDriver(), catalog.HOLDOVER_FORCE)

    assert button.isHidden() is False


def test_a_supported_command_enables_and_clears_the_explanation() -> None:
    """A control that says why it is disabled while being enabled is worse than one that says
    nothing."""
    from conftest import NOW
    from smartclock_device.clock import FixedClock
    from smartclock_device.drivers.smartclock import SmartClockDriver

    button = QPushButton("Force holdover")
    gate(button, TalkerDriver(), catalog.HOLDOVER_FORCE)
    assert button.toolTip()

    gate(button, SmartClockDriver(clock=FixedClock(NOW)), catalog.HOLDOVER_FORCE)

    assert button.isEnabled() is True
    assert button.toolTip() == ""


def test_a_tooltip_the_page_wrote_is_not_taken_away() -> None:
    """A page may have documented its own control, and clearing that on connect would silently
    remove documentation nobody noticed was gone."""
    from conftest import NOW
    from smartclock_device.clock import FixedClock
    from smartclock_device.drivers.smartclock import SmartClockDriver

    button = QPushButton("Force holdover")
    button.setToolTip("What this does, written by the page.")

    gate(button, SmartClockDriver(clock=FixedClock(NOW)), catalog.HOLDOVER_FORCE)

    assert button.toolTip() == "What this does, written by the page."


def test_every_command_must_be_supported_not_any() -> None:
    """A control whose action sends three commands and can send two would do half of what it says
    — and half of a destructive operation is what §8.3's confirmations exist to prevent."""
    button = QPushButton("Apply")
    partial = TalkerDriver(supported=frozenset({catalog.CLEAR_EXCLUSIONS.mnemonic}))

    assert gate(button, partial, catalog.CLEAR_EXCLUSIONS) is True
    assert gate(button, partial, catalog.CLEAR_EXCLUSIONS, catalog.EXCLUDE_SATELLITES) is False


def test_not_connected_is_not_the_same_as_cannot() -> None:
    """Different facts, and the tooltip says which."""
    button = QPushButton("Force holdover")

    gate(button, None, catalog.HOLDOVER_FORCE)

    assert "Not connected" in button.toolTip()
    assert "no command" not in button.toolTip()
    assert "no command for this" in explain(TalkerDriver(), catalog.HOLDOVER_FORCE)


# ---- The pages, against a family that supports nothing -----------------------------------------


def test_the_holdover_page_greys_its_controls_rather_than_crashing() -> None:
    """The exact scenario §12's #304 names: navigation to a page whose commands the connected
    family does not have."""
    page = HoldoverPage()
    page.set_command_runner(talking())

    assert page._force.isEnabled() is False
    assert page._recover.isEnabled() is False
    assert page.apply_button.isEnabled() is False
    assert "NMEA 0183 talker" in page._force.toolTip()


def test_the_satellites_page_greys_its_controls() -> None:
    page = SatellitesPage()
    page.set_command_runner(talking())

    assert page._apply_mask.isEnabled() is False
    assert page._manage.isEnabled() is False


def test_the_position_page_greys_its_survey_controls() -> None:
    page = PositionPage()
    page.set_command_runner(talking())

    assert page._start_survey.isEnabled() is False
    assert page._adopt.isEnabled() is False
    assert page._on_power_up.isEnabled() is False


def test_the_smartclock_still_has_everything_enabled() -> None:
    """The gate must not have quietly disabled the family it was built around."""
    page = HoldoverPage()
    page.set_command_runner(FakeRunner({catalog.HOLDOVER_DURATION_THRESHOLD.mnemonic: "+600"}))

    assert page._force.isEnabled() is True
    assert page._recover.isEnabled() is True
    assert page.apply_button.isEnabled() is True
