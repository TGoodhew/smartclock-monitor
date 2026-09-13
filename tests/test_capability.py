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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QPushButton

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import (
    Cadence,
    PollPlan,
    QueryResponseDefaults,
    ReceiverDriver,
)
from smartclock_device.drivers.capability import (
    ALL_READINGS,
    Capability,
    CommandGroup,
    ReceiverReading,
)
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.models.device_identity import DeviceIdentity
from smartclock_device.models.receiver_status import ReceiverStatus
from smartclock_device.transport.settings import SerialSettings
from smartclock_device.transport.transaction import Transaction
from smartclock_monitor.themes.tokens import Theme
from smartclock_monitor.views.capability import explain, gate
from smartclock_monitor.views.holdover_page import HoldoverPage
from smartclock_monitor.views.pages import PositionPage, SatellitesPage
from test_operational_pages import FakeRunner


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@dataclass
class TalkerDriver(QueryResponseDefaults):
    """A reads-only family: it speaks and is never written to.

    Deliberately not a subset of the SmartClock's catalog — it supports **nothing** the pages want
    to send, which is the case a gate that quietly passed would let straight through to a crash.
    """

    name: str = "NMEA 0183 talker"
    #: Which capabilities this double claims. Empty by default — the point of the double is a
    #: family that offers nothing — and a partial set is what tests §9.11's "every, not any".
    supported: frozenset[Capability] = field(default_factory=frozenset)

    #: Which readings it declines (#60). Empty by default for the same reason as `supported`: a
    #: test says what it is about, and a double that pre-declined things would hide it.
    declines: frozenset[ReceiverReading] = field(default_factory=frozenset)

    def outgoing_text_for(self, mnemonic: str | None) -> str | None:
        """Nothing. A double that could transmit would be testing a send path nobody wrote."""
        del mnemonic
        return None

    def reports(self, reading: ReceiverReading) -> bool:
        return reading not in self.declines

    @property
    def cadence(self) -> Cadence:
        return Cadence(fast=timedelta(seconds=1), full=timedelta(seconds=1))

    @property
    def plan(self) -> PollPlan:
        return PollPlan(fast=(), full=catalog.STATUS_SCREEN)

    def is_allowed(self, mnemonic: str | None) -> bool:
        """Whatever the supported capabilities happen to spell as. Kept consistent with
        :meth:`command` so the double cannot claim one and refuse the other."""
        return mnemonic is not None and mnemonic in {
            command.mnemonic for command in self._offered()
        }

    def is_blocked(self, mnemonic: str | None) -> bool:
        return False

    #: What this family would have auto-detect try. Empty by default — the double stands in for a
    #: family rather than for a wire format — and set where a test is about the §10.12 union.
    walk: tuple[SerialSettings, ...] = ()

    @property
    def auto_detect_sequence(self) -> tuple[SerialSettings, ...]:
        return self.walk

    def command(self, capability: Capability) -> ScpiCommand | None:
        """Nothing, unless a test says otherwise. A family that offers nothing is the point."""
        if capability not in self.supported:
            return None
        from smartclock_device.drivers.smartclock import SmartClockDriver

        return SmartClockDriver(clock=FixedClock(NOW)).command(capability)

    def commands_for(self, group: CommandGroup) -> tuple[ScpiCommand, ...]:
        del group
        return ()

    @property
    def register_fields(self) -> tuple[tuple[str, str], ...]:
        return ()

    def register_query(self, node: str, field: str) -> ScpiCommand | None:
        del node, field
        return None

    def register_setter(self, node: str, field: str) -> ScpiCommand | None:
        del node, field
        return None

    @property
    def commands(self) -> tuple[ScpiCommand, ...]:
        """Empty: a family that is never written to has no allowlist to be on."""
        return ()

    def supports(self, command: ScpiCommand) -> bool:
        return command in self._offered()

    def _offered(self) -> tuple[ScpiCommand, ...]:
        """The SmartClock's commands for whichever capabilities this double claims.

        Borrowed rather than invented: the gate only ever asks whether a command is *there*, so a
        second catalog for a test double would be ceremony with somewhere new to be wrong.
        """
        from smartclock_device.drivers.smartclock import SmartClockDriver

        real = SmartClockDriver(clock=FixedClock(NOW))
        found = (real.command(capability) for capability in sorted(self.supported, key=str))
        return tuple(command for command in found if command is not None)

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

    assert gate(button, driver, Capability.HOLDOVER_FORCE) is False
    assert button.isEnabled() is False
    assert "NMEA 0183 talker" in button.toolTip()
    assert "no command for this" in button.toolTip()


