"""§9.7.4's confirmation dialog and §7.2's tier C send path.

The assertions here are about *roles*, not about appearance. §9.7.4 amends §8.3 to put the
destructive action on the primary button and Cancel as the default, and §8.3's own note records
that the specification said the opposite for a while — so anyone implementing §8 in order would
have built a dialog where Enter fires the destructive command. That is what these pin.
"""

from __future__ import annotations

import asyncio
import os
from datetime import timedelta

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.commands.scpi_command import (
    ArgumentKind,
    ResponseFormat,
    SafetyTier,
    ScpiCommand,
)
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.transport.fake import FakeTransport
from smartclock_monitor.services.session import DeviceSession
from smartclock_monitor.themes.tokens import ALL_THEMES, Theme, palette_for
from smartclock_monitor.views.confirm_dialog import ACKNOWLEDGEMENT, ConfirmDialog, ask

PROMPT = "scpi > "


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(NOW)


# ---- The dialog's roles ------------------------------------------------------------------------


def test_cancel_is_the_default_button_not_the_destructive_one() -> None:
    """§9.7.4, in as many words: *"Cancel is the CloseButton and is DefaultButton, so Enter and
    initial focus land on the safe option."* Someone holding Enter through a dialog they did not
    read must not force the receiver into holdover."""
    dialog = ConfirmDialog(catalog.HOLDOVER_FORCE)
    dialog.show()

    assert dialog.cancel_button.isDefault() is True
    assert dialog.confirm_button.isDefault() is False
    # Shown first: Qt assigns focus when a widget becomes visible, so a dialog asserted on before
    # that would pass with focus nowhere — which is the state a user never sees.
    assert dialog.focusWidget() is dialog.cancel_button
    dialog.close()


def test_the_destructive_button_is_never_the_accent_one() -> None:
    """*"Accent means the safe thing to do next."* The role is what the generated stylesheet keys
    the destructive treatment on, so asserting the role asserts the styling."""
    dialog = ConfirmDialog(catalog.CLEAR_DIAGNOSTIC_LOG)

    assert dialog.confirm_button.property("role") == "destructive"
    assert dialog.cancel_button.property("role") != "destructive"


@pytest.mark.parametrize("theme", ALL_THEMES, ids=lambda t: t.value)
def test_the_destructive_style_reaches_the_stylesheet_in_every_theme(theme: Theme) -> None:
    """A role nothing styles is a plain button wearing a safety claim."""
    from smartclock_monitor.themes.qss import stylesheet

    sheet = stylesheet(palette_for(theme))

    assert 'QPushButton[role="destructive"]' in sheet
    assert palette_for(theme).critical in sheet


def test_the_button_says_what_it_will_do_rather_than_ok() -> None:
    """§9.7.4 puts the destructive action on the primary button precisely so a user can see what
    they are about to do without re-reading the sentence. "OK" undoes that."""
    dialog = ConfirmDialog(catalog.CLEAR_DIAGNOSTIC_LOG)
    label = dialog.confirm_button.text()

    assert label.lower() != "ok"
    assert "log" in label.lower()


def test_the_sentence_is_the_command_s_own() -> None:
    """§8.3's amendment note: ``:IGN:NONE`` shared the exclusion sentence for a command that
    *clears* the exclusion list. A dialog assembling its own text from a template would
    reintroduce that one template at a time."""
    dialog = ConfirmDialog(catalog.HOLDOVER_FORCE)

    assert catalog.HOLDOVER_FORCE.confirmation in _labels(dialog)


def _labels(dialog: ConfirmDialog) -> list[str]:
    return [label.text() for label in dialog.findChildren(QLabel)]


def test_the_exact_command_is_shown() -> None:
    """§9.5.1's device-literal rule. Someone checking a destructive command against the manual
    needs the text that will actually go out, including its argument."""
    dialog = ConfirmDialog(catalog.SET_HOLDOVER_DURATION_THRESHOLD, 600)

    assert ":SYNC:HOLD:DUR:THR 600" in _labels(dialog)


# ---- The acknowledgement tick --------------------------------------------------------------------


def test_the_strong_variant_gates_the_button_behind_a_tick() -> None:
    """P0-8.

    §9.7.4: a CheckBox gates the PrimaryButton's IsEnabled for the strong variants. Forcing
    holdover inside 24 hours of power-up corrupts oscillator learning, and no amount of clicking
    again undoes it."""
    dialog = ConfirmDialog(catalog.HOLDOVER_FORCE)

    assert dialog.acknowledgement is not None
    assert dialog.acknowledgement.text() == ACKNOWLEDGEMENT
    assert dialog.confirm_button.isEnabled() is False

    dialog.acknowledgement.setChecked(True)
    assert dialog.confirm_button.isEnabled() is True

    dialog.acknowledgement.setChecked(False)
    assert dialog.confirm_button.isEnabled() is False


def test_an_ordinary_tier_c_command_has_no_tick() -> None:
    """The tick is the strong variant's mechanism. On every dialog it would stop being read, which
    is the same failure as a gate that cries wolf."""
    dialog = ConfirmDialog(catalog.SET_HOLDOVER_DURATION_THRESHOLD, 600)

    assert dialog.acknowledgement is None
    assert dialog.confirm_button.isEnabled() is True


