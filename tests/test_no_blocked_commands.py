"""CI gate for §8.4: no excluded command is named anywhere but the one file that holds the patterns.

The port of ``build/Test-NoBlockedCommands.ps1``, and — per CLAUDE.md — landed in the same change
as ``blocked.py`` rather than after it. Until this existed, ``docs/provenance.md`` was the only
thing saying the two repositories' lists must not diverge.

§8.4 requires that the commands it excludes are absent from the application in every user-visible
sense: not in the catalog, a picker, an autocomplete, help text, or any log a user can read. They
are not entries carrying a flag; they do not exist as data. CLAUDE.md extends the same rule to
comments, tests, fixtures, commit messages and branch names.

**This file takes its tokens from the patterns rather than restating them.** That is the whole
mechanism: a gate with its own copy of the list would be a second place for the list to live, which
is the thing being prevented. It is also why the check keeps working when the list changes.

The receiver accepts commands that can render it unusable, and one bricked by these is bricked
either way. This is the highest-value gate in the set.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

# The one sanctioned reader of the patterns. Importing the private name is the point: nothing else
# in the tree may, and the gate is the exception that proves it.
from smartclock_device.commands.blocked import _PATTERNS, is_blocked

ROOT: Final = Path(__file__).resolve().parent.parent

#: The one file permitted to name them.
PERMITTED: Final = ROOT / "src" / "smartclock_device" / "commands" / "blocked.py"

#: Directories worth scanning. Everything a user or a maintainer reads.
SCANNED_DIRECTORIES: Final = ("src", "tests", "build", ".github", "docs")

#: Extensions worth scanning.
SCANNED_SUFFIXES: Final = frozenset(
    {".py", ".md", ".toml", ".yml", ".yaml", ".txt", ".json", ".ps1", ".cfg", ".ini"}
)

#: The inherited specification is exempt, and only it.
#:
#: §8.4 is *in* ``docs/requirements.md`` — it is the section that names these commands in order to
#: exclude them, which is why the list can be ported at all. The file is carried byte-exact from
#: WinZ3805A and CLAUDE.md forbids editing it, so a gate that failed on it would be a gate nobody
#: could make pass. `docs/provenance.md` records why it is byte-exact.
EXEMPT: Final = frozenset({ROOT / "docs" / "requirements.md"})

#: A command-shaped string as it appears in prose or code: one or more colon-separated nodes, with
#: an optional leading colon or asterisk and an optional trailing question mark.
#:
#: **A candidate must carry a colon** (or lead with an asterisk, for IEEE 488.2 common commands).
#: :func:`_is_command_shaped` enforces that, and it is the whole difference between a usable gate
#: and one nobody reads.
#:
#: The reason is measured rather than assumed. The categorical pattern in ``blocked.py`` matches a
#: bare node name — its path prefix is optional — so an earlier version of this scan offered every
#: word in the tree as a candidate. Six ordinary English words in this project's own docstrings
#: came back blocked: the undocumented node names are short, and short uppercase-insensitive
#: tokens collide with prose. Every one of the six had no colon in it.
#:
#: CLAUDE.md: a gate that cries wolf is one people learn to scroll past. This is the same rule the
#: PowerShell original applies, and the same trade it accepts — **the known limit is that a bare
#: node name written in prose with no colon is not caught.** A command in this codebase is always
#: written with one.
_COMMAND_SHAPED: Final = re.compile(r"[:*]?[A-Za-z][A-Za-z0-9]*(?::[A-Za-z][A-Za-z0-9]*)*\??")

#: The categorical pattern, which is set-only by design.
#:
#: §8.5 enables the query form of a small subset as an opt-in read-only card, so those nodes are
#: allowed to be named as queries and refused only as setters. The pattern encodes that itself with
#: a leading negative lookahead, so the gate needs no special case — this index exists only so the
#: test below can name the pattern it is asserting about.
_QUERY_ONLY_PATTERN_INDEX: Final = len(_PATTERNS) - 1


def _example_matching(pattern: re.Pattern[str]) -> str:
    """A concrete string that the given pattern matches.

    Built by expanding the pattern's own source rather than by typing an example out, which is what
    keeps every excluded command out of this file while still letting the gate be tested against a
    real violation. If the patterns change, the examples change with them; if the expansion breaks,
    the generated string stops matching and
    :func:`test_every_pattern_can_be_rendered_into_something_it_matches` says so.

    Hand-written rather than walking ``re``'s parse tree, because that lives behind a private
    module whose name has already changed once and which ships no type stubs. This handles the
    small grammar these four patterns actually use, and refuses anything else loudly.
    """
    text, at = _expand(pattern.pattern, 0)
    assert at == len(pattern.pattern), "The expansion did not consume the whole pattern."
    return text


def _expand(source: str, at: int, *, stop_at_bar: bool = False) -> tuple[str, int]:
    """Expand a sequence, preferring the fullest bounded spelling.

    An optional group is emitted once — that is what supplies the optional leading colon, without
    which a generated example would not even be command-shaped and would prove nothing. An
    unbounded repeat is emitted its minimum number of times, since one is enough to match.
    """
    out: list[str] = []

    while at < len(source):
        character = source[at]

        if character in "^$":
            at += 1
            continue

        if character == ")" or (stop_at_bar and character == "|"):
            break

        if character == "(":
            piece, at = _expand_group(source, at)
        elif character == "[":
            piece, at = _expand_class(source, at)
        elif character == "\\":
            piece, at = source[at + 1], at + 2
        else:
            piece, at = character, at + 1

        piece, at = _apply_quantifier(piece, source, at)
        out.append(piece)

    return "".join(out), at


def _expand_group(source: str, at: int) -> tuple[str, int]:
    """Expand ``(...)``, ``(?:...)``, and drop ``(?!...)`` / ``(?=...)``."""
    assert source[at] == "("
    at += 1

    if source.startswith("?:", at):
        at += 2
    elif source.startswith("?!", at) or source.startswith("?=", at):
        # A lookaround contributes no characters, so its body is skipped rather than expanded —
        # it may legitimately contain constructs (a negated character class, for one) that the
        # emitting path refuses. The one negative lookahead in these patterns forbids a question
        # mark, and nothing here emits one outside an escape.
        return "", _skip_group(source, at - 1)

    # The first alternative is enough; every branch matches by construction.
    chosen, at = _expand(source, at, stop_at_bar=True)
    depth = 0
    while at < len(source):
        if source[at] == "|" and depth == 0:
            _, at = _expand(source, at + 1, stop_at_bar=True)
            continue
        if source[at] == ")":
            break
        raise AssertionError(f"Unexpected character {source[at]!r} while expanding a group.")

    assert at < len(source) and source[at] == ")", "Unclosed group in a pattern."
    return chosen, at + 1


def _skip_group(source: str, at: int) -> int:
    """The index just past the ``)`` closing the group that starts at ``at``."""
    assert source[at] == "("
    depth = 0
    index = at
    while index < len(source):
        character = source[index]
        if character == "\\":
            index += 2
            continue
        if character == "[":
            index = source.index("]", index + 1) + 1
            continue
        if character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise AssertionError("Unclosed lookaround in a pattern.")


def _expand_class(source: str, at: int) -> tuple[str, int]:
    """Expand ``[...]`` to its first member."""
    assert source[at] == "["
    close = source.index("]", at + 1)
    body = source[at + 1 : close]
    assert body and not body.startswith("^"), "Negated character class in a pattern."
    return body[0], close + 1


def _apply_quantifier(piece: str, source: str, at: int) -> tuple[str, int]:
    if at >= len(source):
        return piece, at
    match source[at]:
        case "?":
            return piece, at + 1  # optional: take it, for the fullest spelling
        case "*":
            return "", at + 1  # unbounded: the minimum is none
        case "+":
            return piece, at + 1  # unbounded: the minimum is one
        case _:
            return piece, at


def _is_command_shaped(candidate: str) -> bool:
    """Whether a candidate is written the way a command is written, rather than the way a word is.

    See the note on :data:`_COMMAND_SHAPED`. A colon anywhere, or a leading asterisk.
    """
    return ":" in candidate or candidate.startswith("*")


def _scanned_files() -> list[Path]:
    """Everything a user or a maintainer reads, minus the one permitted file and the exemption."""
    files: list[Path] = []
    for directory in SCANNED_DIRECTORIES:
        base = ROOT / directory
        if not base.is_dir():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SCANNED_SUFFIXES:
                continue
            resolved = path.resolve()
            if resolved == PERMITTED.resolve() or resolved in {e.resolve() for e in EXEMPT}:
                continue
            files.append(path)

    # The repository-root documents share the rule; a README naming one would be as public as a
    # picker.
    files.extend(path for path in ROOT.glob("*.md") if path.is_file())
    files.extend(path for path in ROOT.glob("*.toml") if path.is_file())
    return files


def _display(path: Path) -> str:
    """Repository-relative where possible, absolute otherwise — the deliberate-violation tests
    scan files in a temporary directory that is not under the repository root."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def scan(paths: list[Path]) -> list[str]:
    """Every occurrence of an excluded command outside the permitted file, as ``path:line``.

    Runs the patterns themselves over every command-shaped string, rather than deriving tokens and
    re-implementing the matching. That is what keeps the list in one place: this file asks
    ``blocked.py`` for a verdict exactly as the application does.
    """
    hits: list[str] = []

    for path in paths:
        try:
            text = path.read_bytes().decode("latin-1")
        except OSError:  # pragma: no cover - unreadable file is not a §8.4 finding
            continue

        for number, line in enumerate(text.splitlines(), start=1):
            for match in _COMMAND_SHAPED.finditer(line):
                candidate = match.group(0)
                if _is_command_shaped(candidate) and is_blocked(candidate):
                    hits.append(f"{_display(path)}:{number}")

    return hits


