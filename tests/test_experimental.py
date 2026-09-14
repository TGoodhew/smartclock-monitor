"""§8.5's experimental queries (P1-8), and §10.9's two omitted cards."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Callable, Sequence

from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from conftest import NOW
from smartclock_device.clock import FixedClock
from smartclock_device.commands import catalog
from smartclock_device.commands.blocked import is_blocked
from smartclock_device.commands.scpi_command import ResponseFormat, SafetyTier, ScpiCommand
from smartclock_device.drivers.capability import Capability
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.transport.transaction import Transaction, TransactionOutcome
from smartclock_monitor.platform.paths import log_directory, trend_database
from smartclock_monitor.services.preferences import Preferences
from smartclock_monitor.services.session import CommandOutcome
from smartclock_monitor.themes.tokens import Theme
from smartclock_monitor.views.details_window import DetailsWindow
from smartclock_monitor.views.diagnostics_page import DiagnosticsPage, _experimental_answer
from smartclock_monitor.views.settings_page import SettingsPage


@pytest.fixture(scope="module", autouse=True)
def application() -> QApplication:
    existing = QApplication.instance()
    return existing if isinstance(existing, QApplication) else QApplication([])


# ---- The list ----------------------------------------------------------------------------------


def test_there_are_exactly_six() -> None:
    """§8.5 says *"exactly"*, and says why the list is not filtered to what the connected receiver
    supports: the application would have to probe all six to know, which is what the card does
    anyway, and a list that changed shape by model would make "exactly" untrue."""
    assert len(catalog.EXPERIMENTAL) == 6


def test_they_are_the_six_the_spec_names() -> None:
    assert [command.mnemonic for command in catalog.EXPERIMENTAL] == [
        ":DIAG:ROSC:EFC:ABS?",
        ":DIAG:ROSC:EFC:TCO?",
        ":SYST:STAT:SLOG?",
        ":DIAG:STAC?",
        ":DIAG:PROC?",
        ":DIAG:MEM?",
    ]


def test_every_one_is_a_query_and_none_confirms() -> None:
    """§8.5's title: **query-only**. A setter here would be a command nobody has documentation for
    changing something nobody has documentation for."""
    for command in catalog.EXPERIMENTAL:
        assert command.is_query is True, command.mnemonic
        assert command.tier is SafetyTier.SAFE
        assert command.response is ResponseFormat.TEXT


def test_none_of_them_is_excluded() -> None:
    """The join between §8.1 and §8.4 again, for the one group most likely to trip it: these are
    undocumented, which is not the same as forbidden."""
    for command in catalog.EXPERIMENTAL:
        assert is_blocked(command.mnemonic) is False


def test_they_are_on_the_allowlist_whether_or_not_the_card_is_shown() -> None:
    """§10.13: *"Opting in changes what is reachable, never what is permitted."* The switch adds
    a card, not a capability."""
    for command in catalog.EXPERIMENTAL:
        assert catalog.is_allowed(command.mnemonic) is True


# ---- What the card shows -----------------------------------------------------------------------


def answered(text: str = "", prompt: str | None = None) -> Transaction:
    return Transaction(
        command=":DIAG:MEM?",
        outcome=TransactionOutcome.COMPLETED,
        lines=(text,) if text else (),
        prompt_status=prompt,
    )


def test_a_body_is_shown_verbatim() -> None:
    """§8.5: results shown as raw text. `:DIAG:ROSC:EFC:ABSolute?` returns +436061 on this
    receiver while the documented relative query returns −16.83 % at the same moment — nothing
    states the units of the first, and nothing may assume them."""
    assert _experimental_answer(answered("+437265")) == "+437265"


def test_e_113_is_reported_as_an_answer_not_a_failure() -> None:
    """§8.5: *"E-113 is an answer, not a failure."* It is SCPI's undefined header — the node is
    not in this firmware's parser — and for a card whose entire purpose is asking undocumented
    questions that is a result, and the most useful one available for five of the six."""
    shown = _experimental_answer(answered(prompt="E-113"))

    assert "E-113" in shown
    assert "fail" not in shown.lower()
    assert "error in" not in shown.lower()


def test_it_is_worded_as_the_queue_s_state_not_this_query_s_answer() -> None:
    """§7.2 measured the difference: with a single error queued, three successive commands that
    each succeeded and returned correct data all carried an E-113 prompt, because the prompt names
    the *newest queued* error while :SYST:ERR? returns the oldest first. "This returned E-113"
    would be a claim the prompt does not support."""
    shown = _experimental_answer(answered(prompt="E-113"))

    assert "error queue" in shown
    assert "returned E-113" not in shown


def test_no_answer_and_no_prompt_says_so() -> None:
    assert _experimental_answer(answered()) == "no answer"


# ---- The opt-in --------------------------------------------------------------------------------


def test_the_card_is_hidden_by_default() -> None:
    """Off by default, per §8.5 and §10.13's table — it reveals a surface a user has to go looking
    for."""
    assert Preferences().undocumented_queries is False
    assert DiagnosticsPage()._experimental_card.isVisible() is False


def test_the_switch_shows_the_card() -> None:
    window = DetailsWindow(Theme.DARK)
    page = window.page_named(DiagnosticsPage.title)
    assert isinstance(page, DiagnosticsPage)

    window.apply_preferences(Preferences(undocumented_queries=True))
    assert page._experimental_card.isHidden() is False

    window.apply_preferences(Preferences(undocumented_queries=False))
    assert page._experimental_card.isHidden() is True


def test_the_switch_carries_section_8_5_s_own_words() -> None:
    """It is the one place a user is told what they are opting into, and paraphrasing a safety
    notice is how the guarantee drifts."""
    page = SettingsPage()
    text = " ".join(child.text() for child in page.findChildren(QLabel))

    assert "absent from the published manual" in text
    assert "may return errors or nonsense" in text
    assert "No setting is changed" in text


def test_the_switch_round_trips_through_preferences() -> None:
    page = SettingsPage()
    page.undocumented_switch.setChecked(True)

    assert page.preferences.undocumented_queries is True


# ---- §10.9's application log card --------------------------------------------------------------


def test_the_log_folder_sits_beside_the_trend_store() -> None:
    """§10.9's *Show log folder* opens one folder, and a user looking for "the files this thing
    wrote" should find all of them there."""
    assert log_directory().parent == trend_database().parent


