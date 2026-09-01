"""P1-9's lock-loss watch.

**The quiet is what is being tested.** §10.13 defaults the preference on and says it is only safe
to default on because the watch stays quiet through the flapping a real receiver's log is full of —
the bench Z3805A's log alternates *GPS lock started* and *Holdover started, not tracking GPS* for
most of its 222 entries. A watch that fired on every transition would produce dozens of
notifications a day and the user would turn it off, which means it would be silent at the moment it
existed for.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from conftest import NOW
from smartclock_device.models.receiver_status import ReceiverStatus, SmartClockMode
from smartclock_monitor.platform.notifications import (
    NoNotifier,
    for_this_desktop,
)
from smartclock_monitor.services.lock_watch import (
    SUSTAINED_LOSS,
    SUSTAINED_RECOVERY,
    LockWatch,
    Watched,
)
from smartclock_monitor.services.polling import Reading


def at(seconds: float, mode: SmartClockMode) -> Reading:
    moment = NOW + timedelta(seconds=seconds)
    return Reading(status=ReceiverStatus(captured_at=moment, mode=mode), captured_at=moment)


def watching() -> tuple[LockWatch, list[str], list[str]]:
    lost: list[str] = []
    back: list[str] = []
    return LockWatch(on_lost=lost.append, on_recovered=back.append), lost, back


LOCKED = SmartClockMode.LOCKED
HOLD = SmartClockMode.HOLDOVER


# ---- Staying quiet -----------------------------------------------------------------------------


def test_a_receiver_that_flaps_says_nothing() -> None:
    """The case the default depends on. Ten cycles of a few seconds each, which is what the
    receiver's own log looks like — and not one notification."""
    watch, lost, back = watching()

    second = 0.0
    for _ in range(10):
        watch.observe(at(second, LOCKED))
        watch.observe(at(second + 5, HOLD))
        watch.observe(at(second + 15, LOCKED))
        second += 30

    assert lost == []
    assert back == []


def test_a_brief_loss_is_not_announced() -> None:
    """Under the threshold. The receiver's own recovery from a brief obstruction is measured in
    seconds, which is why the threshold sits above it."""
    watch, lost, _ = watching()
    watch.observe(at(0, LOCKED))
    watch.observe(at(1, HOLD))
    watch.observe(at(SUSTAINED_LOSS.total_seconds() - 1, HOLD))
    watch.observe(at(SUSTAINED_LOSS.total_seconds(), LOCKED))

    assert lost == []
    assert watch.state is Watched.LOCKED


def test_the_first_reading_never_announces() -> None:
    """An application started while the receiver was already in holdover would otherwise open
    with an alert about a condition that predates it, which the user cannot act on and did not
    cause."""
    watch, lost, _ = watching()
    watch.observe(at(0, HOLD))

    assert lost == []
    assert watch.state is Watched.SLIPPING


# ---- Speaking up -------------------------------------------------------------------------------


def test_a_sustained_loss_is_announced_once() -> None:
    watch, lost, _ = watching()
    watch.observe(at(0, LOCKED))
    watch.observe(at(1, HOLD))
    watch.observe(at(SUSTAINED_LOSS.total_seconds() + 1, HOLD))

    assert len(lost) == 1
    assert "holdover" in lost[0]
    assert watch.state is Watched.LOST


def test_it_does_not_repeat_while_the_loss_continues() -> None:
    """A repeating alarm about a condition the user has already seen is how an alert channel gets
    muted. It reports the *transition*, not the state."""
    watch, lost, _ = watching()
    watch.observe(at(0, LOCKED))
    for second in range(1, 600, 5):
        watch.observe(at(second, HOLD))

    assert len(lost) == 1


def test_the_sentence_is_a_whole_one_and_names_the_mode() -> None:
    """§9.4.3.1: *"Holdover" alone is this application's vocabulary*, and someone meeting it in a
    desktop notification has no other context to read it in."""
    watch, lost, _ = watching()
    watch.observe(at(0, LOCKED))
    watch.observe(at(1, SmartClockMode.RECOVERY))
    watch.observe(at(SUSTAINED_LOSS.total_seconds() + 1, SmartClockMode.RECOVERY))

    assert lost[0].endswith(".")
    assert "reacquire" in lost[0]
    assert lost[0] != "Holdover"