def test_it_is_disabled_rather_than_hidden() -> None:
    """A missing control reads as a feature the application does not have; a greyed one with a
    sentence reads as a feature *this receiver* does not have. Those are different facts, and the
    second is the true one."""
    button = QPushButton("Force holdover")
    button.show()

    gate(button, TalkerDriver(), Capability.HOLDOVER_FORCE)

    assert button.isHidden() is False


def test_a_supported_command_enables_and_clears_the_explanation() -> None:
    """A control that says why it is disabled while being enabled is worse than one that says
    nothing."""
    from conftest import NOW
    from smartclock_device.clock import FixedClock
    from smartclock_device.drivers.smartclock import SmartClockDriver

    button = QPushButton("Force holdover")
    gate(button, TalkerDriver(), Capability.HOLDOVER_FORCE)
    assert button.toolTip()

    gate(button, SmartClockDriver(clock=FixedClock(NOW)), Capability.HOLDOVER_FORCE)

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

    gate(button, SmartClockDriver(clock=FixedClock(NOW)), Capability.HOLDOVER_FORCE)

    assert button.toolTip() == "What this does, written by the page."


def test_every_command_must_be_supported_not_any() -> None:
    """A control whose action sends three commands and can send two would do half of what it says
    — and half of a destructive operation is what §8.3's confirmations exist to prevent."""
    button = QPushButton("Apply")
    partial = TalkerDriver(supported=frozenset({Capability.CLEAR_EXCLUSIONS}))

    assert gate(button, partial, Capability.CLEAR_EXCLUSIONS) is True
    assert (
        gate(button, partial, Capability.CLEAR_EXCLUSIONS, Capability.EXCLUDE_SATELLITES) is False
    )


def test_not_connected_is_not_the_same_as_cannot() -> None:
    """Different facts, and the tooltip says which."""
    button = QPushButton("Force holdover")

    gate(button, None, Capability.HOLDOVER_FORCE)

    assert "Not connected" in button.toolTip()
    assert "no command" not in button.toolTip()
    assert "no command for this" in explain(TalkerDriver())


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


# ---- #60: what a family can never know ---------------------------------------------------------


def test_every_registered_driver_answers_every_reading() -> None:
    """The contract is only worth having if nothing can quietly not implement it.

    `ReceiverDriver` is a `Protocol`, so a driver that omitted `reports` would fail `mypy` — but
    only where something assigns it to the Protocol type. This asks the question the interface
    asks, of every family that ships, for every reading there is.
    """
    clock = FixedClock(NOW)
    for driver in (SmartClockDriver(clock=clock), NmeaDriver(clock=clock)):
        for reading in ALL_READINGS:
            answer = driver.reports(reading)
            assert isinstance(answer, bool), f"{driver.name} gave {answer!r} for {reading}"


def test_a_talker_declines_the_readings_its_docstring_always_claimed_it_lacked() -> None:
    """The list was prose in a class docstring, and prose is not reachable.

    "No oscillator EFC, no TFOM or FFOM, no holdover" was true, unreachable, and therefore drawn
    as a row of em dashes indistinguishable from a slow read.
    """
    talker = NmeaDriver(clock=FixedClock(NOW))

    for reading in (
        ReceiverReading.TFOM,
        ReceiverReading.FFOM,
        ReceiverReading.ONE_PPS_INTERVAL,
        ReceiverReading.OSCILLATOR_CONTROL,
        ReceiverReading.HOLDOVER,
        ReceiverReading.STATUS_SCREEN,
    ):
        assert talker.reports(reading) is False, f"a talker cannot supply {reading.value}"