# ---- The gate --------------------------------------------------------------------------------


def test_the_patterns_file_exists_and_is_the_only_permitted_one() -> None:
    assert PERMITTED.is_file()


def test_there_are_patterns_to_enforce() -> None:
    """Guarding the guard. A patterns tuple that had been emptied would make every check below
    pass while enforcing nothing — the exact silent failure CLAUDE.md warns about."""
    assert len(_PATTERNS) >= 4


def test_every_pattern_can_be_rendered_into_something_it_matches() -> None:
    """The gate below is only as good as this: if the walk stops producing matching strings, the
    deliberate-violation tests silently start testing nothing."""
    for pattern in _PATTERNS:
        example = _example_matching(pattern)
        assert pattern.match(example), "A pattern no longer matches its own rendered example."
        assert is_blocked(example) is True


def test_the_scan_reaches_a_meaningful_number_of_files() -> None:
    """A glob that matched nothing would leave the gate passing while scanning an empty set."""
    assert len(_scanned_files()) > 30


def test_no_excluded_command_is_named_anywhere_else() -> None:
    """The gate itself."""
    hits = scan(_scanned_files())

    assert not hits, (
        "§8.4 exclusion named outside src/smartclock_device/commands/blocked.py at: "
        + ", ".join(sorted(set(hits)))
    )


