"""Why a transport operation failed, in the terms the UI and the reconnect policy care about.

§6.4 requires every read and write to survive the whole family of errors reachable when a
USB-serial adapter is pulled while the port is open. This module is what those collapse into once
caught, so no caller has to re-derive the meaning from an exception type.

Public rather than private, because §6.4's rule applies to anything that owns a transport, not
only to the transport itself: the session service needs the same predicate to decide when to start
reconnecting, and a second hand-written copy of the list is precisely the drift this exists to
prevent.
"""

from __future__ import annotations

import errno
from enum import Enum
from typing import Final


class TransportFault(Enum):
    """What went wrong with the link."""

    #: No fault.
    NONE = 0

    #: The named port does not exist — the adapter unplugged, or its driver not loaded.
    PORT_NOT_FOUND = 1

    #: The port exists but is held by another process — usually a terminal emulator (§9.11).
    #:
    #: On Linux this is also the ordinary state of a user who is not in ``dialout``, which is the
    #: first thing that will go wrong for a new user and is why the message says so.
    ACCESS_DENIED = 2

    #: The port went away underneath an open handle. P0-14's unplug case.
    DEVICE_REMOVED = 3

    #: An I/O error that is not obviously a removal. Treated as recoverable by §7.2's policy.
    IO = 4

    #: The transport was used before it opened, or after it closed.
    NOT_OPEN = 5

    #: Something the classifier does not recognise.
    UNKNOWN = 6


class TransportError(Exception):
    """A link failure, classified.

    Raised by open, by write, and by reading a transport that is not open. The read path otherwise
    reports faults through :attr:`Transaction.outcome`, because a transaction that dies mid-read
    still has a result to report.
    """

    def __init__(self, fault: TransportFault, message: str) -> None:
        super().__init__(message)
        #: What went wrong, in the terms the reconnect policy and the connection dialog use.
        self.fault = fault


def is_transport_fault(exception: BaseException) -> bool:
    """Whether this is an exception the read and write paths are required to survive.

    The Python counterpart of §6.4's four-exception list. ``serial.SerialException`` subclasses
    ``OSError``, as do ``FileNotFoundError`` and ``PermissionError``, so the set is narrower here
    than in C# — but ``ValueError`` is included because pyserial raises it for a port used after
    close, which is the same surprise-removal case C# sees as ``ObjectDisposedException``.
    """
    return isinstance(exception, TransportError | OSError | ValueError)


#: What each errno means for a serial port.
#:
#: **Consulted before the message text**, and that ordering is the whole point. pyserial wraps a
#: permission failure in a ``SerialException`` whose message reads *"could not open port
#: /dev/ttyUSB0: [Errno 13] Permission denied"* — so a classifier that matched "could not open
#: port" first called it a missing port and told the user their adapter might be unplugged. That
#: is worse than saying nothing: it sends someone to check a cable when the fix is
#: ``usermod -aG dialout``. Found against a real receiver, which is the only place it shows.
_BY_ERRNO: Final[dict[int, TransportFault]] = {
    errno.EACCES: TransportFault.ACCESS_DENIED,
    errno.EPERM: TransportFault.ACCESS_DENIED,
    errno.ENOENT: TransportFault.PORT_NOT_FOUND,
    errno.ENODEV: TransportFault.DEVICE_REMOVED,
    errno.ENXIO: TransportFault.DEVICE_REMOVED,
    errno.EIO: TransportFault.IO,
}


def classify(exception: BaseException) -> TransportFault:
    """Map an exception raised by the port onto a fault.

    **The errno is the evidence; the message is the fallback.** pyserial reports almost everything
    as a ``SerialException`` — an ``OSError`` subclass — so the exception *type* separates very
    little, and its message is prose that has changed between releases. The errno is neither.
    """
    if isinstance(exception, TransportError):
        return exception.fault

    # These two are still worth naming: a bare OSError subclass carries the meaning in its type,
    # and it costs nothing to trust that where it is present.
    if isinstance(exception, PermissionError):
        return TransportFault.ACCESS_DENIED
    if isinstance(exception, FileNotFoundError):
        return TransportFault.PORT_NOT_FOUND

    if isinstance(exception, OSError):
        code = exception.errno
        if code is not None and code in _BY_ERRNO:
            return _BY_ERRNO[code]

        # No errno. Fall back to the message, permission first — see the note on _BY_ERRNO.
        text = str(exception).lower()
        if "permission" in text or "access is denied" in text:
            return TransportFault.ACCESS_DENIED
        if "disconnect" in text or "removed" in text:
            return TransportFault.DEVICE_REMOVED
        if "no such file" in text or "could not open port" in text or "does not exist" in text:
            return TransportFault.PORT_NOT_FOUND
        return TransportFault.IO

    # pyserial raises ValueError when a port is used after being closed. The handle outlives the
    # hardware behind it, which is the surprise-removal shape rather than a programming error.
    if isinstance(exception, ValueError):
        return TransportFault.DEVICE_REMOVED

    return TransportFault.UNKNOWN


def describe(fault: TransportFault, port: str) -> str:
    """One sentence a user can act on, per §9.11's copy rules.

    The access-denied case names ``dialout`` because on Linux that is what it almost always is, and
    "permission denied" on its own sends a user to look for the wrong problem.
    """
    match fault:
        case TransportFault.PORT_NOT_FOUND:
            return f"{port} does not exist. The adapter may be unplugged."
        case TransportFault.ACCESS_DENIED:
            return (
                f"{port} is not accessible. Another program may have it open, or your user may "
                f"not be in the 'dialout' group."
            )
        case TransportFault.DEVICE_REMOVED:
            return f"{port} was disconnected."
        case TransportFault.IO:
            return f"{port} reported an I/O error."
        case TransportFault.NOT_OPEN:
            return f"{port} is not open."
        case _:
            return f"{port} failed for an unrecognised reason."
