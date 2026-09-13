"""Every captured talker, replayed through the real driver.

`tests/fixtures/nmea/` holds ten sittings carried from WinZ3805A (#56) and two taken on this
bench. They are the NMEA family's oracle in the way `tests/fixtures/captured/` is the SmartClock
family's, and for the same reason: until they arrived, everything the driver had ever been tested
against came from `tools/nmea_simulator.py`, which can only produce what we already believed a
talker sends.

**Three of the assertions here are expected failures**, and that is the point of the file rather
than a defect in it. Each names the issue it belongs to:

- `xfail_gns` — a talker that sends `GNS` instead of `GGA` yields **no cycles at all** (#58)
- `xfail_identity` — two constellations collide on one satellite number (#57)
- `xfail_error_statistics` — `GST` and `GBS` are not read (#58)

`CLAUDE.md`: *"Write the fixture assertion before the parsing code."* These are those assertions.
When one of them starts passing, take the marker off; ``strict`` makes an unexpected pass a
failure, so none can be left behind by accident.
"""

from __future__ import annotations

import collections
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from smartclock_device.clock import FixedClock
from smartclock_device.drivers.base import WHOLE_CYCLE
from smartclock_device.drivers.nmea import sentences
from smartclock_device.drivers.nmea.driver import NmeaDriver
from smartclock_device.models.receiver_status import ReceiverStatus
from smartclock_device.transport.broadcast import BroadcastListener
from smartclock_device.transport.transaction import Transaction, TransactionOutcome

CAPTURES: Final = Path(__file__).parent / "fixtures" / "nmea"

#: The sittings carried from WinZ3805A. Named rather than globbed, so a capture that goes missing
#: fails here instead of quietly reducing the corpus — the same reason `test_fixtures.py` walks all
#: ten status screens rather than the one at the top of the directory.
CARRIED: Final = (
    "vk162-steady-state",
    "vk162-cold-start",
    "vk162-glonass-only",
    "vk162-gns-no-gga",
    "vk162-microwave",
    "form8n-gps-beidou-first-light",
    "form8n-gns-without-gga",
    "form8n-gps-beidou-outdoors",
    "form8n-gst-gbs",
    "form8n-fix-lost",
)


def _replay(name: str) -> list[ReceiverStatus]:
    """Drive one capture through the driver and the listener, exactly as a session would.

    Bytes off the file, decoded the way the transport decodes them — ``replace`` rather than
    ``strict``, because §11.1 forbids raising and a capture holding a byte no codec likes is a
    capture doing its job.
    """
    clock = FixedClock(datetime(2026, 9, 13, tzinfo=UTC))
    driver = NmeaDriver(clock)
    listener = BroadcastListener(clock=clock, boundary=driver.plan.fast[0].mnemonic)

    statuses: list[ReceiverStatus] = []
    previous: ReceiverStatus | None = None
    for raw in (CAPTURES / f"{name}.nmea").read_bytes().decode("ascii", "replace").splitlines():
        line = raw.strip()
        if not line:
            continue
        before = listener.cycles
        listener.feed(driver.classify(line), line)
        if listener.cycles > before:
            transaction = Transaction(
                command=WHOLE_CYCLE,
                outcome=TransactionOutcome.COMPLETED,
                lines=listener.whole_cycle(),
            )
            previous = driver.parse_full(transaction, previous)
            statuses.append(previous)
    return statuses


def _headers(name: str) -> collections.Counter[str]:
    counted: collections.Counter[str] = collections.Counter()
    for raw in (CAPTURES / f"{name}.nmea").read_bytes().decode("ascii", "replace").splitlines():
        parsed = sentences.parse(raw.strip())
        if parsed is not None:
            counted[f"{parsed.talker}{parsed.kind}"] += 1
    return counted


# ---- The corpus is here at all -----------------------------------------------------------------


def test_every_carried_capture_is_present_and_has_its_note() -> None:
    """A capture cannot be regenerated on demand, so a missing one is a loss, not a skip."""
    for name in CARRIED:
        assert (CAPTURES / f"{name}.nmea").is_file(), f"{name}.nmea is missing"
        assert (CAPTURES / f"{name}.md").is_file(), f"{name}.md is missing"


