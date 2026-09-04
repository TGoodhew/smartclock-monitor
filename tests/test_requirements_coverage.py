"""§13's priority table, walked by CI instead of by hand.

Issue #14 was an audit: someone read §13's table, checked each row against the code, and wrote down
what they found. That is worth doing once and worthless afterwards — the tree moves and the audit
does not, and the only way to know whether it still holds is to do it again.

**So the table is parsed from the specification and the suite is asked to account for every row.**
A P0 is accounted for when some test names it. Where a criterion cannot honestly be automated, it
is listed below with the reason, which is the same discipline the exclusions use: the exemption is
data, in one place, rather than an absence nobody can see.

This does not check that a test is *correct* — nothing can. It checks that every P0 has somewhere
to look, which is what the audit actually established and what quietly stops being true.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPECIFICATION = ROOT / "docs" / "requirements.md"
TESTS = Path(__file__).resolve().parent

#: Criteria no test can honestly assert, and why. Each needs a person, a desktop, or hardware.
#:
#: **Listed rather than omitted.** An untestable criterion that is simply absent from the suite is
#: indistinguishable from one nobody thought about, which is exactly the state #14 was opened to
#: get out of.
MANUAL: dict[str, str] = {
    "P0-15": (
        "Struck by the specification itself (#15, #39), and D2 settled the Store as not a goal "
        "of this repository at all."
    ),
}

#: Criteria a test names but only partly covers, with what is left to a person.
#:
#: These still have to be named by a test — the entry here records what that test does *not* reach,
#: so a reader is not misled into thinking the row is fully closed.
PARTIAL: dict[str, str] = {
    "P0-14": (
        "The arithmetic is gated — §7.2's backoff and the three-failures rule. The clause itself, "
        "'Disconnected within 10 s and reconnected within 45 s of replug', needs an adapter and a "
        "hand. Verified that way on the bench Z3805A."
    ),
    "P0-16": (
        "Three of §9.12's criteria are automated in test_accessibility.py: A11Y-3, A11Y-5 and "
        "A11Y-12. A11Y-4 and A11Y-8 concern high contrast, which D3 settled as not shipped. The "
        "rest need a person: tab order against visual reading order, 200 % text scaling, focus "
        "contrast, live-region announcements, automation trees, animation-disabled."
    ),
    "P0-17": (
        "The parity half holds and is gated — every token defined in every theme. The clause "
        "naming a *HighContrast* dictionary is withdrawn by D3, which settled that this port "
        "ships Light and Dark only; see docs/divergences.md."
    ),
    "P0-7": (
        "Automated *better* than the specification asks. It says to search the built binary's "
        "string table by hand; test_no_blocked_commands.py scans the whole tree on every run."
    ),
}


#: P1 rows this port does **not** ship, and the decision that settled each.
#:
#: §13 is WinZ3805A's table and it is inherited byte-exact, so it lists features D5 removed. An
#: unshipped requirement is not an unmet one when the decision is written down — but it has to be
#: written down *here*, beside the tier that would otherwise demand a test, or "no test names it"
#: and "we decided not to build it" are indistinguishable.
#:
#: Every entry cites the document that decided it. `docs/divergences.md` is the authority.
NOT_SHIPPED: dict[str, str] = {
    "P1-9": "D5 — no notification area, so no holdover/lock-loss notification. divergences.md.",
    "P1-10": "D5 — no system tray icon. divergences.md.",
    "P1-11": (
        "Not offered — the system accent opt-in has nothing to read on Linux, and the brand accent "
        "is always used. divergences.md."
    ),
    "P1-13": "D5 — no taskbar overlay badge. divergences.md.",
    "P1-14": (
        "D5 — close-to-tray and start-minimised both rested on a tray icon to come back to, and "
        "§10.3.1's own argument then settles the close: the window closes and polling stops."
    ),
}


def p0_identifiers() -> list[str]:
    """Every P0 in §13's table, in the order the specification lists them.

    Read from the specification rather than kept here, because a list kept here would be a second
    copy of §13 and would drift from it silently — which is the failure this file is about.
    """
    text = SPECIFICATION.read_text(encoding="latin-1")
    section = text[text.index("## 13. Requirements by Priority") :]
    section = section[: section.index("### P1")]
    # Struck rows are written ~~P0-15~~; the identifier is still the row's name.
    return list(dict.fromkeys(re.findall(r"\|\s*~?~?(P0-\d+)~?~?\s*\|", section)))


def p1_identifiers() -> list[str]:
    """Every P1 in §13's table. Read from the specification, for the same reason as the P0s."""
    text = SPECIFICATION.read_text(encoding="latin-1")
    section = text[text.index("### P1") :]
    section = section[: section.index("### P2")]
    return list(dict.fromkeys(re.findall(r"\|\s*~?~?(P1-\d+)~?~?\s*\|", section)))