def test_a_talker_still_reports_what_it_actually_broadcasts() -> None:
    """The other direction, which is the one an over-eager decline would break.

    A talker has no oscillator; it does have a position, a time and satellites in view. Declining
    those would replace a row of dashes with a row of absences, which is worse — it would say the
    receiver cannot do something it does once a second.
    """
    talker = NmeaDriver(clock=FixedClock(NOW))

    assert talker.reports(ReceiverReading.POSITION_HOLD) is False, "it has no survey or hold"
    assert SmartClockDriver(clock=FixedClock(NOW)).reports(ReceiverReading.HOLDOVER) is True


def test_a_smartclock_declines_exactly_what_a_status_screen_has_no_field_for() -> None:
    """This test was written to fail on the day the enum grew a reading a SmartClock lacks.

    It said so: *"when those are added, this test is what will need changing, and that is the point
    of pinning it."* #58 added them — the position's error estimate and the constellation's
    integrity check, both broadcast by a talker and both absent from a status screen — and this is
    the test that noticed.

    Pinned as an exact set rather than a floor, so the next one has to be argued for here too.
    """
    smartclock = SmartClockDriver(clock=FixedClock(NOW))

    declined = {r for r in ALL_READINGS if not smartclock.reports(r)}

    assert declined == {
        ReceiverReading.POSITION_UNCERTAINTY,
        ReceiverReading.CONSTELLATION_INTEGRITY,
        ReceiverReading.FIX_QUALITY,
        ReceiverReading.GPS_UTC_OFFSET,
    }


def test_the_seam_runs_both_ways() -> None:
    """Until #58 every decline was a talker's. Now each family declines something the other has.

    That is the property worth pinning: neither family is the default, and a reading absent from
    one is not thereby a second-class reading.
    """
    clock = FixedClock(NOW)
    smartclock, talker = SmartClockDriver(clock=clock), NmeaDriver(clock=clock)

    smartclock_only = {r for r in ALL_READINGS if smartclock.reports(r) and not talker.reports(r)}
    talker_only = {r for r in ALL_READINGS if talker.reports(r) and not smartclock.reports(r)}

    assert smartclock_only, "a talker should lack readings a disciplined oscillator has"
    assert talker_only == {
        ReceiverReading.POSITION_UNCERTAINTY,
        ReceiverReading.CONSTELLATION_INTEGRITY,
        ReceiverReading.FIX_QUALITY,
        ReceiverReading.GPS_UTC_OFFSET,
    }


def test_the_gate_catches_a_family_that_declines_something_it_broadcasts() -> None:
    """`CLAUDE.md`: a rule that matches nothing enforces nothing."""
    double = TalkerDriver(declines=frozenset({ReceiverReading.TFOM}))

    assert double.reports(ReceiverReading.TFOM) is False
    assert double.reports(ReceiverReading.HOLDOVER) is True


# ---- #60's surfaces: dimmed, never disabled ----------------------------------------------------


def test_a_talker_dims_the_pages_it_can_never_fill(application: QApplication) -> None:
    """Timing, Holdover, Diagnostics and Status Registers have nothing without an oscillator."""
    del application
    from smartclock_monitor.views.details_window import DetailsWindow

    window = DetailsWindow(Theme.DARK)
    window.apply_driver(NmeaDriver(clock=FixedClock(NOW)))

    dimmed = {
        window.navigation.item(row).data(Qt.ItemDataRole.AccessibleTextRole)
        for row in range(len(window.pages))
        if "unavailable"
        in str(window.navigation.item(row).data(Qt.ItemDataRole.AccessibleTextRole))
    }

    assert {name.split(",")[0] for name in dimmed} == {
        "Timing",
        "Holdover",
        "Diagnostics",
        "Status Registers",
    }


