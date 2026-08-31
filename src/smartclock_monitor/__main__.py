"""The application entry point.

Runs one asyncio loop on Qt's, through ``qasync``. §6.3 is explicit about why: the device layer is
async top to bottom and must stay that way, the serial read happens in asyncio, and the UI is
notified by a queued signal. **Do not** run the serial read in a thread and marshal by hand, and do
not poll from a ``QTimer`` — the equivalent shortcuts were banned in the C# tree for reasons that
are not language-specific.

Two ways to start it:

``smartclock-monitor --demo``
    Replays the ten captured status screens through the real line protocol, session and poll loop.
    No hardware, no serial port. This is the reviewable one.

``smartclock-monitor --port /dev/ttyUSB0``
    A real receiver. ``--baud``, ``--data-bits``, ``--parity`` and ``--stop-bits`` follow §7.1's
    permitted values, because the family is not consistent about them.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable, Sequence
from contextlib import suppress
from pathlib import Path

from smartclock_device.clock import SystemClock
from smartclock_device.drivers.smartclock import SmartClockDriver
from smartclock_device.transport.base import Transport
from smartclock_device.transport.faults import TransportError
from smartclock_device.transport.settings import (
    SUPPORTED_BAUD_RATES,
    SUPPORTED_DATA_BITS,
    Parity,
    SerialSettings,
    StopBits,
)
from smartclock_monitor.platform.paths import trend_database
from smartclock_monitor.services.polling import PollingService, Reading
from smartclock_monitor.services.replay import ReplayTransport
from smartclock_monitor.services.session import DeviceSession
from smartclock_monitor.services.trend_store import TrendStore, TrendStoreError
from smartclock_monitor.themes.tokens import Theme


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartclock-monitor",
        description="Monitor an HP/Symmetricom SmartClock GPS-disciplined oscillator.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--demo",
        action="store_true",
        help="replay the captured status screens instead of opening a serial port",
    )
    source.add_argument("--port", help="serial port, e.g. /dev/ttyUSB0 or COM3")

    parser.add_argument(
        "--baud", type=int, default=9600, choices=SUPPORTED_BAUD_RATES, help="§7.1's rates"
    )
    parser.add_argument("--data-bits", type=int, default=8, choices=SUPPORTED_DATA_BITS)
    parser.add_argument(
        "--parity", default="N", choices=[member.value for member in Parity], help="N, E, O, M or S"
    )
    parser.add_argument("--stop-bits", default="1", choices=[m.value for m in StopBits])
    parser.add_argument(
        "--theme",
        default=Theme.DARK.value,
        choices=[theme.value for theme in Theme],
        help="which token set to start in",
    )
    parser.add_argument(
        "--trend-store",
        default=None,
        help=(
            "where to keep the trend history "
            f"(default: {trend_database()}). Pass --no-trend-store to keep none."
        ),
    )
    parser.add_argument(
        "--no-trend-store",
        action="store_true",
        help="do not persist readings; the trend charts show only this session",
    )
    parser.add_argument(
        "--list-ports", action="store_true", help="print the serial ports this machine can see"
    )
    return parser


def settings_from(arguments: argparse.Namespace) -> SerialSettings:
    return SerialSettings(
        baud_rate=arguments.baud,
        data_bits=arguments.data_bits,
        parity=Parity(arguments.parity),
        stop_bits=StopBits(arguments.stop_bits),
    )


def list_ports() -> int:
    """Print what the machine can see, and say the useful thing when it sees nothing."""
    from smartclock_device.transport.serial_port import available_ports

    ports = available_ports()
    if not ports:
        print("No serial ports found.")
        print(
            "On WSL, a USB adapter needs 'usbipd attach' from an elevated Windows prompt; only\n"
            "motherboard COM ports appear as /dev/ttyS* without it."
        )
        return 1

    for port in ports:
        print(port.label)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)

    if arguments.list_ports:
        return list_ports()

    # Imported here rather than at module scope so that --list-ports and --help work on a machine
    # with no display and no Qt libraries installed.
    import qasync
    from PySide6.QtWidgets import QApplication

    from smartclock_monitor.views.main_window import APPLICATION_NAME, MainWindow

    application = QApplication(sys.argv[:1])
    application.setApplicationName(APPLICATION_NAME)

    window = MainWindow(Theme(arguments.theme))
    window.show()

    loop = qasync.QEventLoop(application)
    asyncio.set_event_loop(loop)

    with loop:
        loop.create_task(_run(arguments, window))
        loop.run_forever()

    return 0


async def _run(arguments: argparse.Namespace, window: object) -> None:
    """Connect, then poll until the window closes."""
    from smartclock_monitor.views.main_window import MainWindow

    assert isinstance(window, MainWindow)

    clock = SystemClock()
    driver = SmartClockDriver(clock=clock)

    transport: Transport
    if arguments.demo or not arguments.port:
        transport = ReplayTransport(clock)
        window.set_connection_text("Demo — replaying captured status screens")
    else:
        from smartclock_device.transport.serial_port import SerialTransport

        transport = SerialTransport(arguments.port, settings_from(arguments))
        window.set_connection_text(f"Connecting to {transport.description}…")

    session = DeviceSession(transport, driver, clock)
    store = _open_store(arguments, clock, window)

    try:
        await session.open()
    except TransportError as error:
        # §9.11's copy rule: the failure reaches the user in words they can act on.
        window.set_connection_text(str(error))
        return

    identity = session.identity
    named = identity.model if identity is not None else "receiver"
    window.set_connection_text(f"Connected to {named} — {session.description}")

    service = PollingService(session=session, driver=driver, clock=clock)
    service.on_reading = _publish(window, store)

    try:
        await service.run()
    except asyncio.CancelledError:
        raise
    finally:
        await session.close()
        if store is not None:
            store.close()


def _open_store(
    arguments: argparse.Namespace, clock: SystemClock, window: object
) -> TrendStore | None:
    """Open the trend store, or run without one.

    **A store that will not open is never fatal.** A read-only home directory, a file written by a
    newer build, a full disk — all of them are ordinary, and none is a reason to refuse to monitor
    a receiver. The failure is reported in the status bar in §9.11's terms and the charts show
    their empty state.
    """
    from smartclock_monitor.views.main_window import MainWindow

    assert isinstance(window, MainWindow)

    if arguments.no_trend_store:
        return None

    path = Path(arguments.trend_store) if arguments.trend_store else trend_database()
    try:
        store = TrendStore.open(path, clock)
    except TrendStoreError as error:
        window.set_connection_text(f"No trend history this run: {error}")
        return None

    window.set_trend_store(store)
    return store


def _publish(window: object, store: TrendStore | None) -> Callable[[Reading], None]:
    """One callback that files the reading and then draws it.

    **Stored before displayed, and a store that fails does not cost the display.** The reading is
    on screen either way; the only thing a failed write loses is a pixel of history, and taking
    the poll loop down over it would lose the receiver.
    """
    from smartclock_monitor.views.main_window import MainWindow

    assert isinstance(window, MainWindow)

    def publish(reading: Reading) -> None:
        if store is not None:
            # Suppressed deliberately, and this is the one place it is right to: a failed write
            # costs a pixel of history, and letting it out of a poll-loop callback would cost the
            # receiver.
            with suppress(TrendStoreError):
                store.append(reading)
        window.show_reading(reading)

    return publish


if __name__ == "__main__":
    raise SystemExit(main())
