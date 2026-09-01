"""§12's composition root: which driver serves the receiver that answered.

**The probe phase belongs to no driver.** The session opens the port, absorbs the banner and asks
``*IDN?`` neutrally, and only then is a driver chosen — because choosing one first would mean
asking a family's questions of a receiver that may be a different family.

**Re-selected on every connect**, not once at startup. The receiver on the port can have been
swapped while the link was down, and a session that kept the driver it chose an hour ago would be
parsing one family's answers with another's rules.

**Registration order is priority order, and the first claim wins.** A family that recognises
nothing never displaces one that does, and the fallback is the first registered — which in a
single-driver build is the driver that would have served it regardless, which is why that case is
silent rather than warned about.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from smartclock_device.drivers.base import ReceiverDriver
from smartclock_device.models.device_identity import DeviceIdentity


@dataclass(frozen=True, slots=True)
class Selection:
    """Which driver was chosen, and whether anything actually claimed the receiver."""

    driver: ReceiverDriver

    #: ``False`` where nothing recognised the identity and the first registered driver was used.
    #: The caller warns on this **only when more than one driver is registered**: with one, the
    #: fallback is the driver that would have served it anyway and a warning would be noise.
    recognised: bool


class Registry:
    """The registered families, in priority order."""

    def __init__(self, drivers: Sequence[ReceiverDriver]) -> None:
        if not drivers:
            raise ValueError(
                "A registry needs at least one driver; there is nothing to fall back to."
            )
        self._drivers = tuple(drivers)

    @property
    def drivers(self) -> tuple[ReceiverDriver, ...]:
        return self._drivers

    def select(self, identity: DeviceIdentity | None) -> Selection:
        """The first driver that claims this identity, or the first registered.

        ``None`` — nothing answered ``*IDN?`` — is not a reason to fail: a receiver that says
        nothing is the ordinary state of half §7.1's serial combinations during auto-detect, and
        the walk needs a driver to keep asking with.
        """
        for driver in self._drivers:
            if driver.recognises(identity):
                return Selection(driver=driver, recognised=True)

        return Selection(driver=self._drivers[0], recognised=False)

    @property
    def is_ambiguous(self) -> bool:
        """Whether a failed match is worth warning about.

        One registered driver means the fallback *is* the answer. More than one means the
        application quietly served a receiver with a family nothing claimed, which somebody should
        be able to find in the log afterwards.
        """
        return len(self._drivers) > 1