def test_the_card_names_the_path_and_what_goes_in_it() -> None:
    """§10.9: what *this application* saw, as distinct from what the receiver logged. The two are
    different records and the page carries both, because "did the receiver drop out" and "did we
    lose the port" look identical from the outside."""
    page = DiagnosticsPage()
    text = " ".join(child.text() for child in page.findChildren(QLabel))

    assert str(log_directory()) in text
    assert "port opening" in text
    assert "connection change" in text


# ---- #105: five of the six do not exist on the bench firmware -----------------------------------


def test_an_undefined_header_is_reported_as_a_fact_about_the_receiver(
    application: QApplication,
) -> None:
    """**Measured on the bench Z3805A**, `SYMMETRICOM,Z3805A,3625A02931,1.01.03-A`.

    With the error queue drained first, five of §8.5's six answer `-113,"Undefined header"` — the
    receiver does not have the mnemonic at all — and only `:DIAG:ROSC:EFC:ABS?` answers, with
    `+437157`. §10.13's opt-in was offering six controls, five of which cannot work.

    "This receiver does not have this query" is the most useful answer a card of undocumented
    questions can give, and it is only sayable because the queue is read straight after the ask.
    """
    del application
    page = DiagnosticsPage()
    runner = _FakeRunner(
        {":DIAG:STAC?": ("", '-113,"Undefined header"')},
    )
    page.set_command_runner(runner)
    page._rebuild_experimental(SmartClockDriver(clock=FixedClock(NOW)))

    page._run_experimental(_command(":DIAG:STAC?"))

    assert "does not have this query" in page._experimental_rows[":DIAG:STAC?"].text()


