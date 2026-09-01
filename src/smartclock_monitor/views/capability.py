"""§9.11's rule for a control the connected family cannot support.

**Absent means disabled and explained, never hidden.** The control stays where it is, greyed, with
one sentence naming the family and saying it has no command for this. §12's #304 is the reason
that is a rule rather than a preference: every Details page asked for its tier C commands in a form
that throws, which was *"correct while one family shipped, and a crash on navigation the day a
reads-only talker arrived"*.

Hiding would be worse than greying for the same reason §9.11 gives everywhere else — a control that
is missing reads as a feature the application does not have, where a greyed one with a sentence
reads as a feature *this receiver* does not have. Those are different facts, and the second is the
true one.

**Nothing here decides what a family supports.** It asks the driver, which is the whole point of
the seam: a page that knew which families had which commands would be the scatter of conditionals
the driver exists to prevent.

**It takes capabilities, not commands.** A page names what it wants done and the driver answers
with its own command or with nothing, so the page never holds another family's mnemonic. Passing a
``ScpiCommand`` here would have meant passing *the SmartClock's* command object to whichever driver
happened to be connected — which worked, because the other one answers ``False``, and read as
decoupled without being so.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.drivers.capability import Capability
from smartclock_monitor.services.commands import CommandRunner


def explain(driver: ReceiverDriver | None) -> str:
    """One sentence for a control the connected receiver cannot drive."""
    if driver is None:
        return "Not connected, so this cannot be sent yet."
    return f"{driver.name} has no command for this."


def resolve(driver: ReceiverDriver | None, capability: Capability) -> ScpiCommand | None:
    """The connected family's command for a capability, or ``None``.

    The one place a page turns a want into something sendable. Kept beside the gate because the
    two answer the same question — the gate asks whether it *can* be sent, this asks *what* — and
    a page that resolved without gating would be back to a button that fails on click.
    """
    return None if driver is None else driver.command(capability)


def command_for(runner: CommandRunner | None, capability: Capability) -> ScpiCommand | None:
    """The connected family's command for a capability, given a page's runner.

    The form a page actually needs: pages hold a runner, not a driver, and going through the
    runner keeps "which family is connected" a single fact read at the moment it is used rather
    than a copy kept on the page and gone stale by the next reconnect.
    """
    return resolve(None if runner is None else runner.driver, capability)


def gate(control: QWidget, driver: ReceiverDriver | None, *capabilities: Capability) -> bool:
    """Enable ``control`` only where the driver offers **every** capability it would use.

    Returns whether it was enabled, so a caller can gate a second thing on the same answer without
    asking twice.

    **Every**, not any: a control whose action sends three commands and can send two of them would
    do half of what it says, and half of a destructive operation is the outcome §8.3's
    confirmations exist to prevent a user stumbling into.

    A missing driver disables without claiming the family lacks anything — not connected and
    cannot do this are different facts, and the tooltip says which.
    """
    supported = driver is not None and all(
        driver.command(capability) is not None for capability in capabilities
    )
    control.setEnabled(supported)

    if supported:
        # Clear a previous explanation rather than leaving it: a control that says why it is
        # disabled while being enabled is worse than one that says nothing.
        if control.toolTip().endswith(_MARKER):
            control.setToolTip("")
        return True

    control.setToolTip(explain(driver) + _MARKER)
    return False


#: A zero-width marker on tooltips this module wrote, so it can take back its own and never
#: somebody else's. A page may have set a useful tooltip of its own, and clearing that on connect
#: would silently remove documentation nobody noticed was gone.
_MARKER = "​"
