"""A parsed ``*IDN?`` response, and which SmartClock-family receiver it names (§8.6, P2-4).

The model names are the fields these units put in ``*IDN?``. :attr:`ReceiverModel.UNKNOWN` is not a
failure state — the family is wider than this list, and an unrecognised model gets the conservative
profile rather than an error.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReceiverModel(Enum):
    """Which member of the family is on the other end of the port."""

    #: Not recognised, or not yet read. Treated conservatively.
    UNKNOWN = 0

    #: The Z3805A this application was written against.
    Z3805A = 1

    #: The Z3801A. Differs most visibly in its serial defaults.
    Z3801A = 2

    #: The Z3816A.
    Z3816A = 3

    #: The 58503A and 58503B, whose programming guide is this family's reference.
    HP58503 = 4

    #: The 59551A, which has hardware none of the others do.
    HP59551 = 5


def _model_for(model: str) -> ReceiverModel:
    """Map the model field onto the family.

    Prefix matching, case-insensitively, because the suffix carries a variant the profile does not
    care about — a ``58503B`` takes the same profile as a ``58503A``, and §11.1 already treats them
    as one class for the signal-strength scale.

    **Only the Z3805A spelling has been seen.** The others are the model numbers the manuals and
    §8.6 use; no ``*IDN?`` example is published for any of them, so these are the best available
    evidence rather than confirmed strings. An unrecognised model falls to
    :attr:`ReceiverModel.UNKNOWN` and its conservative profile, which is why guessing wrong here
    degrades rather than breaks.
    """
    upper = model.upper()

    if upper.startswith("Z3805"):
        return ReceiverModel.Z3805A
    if upper.startswith("Z3801"):
        return ReceiverModel.Z3801A
    if upper.startswith("Z3816"):
        return ReceiverModel.Z3816A
    if "58503" in upper:
        return ReceiverModel.HP58503
    if "59551" in upper:
        return ReceiverModel.HP59551
    return ReceiverModel.UNKNOWN


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    """The four comma-separated fields IEEE 488.2 defines for ``*IDN?``."""

    #: Field 1, e.g. ``SYMMETRICOM``.
    manufacturer: str

    #: Field 2 verbatim, e.g. ``Z3805A``.
    model: str

    #: Field 3, e.g. ``3625A02931``.
    serial_number: str

    #: Field 4, e.g. ``1.01.03-A``.
    firmware_revision: str

    #: Which model the second field names, or :attr:`ReceiverModel.UNKNOWN`.
    receiver: ReceiverModel

    @staticmethod
    def parse(response: str | None) -> DeviceIdentity | None:
        """Parse the four fields, or return ``None`` when it is not four fields.

        Confirmed against the live receiver, which answers
        ``SYMMETRICOM,Z3805A,3625A02931,1.01.03-A``. The four-field shape is the standard's rather
        than this unit's, which is why parsing it is safe for models nobody here has seen.

        **Never raises**, on §11.1's rule. A response in an unexpected shape yields ``None``, and
        the caller keeps the raw string — which is what the session service already displays, so
        nothing is lost by failing to parse.
        """
        if response is None or not response.strip():
            return None

        fields = response.strip().split(",")
        if len(fields) != 4:
            return None

        model = fields[1].strip()

        return DeviceIdentity(
            manufacturer=fields[0].strip(),
            model=model,
            serial_number=fields[2].strip(),
            firmware_revision=fields[3].strip(),
            receiver=_model_for(model),
        )
