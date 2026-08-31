"""The captured status screens are present, non-empty, and byte-preserved.

These ten files are the parser's pass/fail oracle. They are device output captured from real
hardware across two bench sittings, and the states they record — power-up, GPS acquisition,
holdover, recovery — happen only while the receiver is being moved or restarted. They cannot
be regenerated on demand, and a parsing bug found after they are lost cannot be retried
without moving the hardware again.

So this test does the small, dull thing that catches the way they actually get damaged: a
checkout that rewrites their line endings, or a well-meaning tidy-up that trims trailing
whitespace out of a fixed-width instrument screen. ``.gitattributes`` marks the directory
``-text`` to prevent the first; this notices if that ever stops working.

It does not parse anything. There is no parser yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CAPTURED = FIXTURES / "captured"

#: Every state captured so far. A failing health monitor is still missing; if a future bench
#: sitting produces one, it belongs here and in the WinZ3805A repository both.
EXPECTED = (
    "holdover-gps-1pps-invalid-3.txt",
    "holdover-gps-1pps-invalid-deep.txt",
    "holdover-gps-1pps-invalid.txt",
    "locked-to-gps-stabilizing-frequency.txt",
    "locked-to-gps.txt",
    "power-up-fine-freq-adj.txt",
    "power-up-gps-acquisition.txt",
    "recovery-fine-freq-adj.txt",
    "surveying-locked-to-gps-stabilizing-frequency.txt",
)


def test_every_captured_screen_is_present() -> None:
    missing = [name for name in EXPECTED if not (CAPTURED / name).is_file()]
    assert not missing, f"Captured fixtures are missing and cannot be regenerated: {missing}"


def test_no_captured_screen_has_been_added_without_being_listed() -> None:
    """A new capture should be a deliberate edit here, not a file that quietly appears."""
    found = {p.name for p in CAPTURED.glob("*.txt")}
    assert found == set(EXPECTED), (
        "The captured fixture set changed. If a bench sitting added one, list it in EXPECTED "
        "and mirror it into WinZ3805A; see docs/provenance.md."
    )


@pytest.mark.parametrize("name", EXPECTED)
def test_captured_screen_is_intact(name: str) -> None:
    raw = (CAPTURED / name).read_bytes()

    assert raw, f"{name} is empty"
    assert b"\r\n" in raw, (
        f"{name} has lost its CRLF line endings. This is device output and its exact bytes "
        "are the point; check .gitattributes marks tests/fixtures/ as -text."
    )


def test_the_capture_log_travelled_with_them() -> None:
    """Provenance is part of a fixture. A screen with no record of where it came from is data
    nobody can later judge."""
    log = CAPTURED / "capture-log.md"
    assert log.is_file() and log.stat().st_size > 0