def test_recovery_is_announced_once_it_has_settled() -> None:
    watch, lost, back = watching()
    watch.observe(at(0, LOCKED))
    watch.observe(at(1, HOLD))
    watch.observe(at(120, HOLD))
    assert len(lost) == 1

    watch.observe(at(121, LOCKED))
    assert back == [], "not yet — it has to hold"

    watch.observe(at(121 + SUSTAINED_RECOVERY.total_seconds(), LOCKED))
    assert len(back) == 1
    assert watch.state is Watched.LOCKED


def test_dropping_out_again_before_recovery_settles_does_not_re_announce() -> None:
    """The hysteresis. A receiver hovering at the edge would otherwise produce a notification per
    cycle, which is the flapping case wearing a different hat."""
    watch, lost, back = watching()
    watch.observe(at(0, LOCKED))
    watch.observe(at(1, HOLD))
    watch.observe(at(120, HOLD))

    for second in range(121, 2000, 30):
        watch.observe(at(second, LOCKED if (second // 30) % 2 else HOLD))

    assert len(lost) == 1, "announced once, at the start"
    assert back == [], "and never claimed to have recovered"


def test_a_second_real_loss_is_announced_again() -> None:
    """One notification per real event — including the second one."""
    watch, lost, back = watching()
    watch.observe(at(0, LOCKED))
    watch.observe(at(1, HOLD))
    watch.observe(at(120, HOLD))
    watch.observe(at(121, LOCKED))
    watch.observe(at(600, LOCKED))
    assert len(back) == 1

    watch.observe(at(601, HOLD))
    watch.observe(at(700, HOLD))

    assert len(lost) == 2


# ---- The preference ----------------------------------------------------------------------------


def test_switching_it_off_silences_it_without_losing_track() -> None:
    """The state is still followed while the preference is off, so switching it *on* does not
    immediately announce a loss that happened an hour ago."""
    watch, lost, _ = watching()
    watch.enabled = False
    watch.observe(at(0, LOCKED))
    watch.observe(at(1, HOLD))
    watch.observe(at(120, HOLD))

    assert lost == []
    assert watch.state is Watched.LOST

    watch.enabled = True
    watch.observe(at(200, HOLD))
    assert lost == [], "still nothing: the transition already happened"


# ---- The notifier ------------------------------------------------------------------------------


def test_the_fallback_says_nothing_successfully() -> None:
    """Silence is a supported outcome. P1-10's notification area and #274's badge are Windows
    shell surfaces and whether this port grows equivalents is issue #6 — undecided."""
    assert NoNotifier().notify("anything") is False


def test_a_notifier_is_always_available() -> None:
    """A caller asks for one and gets one that works or one that does nothing; there is no third
    case for it to handle."""
    notifier = for_this_desktop()

    assert hasattr(notifier, "notify")
    assert isinstance(notifier.notify("probe"), bool)


def test_a_notification_is_never_the_only_channel() -> None:
    """Structural: the watch is fed by the same readings the window renders, so anything it would
    announce is on screen whether or not the desktop can raise a notification."""
    watch, lost, _ = watching()
    watch.on_lost = None  # nobody listening at all
    watch.observe(at(0, LOCKED))
    watch.observe(at(1, HOLD))
    watch.observe(at(120, HOLD))

    assert watch.state is Watched.LOST, "the state is tracked regardless"
    assert lost == []


@pytest.mark.parametrize("mode", list(SmartClockMode))
def test_every_mode_produces_a_sentence(mode: SmartClockMode) -> None:
    """§11.1's discipline applied to copy: a mode this build does not expect must still say
    something a user can read."""
    watch, lost, _ = watching()
    watch.observe(at(0, LOCKED))
    watch.observe(at(1, mode))
    watch.observe(at(200, mode))

    if mode is LOCKED:
        assert lost == []
    else:
        assert lost and lost[0].endswith(".")
