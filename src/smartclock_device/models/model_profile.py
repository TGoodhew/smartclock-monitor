"""What a given receiver model has, so divergence is a table rather than a scatter of conditionals.

§8.6, P2-4, #64.

§8.6 lists ``:PULSe:*``, ``:SENSe:TSTamp<n>:*``, ``:SENSe:DATA:*``, ``:FORMat:DATA``,
``:PTIM:PPS:EDGE`` and ``:SYST:COMM:SER2:*`` as **59551A-only hardware features**, and the 58503A
guide confirms PORT 2 as "(59551A Only)". Every row in the table below follows from that one list.

**Only the SER2 cell of the Z3805A row is measured.** ``:SYST:COMM:SER2:BAUD?`` answers
``-113,"Undefined header"`` on the live unit and it has one serial connector (#62), which is why
that cell rests on evidence rather than on the specification's own table. The row's other three
cells follow from §16.1 — its bench probes (the PPS edge answers the same error; the pulse
subsystem is only half accepted) and its connector inspection (one BNC output, no Time Tag inputs)
— rather than from the table alone.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from smartclock_device.models.device_identity import DeviceIdentity, ReceiverModel


def _starts_with_node(header: str, path: str) -> bool:
    """Whether a header begins with a node path, allowing either side to be the abbreviation.

    The same rule the §16.1 inventory (#154, now closed) used, and for the same reason: a mechanical
    short form is wrong in both directions because the manuals' own capitalisation is inconsistent.
    """
    wanted = [node for node in path.split(":") if node]
    actual = [node for node in header.replace(" ", ":").split(":") if node]

    if len(actual) < len(wanted):
        return False

    for want, have in zip(wanted, actual, strict=False):
        want_upper = want.upper()
        have_upper = have.upper()
        if not (have_upper.startswith(want_upper) or want_upper.startswith(have_upper)):
            return False

    return True


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Which optional hardware a model has."""

    #: Which model this describes.
    model: ReceiverModel

    #: Whether a ``PORT 2`` exists, which is what ``:SYST:COMM:SER2:*`` addresses.
    has_second_serial_port: bool

    #: Whether ``:PULSe:*`` exists.
    has_programmable_pulse_output: bool

    #: Whether ``:SENSe:DATA:*`` and ``:SENSe:TSTamp*`` exist.
    has_timestamp_memory: bool

    #: Whether ``:PTIMe:PPS:EDGE`` exists.
    has_pps_edge_control: bool

    def supports(self, mnemonic: str | None) -> bool:
        """Whether this model can be sent a command, by its SCPI header.

        §8.6 says these are "hidden entirely" on a model that lacks them. Today that holds
        **vacuously** — none of them is in the command catalog, so there is nothing to hide, and
        §16.1 records why each stays out (#154's inventory, closed 29 Aug 2026). This exists so
        that adding one later cannot quietly offer it on hardware without the feature.

        Node-prefix matching, because SCPI abbreviations are legal and the catalog spells some
        headers short: ``:PTIM:PPS:EDGE`` and ``:PTIMe:PPS:EDGE`` are the same command.
        """
        if mnemonic is None or not mnemonic.strip():
            return False

        header = mnemonic.strip()

        if _starts_with_node(header, ":PULS") and not self.has_programmable_pulse_output:
            return False
        if _starts_with_node(header, ":SYST:COMM:SER2") and not self.has_second_serial_port:
            return False
        if _starts_with_node(header, ":PTIM:PPS:EDG") and not self.has_pps_edge_control:
            return False

        return self.has_timestamp_memory or not (
            _starts_with_node(header, ":SENS:DATA")
            or _starts_with_node(header, ":SENS:TST")
            or _starts_with_node(header, ":FORM:DATA")
        )


#: The profile applied when the model is not recognised.
#:
#: **Everything optional is off.** An unknown receiver gets the smallest surface, so the failure
#: mode of not recognising a model is a feature that is missing rather than a command sent to
#: hardware that may not have it. §8.5's rule is the same one: absent unless shown to be present.
CONSERVATIVE: Final = ModelProfile(
    model=ReceiverModel.UNKNOWN,
    has_second_serial_port=False,
    has_programmable_pulse_output=False,
    has_timestamp_memory=False,
    has_pps_edge_control=False,
)

#: The profile for each model, from §8.6 and the manuals.
_PROFILES: Final[MappingProxyType[ReceiverModel, ModelProfile]] = MappingProxyType(
    {
        ReceiverModel.Z3805A: ModelProfile(ReceiverModel.Z3805A, False, False, False, False),
        ReceiverModel.Z3801A: ModelProfile(ReceiverModel.Z3801A, False, False, False, False),
        ReceiverModel.Z3816A: ModelProfile(ReceiverModel.Z3816A, False, False, False, False),
        ReceiverModel.HP58503: ModelProfile(ReceiverModel.HP58503, False, False, False, False),
        ReceiverModel.HP59551: ModelProfile(ReceiverModel.HP59551, True, True, True, True),
    }
)


def for_model(model: ReceiverModel) -> ModelProfile:
    """The profile for a model, or :data:`CONSERVATIVE` when it is unrecognised."""
    return _PROFILES.get(model, CONSERVATIVE)


def for_identity(identity: DeviceIdentity | None) -> ModelProfile:
    """The profile for a parsed identity, or :data:`CONSERVATIVE` when there is none."""
    return CONSERVATIVE if identity is None else for_model(identity.receiver)