# ---- The gate, tested against a deliberate violation -----------------------------------------


@pytest.mark.parametrize("index", range(len(_PATTERNS)))
def test_the_gate_catches_a_deliberate_violation(index: int, tmp_path: Path) -> None:
    """CLAUDE.md's rule: a rule that matches nothing is a rule that enforces nothing, and it fails
    silently — which is worse than no rule, because it reads as coverage.

    The violation is rendered **from the patterns themselves**, so this cannot be satisfied by a
    hand-written string that happens to look right, and no excluded command is typed into this
    file. Once per pattern, because a gate that catches three of four is a gate that misses one.
    """
    offender = tmp_path / "offender.py"
    offender.write_text(f'COMMAND = "{_example_matching(_PATTERNS[index])}"\n')

    hits = scan([offender])

    assert hits, "The gate did not catch a violation rendered from its own patterns."


def test_the_gate_is_quiet_once_the_violation_is_removed(tmp_path: Path) -> None:
    """The other half of the same rule: confirm green after the violation goes."""
    innocent = tmp_path / "innocent.py"
    innocent.write_text('COMMAND = ":SYST:STAT?"\n')

    assert scan([innocent]) == []


def test_the_categorical_case_is_refused_as_a_setter_and_allowed_as_a_query(tmp_path: Path) -> None:
    """§8.5 enables the query form of a small subset as an opt-in read-only card, so the
    categorical pattern is set-only by design. A gate that ignored the question mark would block a
    feature the specification asks for two sections later.

    The set form has no way to be safe: those nodes are undocumented, so what they write is
    unknown, and §8.4 gives them no override.
    """
    setter = _example_matching(_PATTERNS[_QUERY_ONLY_PATTERN_INDEX])

    as_setter = tmp_path / "setter.py"
    as_setter.write_text(f'COMMAND = "{setter}"\n')

    as_query = tmp_path / "query.py"
    as_query.write_text(f'COMMAND = "{setter}?"\n')

    assert scan([as_setter]), "The categorical set form must be refused."
    assert scan([as_query]) == [], "§8.5's read-only query form must survive."


