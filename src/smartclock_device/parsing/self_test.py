"""What the receiver said about a self-test, and how far that can honestly be read (#53).

Never raises, per §11.1. An answer in a shape nobody has seen yields a result whose :attr:`code`
is ``None`` and whose :attr:`passed` is therefore ``None`` — rendered as ``—`` rather than guessed
at either way.
"""

from __future__ import annotations

from dataclasses import dataclass

from smartclock_device.models.self_test_subsystem import SelfTestSubsystem, by_keyword
from smartclock_device.parsing.scalars import parse_integer


@dataclass(frozen=True, slots=True)
class SelfTestResult:
    """One self-test outcome."""

    #: The subsystem the result belongs to, or ``None`` when it is unrecognised.
    subsystem: SelfTestSubsystem | None = None

    #: The receiver's code. Zero is a pass; anything else is undocumented.
    code: int | None = None

    #: The keyword exactly as the receiver echoed it.
    raw_subsystem: str | None = None

    @property
    def passed(self) -> bool | None:
        """Whether the receiver reported a pass.

        Only ``0`` is a pass, per the Z3801A guide's ``*TST?`` row: "0 = passed, non-zero is test
        specific code". ``None`` when nothing parsed, which is **not** the same as a failure.
        """
        return None if self.code is None else self.code == 0

    @staticmethod
    def parse(reply: str | None) -> SelfTestResult:
        """Parse ``:DIAG:TEST:RES?``'s answer, which is ``<code>,<subsystem>``.

        Observed on the live receiver as ``+0,ALL`` and ``+65536,GPS``. The leading sign is always
        present, and :func:`~smartclock_device.parsing.scalars.parse_integer` takes it.
        """
        if reply is None or not reply.strip():
            return SelfTestResult()

        parts = [part.strip() for part in reply.strip().split(",")]

        code = parse_integer(parts[0]) if parts else None
        keyword = parts[1] if len(parts) > 1 and parts[1] else None

        return SelfTestResult(subsystem=by_keyword(keyword), code=code, raw_subsystem=keyword)

    @staticmethod
    def parse_run(reply: str | None, subsystem: SelfTestSubsystem) -> SelfTestResult:
        """Parse the reply to ``:DIAG:TEST? <keyword>``, which is three integers.

        :param reply: The receiver's answer, observed as ``+0,+0,+0``.
        :param subsystem: The subsystem that was asked for — the reply does not name it.

        Only the first integer is read, because only the first is understood: it matches the code
        ``:DIAG:TEST:RES?`` reports afterwards. **What the other two mean is unknown**, and they
        are deliberately not surfaced — a number shown on a diagnostics page is read as meaningful,
        and these would be decoration.
        """
        parsed = SelfTestResult.parse(reply)

        return SelfTestResult(
            subsystem=subsystem,
            code=parsed.code,
            raw_subsystem=subsystem.keyword,
        )
