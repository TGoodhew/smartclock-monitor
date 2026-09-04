"""``--doctor``: the check that runs before anything works.

Its whole value is on a machine where something is missing, which is by definition not this one.
So the checks are exercised through their own seams rather than by hoping the developer's laptop is
broken in an interesting way.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from smartclock_monitor import doctor


def test_every_check_runs_even_when_one_fails() -> None:
    """**The report is the point.** Stopping at the first failure sends somebody round the loop
    once per problem, and the machine missing Qt's libraries is usually the machine that is also
    not in dialout."""
    findings = list(doctor.checks())

    assert len(findings) >= 6
    assert len({finding.name for finding in findings}) == len(findings), "a check is duplicated"


def test_a_failure_carries_the_command_that_fixes_it() -> None:
    """A checklist that says something is wrong and not what to do about it has moved the problem
    rather than solved it."""
    broken = doctor.Finding("Qt platform", ok=False, detail="no display", remedy="sudo apt …")

    rendered = broken.rendered()

    assert "FAIL" in rendered
    assert "sudo apt" in rendered
    assert "→" in rendered, "the remedy is not called out"


def test_a_passing_check_does_not_lecture() -> None:
    """A remedy printed beside something that works is noise, and noise is what makes a checklist
    stop being read."""
    fine = doctor.Finding("pyserial", ok=True, detail="3.5", remedy="pip install pyserial")

    assert "→" not in fine.rendered()


def test_the_exit_status_says_whether_anything_is_broken(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """So it can be used in a script, and so a VM image build fails rather than ships broken."""
    monkeypatch.setattr(
        doctor, "checks", lambda: iter([doctor.Finding("Something", ok=False, detail="no")])
    )
    assert doctor.report() == 1

    monkeypatch.setattr(
        doctor, "checks", lambda: iter([doctor.Finding("Something", ok=True, detail="yes")])
    )
    assert doctor.report() == 0

    assert "Nothing to fix" in capsys.readouterr().out


def test_the_dialout_check_asks_about_this_session_not_the_file() -> None:
    """The commonest form of this problem is a shell opened *before* the group was granted: the
    user is in ``/etc/group`` and the process is not in the group, and the port keeps refusing.
    Reading the file would report success while every open failed."""
    import inspect

    source = inspect.getsource(doctor._dialout)

    assert "os.getgroups()" in source, "membership is read from the file rather than the process"


def test_it_finds_the_bundled_faces() -> None:
    """Ties the doctor to what D4 settled: if the faces stop being bundled, this says so on every
    machine rather than only on one without them installed.

    The probe is supplied rather than run: #46 moved the GUI checks into a child process, and this
    test is about what the doctor *says* about a set of faces, not about whether this machine can
    start Qt.
    """
    finding = doctor._fonts(doctor._GuiProbe("offscreen", ("Noto Sans", "Cascadia Mono"), ""))

    assert finding.ok, finding.detail
    assert "Cascadia Mono" in finding.detail


def test_the_report_survives_a_qt_that_cannot_start() -> None:
    """#46: `--doctor` aborted instead of reporting, on exactly the machine it exists to diagnose.

    Qt does not raise when it cannot load a platform plugin — it calls `qFatal()`, which calls
    `abort()` — so the `except Exception` that used to guard this could never see it, and the
    process died mid-check having printed nothing. The whole report was lost to one missing
    library.

    Driven by pointing the child at a platform plugin that does not exist, which is the same
    failure by a different cause.
    """
    finished = subprocess.run(
        [sys.executable, "-m", "smartclock_monitor", "--doctor"],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env={**os.environ, "QT_QPA_PLATFORM": "no-such-platform-plugin"},
    )

    assert finished.returncode in (0, 1), (
        f"the doctor exited {finished.returncode} — a negative or 134 status is the abort #46 was "
        f"about, and means the report was never printed"
    )
    assert "Qt platform" in finished.stdout, finished.stdout[-500:]

    # The point of the fix: the checks *after* the one that failed still ran.
    for expected in ("pyserial", "Serial ports", "dialout"):
        assert expected in finished.stdout, (
            f"{expected!r} is missing — the report stopped at the Qt check again"
        )


# ---- The adapter that is present and has no port -------------------------------------------------


def _fake_usb(tmp_path: Path, vendors: list[str]) -> Path:
    """A sysfs-shaped tree with these vendor ids on the bus."""
    root = tmp_path / "devices"
    root.mkdir(parents=True, exist_ok=True)
    for index, vendor in enumerate(vendors):
        entry = root / f"1-{index}"
        entry.mkdir()
        (entry / "idVendor").write_text(vendor, encoding="ascii")
    return root


def test_an_adapter_with_no_port_is_reported_as_the_problem_it_is(tmp_path: Path) -> None:
    """**The gap that looks like nothing at all.** An adapter can be attached and enumerated while
    no ``/dev/ttyUSB*`` exists, and the port check then says, truthfully, that none was found — so
    the user believes the cable is wrong when the kernel handed the device to something else.

    On Ubuntu that is usually brltty, which ships by default and claims these chips because Braille
    displays share their vendor ids. Not a misconfiguration anybody made, and not discoverable
    without being told — which is the whole reason a doctor exists.
    """
    bus = _fake_usb(tmp_path, ["067b"])

    finding = doctor._usb_serial_hardware(bus, has_port=False)

    assert not finding.ok
    assert "Prolific" in finding.detail
    assert "no port" in finding.detail
    assert "brltty" in finding.remedy


def test_an_adapter_with_a_port_is_fine(tmp_path: Path) -> None:
    """The ordinary working case must not read as a warning."""
    bus = _fake_usb(tmp_path, ["067b"])

    finding = doctor._usb_serial_hardware(bus, has_port=True)

    assert finding.ok
    assert "Prolific" in finding.detail


def test_a_bus_with_no_serial_hardware_says_so_quietly(tmp_path: Path) -> None:
    """A machine with nothing plugged in is the ordinary case and must not read as broken."""
    finding = doctor._usb_serial_hardware(_fake_usb(tmp_path, []), has_port=False)

    assert finding.ok
    assert "none on the bus" in finding.detail


def test_the_port_list_does_not_bury_the_adapter_in_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    """A desktop Linux kernel offers ttyS0 through ttyS31 whether or not any exists in hardware.
    Printing all thirty-two buries the one fact that matters, which is what a clean VM reported —
    WSL offers eight, few enough that it never showed here."""
    from types import SimpleNamespace

    from serial.tools import list_ports

    stubs = [
        SimpleNamespace(device=f"/dev/ttyS{n}", vid=None, pid=None, description="n/a")
        for n in range(32)
    ]
    adapter = SimpleNamespace(
        device="/dev/ttyUSB0", vid=0x067B, pid=0x2303, description="USB-Serial Controller"
    )

    monkeypatch.setattr(list_ports, "comports", lambda: [*stubs, adapter])
    with_adapter = doctor._ports()

    monkeypatch.setattr(list_ports, "comports", lambda: stubs)
    without = doctor._ports()

    assert "/dev/ttyUSB0" in with_adapter.detail
    assert "ttyS0" not in with_adapter.detail, "the stubs are back to drowning the adapter"
    assert "32 built-in" in with_adapter.detail, "the stubs are not accounted for at all"

    assert "no USB adapter found" in without.detail
    assert "ttyS" not in without.detail
