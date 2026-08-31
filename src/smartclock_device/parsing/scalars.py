"""Turns the single-value answers of the §7.3 fast tier into numbers (§6.2).

**Nothing here raises**, on the same principle as the status screen parser (§11.1): a value
that will not parse becomes ``None`` and renders as an em dash. A poll that raised would take
down the loop that produced it, and one odd reply per hour would then look like a dead
application.

Every response arrives with a **leading space** — the device answers ``_+3``, not ``+3``. That
is a framing artefact of the receiver rather than part of any value, and it is the single most
likely thing to break a naive ``int()``, so trimming happens here once instead of at every call
site. Values also carry an explicit sign (``+3``), and reals arrive in scientific notation with
a three-digit exponent (``-5.4E-009``).

Why a grammar rather than ``try: int(text)``
--------------------------------------------

The C# original leans on ``int.TryParse`` with ``NumberStyles.Integer`` and
``CultureInfo.InvariantCulture``, which is both non-throwing *and* narrow. Python's builtins are
non-throwing only if wrapped, and they are considerably wider than the receiver's output:

* ``int("1_0")`` is 10 and ``float("1_0.5")`` is 10.5 — PEP 515 digit separators.
* ``int("٣")`` is 3 — ``str.isdigit`` and the builtins accept every Unicode decimal digit, and
  so does ``\\d`` in :mod:`re` unless it is told otherwise. Hence ``[0-9]`` below, spelled out.
* ``float("nan")``, ``float("inf")`` and ``float("infinity")`` all succeed.

None of those are things the receiver emits, so accepting them can only turn a corrupted read
into a plausible-looking number. That is the worst failure mode available to a timing
instrument, and it is worse than ``None``: ``None`` renders as ``—`` and tells the user the
truth. So the shape is matched first and converted second.

Two deliberate divergences from the C# original, both in the direction of rejecting more:

* **Non-finite results are ``None``.** .NET Core 3.0 changed ``double.TryParse`` to accept
  ``NaN`` and ``Infinity``, and to return ``true`` with an infinity on overflow (``1E+400``).
  A NaN reaching §9.10.2's medallion ring propagates silently through every subsequent
  calculation, so it stops here.
* **Integers outside the signed 32-bit range are ``None``**, which is what C#'s ``int`` gives
  for free and Python's unbounded ``int`` does not. Parity, cheaply.

Neither can change how any captured fixture parses: no fixture, and no observed reply, contains
a value of either kind.
"""

from __future__ import annotations

import math
import re
from typing import Final

#: A signed integer answer, and nothing else. ``[0-9]`` rather than ``\d`` on purpose — see the
#: module docstring. Equivalent to C#'s ``NumberStyles.Integer`` once the text has been trimmed.
_INTEGER: Final = re.compile(r"^[+-]?[0-9]+$")

#: A signed real in the receiver's scientific notation, and nothing else. Equivalent to C#'s
#: ``NumberStyles.Float``: sign, decimal point and exponent, but no thousands separators.
_DECIMAL: Final = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?$")

#: The bounds of the C# ``int`` the original parses into. See the module docstring.
_INT32_MIN: Final = -(2**31)
_INT32_MAX: Final = 2**31 - 1

#: How many significant digits an in-range value can have. ``2147483647`` has ten, so anything
#: longer is out of range and can be rejected without being converted — see :func:`parse_integer`.
_INT32_DIGITS: Final = 10


def _clean(response: str | None) -> str | None:
    """Trim the leading space and anything else stray, or return ``None`` for an empty answer."""
    if response is None:
        return None
    text = response.strip()
    return text or None


def parse_integer(response: str | None) -> int | None:
    """Parse a signed integer answer such as ``+3``.

    The digits are counted before they are converted, because ``int()`` **raises** on a long
    enough string: CPython caps integer-from-string conversion at 4300 digits (CVE-2020-10735,
    the quadratic-parsing denial of service), and a corrupted read is exactly how a five-thousand
    character run of digits arrives. The grammar above matches it happily, so without this the one
    function whose contract is that it never raises would raise (§11.1).

    Counting significant digits rather than the string's length keeps ``00000000000000001``
    parsing as ``1``, which is what C#'s ``int.TryParse`` does with it.
    """
    text = _clean(response)
    if text is None or not _INTEGER.match(text):
        return None

    digits = text.lstrip("+-").lstrip("0")
    if len(digits) > _INT32_DIGITS:
        return None

    value = -int(digits or "0") if text.startswith("-") else int(digits or "0")
    return value if _INT32_MIN <= value <= _INT32_MAX else None


def parse_decimal(response: str | None) -> float | None:
    """Parse a real answer such as ``-5.4E-009``."""
    text = _clean(response)
    if text is None or not _DECIMAL.match(text):
        return None
    value = float(text)
    # The grammar admits no literal spelling of a non-finite value, so this catches overflow
    # alone — "1E+400", which float() returns as inf rather than refusing.
    return value if math.isfinite(value) else None


def parse_seconds_as_nanoseconds(response: str | None) -> float | None:
    """Parse a real answer expressed in seconds and return it in nanoseconds.

    The time interval is the case this exists for: the receiver answers ``:SYNC:TINT?`` in
    seconds (``-5.4E-009``) while every display of it, and §9.10.2's medallion ring, works in
    nanoseconds. Converting once here keeps the factor of a billion out of the view models.
    """
    seconds = parse_decimal(response)
    if seconds is None:
        return None
    nanoseconds = seconds * 1e9
    return nanoseconds if math.isfinite(nanoseconds) else None


def parse_keyword(response: str | None) -> str | None:
    """Parse an enumerated keyword answer such as ``LOCK``, upper-cased."""
    text = _clean(response)
    return None if text is None else text.upper()


def parse_first_of_list(response: str | None) -> float | None:
    """Parse the first field of a comma-separated answer.

    ``:SYNC:HOLD:DUR?`` answers ``+6.00000E+002,0`` — a value and a flag. Only the first field
    is the duration.
    """
    text = _clean(response)
    if text is None:
        return None
    head, _, _ = text.partition(",")
    return parse_decimal(head)


def parse_boolean(response: str | None) -> bool | None:
    """Parse a boolean answer, which the receiver spells ``0`` or ``1``."""
    value = parse_integer(response)
    return None if value is None else value != 0