def test_the_captures_kept_their_bytes() -> None:
    """`.gitattributes` marks `tests/fixtures/**` as `-text`; this notices if that stops working.

    A talker's output is CRLF-terminated and a checkout that converted it would change every byte
    offset the sidecars quote — `form8n-fix-lost.md` names the cold start at byte 87164.
    """
    raw = (CAPTURES / "vk162-steady-state.nmea").read_bytes()
    assert b"\r\n" in raw, "the line endings have been converted; see .gitattributes"


# ---- What the driver makes of them today -------------------------------------------------------


@pytest.mark.parametrize("name", CARRIED)
def test_no_capture_makes_the_parser_raise(name: str) -> None:
    """§11.1, against the only input that has ever been near a receiver."""
    _replay(name)


def test_the_boring_case_at_length_is_boring() -> None:
    """1,800 cycles of a differential 3D fix. The control for every other capture."""
    statuses = _replay("vk162-steady-state")

    assert len(statuses) == 1799, "a cycle went missing in the capture that has no gaps"
    assert all(s.position is not None for s in statuses), "the steady state lost a fix"


def test_a_cold_start_has_exactly_one_cycle_without_a_fix() -> None:
    """The corpus's only no-fix cycle on this receiver, and the one the acquisition path needs."""
    statuses = _replay("vk162-cold-start")

    assert sum(1 for s in statuses if s.position is None) == 1


def test_a_talker_that_is_not_gp_is_heard() -> None:
    """`bfe46b7` upstream. The VK-162 configured for GLONASS speaks `GL`, and nothing else.

    Then 152 consecutive cycles with no fix — the corpus's longest outage — followed by
    acquisition. A driver that keyed on the `GP` talker would read none of it.
    """
    headers = _headers("vk162-glonass-only")
    assert not any(h.startswith("GP") for h in headers), "this capture should be GLONASS only"

    statuses = _replay("vk162-glonass-only")
    assert len(statuses) > 800
    assert sum(1 for s in statuses if s.position is None) == 152


def test_a_fix_is_taken_away_and_given_back() -> None:
    """The only capture in which a receiver loses a fix and recovers it (#420)."""
    statuses = _replay("form8n-fix-lost")

    without = [i for i, s in enumerate(statuses) if s.position is None]
    assert len(without) == 65, "the outage is not the length the sitting recorded"
    assert without[0] > 0, "it should start with a fix"
    assert without[-1] < len(statuses) - 1, "and end with one"


# ---- The three that are expected to fail -------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason="#58: the cycle boundary is GGA only, so a GNS talker yields no cycles at all",
)
@pytest.mark.parametrize("name", ["vk162-gns-no-gga", "form8n-gns-without-gga"])
def test_a_talker_that_sends_gns_instead_of_gga_is_read(name: str) -> None:
    """**Not a missing readout — an unreadable receiver.**

    Both captures carry a valid fix in every cycle and not one `GGA`. `sentences.py` calls `GGA`
    "the sentence every talker emits exactly once per cycle"; these are two receivers that do not.
    The listener's boundary never comes round, no cycle ever closes, and the application shows
    nothing at all while connected to a working talker.
    """
    headers = _headers(name)
    assert not any(h.endswith("GGA") for h in headers), "this capture should have no GGA"
    assert any(h.endswith("GNS") for h in headers), "this capture should have GNS"

    statuses = _replay(name)

    assert statuses, "no cycle closed: the receiver is unreadable"
    assert any(s.position is not None for s in statuses), "GNS carries the fix that GGA would"


@pytest.mark.xfail(
    strict=True, reason="#57: a satellite is a bare number, so two constellations collide"
)
def test_two_constellations_do_not_collide_on_one_number() -> None:
    """The forM8N outdoors, where BeiDou actually tracks.

    Every cycle in this capture has at least one satellite number reported by two talkers, and
    `TrackedSatellite` is keyed on the number alone — so `_visible` collapses the pair and the
    count is short by however many collided.
    """
    name = "form8n-gps-beidou-outdoors"
    talkers_by_number: dict[int, set[str]] = collections.defaultdict(set)
    for raw in (CAPTURES / f"{name}.nmea").read_bytes().decode("ascii", "replace").splitlines():
        parsed = sentences.parse(raw.strip())
        if parsed is None or parsed.kind != sentences.GSV:
            continue
        for index in range(3, len(parsed.fields), 4):
            number = sentences.parse_int(parsed.fields[index])
            if number is not None:
                talkers_by_number[number].add(parsed.talker)

    shared = {n for n, talkers in talkers_by_number.items() if len(talkers) > 1}
    assert shared, "this capture should carry colliding satellite numbers"

    statuses = _replay(name)
    richest = max(statuses, key=lambda s: len(s.tracked))

    assert len({(s.constellation, s.prn) for s in richest.tracked}) == len(richest.tracked)  # type: ignore[attr-defined]


