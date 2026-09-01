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
from smartclock_device.transport.settings import SerialSettings


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

    def overhear(self, lines: Sequence[str]) -> Selection | None:
        """The first driver that claims this stream from what arrived unprompted, or ``None``.

        **This runs before the probe, and a claim here means the probe is never sent.** A talker
        has no command parser: ``*IDN?`` would cost a full timeout and would be a *write* to a
        receiver whose driver says it is never written to. §12 puts recognition-by-listening ahead
        of recognition-by-identity for exactly that reason.

        ``None`` is the ordinary answer — a query/response receiver's banner is not a stream, and
        nothing claiming it means the probe proceeds as it always did.
        """
        for driver in self._drivers:
            if driver.overhear(lines):
                return Selection(driver=driver, recognised=True)
        return None

    @property
    def auto_detect_sequence(self) -> tuple[SerialSettings, ...]:
        """§10.12: the union of every registered driver's sequence, in registration order.

        **De-duplicated, and first occurrence wins.** Registration order is priority order, so a
        combination two families both name is tried at the earlier one's position — which keeps the
        Z3805A answering on the first attempt after a talker's rates were added to the walk.

        The union is what makes a second family *reachable*: a talker runs at 4800 and the walk had
        only ever known one receiver's rates, so the driver was registered and could not be found.
        """
        found: list[SerialSettings] = []
        for driver in self._drivers:
            for candidate in driver.auto_detect_sequence:
                if candidate not in found:
                    found.append(candidate)
        return tuple(found)

    @property
    def is_ambiguous(self) -> bool:
        """Whether a failed match is worth warning about.

        One registered driver means the fallback *is* the answer. More than one means the
        application quietly served a receiver with a family nothing claimed, which somebody should
        be able to find in the log afterwards.
        """
        return len(self._drivers) > 1
