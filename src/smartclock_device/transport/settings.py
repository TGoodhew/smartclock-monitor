"""The RS-232 line parameters for one receiver connection (§7.1).

Every parameter is settable because the SmartClock family is not consistent: the Z3805A ships
9600-8-N-1 while a Z3801A leaves the factory at 19200-7-O-1. **Nothing in the transport may assume
a default.**

Handshake is deliberately absent — §7.1 permits none only, so it is not a choice the user or the
caller gets to make.

The enums here are this project's own rather than pyserial's, so that the settings, the auto-detect
walk and every test over them stay importable with no serial port and no pyserial. The mapping to
pyserial's constants happens once, at the transport boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final


class Parity(Enum):
    """Parity, spelled as instrument documentation spells it."""

    NONE = "N"
    EVEN = "E"
    ODD = "O"
    MARK = "M"
    SPACE = "S"


class StopBits(Enum):
    """Stop bits."""

    ONE = "1"
    ONE_POINT_FIVE = "1.5"
    TWO = "2"


@dataclass(frozen=True, slots=True)
class SerialSettings:
    """One line configuration."""

    #: Baud rate. §7.1 permits 1200, 2400, 9600 and 19200; 4800 and 38400 were added for NMEA.
    baud_rate: int = 9600

    #: Data bits, 7 or 8.
    data_bits: int = 8

    #: Parity.
    parity: Parity = Parity.NONE

    #: Stop bits.
    stop_bits: StopBits = StopBits.ONE

    def __str__(self) -> str:
        """Rendered the way instrument documentation writes it, e.g. ``9600-8-N-1``."""
        return f"{self.baud_rate}-{self.data_bits}-{self.parity.value}-{self.stop_bits.value}"


#: The Z3805A factory configuration, 9600-8-N-1.
DEFAULT: Final = SerialSettings()

#: The baud rates offered by the connection dialog (§7.1).
#:
#: 4800 and 38400 are there for NMEA 0183, which specifies 4800 and its high-speed variant 38400:
#: a talker at the standard's own rate could not otherwise be connected to by hand.
SUPPORTED_BAUD_RATES: Final[tuple[int, ...]] = (1200, 2400, 4800, 9600, 19200, 38400)

#: The data-bit counts offered by the connection dialog (§7.1).
SUPPORTED_DATA_BITS: Final[tuple[int, ...]] = (7, 8)

#: The eight combinations auto-detect walks, most-likely-first, so a Z3805A answers on the first
#: attempt and a Z3801A on the second. Each attempt sends ``*IDN?`` with the probe timeout.
#:
#: **Second place is 19200-7-O-1 because the Z3801A guide says odd**, twice — "Baud Rate: 19200 /
#: Parity: Odd / Data Bits: 7/char / Stop Bits: 1", and again as "19200 — 7 data bits, 1 start bit,
#: 1 stop bit, odd parity". An even-parity spelling had propagated through the specification with
#: no source behind it, and sat odd *eighth*: a Z3801A was found on the last attempt of eight
#: rather than the second, around fourteen extra seconds at the probe timeout.
#:
#: **Even is kept, one place lower, rather than removed.** The specification called it "commonly"
#: that, which is a claim about units in the field rather than about the factory, and second-hand
#: receivers are exactly this project's audience (§4). Documented default first, folklore
#: immediately after — that ordering costs one probe if the folklore is right and saves six if it
#: is not.
AUTO_DETECT_SEQUENCE: Final[tuple[SerialSettings, ...]] = (
    SerialSettings(9600, 8, Parity.NONE, StopBits.ONE),
    SerialSettings(19200, 7, Parity.ODD, StopBits.ONE),
    SerialSettings(19200, 7, Parity.EVEN, StopBits.ONE),
    SerialSettings(9600, 7, Parity.EVEN, StopBits.ONE),
    SerialSettings(19200, 8, Parity.NONE, StopBits.ONE),
    SerialSettings(2400, 8, Parity.NONE, StopBits.ONE),
    SerialSettings(1200, 8, Parity.NONE, StopBits.ONE),
    SerialSettings(9600, 7, Parity.ODD, StopBits.ONE),
)