def test_a_query_the_receiver_does_have_shows_its_answer(application: QApplication) -> None:
    """`:DIAG:ROSC:EFC:ABS?` is the one of the six this firmware answers."""
    del application
    page = DiagnosticsPage()
    page.set_command_runner(_FakeRunner({":DIAG:ROSC:EFC:ABS?": ("+437157", '+0,"No error"')}))
    page._rebuild_experimental(SmartClockDriver(clock=FixedClock(NOW)))

    page._run_experimental(_command(":DIAG:ROSC:EFC:ABS?"))

    assert page._experimental_rows[":DIAG:ROSC:EFC:ABS?"].text() == "+437157"


def test_the_queue_is_drained_before_the_query_is_asked(application: QApplication) -> None:
    """**Without this the card cannot say anything, and used to say so.**

    §7.2 measured it: with one error queued, three successive commands that each *succeeded* all
    carried an `E-113` prompt, because the prompt names a queued error rather than a verdict. The
    card correctly refused to interpret that. Draining first is what makes the reading afterwards
    this query's.
    """
    del application
    page = DiagnosticsPage()
    runner = _FakeRunner({":DIAG:MEM?": ("", '-113,"Undefined header"')})
    page.set_command_runner(runner)
    page._rebuild_experimental(SmartClockDriver(clock=FixedClock(NOW)))

    page._run_experimental(_command(":DIAG:MEM?"))

    asked = [getattr(c, "mnemonic", c) for c, _ in runner.last_batch]
    assert asked.count(Capability.ERROR_QUEUE) >= 2, "drained before, and read after"
    assert asked.index(":DIAG:MEM?") > 0, "the drains come first"
    assert asked[-1] is Capability.ERROR_QUEUE, "and the attributing read comes last"


def test_a_reconnection_forgets_what_the_last_receiver_lacked(application: QApplication) -> None:
    """§8.5's queries are undocumented, so no model number predicts which a firmware has.

    Carrying one unit's answer to the next would be the singleton defect #61 was about, in a
    different costume.
    """
    del application
    page = DiagnosticsPage()
    page.set_command_runner(_FakeRunner({":DIAG:MEM?": ("", '-113,"Undefined header"')}))
    driver = SmartClockDriver(clock=FixedClock(NOW))
    page._rebuild_experimental(driver)
    page._run_experimental(_command(":DIAG:MEM?"))
    assert page._experimental_absent

    page._rebuild_experimental(None)
    page._rebuild_experimental(SmartClockDriver(clock=FixedClock(NOW)))

    assert page._experimental_absent == set()


class _FakeRunner:
    """Answers a batch in order, the way `CommandRunner` does."""

    def __init__(self, answers: dict[str, tuple[str, str]]) -> None:
        self._answers = answers
        self.last_batch: list[tuple[Capability | ScpiCommand, object]] = []
        self.driver = SmartClockDriver(clock=FixedClock(NOW))
        self.is_connected = True

    def run(
        self,
        commands: Sequence[tuple[Capability | ScpiCommand, object]],
        then: Callable[[Sequence[CommandOutcome]], None] | None = None,
    ) -> None:
        """Typed to the real `CommandRunner`'s signature rather than to `Any`.

        `mypy --strict` is what makes §11.1's "every consumer handles None" checkable, and a double
        that satisfies a call by being untyped opts the test out of exactly that.
        """
        self.last_batch = list(commands)
        outcomes = []
        queued = ""
        for command, _argument in commands:
            # The page also asks by **capability** elsewhere, and `refresh()` does so the moment a
            # runner is set — so a double for this card has to tolerate both kinds of request.
            if isinstance(command, Capability):
                body = queued or '+0,"No error"' if command is Capability.ERROR_QUEUE else ""
                if command is Capability.ERROR_QUEUE:
                    queued = ""
                outcomes.append(
                    CommandOutcome(
                        command=None,
                        capability=command,
                        transaction=Transaction(
                            command=str(command),
                            outcome=TransactionOutcome.COMPLETED,
                            lines=(body,) if body else (),
                        ),
                    )
                )
                continue
            # Past the branch above, this is a ScpiCommand — the error queue is only ever asked
            # for by capability now, which is what `test_layering.py` requires of a page.
            body, raised = self._answers.get(command.mnemonic, ("", ""))
            if raised:
                queued = raised
            outcomes.append(
                CommandOutcome(
                    command=command,
                    transaction=Transaction(
                        command=command.mnemonic,
                        outcome=TransactionOutcome.COMPLETED,
                        lines=(body,) if body else (),
                    ),
                )
            )
        if then is not None:
            then(outcomes)


