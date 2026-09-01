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
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.drivers.base import ReceiverDriver


def explain(driver: ReceiverDriver | None, command: ScpiCommand) -> str:
    """One sentence for a control the connected receiver cannot drive."""
    if driver is None:
        return "Not connected, so this cannot be sent yet."
    return f"{driver.name} has no command for this."


def gate(control: QWidget, driver: ReceiverDriver | None, *commands: ScpiCommand) -> bool:
    """Enable ``control`` only where the driver supports **every** command it would send.

    Returns whether it was enabled, so a caller can gate a second thing on the same answer without
    asking twice.

    **Every**, not any: a control whose action sends three commands and can send two of them would
    do half of what it says, and half of a destructive operation is the outcome §8.3's
    confirmations exist to prevent a user stumbling into.

    A missing driver disables without claiming the family lacks anything — not connected and
    cannot do this are different facts, and the tooltip says which.
    """
    supported = driver is not None and all(driver.supports(command) for command in commands)
    control.setEnabled(supported)

    if supported:
        # Clear a previous explanation rather than leaving it: a control that says why it is
        # disabled while being enabled is worse than one that says nothing.
        if control.toolTip().endswith(_MARKER):
            control.setToolTip("")
        return True

    control.setToolTip(explain(driver, commands[0]) + _MARKER)
    return False


#: A zero-width marker on tooltips this module wrote, so it can take back its own and never
#: somebody else's. A page may have set a useful tooltip of its own, and clearing that on connect
#: would silently remove documentation nobody noticed was gone.
_MARKER = "​"