@pytest.mark.xfail(strict=True, reason="#58: GST and GBS are not in KEYS, so neither is read")
def test_the_fix_reports_its_own_error() -> None:
    """The only capture carrying `GST` or `GBS` — 300 of each, enabled deliberately (#516).

    §10.6 has a row for the position's error in metres, and this is the sitting that can fill it.
    """
    headers = _headers("form8n-gst-gbs")
    assert headers["GNGST"] == 300, "this capture should carry 300 GST"

    assert sentences.GST in sentences.KEYS  # type: ignore[attr-defined]
    assert sentences.GBS in sentences.KEYS  # type: ignore[attr-defined]


# ---- The two taken on this bench ---------------------------------------------------------------

#: Captured here with `tools/capture_talker.py`, from the same two module families, five days
#: after the carried sittings. They are a cross-check rather than new states — see their notes.
BENCH: Final = ("vk162-wsl-bench", "form8n-wsl-bench")


@pytest.mark.parametrize("name", BENCH)
def test_the_bench_captures_are_present_and_written_up(name: str) -> None:
    assert (CAPTURES / f"{name}.nmea").is_file()
    assert (CAPTURES / f"{name}.md").is_file()


@pytest.mark.parametrize("name", BENCH)
def test_the_harness_here_produces_what_the_upstream_one_did(name: str) -> None:
    """`tools/capture_talker.py` writes raw bytes, CRLF intact, and the driver reads them.

    The point of the assertion is the harness, not the receiver: a capture tool that silently
    re-terminated or decoded would produce a corpus that agrees with the parser because both had
    made the same assumption, which is the one way a fixture can be worse than none.
    """
    raw = (CAPTURES / f"{name}.nmea").read_bytes()

    assert b"\r\n" in raw, "the harness did not preserve CRLF"
    assert raw.count(b"\r") == raw.count(b"\r\n"), "a bare CR survived, so something re-terminated"

    statuses = _replay(name)
    assert len(statuses) > 600, "ten minutes of a 1 Hz talker should close about 600 cycles"
    assert all(s.position is not None for s in statuses), "an indoor fix was held throughout"


def test_a_navigational_status_field_is_not_mistaken_for_the_fix() -> None:
    """The forM8N sends `V` as RMC's last field in every cycle; the VK-162 sends `A`.

    That field is NMEA 4.1's navigational-status indicator, which this firmware carries and does
    not implement. It sits exactly where a reader skimming for "the mode indicator" would land,
    and reading it as one would report no valid fix for a receiver whose GGA quality is 1 and
    whose position is good.

    Gated because it is a *latent* mistake rather than a present one: nothing reads that field
    today, and this is what notices if something starts.
    """
    trailing = collections.Counter[str]()
    for raw in (CAPTURES / "form8n-wsl-bench.nmea").read_bytes().decode("ascii").splitlines():
        parsed = sentences.parse(raw.strip())
        if parsed is not None and parsed.kind == sentences.RMC and parsed.fields:
            trailing[parsed.fields[-1]] += 1

    assert set(trailing) == {"V"}, "this capture should carry V in RMC's last field throughout"

    statuses = _replay("form8n-wsl-bench")
    assert all(s.position is not None for s in statuses), (
        "RMC's navigational-status field is being read as the fix"
    )


def test_the_banner_is_present_and_says_what_the_unit_is_programmed_for() -> None:
    """#62's once-only reading, captured by construction rather than by luck.

    `usbipd attach` re-enumerates the device, so every capture taken through it starts at the
    talker's power-on. The forM8N prints both what its firmware supports and what this unit is
    one-time-programmed for, and only the second is true of the receiver in front of you — there
    is not one GLONASS sentence in the capture despite GLO appearing in the supported line.
    """
    text = (CAPTURES / "form8n-wsl-bench.nmea").read_bytes().decode("ascii")

    assert "GPS;GLO;BDS" in text, "the supported-constellation line"
    assert "GNSS OTP=GPS;BDS" in text, "and the one that describes this unit"
    assert "GLGSV" not in text, "GLO is supported and not programmed, so nothing GLONASS arrives"
