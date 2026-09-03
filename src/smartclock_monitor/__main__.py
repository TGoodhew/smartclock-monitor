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
from smartclock_device.drivers.nmea import NmeaDriver
from smartclock_device.drivers.registry import Registry
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
from smartclock_monitor.services import logging as app_log
from smartclock_monitor.services.commands import SessionCommands
from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.replay import ReplayTransport
from smartclock_monitor.services.session import DeviceSession
from smartclock_monitor.services.supervisor import Supervisor
from smartclock_monitor.services.trend_store import TrendStore, TrendStoreError
from smartclock_monitor.themes import fonts
from smartclock_monitor.themes.tokens import Theme
from smartclock_monitor.views.connection_dialog import ConnectionChoice


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="smartclock-monitor",
        description="Monitor an HP/Symmetricom SmartClock GPS-disciplined oscillator.",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help=(
            "check this machine and say what is missing — Qt's libraries, serial access, the "
            "bundled fonts — then exit. Runs before anything else and needs no receiver."
        ),
    )

    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--demo",
        action="store_true",
        help="replay the captured status screens instead of opening a serial port",
    )
    source.add_argument("--port", help="serial port, e.g. /dev/ttyUSB0 or COM3")

    parser.add_argument(
        "--auto-detect",
        action="store_true",
        help=(
            "walk every registered family's serial settings until the receiver answers, instead "
            "of using --baud and friends. A second-hand receiver's settings are not knowable in "
            "advance, and §10.12 makes the walk the union across families rather than one "
            "receiver's eight."
        ),
    )
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

    # Before the Qt import below, deliberately: the machine that needs the doctor most is the one
    # where importing PySide6 is itself the thing that fails.
    if arguments.doctor:
        from smartclock_monitor.doctor import report

        return report()

    # Imported here rather than at module scope so that --list-ports and --help work on a machine
    # with no display and no Qt libraries installed.
    import qasync
    from PySide6.QtWidgets import QApplication

    from smartclock_monitor.views.main_window import APPLICATION_NAME, MainWindow

    application = QApplication(sys.argv[:1])
    application.setApplicationName(APPLICATION_NAME)

    # **Before the first window.** A widget measured before its font exists is measured in the
    # default one, and every layout minimum computed from that is wrong — which is the defect this
    # bundling exists to end, so registering late would leave it in place.
    fonts.load()

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

    # §12's composition root: registration order is priority order, and the fallback is the first
    # registered — so the SmartClock leads, because a receiver that says nothing on a query/response
    # port is far more likely to be a sibling model than a talker that has stopped talking.
    #
    # The NMEA driver is here to be *used*, not to prove a point: a talker on the port is claimed
    # by what it said before anything was asked, is never written to, and fills only the fields
    # NMEA carries. Adding it is one line here rather than an edit everywhere, which was the whole
    # claim the seam made.
    registry = Registry([SmartClockDriver(clock=clock), NmeaDriver(clock=clock)])
    driver = registry.drivers[0]

    # #127: the writer starts before anything is opened, so the port opening is the first line.
    app_log.configure()
    changes = app_log.ChangeLog()

    store = _open_store(arguments, clock, window)

    #: What the next attempt should use. Mutable, because §10.12's dialog can change it while the
    #: supervisor is running — the cycle re-reads it on every attempt rather than capturing it
    #: once, which is the difference between a Connect button and a restart.
    chosen: dict[str, object] = {
        "port": arguments.port,
        "settings": None if arguments.auto_detect else settings_from(arguments),
    }

    def take(choice: ConnectionChoice) -> None:
        chosen["port"] = choice.port
        chosen["settings"] = choice.settings
        supervisor.stay_connected = choice.reconnect_automatically
        supervisor.reconnect()

    window.on_connection_chosen = take
    # So a session started from --port is the one the dialog offers back after a disconnect.
    window.remember_port(arguments.port)

    async def connect() -> DeviceSession | None:
        """One connection attempt. Called again by the supervisor after every drop."""
        if arguments.demo or not chosen["port"]:
            window.set_connection_text("Demo — replaying captured status screens")
            session = DeviceSession(ReplayTransport(clock), driver, clock, registry=registry)
            try:
                await session.open()
            except TransportError as error:
                # §9.11's copy rule: the failure reaches the user in words they can act on.
                window.set_connection_text(str(error))
                return None
            return session

        return await _connect_serial(
            str(chosen["port"]),
            chosen["settings"],  # type: ignore[arg-type]
            registry,
            clock,
            window,
            changes,
        )

    def announce(session: DeviceSession | None) -> None:
        """Rewire the window as sessions come and go.

        The runner is cleared when the link drops, so the pages disable their controls rather than
        offering buttons that would send into a closed port.
        """
        if session is None:
            window.set_command_runner(None)
            if supervisor.stopped_by_user:
                changes.user_disconnected()
            else:
                changes.disconnected("the link went")
            return
        identity = session.identity
        named = identity.model if identity is not None else "receiver"
        window.set_connection_text(f"Connected to {named} — {session.description}")
        changes.connected(session.description, identity.model if identity is not None else None)
        window.set_command_runner(SessionCommands(session))

    supervisor = Supervisor(
        connect=connect,
        driver=driver,
        clock=clock,
        on_session=announce,
        on_reading=_publish(window, store, changes),
        on_status=window.set_connection_text,
    )
    window.set_supervisor(supervisor)

    try:
        await supervisor.run()
    except asyncio.CancelledError:
        raise
    finally:
        if supervisor.session is not None:
            await supervisor.session.close()
        if store is not None:
            store.close()