def test_a_safe_command_is_never_asked_about() -> None:
    """§8.2: tier S executes on click. Keeping that decision in the catalog rather than at each
    call site is what stops it being got wrong somewhere."""
    assert ask(catalog.STATUS_SCREEN) is True
    assert ask(catalog.HOLDOVER_RECOVER) is True


# ---- The send path -----------------------------------------------------------------------------

PROBE = timedelta(milliseconds=20)


async def _session(clock: FixedClock, responses: dict[str, str]) -> DeviceSession:
    transport = FakeTransport(
        {
            # *CLS is part of the connect sequence, and a fake that does not answer it costs the
            # full timeout twice — four seconds a session, which was most of this module's runtime.
            "*CLS": "",
            "*IDN?": "SYMMETRICOM,Z3805A,3625A02931,1.01.03-A",
            **responses,
        }
    )
    session = DeviceSession(transport, SmartClockDriver(clock=clock), clock)
    await session.open(probe=PROBE)
    return session


def test_a_setter_sends_its_rendered_argument(clock: FixedClock) -> None:
    async def run() -> None:
        session = await _session(
            clock,
            {":SYNC:HOLD:DUR:THR 600": "", ":SYST:ERR?": '+0,"No error"'},
        )
        outcome = await session.execute_command(catalog.SET_HOLDOVER_DURATION_THRESHOLD, 600)

        assert outcome.sent == ":SYNC:HOLD:DUR:THR 600"
        assert outcome.error is None
        assert outcome.succeeded is True
        await session.close()

    asyncio.run(run())


def test_the_error_queue_is_read_after_a_tier_c_command(clock: FixedClock) -> None:
    """§7.2, and the reason it is here rather than at each call site: a receiver that rejected a
    setter answers the setter itself with a prompt and says why only when asked. A page that
    forgot to ask would report success for a command the receiver refused."""

    async def run() -> None:
        session = await _session(
            clock,
            {":DIAG:LOG:CLE": "", ":SYST:ERR?": '-221,"Settings conflict"'},
        )
        outcome = await session.execute_command(catalog.CLEAR_DIAGNOSTIC_LOG)

        assert outcome.transaction is not None and outcome.transaction.succeeded
        assert outcome.error == '-221,"Settings conflict"'
        assert outcome.succeeded is False, "it went out; it did not work"
        await session.close()

    asyncio.run(run())


def test_no_error_is_not_reported_as_one(clock: FixedClock) -> None:
    """``+0,"No error"`` is the receiver saying it is happy. Reporting it as a fault would make
    every successful setter look like a failure."""

    async def run() -> None:
        session = await _session(clock, {":DIAG:LOG:CLE": "", ":SYST:ERR?": '+0,"No error"'})
        outcome = await session.execute_command(catalog.CLEAR_DIAGNOSTIC_LOG)

        assert outcome.error is None
        assert outcome.succeeded is True
        await session.close()

    asyncio.run(run())


def test_a_safe_command_does_not_cost_an_extra_round_trip(clock: FixedClock) -> None:
    """§7.2 requires the error queue after tier C. Reading it after every command would double the
    traffic on a link where the full status screen already takes 3.5 seconds."""

    async def run() -> None:
        session = await _session(clock, {":DIAG:LIF:COUN?": "+1247"})
        outcome = await session.execute_command(catalog.LIFETIME_HOURS)

        assert outcome.succeeded is True
        assert outcome.error is None, "not read at all, rather than read and empty"
        await session.close()

    asyncio.run(run())


def test_an_out_of_range_argument_is_refused_before_anything_is_sent(clock: FixedClock) -> None:
    """The bounds are the validation — there is nowhere else it happens. A refusal here costs a
    message; a value out of range costs a round trip and an error the user has to interpret."""

    async def run() -> None:
        session = await _session(clock, {})
        outcome = await session.execute_command(catalog.SET_HOLDOVER_DURATION_THRESHOLD, 0)

        assert outcome.refusal is not None
        assert outcome.sent is None
        assert outcome.succeeded is False
        await session.close()

    asyncio.run(run())


def test_an_uncatalogued_command_object_is_still_refused(clock: FixedClock) -> None:
    """The point-of-send check is on the header and does not care where the object came from.
    Handing the session a hand-built ScpiCommand must not get past the allowlist — §8.1's whole
    claim is that a command not in the catalog does not exist."""
    invented = ScpiCommand(
        mnemonic=":NOSUCH:THING",
        summary="Not in the catalog",
        response=ResponseFormat.NONE,
        tier=SafetyTier.CONFIRM,
        argument=ArgumentKind.NONE,
        confirmation="Do the thing?",
    )

    async def run() -> None:
        session = await _session(clock, {})
        outcome = await session.execute_command(invented)

        assert outcome.refusal is not None
        assert "not in the catalog" in outcome.refusal.reason
        assert outcome.sent is None
        await session.close()

    asyncio.run(run())