def _command(mnemonic: str) -> ScpiCommand:
    """One catalogued command, typed. `catalog.find` is `ScpiCommand | None` by design."""
    found = catalog.find(mnemonic)
    assert found is not None, f"{mnemonic} is not catalogued"
    return found


# ---- #114: a third answer, beside an answer and an undefined header ------------------------------


def _button_for(page: DiagnosticsPage, mnemonic: str) -> QPushButton:
    for button, command in zip(page._experimental_buttons, page._experimental_shown, strict=False):
        if command.mnemonic == mnemonic:
            return button
    raise KeyError(mnemonic)


def test_stale_data_is_worded_as_not_yet_rather_than_never(application: QApplication) -> None:
    """**Measured on the bench Z3805A**, 13 Sep 2026: `:PTIM:LEAP:GPST?` answers
    `-230,"Data corrupt or stale"` — the receiver has the mnemonic and has nothing to answer with.

    That is a different fact from `-113`, and the difference is the whole point: `-113` means never
    and this means *not yet*. §10.14 records the same code from `:PTIM:LEAP:DATE?` and `:DUR?`
    whenever no leap second is announced, which is most of the time and never permanently.
    """
    del application
    page = DiagnosticsPage()
    page.set_command_runner(_FakeRunner({":DIAG:STAC?": ("", '-230,"Data corrupt or stale"')}))
    page._rebuild_experimental(SmartClockDriver(clock=FixedClock(NOW)))

    page._run_experimental(_command(":DIAG:STAC?"))

    assert "no data for it yet" in page._experimental_rows[":DIAG:STAC?"].text()


def test_a_stale_answer_leaves_the_button_offering(application: QApplication) -> None:
    """The behavioural half, and the one that matters. The same query may answer perfectly an hour
    later; disabling it would be the `-113` treatment applied to the opposite fact."""
    del application
    page = DiagnosticsPage()
    page.set_command_runner(_FakeRunner({":DIAG:STAC?": ("", '-230,"Data corrupt or stale"')}))
    page._rebuild_experimental(SmartClockDriver(clock=FixedClock(NOW)))

    page._run_experimental(_command(":DIAG:STAC?"))

    assert _button_for(page, ":DIAG:STAC?").isEnabled() is True


def test_an_undefined_header_still_stops_offering(application: QApplication) -> None:
    """The control for the test above: the two codes must part company, and a change that worded
    `-230` by widening the `-113` branch would pass one of these and fail this one."""
    del application
    page = DiagnosticsPage()
    page.set_command_runner(_FakeRunner({":DIAG:STAC?": ("", '-113,"Undefined header"')}))
    page._rebuild_experimental(SmartClockDriver(clock=FixedClock(NOW)))

    page._run_experimental(_command(":DIAG:STAC?"))

    assert _button_for(page, ":DIAG:STAC?").isEnabled() is False


def test_any_other_error_is_shown_in_the_receivers_own_words(application: QApplication) -> None:
    """Two codes are worded and no more. Inventing sentences for codes nobody has seen is how a
    catalogue of wrong explanations gets built, so everything else is quoted rather than
    interpreted."""
    del application
    page = DiagnosticsPage()
    page.set_command_runner(_FakeRunner({":DIAG:STAC?": ("", '-221,"Settings conflict"')}))
    page._rebuild_experimental(SmartClockDriver(clock=FixedClock(NOW)))

    page._run_experimental(_command(":DIAG:STAC?"))

    assert "Settings conflict" in page._experimental_rows[":DIAG:STAC?"].text()
