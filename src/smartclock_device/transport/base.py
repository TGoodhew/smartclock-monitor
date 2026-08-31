"""A byte-level, full-duplex link to a receiver.

:class:`~smartclock_device.transport.serial_port.SerialTransport` is the real one;
:class:`~smartclock_device.transport.fake.FakeTransport` replays captured bytes through the
identical interface so the §7.2 transaction loop can be proved with no hardware attached
(§15 step 1).

The read side is a coroutine returning whatever has arrived, rather than a stream with
``readline()``. That is deliberate: §7.2's terminator is a prompt, not a newline, so a line-based
reader cannot express the protocol at all — see
:mod:`smartclock_device.transport.response_buffer`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Transport(Protocol):
    """The link. Owned by whoever opened it; the line protocol borrows and never closes it."""

    @property
    def description(self) -> str:
        """Identification for logs and the connection UI, e.g. ``COM3 @ 9600-8-N-1``."""
        ...

    @property
    def is_open(self) -> bool:
        """True between a successful :meth:`open` and :meth:`close`."""
        ...

    async def open(self) -> None:
        """Open the link.

        :raises TransportError: The port is missing, held by another process, or otherwise
            unopenable.
        """
        ...

    async def read(self) -> bytes:
        """Wait for and return the next bytes to arrive.

        Returns ``b""`` when the link has closed cleanly, which the line protocol reads as the
        device having gone. Never returns ``b""`` merely because nothing has arrived yet — a
        transaction's deadline is the caller's business, not the transport's.

        :raises TransportError: The transport is not open.
        """
        ...

    async def write(self, data: bytes) -> None:
        """Write bytes to the device and flush them.

        :raises TransportError: The write failed; the error's ``fault`` says how.
        """
        ...

    def discard_input(self) -> None:
        """Throw away anything the device has already sent but nobody has read.

        Called at the start of every transaction. Because the receiver only speaks when spoken to
        and serves one transaction at a time (§7.2), any bytes sitting in the buffer beforehand are
        the late tail of a transaction that timed out, and letting them run into the next response
        is how a single timeout turns into a permanently misaligned session.
        """
        ...

    async def close(self) -> None:
        """Close the link. Idempotent — closing a closed transport is not an error."""
        ...
