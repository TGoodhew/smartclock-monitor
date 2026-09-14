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


@pytest.mark.parametrize("mnemonic", sorted(set(inventory())))
def test_every_command_the_specification_lists_can_be_sent(mnemonic: str) -> None:
    """**Every one of them, with no exclusions left.**

    There were two. `:LED:ACTive` was §8.2's Safe setter, catalogued in #118's second batch.
    `*TST?` looked like a conflict — §8.2 lists it under a heading saying *"all queries plus
    non-disruptive actions"* while §8.3 and §10.9 give the same self-test a confirmation — and the
    resolution was that §8.3's table carries `*TST?` explicitly, with a sentence naming the
    consequence. The specific row wins over the general heading, and there was nothing to escalate.
    """
    assert catalogued(mnemonic), f"§8.2 lists {mnemonic} and the catalogue has no entry for it"


# ---- §8.3, the other half ------------------------------------------------------------------------

#: Where §8.3's confirmation table begins.
_CONFIRM_SECTION: Final = "### 8.3 Tier C"

#: Fragments in §8.3's first column that are not mnemonics: a wildcard, and the tails of a row that
#: abbreviates a family after naming its head — ``:GPS:SAT:TRAC:IGNore <PRN…> / :IGN:ALL /
#: :IGN:NONE``. Both forms are covered through the head of their own row.
_FRAGMENTS: Final[frozenset[str]] = frozenset(
    {
        ":STAT:*:ENABle",
        ":NTRansition",
        ":PTRansition",
        ":IGN:ALL",
        ":IGN:NONE",
        ":INCL:ALL",
        ":INCL:NONE",
    }
)

#: The one family §8.3 tiers that **neither implementation catalogues** — the serial port's own
#: settings. Excluded by name and with the question attached (#126): cataloguing them would put a
#: control in §10.11's console that drops the link it is sent over, and §8.3's own sentence says
#: the change *"persists through power cycling"*. §15's OQ-3 declined two of the family's other
#: nodes on related reasoning and said so; the six here have never been decided either way.
_UNDECIDED: Final[frozenset[str]] = frozenset(
    {
        ":SYST:COMM:SER1:BAUD",
        ":SYST:COMM:SER1:BITS",
        ":SYST:COMM:SER1:PARity",
        ":SYST:COMM:SER1:SBITs",
        ":SYST:COMM:SER1:PACE",
        ":SYST:COMM:SER1:FDUPlex",
        ":SYST:COMM:SER1:PRESet",
    }
)


def confirm_table() -> list[str]:
    """Every mnemonic in the first column of §8.3's table."""
    text = SPECIFICATION.read_bytes().decode("utf-8")
    start = text.index(_CONFIRM_SECTION)
    rows = [
        line
        for line in text[start : text.index("### 8.4", start)].splitlines()
        if line.startswith("|")
    ]
    found = []
    for row in rows:
        for quoted in re.findall(r"`([^`]+)`", row.split("|")[1]):
            # A parameter is written beside the mnemonic — `<s>`, `<PRN…>` — and is not part of it.
            # A keyword suffix is: `:GPS:POSition LAST` is its own entry in §8.1 for the reason
            # §8.3 gives it its own sentence.
            head = re.sub(r"\s*<[^>]*>\s*", "", quoted).strip()
            if head.startswith((":", "*")):
                found.append(head)
    return found


def test_the_confirmation_table_is_found_and_is_the_size_it_looks() -> None:
    found = confirm_table()

    assert len(found) == 36
    assert ":SYST:PRESet" in found
    assert "*TST?" in found


@pytest.mark.parametrize("mnemonic", sorted(set(confirm_table()) - _FRAGMENTS - _UNDECIDED))
def test_every_command_the_specification_confirms_is_catalogued_and_confirms(mnemonic: str) -> None:
    """**Tier and sentence, not just presence.** A command catalogued at the wrong tier is worse
    than one missing: it is a consequence a user is never warned about, on a control that looks
    like every other control."""
    from smartclock_device.commands.scpi_command import SafetyTier

    command = next((c for c in catalog.ALL if _same(c.mnemonic, mnemonic)), None)

    assert command is not None, f"§8.3 confirms {mnemonic} and the catalogue has no entry for it"
    assert command.tier is SafetyTier.CONFIRM, (
        f"{mnemonic} is §8.3's and is catalogued {command.tier}"
    )
    assert command.confirmation, f"{mnemonic} confirms with no sentence"


def test_the_undecided_family_is_still_undecided() -> None:
    """An exclusion that quietly became true would be a rule enforcing nothing. When the serial
    settings are catalogued — or ruled out for good — #126 says so and this test is what notices."""
    for mnemonic in _UNDECIDED:
        assert not catalogued(mnemonic), (
            f"{mnemonic} is catalogued now: settle #126 and drop it here"
        )


def _same(ours: str, theirs: str) -> bool:
    mine, is_query = nodes(ours)
    wanted, wanted_is_query = nodes(theirs)
    if is_query != wanted_is_query or len(mine) != len(wanted):
        return False
    return all(
        min(len(a), len(b)) >= 3 and a[: min(len(a), len(b))] == b[: min(len(a), len(b))]
        for a, b in zip(mine, wanted, strict=True)
    )
