"""Ask the five status registers and the status screen in one sitting, and write both down.

The screen and the registers are two accounts of the same instant, and **the value of a capture
is that they were taken in the same breath**. `Models/StatusRegisterMap.cs` and its port here say
what each bit means; nothing in either repository had ever put those meanings beside a screen
taken at the same moment and asked whether they agreed. `tests/test_registers_against_screen.py`
asks, against whatever this harness last wrote.

It came out of the audit against Lady Heather (#98), whose HP masks are an independent reading of
the same register — and whose reading of four bit groups matches this port's exactly. Agreement
between two implementations is worth something; agreement with the hardware is worth more.

    python tools/capture_registers.py --port /dev/ttyUSB0 --label locked-and-holding

**Every command sent is a catalogue constant**, and every one is a query. The harness assembles
no mnemonics of its own: §8.1 makes the catalogue an allowlist, and a capture tool that spelled
its own commands would be a second list to keep in step with it.

Nothing under ``src/`` imports this.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import timedelta
from pathlib import Path

from smartclock_device.clock import Clock, SystemClock
from smartclock_device.commands import catalog
from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_device.models import status_register_map as registers
from smartclock_device.transport.line_protocol import LineProtocol
from smartclock_device.transport.serial_port import SerialTransport
from smartclock_device.transport.settings import DEFAULT

#: Where a sitting lands. Its own directory, away from the ten status screens: those are parser
#: fixtures and this is a transcript, and ``test_parser_fuzz`` learned the hard way what happens
#: when one corpus's glob reaches another's files.
DEFAULT_DIRECTORY = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "smartclock"

#: How long to wait for one answer. The screen is a page and a half at 9600 baud; everything else
#: is a line.
SCREEN_TIMEOUT = timedelta(seconds=20)
REPLY_TIMEOUT = timedelta(seconds=6)


#: What is asked, in the order it is asked. The screen first, so the registers below it describe
#: an instant the screen has already been read for rather than one it will be read for later.
def _commands() -> tuple[ScpiCommand, ...]:
    condition_queries = tuple(
        query
        for register in registers.ALL
        if (query := catalog.register_query(f":STAT:{register.node}", "COND")) is not None
    )
    return (
        catalog.STATUS_SCREEN,
        *condition_queries,
        catalog.TIME_FIGURE_OF_MERIT,
        catalog.FREQUENCY_FIGURE_OF_MERIT,
        catalog.HOLDOVER_DURATION,
        catalog.LOG_COUNT,
        catalog.LIFETIME_HOURS,
    )


#: The marker that opens a sent command in the transcript. Chosen because the receiver's own
#: prompt is ``scpi >`` and a line can therefore never begin with this.
SENT = ">>> "


async def capture(port: str, destination: Path, clock: Clock) -> int:
    """Take one sitting and write it. Returns the number of commands that answered."""
    transport = SerialTransport(port, DEFAULT)
    await transport.open()
    protocol = LineProtocol(transport, clock)
    answered = 0
    try:
        with destination.open("w", encoding="utf-8", newline="\r\n") as out:
            out.write(f"# taken {clock.utc_now().isoformat(timespec='seconds')} from {port}\n")
            out.write("# lines are verbatim; '>>> ' opens what was sent\n")
            for command in _commands():
                timeout = SCREEN_TIMEOUT if command is catalog.STATUS_SCREEN else REPLY_TIMEOUT
                transaction = await protocol.execute(command.mnemonic, timeout)
                out.write(f"{SENT}{command.mnemonic}\n")
                for line in transaction.lines:
                    out.write(f"{line}\n")
                out.flush()
                if transaction.lines:
                    answered += 1
    finally:
        await transport.close()
    return answered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="/dev/ttyUSB0", help="the receiver's port")
    parser.add_argument("--label", required=True, help="what this sitting is, in kebab case")
    parser.add_argument("--into", type=Path, default=DEFAULT_DIRECTORY)
    arguments = parser.parse_args(argv)

    arguments.into.mkdir(parents=True, exist_ok=True)
    destination = arguments.into / f"{arguments.label}.txt"
    answered = asyncio.run(capture(arguments.port, destination, SystemClock()))
    print(f"{answered} of {len(_commands())} answered -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
