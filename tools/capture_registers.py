"""Ask the status screen, the five status registers and the time code in one sitting.

These are **three accounts of one instant**, and the value of the capture is that they were taken
in the same breath. The screen prints the figures of merit; the registers carry the conditions
behind them; and `:PTIM:TCOD?` carries both figures again, in twenty-three characters, by a third
route that touches neither (#113). `Models/StatusRegisterMap.cs` and its port here say
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
from smartclock_device.commands.scpi_command import ArgumentKind, ScpiCommand
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
def every_query() -> tuple[ScpiCommand, ...]:
    """Every argument-free query on the allowlist, in catalogue order.

    The sweep #118 wanted: a sitting that records what the receiver says to everything this
    application may ask it, and that **covers a new catalogue entry automatically** rather than
    waiting for someone to remember this file. Filtered to queries taking no argument, so the
    actions and the setters are not swept and nothing here changes the receiver — except `*ESR?`,
    whose contract is that reading clears it, and the error queue, which is a queue.

    §8.5's experimental six are excluded: they are opt-in by §8.5's own ruling, five of the six
    answer `E-113` on this receiver, and a sweep that collected six errors every time would be a
    sweep nobody could read.
    """
    experimental = set(catalog.EXPERIMENTAL)
    return tuple(
        command
        for command in catalog.ALL
        if command.mnemonic.endswith("?")
        and command.argument is ArgumentKind.NONE
        and command not in experimental
    )


def _commands(time_codes: int = 1) -> tuple[ScpiCommand, ...]:
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
        catalog.TIME_CODE_FORMAT,
        # Last, and with the screen's timeout: this one answers on the receiver's own 1 Hz cadence
        # and blocks until the next slot (#113).
        #
        # Asked **several times** by default, because one message proves a decode and a run of them
        # proves the checksum rule: consecutive messages differ only in the seconds digit, so a
        # checksum that tracks that difference is a checksum and not a coincidence.
        *(catalog.TIME_CODE,) * max(1, time_codes),
    )


#: The marker that opens a sent command in the transcript. Chosen because the receiver's own
#: prompt is ``scpi >`` and a line can therefore never begin with this.
SENT = ">>> "


async def capture(
    port: str,
    destination: Path,
    clock: Clock,
    time_codes: int = 1,
    commands: tuple[ScpiCommand, ...] | None = None,
) -> int:
    """Take one sitting and write it. Returns the number of commands that answered."""
    transport = SerialTransport(port, DEFAULT)
    await transport.open()
    protocol = LineProtocol(transport, clock)
    answered = 0
    try:
        with destination.open("w", encoding="utf-8", newline="\r\n") as out:
            out.write(f"# taken {clock.utc_now().isoformat(timespec='seconds')} from {port}\n")
            out.write("# lines are verbatim; '>>> ' opens what was sent\n")
            for command in commands or _commands(time_codes):
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
    parser.add_argument(
        "--time-codes", type=int, default=8, help="how many time-code messages to ask for"
    )
    parser.add_argument(
        "--every-query",
        action="store_true",
        help="sweep every argument-free query on the allowlist instead of the usual list",
    )
    arguments = parser.parse_args(argv)

    arguments.into.mkdir(parents=True, exist_ok=True)
    destination = arguments.into / f"{arguments.label}.txt"
    asked = every_query() if arguments.every_query else _commands(arguments.time_codes)
    answered = asyncio.run(
        capture(arguments.port, destination, SystemClock(), arguments.time_codes, asked)
    )
    print(f"{answered} of {len(asked)} answered -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
