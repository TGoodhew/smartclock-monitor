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


def test_the_dialout_check_can_fail_inside_a_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """**v1.2.1's could not, which is how a broken bundle passed its own doctor.**

    A Flatpak's ``/etc/group`` is the runtime's and carries no ``dialout``, so the name lookup
    raised ``KeyError`` and was reported as "no dialout group on this system" — an ``ok`` that no
    host configuration could turn into a failure, on precisely the machine the check exists to
    diagnose (#144). This asserts the outcome that used to be unreachable.
    """
    from types import SimpleNamespace

    from serial.tools import list_ports

    adapter = SimpleNamespace(
        device="/dev/ttyUSB0", vid=0x067B, pid=0x2303, description="USB-Serial Controller"
    )
    # Pinned, not skipped: a Flatpak only exists on Linux, but the logic under test is ordinary
    # Python and the Windows leg is as good a place to check it as any.
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(doctor, "_is_flatpak", lambda: True)
    monkeypatch.setattr(list_ports, "comports", lambda: [adapter])
    monkeypatch.setattr("os.access", lambda *_: False)

    finding = doctor._dialout()

    assert not finding.ok
    assert "/dev/ttyUSB0" in finding.detail
    assert "usermod -aG dialout" in finding.remedy
    assert "chmod" in finding.remedy, "the remedy does not warn off the wrong fix"


def test_the_sandbox_dialout_check_reports_a_port_the_kernel_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half: a pass has to remain reachable, or the check above is just an inverted
    version of the bug it replaced."""
    from types import SimpleNamespace

    from serial.tools import list_ports

    adapter = SimpleNamespace(
        device="/dev/ttyUSB0", vid=0x067B, pid=0x2303, description="USB-Serial Controller"
    )
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(doctor, "_is_flatpak", lambda: True)
    monkeypatch.setattr(list_ports, "comports", lambda: [adapter])
    monkeypatch.setattr("os.access", lambda *_: True)

    finding = doctor._dialout()

    assert finding.ok
    assert "/dev/ttyUSB0" in finding.detail


def test_the_sandbox_dialout_check_does_not_claim_an_answer_it_has_not_got(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With nothing attached there is no port to try, and saying so is the honest report. The
    detail has to admit it rather than read as a pass."""
    from serial.tools import list_ports

    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(doctor, "_is_flatpak", lambda: True)
    monkeypatch.setattr(list_ports, "comports", lambda: [])

    finding = doctor._dialout()

    assert "not checked" in finding.detail
    assert finding.remedy, "nothing tells the reader how to get a real answer"


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


def test_the_wsl_remedy_names_the_command_that_actually_needs_elevation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#67. `attach` is the one command in the procedure that does **not** need an elevated prompt.

    The first version sent a stuck user to an administrator prompt for the wrong half and never
    mentioned `bind` at all — so they ran `attach`, were told the device is not shared, and had
    nothing to go on. `--doctor` exists to tell the truth about what a machine needs, and a remedy
    that is confidently wrong is worse than none because it is the line they will act on.

    Measured against usbipd-win 5.3.0: `bind` is elevated and once per device, `attach` is neither.
    """
    monkeypatch.setattr(doctor, "_is_wsl", lambda: True)
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [])

    remedy = doctor._ports().remedy or ""

    assert "bind" in remedy, "the command that needs elevation must be named"
    assert "elevated" in remedy
    assert remedy.index("bind") < remedy.index("attach"), "and it comes first, because it does"
    assert "--wsl" in remedy, "attach needs the flag or it does nothing useful"


def test_the_wsl_remedy_warns_about_the_two_things_that_waste_an_afternoon(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A BUSID names a physical socket, and attaching takes the port away from Windows.

    The first is the commonest reason a device that "worked yesterday" stops appearing; the second
    is why the Windows sibling and this port cannot hold the same receiver at once.
    """
    monkeypatch.setattr(doctor, "_is_wsl", lambda: True)
    monkeypatch.setattr("serial.tools.list_ports.comports", lambda: [])

    remedy = doctor._ports().remedy or ""

    assert "socket" in remedy
    assert "detach" in remedy


