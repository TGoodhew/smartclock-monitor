"""Shared test fixtures and constants.

The pinned instant lives here because three test modules need the same one and a second copy is a
second thing to keep in step — the §7.4 rollover assertions are only meaningful against a clock
that does not move.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

#: A fixed "now" for tests that need one but are not about the rollover arithmetic.
NOW: Final = datetime(2026, 8, 31, 12, 0, 0, tzinfo=UTC)
