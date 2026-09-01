"""Every enum a page shows, rendered as words.

``member.name.replace("_", " ").title()`` was written at fourteen call sites, and it lower-cases
acronyms. The Position page showed the height datum as **"Msl"** — not a word, not the
abbreviation, and not something a user can look up. ``GPS`` became ``Gps``.

The check below is exhaustive over the model's enums rather than over a list kept here, so an enum
added later is covered without anyone remembering to add it.
"""

from __future__ import annotations

import enum
import inspect

import pytest

from smartclock_device.models import position, receiver_status, satellite
from smartclock_monitor.views.wording import ACRONYMS, humanise, humanise_name

MODULES = (receiver_status, position, satellite)


def every_member() -> list[tuple[str, enum.Enum]]:
    found: list[tuple[str, enum.Enum]] = []
    for module in MODULES:
        for kind in vars(module).values():
            if (
                inspect.isclass(kind)
                and issubclass(kind, enum.Enum)
                and kind.__module__ == module.__name__
            ):
                found.extend((kind.__name__, member) for member in kind)
    return found


def test_the_walk_finds_the_enums() -> None:
    """A sweep that found nothing would pass while enforcing nothing."""
    names = {name for name, _ in every_member()}

    assert "HeightDatum" in names
    assert "TimeScale" in names
    assert len(every_member()) > 30


@pytest.mark.parametrize(("owner", "member"), every_member(), ids=lambda v: getattr(v, "name", v))
def test_no_acronym_is_lower_cased(owner: str, member: enum.Enum) -> None:
    """The defect, stated as a rule. ``MSL`` and ``GPS`` are the receiver's vocabulary and the
    specification's, and a page that spells them as words spells them wrong."""
    rendered = humanise(member)

    for word in member.name.split("_"):
        if word.upper() in ACRONYMS:
            assert word.upper() in rendered.split(), (
                f"{owner}.{member.name} renders as {rendered!r}, "
                f"which has lost the acronym {word.upper()}"
            )


@pytest.mark.parametrize(("owner", "member"), every_member(), ids=lambda v: getattr(v, "name", v))
def test_nothing_renders_as_an_identifier(owner: str, member: enum.Enum) -> None:
    """No underscores, and nothing SHOUTING. ``VALID_REDUCED`` reached the main window's most
    important row as ``Valid_Reduced``, which is an identifier rather than a state."""
    rendered = humanise(member)

    assert "_" not in rendered, f"{owner}.{member.name} renders as {rendered!r}"
    assert rendered.strip(), f"{owner}.{member.name} renders as nothing"
    if rendered.upper() not in ACRONYMS:
        assert rendered != rendered.upper() or len(rendered) <= 4, (
            f"{owner}.{member.name} renders as {rendered!r}, which is still shouting"
        )


def test_the_known_mangled_cases() -> None:
    """The four that were visibly wrong on screen, pinned by name."""
    assert humanise_name("MSL") == "MSL"
    assert humanise_name("GPS_ELLIPSOID") == "GPS Ellipsoid"
    assert humanise_name("LOCAL_GPS") == "Local GPS"
    assert humanise_name("SYNCHRONIZED_TO_UTC") == "Synchronized to UTC"


def test_a_missing_value_is_the_em_dash_everything_else_uses() -> None:
    """§11.1: what could not be read renders as ``—``. A state nobody read and a field nobody read
    look alike here because they are alike."""
    assert humanise(None) == "—"
