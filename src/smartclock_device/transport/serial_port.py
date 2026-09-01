"""The real link: a serial port, read on a thread and delivered to asyncio.

``pyserial`` is a blocking library. Rather than take ``pyserial-asyncio`` — which is unmaintained
and wraps the same blocking reads anyway — the port is read on a worker thread through
:func:`asyncio.to_thread`, which is exactly what a blocking file descriptor wants and keeps the
event loop free. §6.3's rule is about the *device layer*'s reads not blocking the UI, and this
satisfies it without a second dependency.

**pyserial is imported here and nowhere else in the device layer.** Every other module in
``transport/`` is importable with no serial port present, which is what lets the protocol tests run
on a machine with no hardware — and on CI.

The enumeration side replaces the C# original's whole registry crawl with
``serial.tools.list_ports.comports()``, which reports description and hardware id on Linux, Windows
and macOS alike. A clear simplification, and the one place this port is smaller than its sibling.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import serial
from serial.tools import list_ports

from smartclock_device.transport.faults import TransportError, TransportFault, classify
from smartclock_device.transport.settings import DEFAULT, Parity, SerialSettings, StopBits

#: How long a blocking read waits before returning empty-handed.
#:
#: Not a transaction timeout — that is the line protocol's business. This only bounds how long the
#: worker thread sits inside pyserial, so that closing the port cannot be blocked behind a read
#: that will never return.
_READ_POLL_SECONDS = 0.2

#: The largest read handed back at once. The status screen is around 1,900 bytes.
_READ_SIZE = 4096

_PARITY_TO_SERIAL = {
    Parity.NONE: serial.PARITY_NONE,
    Parity.EVEN: serial.PARITY_EVEN,
    Parity.ODD: serial.PARITY_ODD,
    Parity.MARK: serial.PARITY_MARK,
    Parity.SPACE: serial.PARITY_SPACE,
}

_STOP_BITS_TO_SERIAL = {
    StopBits.ONE: serial.STOPBITS_ONE,
    StopBits.ONE_POINT_FIVE: serial.STOPBITS_ONE_POINT_FIVE,
    StopBits.TWO: serial.STOPBITS_TWO,
}


@dataclass(frozen=True, slots=True)
class PortInfo:
    """One serial port the machine can see."""

    #: The device path or name — ``/dev/ttyUSB0``, ``COM3``.
    device: str

    #: What the driver calls it, which is usually the adapter's chipset.
    description: str

    #: The USB or PCI identification, for telling two identical adapters apart.
    hardware_id: str

    @property
    def label(self) -> str:
        """Device and description together, for the connection dialog."""
        return f"{self.device} — {self.description}" if self.description else self.device


def available_ports() -> tuple[PortInfo, ...]:
    """Every serial port the machine can see, sorted by device name.

    Sorted because ``comports()`` does not promise an order and a list that reshuffles between
    openings of the connection dialog is unusable.

    On Linux this reports ``/dev/ttyS*`` motherboard ports as well as USB adapters. A WSL user will
    see only the former unless a USB adapter has been attached with ``usbipd``, which is worth
    saying in the dialog rather than leaving as a mystery.
    """
    return tuple(
        sorted(
            (
                PortInfo(
                    device=port.device,
                    description=port.description or "",
                    hardware_id=port.hwid or "",
                )
                for port in list_ports.comports()
            ),
            key=lambda port: port.device,
        )
    )


class SerialTransport:
    """A real serial port, satisfying :class:`~smartclock_device.transport.base.Transport`."""

    def __init__(self, port: str, settings: SerialSettings = DEFAULT) -> None:
        self._port = port
        self._settings = settings
        self._serial: serial.Serial | None = None

    @property
    def description(self) -> str:
        return f"{self._port} @ {self._settings}"

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    async def open(self) -> None:
        if self.is_open:
            return

        try:
            self._serial = await asyncio.to_thread(
                serial.Serial,
                port=self._port,
                baudrate=self._settings.baud_rate,
                bytesize=self._settings.data_bits,
                parity=_PARITY_TO_SERIAL[self._settings.parity],
                stopbits=_STOP_BITS_TO_SERIAL[self._settings.stop_bits],
                # §7.1 permits no handshake, so it is not a choice anyone gets to make.
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
                timeout=_READ_POLL_SECONDS,
                write_timeout=_READ_POLL_SECONDS * 10,
            )
        except Exception as exception:
            fault = classify(exception)
            raise TransportError(fault, f"Could not open {self._port}: {exception}") from exception

    async def read(self) -> bytes:
        """Wait for bytes.

        Loops over short blocking reads rather than one long one, so that a transaction's deadline
        and a close can both take effect promptly. An empty read is *not* end-of-stream on a serial
        port — it only means nothing arrived in the poll window — so the loop keeps going, and the
        caller's timeout is what ends the wait.
        """
        while True:
            port = self._require_open()
            try:
                data = await asyncio.to_thread(port.read, _READ_SIZE)
            except Exception as exception:
                raise TransportError(
                    self._fault_for(exception), f"Reading {self._port} failed: {exception}"
                ) from exception

            if data:
                return bytes(data)

            # Nothing this window. Yield, then check the port is still there before waiting again.
            await asyncio.sleep(0)

    async def write(self, data: bytes) -> None:
        port = self._require_open()
        try:
            await asyncio.to_thread(port.write, data)
            await asyncio.to_thread(port.flush)
        except Exception as exception:
            raise TransportError(
                self._fault_for(exception), f"Writing to {self._port} failed: {exception}"
            ) from exception

    def discard_input(self) -> None:
        """Drop whatever the driver has buffered.

        Deliberately synchronous and forgiving: it runs at the start of every transaction, and a
        port that has just gone away must not raise from here — the write that follows reports the
        failure through the transaction, which is the shape every caller handles.
        """
        port = self._serial
        if port is None or not port.is_open:
            return
        try:
            port.reset_input_buffer()
        except Exception:
            # See the docstring: the write that follows reports the failure through the
            # transaction, which is the shape every caller already handles.
            return

    async def close(self) -> None:
        port = self._serial
        self._serial = None
        if port is None or not port.is_open:
            return
        try:
            await asyncio.to_thread(port.close)
        except Exception:
            # Closing a port that has already gone is not a failure worth reporting.
            return

    def _fault_for(self, exception: BaseException) -> TransportFault:
        """Classify a failure that happened *during* an operation.

        **A port that is no longer open when the failure surfaced is a removal, whatever the
        exception says.** Closing a port while a read is blocked in a worker thread sets the
        descriptor to ``None`` underneath it, and pyserial then fails with ``TypeError: 'NoneType'
        object cannot be interpreted as an integer`` — which classifies as UNKNOWN and reaches the
        user as *"failed for an unrecognised reason"*.

        That is §6.4's own case, and the message is the one §9.11 exists to prevent: it tells
        someone whose adapter has just been pulled nothing they can act on. The state of the port
        is better evidence than the exception here, because we can see the port went away.

        Found by closing the transport under a live poll against a Z3805A.
        """
        if self._serial is None or not self._serial.is_open:
            return TransportFault.DEVICE_REMOVED
        return classify(exception)

    def _require_open(self) -> serial.Serial:
        port = self._serial
        if port is None or not port.is_open:
            raise TransportError(TransportFault.NOT_OPEN, f"{self._port} is not open.")
        return port
