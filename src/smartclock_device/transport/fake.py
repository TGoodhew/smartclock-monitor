"""A transport that replays scripted bytes, so the §7.2 loop is provable with no hardware.

Most transport tests run against this rather than against a port, and it is what the demo mode
drives the whole application from — a captured status screen replayed through the identical
interface a real receiver is read through.

**The queue is built in the constructor, not on first use from either side.** The C# original
records a lazy-initialisation defect here: whichever of the reader and the writer arrived first
built the pipe, so a test that read before writing got a different object from one that wrote
before reading, and the failure looked like a race in the protocol rather than a bug in the fake.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from typing import Final

from smartclock_device.transport.faults import TransportError, TransportFault

#: The prompt a healthy receiver ends every transaction with. Note the space before the bracket —
#: see :func:`~smartclock_device.transport.response_buffer.match_prompt`.
ORDINARY_PROMPT: Final = "scpi > "


#: What the receiver sends instead while its error queue is not empty.
def error_prompt(code: int) -> str:
    """The prompt for a non-empty error queue, e.g. ``E-113> ``. No space before the bracket."""
    return f"E-{code}> "


class FakeTransport:
    """A scripted receiver.

    :param responses: Command to response body. The body is sent as-is with CRLF line endings, and
        the prompt is appended. A command with no entry gets :paramref:`default_response`.
    :param banner: Bytes delivered the moment the transport opens, before anything is asked — a
        Z3805A announces its identity when DTR is asserted, and absorbing that is what the
        synchronise step exists for.
    :param chunk_size: Deliver everything in pieces of at most this many bytes. ``None`` delivers
        each response whole. Set it to 1 to reproduce 9600 baud's arrival pattern, where the
        prompt lands across a read boundary.
    :param echo: Echo each command back before answering, as a receiver under ``FDUPlex ON`` does.
    :param prompt: The prompt to terminate responses with.
    """

    def __init__(
        self,
        responses: Mapping[str, str] | None = None,
        *,
        banner: str = "",
        chunk_size: int | None = None,
        echo: bool = False,
        prompt: str = ORDINARY_PROMPT,
        default_response: str | None = None,
        description: str = "fake receiver",
    ) -> None:
        if chunk_size is not None and chunk_size < 1:
            raise ValueError("chunk_size must be at least 1 byte, or None to deliver whole.")

        self._responses = dict(responses or {})
        self._banner = banner
        self._chunk_size = chunk_size
        self._echo = echo
        self._prompt = prompt
        self._default_response = default_response
        self._description = description

        # Built here, once, for both sides. See the module docstring.
        self._inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self._is_open = False
        self._closed = False

        #: Every command written, in order. The assertion surface for tests about what was sent.
        self.written: list[str] = []

    # -- Transport ---------------------------------------------------------------------------

    @property
    def description(self) -> str:
        return self._description

    @property
    def is_open(self) -> bool:
        return self._is_open

    async def open(self) -> None:
        if self._closed:
            raise TransportError(TransportFault.NOT_OPEN, "This fake transport has been closed.")
        self._is_open = True
        if self._banner:
            self._enqueue(self._banner + self._prompt)

    async def read(self) -> bytes:
        if not self._is_open:
            raise TransportError(TransportFault.NOT_OPEN, "The fake transport is not open.")
        return await self._inbound.get()

    async def write(self, data: bytes) -> None:
        if not self._is_open:
            raise TransportError(TransportFault.NOT_OPEN, "The fake transport is not open.")

        command = data.decode("latin-1").strip()
        self.written.append(command)
        self._answer(command)

    def discard_input(self) -> None:
        while True:
            try:
                self._inbound.get_nowait()
            except asyncio.QueueEmpty:
                return

    async def close(self) -> None:
        self._is_open = False
        self._closed = True
        # A zero-length read is how the line protocol learns the device has gone.
        self._inbound.put_nowait(b"")

    # -- Scripting ---------------------------------------------------------------------------

    def _answer(self, command: str) -> None:
        """Queue the scripted answer for one command, or nothing if it is unscripted.

        An unscripted command with no default queues **nothing at all**, which is the honest
        simulation of a receiver that has been asked something it does not understand and has not
        answered yet. The caller's timeout is what ends that, exactly as on the wire.
        """
        body = self._responses.get(command, self._default_response)
        if body is None:
            return

        parts: list[str] = []
        if self._echo:
            parts.append(command + "\r\n")
        if body:
            parts.append(body if body.endswith(("\r\n", "\n")) else body + "\r\n")
        parts.append(self._prompt)

        self._enqueue("".join(parts))

    def _enqueue(self, text: str) -> None:
        data = text.encode("latin-1")
        for chunk in _split(data, self._chunk_size):
            self._inbound.put_nowait(chunk)

    def feed(self, text: str) -> None:
        """Push bytes at the reader without any command having been written.

        For the unsolicited cases: the power-up banner, and a broadcast talker that speaks without
        being spoken to.
        """
        self._enqueue(text)

    def simulate_removal(self) -> None:
        """The port goes away underneath an open handle — P0-14's unplug.

        Deliberately **not** the same as :meth:`close`. A close is orderly and the caller knows it
        happened; a removal leaves the transport believing it is open, and the first sign of it is
        a read that returns nothing. That difference is the whole point: one is
        :attr:`~TransportFault.NOT_OPEN` and the other is
        :attr:`~TransportFault.DEVICE_REMOVED`, and a fake that could only do the first would
        leave the case the specification actually names untested.
        """
        self._inbound.put_nowait(b"")


def _split(data: bytes, size: int | None) -> Iterable[bytes]:
    if size is None or len(data) <= size:
        return (data,)
    return tuple(data[at : at + size] for at in range(0, len(data), size))