async def _connect_serial(
    port: str,
    settings: SerialSettings | None,
    registry: Registry,
    clock: SystemClock,
    window: object,
    changes: app_log.ChangeLog,
) -> DeviceSession | None:
    """Open the named port, walking §7.1's sequence if asked to.

    Returns ``None`` when there is nothing to poll, having already said why in the status bar —
    §9.11's rule that the failure reaches the user in words they can act on.
    """
    from smartclock_device.transport.serial_port import SerialTransport
    from smartclock_monitor.services.autodetect import detect, open_with
    from smartclock_monitor.views.main_window import MainWindow

    assert isinstance(window, MainWindow)
    # The walk needs *a* driver to keep asking with; which family actually serves the receiver is
    # decided after the identity is read, by the session.
    driver = registry.drivers[0]

    def build(port: str, settings: SerialSettings) -> Transport:
        return SerialTransport(port, settings)

    try:
        if settings is not None:
            window.set_connection_text(f"Connecting to {port} @ {settings}…")
            changes.opened(port, settings)
            return await open_with(port, settings, driver, clock, build, registry=registry)

        found = await detect(
            port,
            driver,
            clock,
            build,
            registry=registry,
            # §10.12: the union of every registered family's rates, not one receiver's. A talker
            # runs at 4800 and was unreachable by the walk while the sequence belonged to the
            # SmartClock alone.
            sequence=registry.auto_detect_sequence,
            on_progress=lambda candidate, index, total: window.set_connection_text(
                f"Trying {candidate} on {port} — {index} of {total}…"
            ),
        )
    except TransportError as error:
        window.set_connection_text(str(error))
        return None

    if found is None:
        # Distinct from a port that would not open: the port was fine and nothing on it answered.
        window.set_connection_text(
            f"Nothing answered on {port} at any of "
            f"{len(registry.auto_detect_sequence)} known settings."
        )
        return None

    window.set_connection_text(f"Found a receiver at {found.settings} on attempt {found.attempts}.")
    changes.detected(found.settings, found.attempts)
    return found.session


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


def _publish(
    window: object, store: TrendStore | None, changes: app_log.ChangeLog
) -> Callable[[Reading], None]:
    """One callback that files the reading and then draws it.

    **Stored before displayed, and a store that fails does not cost the display.** The reading is
    on screen either way; the only thing a failed write loses is a pixel of history, and taking
    the poll loop down over it would lose the receiver.
    """
    from smartclock_monitor.views.main_window import MainWindow

    assert isinstance(window, MainWindow)

    def publish(reading: Reading) -> None:
        changes.observed(reading)
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
