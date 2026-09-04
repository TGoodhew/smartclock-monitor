"""Every cross-reference a document makes resolves to the thing it names (#41).

The counterpart to WinZ3805A's ``Test-DocumentReferences.ps1``, which had none here. This
repository keeps eleven documents that name each other, name files in the source tree, and name
test functions — and a rename breaks all of them silently, because nothing reads a document on the
way past.

**Paths named in prose are deliberately not checked**, and this was tried rather than assumed. A
first version flagged every backticked thing containing a slash, and nineteen of its twenty-one
findings were noise: branch names from `CLAUDE.md`'s examples (`feat/parser-status-screen`), files
named *because they are absent* (`docs/manual-qa.md`, and `tests/test_guide.py` in the gate map),
and paths written relative to a package root rather than the repository (`themes/qss.py`). Making
it right needed an allowlist that would want maintaining every time a document mentioned a
directory — and `CLAUDE.md` is explicit that a precise check finding nothing beats a loose one
producing noise, because a gate that cries wolf is one people learn to scroll past. Markdown links
and cited test names are unambiguous, so those are what is checked.

**The inherited documents are excluded, and that is not laziness.** ``requirements.md`` and
``adding-a-receiver.md`` are carried byte-exact from WinZ3805A and describe *that* tree: their paths
point at ``src/WinZ3805A/`` and their references are correct there. `provenance.md` records why they
may not be edited, so a gate that demanded their links resolve here would be demanding a change the
repository forbids.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: Carried from WinZ3805A byte-exact. See the module docstring.
INHERITED = {"requirements.md", "adding-a-receiver.md", "how-to-use.md"}

#: `[text](target)`, with the target not a URL, a mail link or a bare anchor.
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def documents() -> list[Path]:
    """Every document this repository wrote, in the order a reader meets them."""
    found = [ROOT / "README.md", ROOT / "CLAUDE.md", ROOT / "THIRD-PARTY-NOTICES.md"]
    found += sorted(p for p in (ROOT / "docs").glob("*.md") if p.name not in INHERITED)
    return [path for path in found if path.is_file()]


def local_targets(document: Path) -> list[str]:
    """The link targets in one document that name something in this repository."""
    targets = []
    for target in LINK.findall(document.read_text(encoding="utf-8")):
        target = target.strip()
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        targets.append(target.split("#", 1)[0])
    return [target for target in targets if target]


def test_there_are_documents_and_links_to_check() -> None:
    """Guard the guard. A glob that matched nothing, or a pattern that found no links, would make
    the assertion below pass while checking nothing — which is the failure this whole file is
    about."""
    found = documents()

    assert len(found) >= 8, f"only found {[p.name for p in found]}"
    assert sum(len(local_targets(path)) for path in found) >= 15, "no local links were parsed"


def test_every_local_link_resolves() -> None:
    """A link to a file that has been renamed or removed."""
    broken: list[str] = []
    for document in documents():
        for target in local_targets(document):
            if not (document.parent / target).resolve().exists():
                broken.append(f"{document.relative_to(ROOT)} -> {target}")

    assert not broken, "These links name something that is not there:\n  " + "\n  ".join(broken)


#: A backticked name that looks like a test function or a repository path. Documents cite both —
#: `ci-gate-map.md` names about fifteen test functions, `provenance.md` names files — and neither
#: is a markdown link, so the check above never sees them.
NAMED = re.compile(r"`([A-Za-z0-9_./-]+)`")


def cited_test_functions() -> dict[str, set[str]]:
    """Test function names a document names, and which documents name them."""
    found: dict[str, set[str]] = {}
    for document in documents():
        for name in NAMED.findall(document.read_text(encoding="utf-8")):
            if name.startswith("test_") and not name.endswith(".py"):
                found.setdefault(name, set()).add(document.name)
    return found


def test_every_test_function_a_document_names_exists() -> None:
    """`ci-gate-map.md` says which test carries which rule, and a renamed test would turn that map
    into fiction while every test still passed."""
    source = "\n".join(path.read_text(encoding="utf-8") for path in ROOT.glob("tests/test_*.py"))
    defined = set(re.findall(r"^def (test_\w+)", source, flags=re.MULTILINE))

    assert len(defined) > 100, f"only found {len(defined)} test functions — has the layout moved?"

    missing = {name: docs for name, docs in cited_test_functions().items() if name not in defined}
    assert not missing, "These tests are named by a document and do not exist:\n  " + "\n  ".join(
        f"{name} — named in {', '.join(sorted(docs))}" for name, docs in sorted(missing.items())
    )