# ---- The predicate ----------------------------------------------------------------------------


@pytest.mark.parametrize("index", range(len(_PATTERNS)))
def test_the_predicate_refuses_what_the_patterns_name(index: int) -> None:
    """Rendered from the patterns, for the same reason as the gate test above."""
    example = _example_matching(_PATTERNS[index])

    assert is_blocked(example) is True
    assert is_blocked(example.lower()) is True, "Case is ignored."
    assert is_blocked(example.upper()) is True, "Case is ignored."
    assert is_blocked(example.lstrip(":")) is True, "The leading colon is optional."


def test_the_predicate_allows_an_ordinary_command() -> None:
    """The other direction. A predicate that returned True for everything would pass every test
    above and make the application useless."""
    for command in (":SYST:STAT?", "*IDN?", ":SYNC:TINT?", ":GPS:REF:ADEL", ":PTIM:TCOD?"):
        assert is_blocked(command) is False


@pytest.mark.parametrize("candidate", [None, "", "   "])
def test_nothing_is_not_blocked(candidate: str | None) -> None:
    """Not commands, and reporting them as excluded would be a false positive on the one path that
    must never cry wolf."""
    assert is_blocked(candidate) is False


def test_an_argument_cannot_smuggle_a_command_past_the_predicate() -> None:
    """The header is what is tested, so appending a parameter must not change the verdict."""
    example = _example_matching(_PATTERNS[0])

    assert is_blocked(f"{example} 1") is True
    assert is_blocked(f"  {example}  ") is True


def test_the_patterns_are_not_reachable_as_data() -> None:
    """§8.4: they do not exist as data. The module exports a verdict, not a list.

    This is the architectural assertion rather than a behavioural one — it checks that the only
    public name is the predicate, so nothing can bind to the patterns, enumerate them, or render
    them into a picker.
    """
    import smartclock_device.commands.blocked as module

    public = [name for name in vars(module) if not name.startswith("_")]

    assert "is_blocked" in public
    assert all(
        "PATTERN" not in name.upper() and "BLOCKED_COMMAND" not in name.upper() for name in public
    ), f"Something enumerable is exported from blocked.py: {public}"
