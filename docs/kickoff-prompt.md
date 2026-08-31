# Kickoff prompt

Paste this at the start of a session to pick the port up. It is short because
[`CLAUDE.md`](../CLAUDE.md) carries the standing context — the boundaries, the safety model,
the conventions — and Claude Code loads that automatically. Do not restate it here; two
copies of a rule is one copy that goes stale.

```text
Read CLAUDE.md, docs/provenance.md, and the port plan it links to.

Then work out from the tree which phase of the plan we are actually on — don't
assume, and don't trust the plan's ordering over what is on disk. Tell me which
phase you think it is and what you propose to do, before you start.

TASK: <what you want, or "continue the port from wherever it is">
```

Change only the last line day to day.

## If you are pasting into something that does not read `CLAUDE.md`

A plain API session, another tool, or a human — none of them get the standing context for
free. Give them `CLAUDE.md` and `docs/provenance.md` to read first, or paste this longer
form:

```text
You're working on smartclock-monitor: a Python 3.12 + PySide6 reimplementation of
WinZ3805A, which monitors and controls HP/Symmetricom SmartClock GPS-disciplined
oscillators (Z3805A, Z3801A, 58503A/B, 59551A, Z3816A) over RS-232.

READ FIRST, before proposing anything:
  - CLAUDE.md             the conventions, and the reasoning behind them
  - docs/provenance.md    what was copied from WinZ3805A, and what must not drift
  - docs/requirements.md  the specification. Every §-number, anywhere, refers to it.
  - The port plan, in the sibling repository:
    https://github.com/TGoodhew/WinZ3805A/blob/main/docs/porting-to-python-qt.md
    Eight phases, each with a done-condition. Work them in order.

Then work out from the tree which phase we are actually on — don't assume. Tell me
which phase you think it is and what you propose, before you start.

THE SPECIFICATION WINS. Where docs/requirements.md disagrees with me, with a
convention, or with a plausible idea, it wins — and you surface the conflict rather
than resolving it quietly. It still describes a WinUI 3 app shipped to the Microsoft
Store: that is deliberate, and it is not to be edited.

NON-NEGOTIABLE:
  - src/smartclock_device/ imports no Qt and no application code, ever.
  - No datetime.now / utcnow / time.time / time.monotonic. Inject a Clock.
  - The parser never raises (§11.1). Unparseable fields are None, rendered "—".
  - The command catalog is an allowlist (§8.1). The §8.4 exclusions do not exist
    as data. Never name one in code, tests, comments, commits or branch names.
  - tests/fixtures/ is irreplaceable hardware output and the parser's oracle.
    Never regenerate or reformat it. Write the assertion before the code.
  - build/palette/ is carried verbatim. Never reformat it.

HOW TO WORK:
  - Never commit to main. Branch, commit in revertable pieces, PR so CI runs,
    merge when green (rebase), delete the branch both sides, prune.
  - Before pushing: ruff check . && ruff format --check . && mypy && pytest
  - Test every new guard against a deliberate violation, then remove it and
    re-confirm green. A rule that matches nothing enforces nothing.

TASK: <what you want, or "continue the port from wherever it is">
```
