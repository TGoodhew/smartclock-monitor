"""A stand-in for a GNSS talker, for driving the NMEA driver without one on the bench.

**Kept apart from the driver on purpose.** §12: *"the simulator that stands in for a talker lives
under ``tools/``, apart from the driver, so a driver author takes one folder and never sees it."*
Nothing under ``src/`` imports this, and a test that did would be testing the simulator.

Run it against a pty pair to drive the real application:

    python tools/nmea_simulator.py --pty
"""

from __future__ import annotations

import argparse
import math
import time
from collections.abc import Iterator

#: A plausible sky: PRN, elevation, azimuth, carrier-to-noise. Six tracked, two visible and not.
_SKY: tuple[tuple[int, int, int, int | None], ...] = (
    (4, 71, 93, 44),
    (7, 44, 250, 41),
    (9, 68, 307, 47),
    (16, 47, 78, 39),
    (21, 22, 323, 33),
    (26, 25, 49, 35),
    (3, 21, 172, None),
    (30, 6, 247, None),
)


def checksum(body: str) -> str:
    result = 0
    for character in body:
        result ^= ord(character)
    return f"{result:02X}"


def sentence(body: str) -> str:
    return f"${body}*{checksum(body)}"


def cycle(when: time.struct_time, fix: bool = True) -> Iterator[str]:
    """One second's worth of sentences, in the order a talker sends them.

    GGA first: §12 requires the plan's first fast-tier entry to delimit a cycle, and the listener
    closes a cycle when it comes round again.
    """
    hhmmss = time.strftime("%H%M%S", when)
    ddmmyy = time.strftime("%d%m%y", when)
    tracked = [entry for entry in _SKY if entry[3] is not None]
    quality = 1 if fix else 0

    yield sentence(
        f"GPGGA,{hhmmss}.00,4731.3091,N,12212.3692,W,{quality},"
        f"{len(tracked) if fix else 0},0.9,38.0,M,-17.6,M,,"
    )

    used = ",".join(str(entry[0]) for entry in tracked) if fix else ""
    padding = "," * (12 - (len(tracked) if fix else 0))
    yield sentence(f"GPGSA,A,{3 if fix else 1},{used}{padding}1.8,0.9,1.5")

    total = math.ceil(len(_SKY) / 4)
    for index in range(total):
        group = _SKY[index * 4 : index * 4 + 4]
        body = f"GPGSV,{total},{index + 1},{len(_SKY)}"
        for prn, elevation, azimuth, strength in group:
            body += (
                f",{prn:02d},{elevation:02d},{azimuth:03d},{'' if strength is None else strength}"
            )
        yield sentence(body)

    status = "A" if fix else "V"
    yield sentence(f"GPRMC,{hhmmss}.00,{status},4731.3091,N,12212.3692,W,0.0,0.0,{ddmmyy},15.5,E,A")


def run(writer: object, seconds: float, fix: bool) -> None:
    """Emit one cycle a second for ``seconds``.

    Counted rather than timed. ``time.monotonic`` is banned across this repository — the clock is
    injected everywhere so the fixture tests can pin it — and a simulator does not need an
    exemption for something it can do by counting. The drift against wall time over a minute is
    irrelevant to something pretending to be a talker.
    """
    for _ in range(max(1, int(seconds))):
        for line in cycle(time.gmtime(), fix=fix):
            writer.write((line + "\r\n").encode())  # type: ignore[attr-defined]
        writer.flush()  # type: ignore[attr-defined]
        time.sleep(1.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pretend to be an NMEA 0183 GNSS talker.")
    parser.add_argument("--pty", action="store_true", help="open a pty and print its device name")
    parser.add_argument("--seconds", type=float, default=60.0)
    parser.add_argument("--no-fix", action="store_true", help="talk, but report no position fix")
    arguments = parser.parse_args(argv)

    if not arguments.pty:
        for line in cycle(time.gmtime(), fix=not arguments.no_fix):
            print(line)
        return 0

    import os
    import pty

    controller, follower = pty.openpty()
    print(os.ttyname(follower), flush=True)
    with os.fdopen(controller, "wb", buffering=0) as writer:
        run(writer, arguments.seconds, fix=not arguments.no_fix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
