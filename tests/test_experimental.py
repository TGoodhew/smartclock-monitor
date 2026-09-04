"""§8.5's experimental queries (P1-8), and §10.9's two omitted cards."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel

from smartclock_device.commands import catalog
from smartclock_device.commands.blocked import is_blocked
from smartclock_device.commands.scpi_command import ResponseFormat, SafetyTier
from smartclock_device.transport.transaction import Transaction, TransactionOutcome
from smartclock_monitor.platform.paths import log_directory, trend_database
from smartclock_monitor.services.preferences import Preferences
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
