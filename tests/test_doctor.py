"""``--doctor``: the check that runs before anything works.

Its whole value is on a machine where something is missing, which is by definition not this one.
So the checks are exercised through their own seams rather than by hoping the developer's laptop is
broken in an interesting way.
"""

from __future__ import annotations

import os

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
    machine rather than only on one without them installed."""
    from PySide6.QtWidgets import QApplication

    if QApplication.instance() is None:
        QApplication([])

    finding = doctor._fonts()

    assert finding.ok, finding.detail
    assert "Cascadia Mono" in finding.detail
