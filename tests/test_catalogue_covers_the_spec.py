"""Every query §8.2 lists is on the allowlist (#118).

**§10.11's Advanced Console is a picker over the allowlist, and there is no free-text path.** So a
command missing from `catalog.py` is not a command that is harder to send — it is one this
application cannot send at all, by anyone, ever. That makes an omission here invisible in exactly
the way a missing feature is not: nothing errors, nothing logs, the picker simply has fewer rows
than the manual has commands.

Thirty of them were missing, and nothing noticed for the length of the port. The audits that should
have found it compared documents and behaviour; a command-by-command diff of the two allowlists had
never been run (#118). This is that diff, run against the specification rather than against the
other repository, and run on every push.

**It reads §8.2 out of `docs/requirements.md`**, which is byte-exact, carried across unedited and
marked `-text` (`docs/provenance.md`). Parsing the specification in a test is unusual and is the
point: the list in that document is the authority, so the gate should fail when the *document* and
the catalogue disagree, whichever of them moved.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

from smartclock_device.commands import catalog

SPECIFICATION: Final = Path(__file__).resolve().parent.parent / "docs" / "requirements.md"

#: Where §8.2's inventory begins, spelled as the document spells it.
_SECTION: Final = "### 8.2 Tier S"

#: A mnemonic as the inventory writes one: a leading ``:`` or ``*``, then nodes and a possible
#: trailing ``?``. Parameters are written ``<PRN>`` beside the mnemonic and are not part of it.
_MNEMONIC: Final = re.compile(r"^[:*][A-Za-z:*]+\??$")

#: The two entries in §8.2 that are **not queries**, each excluded for a stated reason rather than
#: because the gate was inconvenient.
#:
#: ``*TST?`` is a query in spelling and a self-test in effect. §10.9 measured what running one costs
#: — the receiver leaves GPS lock and takes minutes to recover — and §8.3 gives `:DIAG:TEST?` a
#: confirmation for exactly that. §8.2 classing `*TST?` as Safe therefore contradicts §10.9's own
#: warning about the same operation, and cataloguing it as Safe would put an unconfirmed way to
#: unlock the receiver in the console beside the confirmed one. **Surfaced, not resolved** (#120).
#:
#: ``:LED:ACTive`` is §8.2's Safe *setter*, which is a different batch of work with a different
#: question attached (what, if anything, should drive the lamps).
_NOT_QUERIES: Final[frozenset[str]] = frozenset({"*TST?", ":LED:ACTive"})


def inventory() -> list[str]:
    """Every mnemonic in §8.2's fenced block, in the order the document lists them."""
    text = SPECIFICATION.read_bytes().decode("utf-8")
    section = text.index(_SECTION)
    opened = text.index("```", section) + 3
    block = text[opened : text.index("```", opened)]
    return [token for token in block.split() if _MNEMONIC.match(token)]


def nodes(mnemonic: str) -> tuple[list[str], bool]:
    head = mnemonic.strip().split(" ")[0]
    return [node.upper() for node in head.rstrip("?").lstrip(":").split(":")], head.endswith("?")


def catalogued(mnemonic: str) -> bool:
    """Whether the catalogue has this command, allowing for SCPI's long and short spellings.

    ``:DIAGnostic:LIFetime:COUNt?`` and ``:DIAG:LIF:COUN?`` are one command written two ways, and
    the specification and the catalogue do not always pick the same way. A node matches when one
    spelling is a prefix of the other and at least three characters long, which is SCPI's own rule
    for an abbreviation.
    """
    wanted, is_query = nodes(mnemonic)
    for command in catalog.ALL:
        theirs, theirs_is_query = nodes(command.mnemonic)
        if is_query != theirs_is_query or len(wanted) != len(theirs):
            continue
        if all(
            min(len(a), len(b)) >= 3 and a[: min(len(a), len(b))] == b[: min(len(a), len(b))]
            for a, b in zip(wanted, theirs, strict=True)
        ):
            return True
    return False


def test_the_inventory_is_found_and_is_the_size_it_looks() -> None:
    """Guarding the guard. A parser that found nothing would leave every assertion below passing
    while checking nothing, which is the failure mode `test_layering.py` guards itself against for
    the same reason."""
    found = inventory()

    assert len(found) == 93
    assert found[0] == "*IDN?"
    assert ":PTIM:TCOD?" in found


@pytest.mark.parametrize("mnemonic", sorted(set(inventory()) - _NOT_QUERIES))
def test_every_query_the_specification_lists_can_be_sent(mnemonic: str) -> None:
    assert catalogued(mnemonic), f"§8.2 lists {mnemonic} and the catalogue has no entry for it"


def test_the_exclusions_are_still_absent_and_still_have_reasons() -> None:
    """An exclusion that quietly became true would be a rule enforcing nothing. Both of these are
    meant to be added later — ``*TST?`` once #120 settles its tier, ``:LED:ACTive`` with the rest of
    §8.2's setters — and when they are, this test is what says so."""
    for mnemonic in _NOT_QUERIES:
        assert not catalogued(mnemonic), (
            f"{mnemonic} is catalogued now: take it out of _NOT_QUERIES and let the gate cover it"
        )