# ---- The probe, in a build that has no interpreter to hand ---------------------------------------


def test_a_frozen_build_asks_itself_rather_than_an_interpreter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#147. `sys.executable` is only an interpreter when there is one.

    PyInstaller sets it to the launcher, so `[sys.executable, "-c", …]` re-invokes the application
    with an argument its own parser has never heard of. Argparse exits 2 before Qt is reached — on
    every machine, however healthy the display — and the AppImage reported `cannot start a GUI` and
    prescribed four apt packages on a desktop where `--demo` opened its window.
    """
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    argv = doctor._probe_argv()

    assert argv == [sys.executable, doctor.GUI_PROBE_FLAG]
    assert "-c" not in argv, "a frozen build has no interpreter to hand a -c to"


def test_an_ordinary_build_still_uses_an_interpreter() -> None:
    """The other half. A wheel or a checkout has a real `sys.executable`, and going through the
    launcher there would start the whole application to ask it one question."""
    monkeypatch_free = doctor._probe_argv()

    assert monkeypatch_free[:2] == [sys.executable, "-c"]


def test_the_launcher_answers_the_probe_flag() -> None:
    """The flag has to exist on the parser, or the frozen path above swaps one exit-2 for another.

    Run as a subprocess rather than by calling `run_gui_probe`, because a `QApplication` can exist
    once per process and this suite has already made one.
    """
    finished = subprocess.run(
        [sys.executable, "-m", "smartclock_monitor", doctor.GUI_PROBE_FLAG],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )

    assert finished.returncode == 0, finished.stderr[-500:]
    assert finished.stdout.startswith("PROBE "), (
        f"the launcher did not answer its own probe flag: {finished.stdout[:200]!r}"
    )


def test_the_probe_flag_is_not_advertised() -> None:
    """A diagnostic talking to itself. Listing it would describe an implementation detail as a
    feature, and it is the one argument nobody should ever type."""
    finished = subprocess.run(
        [sys.executable, "-m", "smartclock_monitor", "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert "gui-probe" not in finished.stdout


def test_stderr_that_is_not_qt_s_is_not_quoted_as_qt_s(monkeypatch: pytest.MonkeyPatch) -> None:
    """The half of #147 that turned a wrong diagnosis into a misleading one.

    The salvage took the last line of stderr whatever it was, so a probe that never reached Qt had
    somebody else's words attributed to the platform plugin — in the AppImage, a line of the
    probe's own source.
    """

    class Finished:
        returncode = 2
        stdout = ""
        stderr = 'smartclock-monitor: error: unrecognized arguments: -c print("PROBE")\n'

    monkeypatch.setattr("smartclock_monitor.doctor.subprocess.run", lambda *a, **k: Finished())
    probe = doctor._probe_gui()

    assert probe.started is False
    assert "saying nothing about Qt" in probe.detail, probe.detail
    assert "the probe exited 2" in probe.detail


def test_qt_s_own_complaint_is_still_quoted_as_qt_s(monkeypatch: pytest.MonkeyPatch) -> None:
    """Because the salvage is worth keeping: this line names the missing library."""

    class Finished:
        returncode = -6
        stdout = ""
        stderr = 'qt.qpa.plugin: Could not load the Qt platform plugin "xcb"\n'

    monkeypatch.setattr("smartclock_monitor.doctor.subprocess.run", lambda *a, **k: Finished())
    probe = doctor._probe_gui()

    assert "qt.qpa.plugin" in probe.detail
    assert "saying nothing about Qt" not in probe.detail


# ---- The machine the doctor exists for -----------------------------------------------------------


def _without_qt(tmp_path: Path) -> dict[str, str]:
    """An environment in which ``import PySide6`` raises, and nothing else is different.

    A stub package earlier on the path than the real one. `PYTHONPATH` is searched before
    site-packages, so this shadows the installed PySide6 for the child and for any child of its
    own — which matters, because the GUI probe is itself a subprocess.

    Deliberately an `ImportError` rather than a missing directory: that is what a broken wheel, a
    mismatched ABI or an absent `libGL` actually produces, and it is the case the doctor claims to
    survive.
    """
    stub = tmp_path / "no-qt"
    (stub / "PySide6").mkdir(parents=True)
    (stub / "PySide6" / "__init__.py").write_text(
        'raise ImportError("PySide6 is not importable here")', encoding="ascii"
    )
    return {**os.environ, "PYTHONPATH": str(stub)}


def test_the_stub_actually_hides_qt(tmp_path: Path) -> None:
    """Guarding the guard. If the stub does not shadow the real PySide6, the three tests below
    pass against a tree that would fail on a real machine — which is the failure mode this whole
    issue is about, reproduced inside its own gate."""
    finished = subprocess.run(
        [sys.executable, "-c", "import PySide6"],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env=_without_qt(tmp_path),
    )

    assert finished.returncode != 0, "the stub did not shadow the installed PySide6"
    assert "not importable" in finished.stderr


@pytest.mark.parametrize(
    ("argument", "expected"),
    [
        ("--doctor", "smartclock-monitor doctor"),
        ("--help", "usage: smartclock-monitor"),
        ("--list-ports", ""),
    ],
)
def test_it_still_answers_when_qt_cannot_be_imported(
    tmp_path: Path, argument: str, expected: str
) -> None:
    """#151. **The three arguments that must work on a machine with no working Qt.**

    `--doctor` says so itself: *"the machine that needs the doctor most is the one where importing
    PySide6 is itself the thing that fails"*, and `--list-ports` and `--help` carry the same claim.
    All three deferred their own Qt import and were defeated anyway, because `__main__` reached
    PySide6 at module scope through two view imports — so the process died on its own entry point
    before `main()` ran, and the report that would have named the missing library was never
    printed.

    Asserted on the **output**, not the exit status: `--doctor` legitimately exits 1 here, having
    found something to fix, and `--list-ports` exits 1 where there is no adapter. What must never
    happen is a traceback instead of a report.
    """
    finished = subprocess.run(
        [sys.executable, "-m", "smartclock_monitor", argument],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env=_without_qt(tmp_path),
    )

    assert "Traceback" not in finished.stderr, (
        f"{argument} died on an import instead of answering:\n{finished.stderr[-800:]}"
    )
    assert "ModuleNotFoundError" not in finished.stderr
    assert "ImportError" not in finished.stderr
    assert expected in finished.stdout, (
        f"{argument} printed nothing useful: {finished.stdout[:300]!r}"
    )


def test_the_doctor_names_qt_as_the_problem_rather_than_dying_of_it(tmp_path: Path) -> None:
    """And it has to be *useful*, not merely alive: the whole point is the line that says which
    thing is missing. A report that ran every other check and stayed silent about Qt would pass the
    test above while helping nobody."""
    finished = subprocess.run(
        [sys.executable, "-m", "smartclock_monitor", "--doctor"],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
        env=_without_qt(tmp_path),
    )

    assert "PySide6" in finished.stdout
    assert "[FAIL]" in finished.stdout, finished.stdout[-600:]
    # The checks after the failed one still run, which is #46's rule and is what makes the report
    # worth printing at all on this machine.
    for after in ("pyserial", "Serial ports", "dialout"):
        assert after in finished.stdout, f"the report stopped before {after!r}"


def test_the_entry_point_does_not_reach_qt_at_import_time() -> None:
    """The cause, named directly, rather than the consequence the tests above measure.

    Those three prove the symptom is gone. This one says *why*, and it is the check that fires the
    moment somebody adds a module-scope view import again — which is how the guarantee was lost the
    first time, silently, on a machine where nothing could notice.

    Cheap and exact: one interpreter, one import, one question. `CLAUDE.md` prefers a precise check
    that finds nothing today over a loose one that produces noise, and this is the precise one.
    """
    finished = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, smartclock_monitor.__main__; "
            "print('QT' if 'PySide6' in sys.modules else 'CLEAN')",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )

    assert finished.stdout.strip() == "CLEAN", (
        "importing the entry point pulled in PySide6. Every late Qt import below it is then "
        "decoration: --doctor, --help and --list-ports die on this import before main() runs. "
        "See #151."
    )