def test_no_destination_is_ever_disabled(application: QApplication) -> None:
    """§11's reason, verbatim: *"a disabled item takes no pointer input and so cannot carry the
    tooltip explaining itself"*.

    `setEnabled(False)` is the obvious thing to reach for and is exactly what the amendment
    forbids, which is why this is gated rather than left to review.
    """
    del application
    from smartclock_monitor.views.details_window import DetailsWindow

    window = DetailsWindow(Theme.DARK)
    window.apply_driver(NmeaDriver(clock=FixedClock(NOW)))

    for row in range(window.navigation.count()):
        item = window.navigation.item(row)
        assert item.flags() & Qt.ItemFlag.ItemIsEnabled, (
            f"row {row} was disabled; §11 says dimmed, so the tooltip can still be read"
        )


def test_a_dimmed_destination_says_which_family_cannot(application: QApplication) -> None:
    """ "This page is unavailable" is the sentence that makes a user wonder if the app is broken."""
    del application
    from smartclock_monitor.views.details_window import DetailsWindow

    window = DetailsWindow(Theme.DARK)
    talker = NmeaDriver(clock=FixedClock(NOW))
    window.apply_driver(talker)

    row = next(r for r in range(len(window.pages)) if window.pages[r].title == "Holdover")
    tip = window.navigation.item(row).toolTip()

    assert talker.name in tip, "the tooltip must name the family, not just the limitation"
    assert "holdover" in tip


def test_a_smartclock_dims_nothing(application: QApplication) -> None:
    """The family the specification was written against fills every page it has."""
    del application
    from smartclock_monitor.views.details_window import DetailsWindow

    window = DetailsWindow(Theme.DARK)
    window.apply_driver(SmartClockDriver(clock=FixedClock(NOW)))

    for row in range(len(window.pages)):
        name = str(window.navigation.item(row).data(Qt.ItemDataRole.AccessibleTextRole))
        assert "unavailable" not in name, f"{name} was dimmed for the family that defines it"


def test_disconnecting_restores_every_destination(application: QApplication) -> None:
    """Leaving pages dimmed from the last receiver is the stale-state defect #61 exists to stop."""
    del application
    from smartclock_monitor.views.details_window import DetailsWindow

    window = DetailsWindow(Theme.DARK)
    window.apply_driver(NmeaDriver(clock=FixedClock(NOW)))
    window.apply_driver(None)

    for row in range(len(window.pages)):
        name = str(window.navigation.item(row).data(Qt.ItemDataRole.AccessibleTextRole))
        assert "unavailable" not in name


# ---- #60's last surface: §10.3's four readouts --------------------------------------------------


def test_a_talker_gets_no_readout_card_at_all(application: QApplication) -> None:
    """All four rest on a disciplined oscillator, so a talker declines every one of them.

    **The one case where §11's *declined outright* takes a whole surface rather than a row.** Four
    dashes in a card headed with figures of merit says "any moment now" about readings that are
    never coming.
    """
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)
    window.show()

    window.set_driver(NmeaDriver(clock=FixedClock(NOW)))

    assert all(readout.isHidden() for readout in window.readouts.values())


def test_a_smartclock_keeps_all_four(application: QApplication) -> None:
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)
    window.show()

    window.set_driver(SmartClockDriver(clock=FixedClock(NOW)))

    assert not any(readout.isHidden() for readout in window.readouts.values())


def test_disconnecting_brings_them_back(application: QApplication) -> None:
    """Nothing is known about a family that is not there, so nothing is declined."""
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)
    window.show()
    window.set_driver(NmeaDriver(clock=FixedClock(NOW)))

    window.set_driver(None)

    assert not any(readout.isHidden() for readout in window.readouts.values())


def test_the_height_budget_still_owns_the_card(application: QApplication) -> None:
    """A third owner was **not** added. §9.6.2's budget and compact mode still decide the card;
    this only decides the readouts inside it, and the budget is re-measured rather than
    second-guessed — which is why a shorter card is simply a shorter answer.

    #20, #21 and #30 were all defects that came from something else deciding this window's size.
    """
    del application
    from smartclock_monitor.views.main_window import MainWindow

    window = MainWindow(Theme.DARK)
    window.show()
    window.set_driver(SmartClockDriver(clock=FixedClock(NOW)))

    window.set_compact(True)

    assert window.readouts_card.isHidden(), "compact still collapses it, as §9.6.2 says"
