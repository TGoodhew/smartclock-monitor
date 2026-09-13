"""Write exactly what a talker says to a file, and nothing else.

The port of `build/Capture-Talker.ps1` from WinZ3805A, which produced the corpus in
`tests/fixtures/nmea/`. Captures taken by either harness belong in both repositories —
`docs/provenance.md` is the arrangement — so this writes the same shape of artefact: one
`.nmea` of raw bytes and one `.md` beside it saying what the sitting was.

**Raw bytes, not decoded lines.** The capture is an oracle for a parser whose whole job is to
survive what a receiver actually puts on the wire — a truncated sentence, a bad checksum, a
binary frame among the ASCII. Decoding on the way in would throw away the cases worth having,
and re-terminating would answer a question the parser is supposed to be asked.

Nothing under ``src/`` imports this. §12 keeps the talker's tooling apart from the driver so a
driver author takes one folder and never sees it.

    python tools/capture_talker.py --port /dev/ttyACM0 --seconds 300 --name vk162-steady-state

Listing what is on the bench:

    python tools/capture_talker.py --list
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta
from pathlib import Path

import serial
from serial.tools import list_ports

from smartclock_device.clock import Clock, SystemClock

#: Where a capture lands, beside the ones carried from WinZ3805A.
DEFAULT_DIRECTORY = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "nmea"

#: The rate every talker in service runs at unless it has been told otherwise. 9600 is the NMEA
#: 0183 standard rate; a USB talker enumerating as a CDC ACM device ignores it entirely, which is
#: why this is a default rather than a question.
DEFAULT_BAUD = 9600


def _ports() -> None:
    """What is on the bench, with the by-id name that is stable across a re-attach."""
    for port in sorted(list_ports.comports(), key=lambda p: p.device):
        print(f"{port.device:16} {port.description}")
        if port.vid is not None:
            print(f"{'':16} {port.vid:04x}:{port.pid:04x}")


def capture(
    port: str,
    seconds: float,
    destination: Path,
    baud: int = DEFAULT_BAUD,
    clock: Clock | None = None,
) -> int:
    """Read for ``seconds`` and write every byte to ``destination``. Returns the byte count.

    Written as it arrives rather than buffered to the end, so a capture interrupted half way is
    still a capture. The corpus this joins holds a receiver being power-cycled and an antenna
    being pulled; a harness that lost everything on Ctrl-C would lose exactly those.

    **The clock is injected like everywhere else.** `CLAUDE.md` bans ``time.monotonic`` tree-wide
    and ruff's ``TID251`` refused the first draft of this function, which is the gate doing its
    job in the one place it is tempting to wave through: a capture harness is exactly where a
    wall-clock reading looks harmless, and a capture whose duration cannot be pinned is a capture
    whose sidecar says something no test can reproduce.
    """
    ticker = clock if clock is not None else SystemClock()
    limit = timedelta(seconds=seconds)
    written = 0
    started = ticker.utc_now()
    with serial.Serial(port, baud, timeout=1) as link, destination.open("wb") as out:
        while ticker.utc_now() - started < limit:
            chunk = link.read(4096)
            if chunk:
                out.write(chunk)
                out.flush()
                written += len(chunk)
    return written


def _sidecar(
    destination: Path, port: str, baud: int, seconds: float, written: int, clock: Clock
) -> Path:
    """The `.md` that says what the sitting was.

    Written as a stub with the facts the harness knows. **The rest is written by hand**, and the
    upstream README says why: *"Each has a `.md` beside it saying what was happening; read those
    rather than this table."* A sidecar that only ever holds what a script could work out is a
    sidecar nobody reads.
    """
    note = destination.with_suffix(".md")
    note.write_text(
        f"# {destination.stem}\n\n"
        f"- **Captured** {clock.utc_now().isoformat(timespec='seconds')}\n"
        f"- **Port** `{port}` at {baud}-8-N-1\n"
        f"- **Duration** {seconds:.0f} s\n"
        f"- **Bytes** {written:,}\n"
        f"- **Receiver** — *fill in: model, firmware, the banner it printed*\n"
        f"- **Antenna** — *fill in: which one, and where*\n\n"
        "## What this is for\n\n"
        "*Fill in. What state was the receiver in, what was done to it, and what a parser is\n"
        "expected to learn here that no other capture teaches.*\n",
        encoding="utf-8",
    )
    return note


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="list the serial ports and exit")
    parser.add_argument("--port", help="the talker's port, e.g. /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=DEFAULT_BAUD)
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--name", help="capture name, without an extension")
    parser.add_argument("--into", type=Path, default=DEFAULT_DIRECTORY)
    arguments = parser.parse_args(argv)

    if arguments.list:
        _ports()
        return 0

    if not arguments.port or not arguments.name:
        parser.error("--port and --name are both required unless --list is given")

    destination = arguments.into / f"{arguments.name}.nmea"
    if destination.exists():
        parser.error(f"{destination} exists; captures are never overwritten")

    arguments.into.mkdir(parents=True, exist_ok=True)
    print(f"Capturing {arguments.seconds:.0f}s from {arguments.port} → {destination}")
    clock = SystemClock()
    written = capture(arguments.port, arguments.seconds, destination, arguments.baud, clock)
    note = _sidecar(destination, arguments.port, arguments.baud, arguments.seconds, written, clock)
    print(f"{written:,} bytes. Now write up {note.name} — the stub has only what a script knows.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