def named_by_tests(tier: str = "P0") -> dict[str, set[str]]:
    """Which test files name each requirement in a tier."""
    found: dict[str, set[str]] = {}
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        source = path.read_text(encoding="utf-8")
        for code in re.findall(rf"\b{tier}-\d+\b", source):
            found.setdefault(code, set()).add(path.name)
    return found


def test_the_table_is_found_and_is_the_size_it_should_be() -> None:
    """Guard the guard. A parse that returned nothing would make every assertion below vacuous, and
    §13 has twenty P0 rows — nineteen live and one struck."""
    identifiers = p0_identifiers()

    assert len(identifiers) == 20, f"parsed {len(identifiers)} P0 rows: {identifiers}"
    assert identifiers[0] == "P0-1"
    assert "P0-15" in identifiers, "the struck row is still a row, and its exemption is recorded"


def test_every_p0_is_accounted_for() -> None:
    """The audit, re-run. Every P0 is either named by a test or listed as manual with a reason."""
    named = named_by_tests()
    unaccounted = [code for code in p0_identifiers() if code not in named and code not in MANUAL]

    assert not unaccounted, (
        "These P0 criteria are named by no test and are not listed as manual:\n  "
        + "\n  ".join(unaccounted)
        + "\n\nAdd the identifier to the docstring of the test that gates it, or add it to "
        "MANUAL with the reason it cannot be automated."
    )


def test_nothing_is_listed_as_manual_and_also_gated() -> None:
    """An entry in both lists is one nobody has re-read: the exemption outlived the reason for it,
    and the reason is what makes an exemption honest rather than a hole."""
    named = named_by_tests()
    both = sorted(set(MANUAL) & set(named))

    assert not both, f"{both} are gated by a test and still listed as manual"


def test_every_exemption_says_why() -> None:
    """A reason short enough to be a shrug is not a reason."""
    for code, reason in {**MANUAL, **PARTIAL}.items():
        assert len(reason) > 40, f"{code}'s reason is too thin to be one: {reason!r}"


def test_the_partial_list_names_only_gated_criteria() -> None:
    """PARTIAL describes what a test does *not* reach, so it is meaningless for a criterion with no
    test at all — that one belongs in MANUAL."""
    named = named_by_tests()
    stray = sorted(code for code in PARTIAL if code not in named)

    assert not stray, f"{stray} are listed as partly covered but no test names them"


# ---- P1, added by the #22 audit ------------------------------------------------------------------
#
# The P0 half above came from #14 and stops at `### P1`. The audit found the tier below it
# unwatched: of fourteen P1 rows, two were named by a test — while most of the features are built,
# tested and shipped. So "no test names it" carried no information at P1, and the four rows D5
# removed were indistinguishable from four nobody had got to.


def test_the_p1_table_is_found_and_is_the_size_it_should_be() -> None:
    """Guard the guard, as the P0 half does: a parse returning nothing makes the rest vacuous."""
    identifiers = p1_identifiers()

    assert len(identifiers) == 14, f"parsed {len(identifiers)} P1 rows: {identifiers}"
    assert identifiers[0] == "P1-1"
    assert identifiers[-1] == "P1-14"


def test_every_p1_is_accounted_for() -> None:
    """Every P1 is either named by a test or recorded as not shipped, with the decision.

    Weaker than the P0 rule by design: a P0 that no test names is a hole, while a P1 that no test
    names may simply be a feature this port decided against. What is not acceptable is the two
    being indistinguishable.
    """
    named = named_by_tests("P1")
    unaccounted = [
        code for code in p1_identifiers() if code not in named and code not in NOT_SHIPPED
    ]

    assert not unaccounted, (
        "These P1 criteria are named by no test and are not recorded as unshipped:\n  "
        + "\n  ".join(unaccounted)
        + "\n\nName the identifier in the docstring of the test that gates it, or add it to "
        "NOT_SHIPPED with the decision that removed it."
    )


def test_the_unshipped_list_names_a_decision_for_every_row() -> None:
    """An exemption is only worth having if it says who decided and where it is written down.

    **Not "no test names it".** A test that asserts a feature is *absent* is exactly what should
    gate a divergence — `test_closing.py` names P1-9 while asserting there is no notification —
    so being both exempted and named is right rather than contradictory. What the list must not
    contain is a bare identifier with no reason beside it.
    """
    for code, reason in NOT_SHIPPED.items():
        assert len(reason) > 40, f"{code} is exempted without a reason worth reading"
        assert "divergences.md" in reason or "§" in reason, (
            f"{code}'s exemption cites no document — say which decision removed it"
        )
