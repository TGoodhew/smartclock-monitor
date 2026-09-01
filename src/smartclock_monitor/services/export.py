"""Getting values out: §9.7.4's copy layer and `Ctrl+E` export.

**A copied value is data leaving the application, not a readout.** §9.5.3 renders a negative with
U+2212 MINUS SIGN and separates the unit with a hair space, both of which are right on screen and
wrong in a spreadsheet — a cell handed either gets *text* rather than a number, silently, and every
formula over the column then returns zero. So the copy path undoes both.

**A missing value copies as nothing at all.** §11.1's em dash is the *absence* of data, and pasting
a dash into a sheet would make it look like a reading that happened to be a dash.

**Nothing unique lives in the copy layer**, which is what makes it safe to have. Every value it
copies is on screen and every table it copies is the document `Ctrl+E` already writes, so a user
who never discovers the right-click loses a keystroke and no capability.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

#: §11.1's rendering of a field the receiver did not answer.
EM_DASH = "\N{EM DASH}"

#: §9.5.3 rule 4's sign, and rule 3's separator.
MINUS_SIGN = "\N{MINUS SIGN}"
HAIR_SPACE = "\N{HAIR SPACE}"

#: A number, optionally followed by a unit. The unit is dropped on copy: it is a separate element
#: on screen (§9.5.3 rule 3) and it is a separate column in a sheet, so carrying it into the cell
#: would make the cell text.
_NUMBER_AND_UNIT = re.compile(r"^([+-]?\d[\d,]*(?:\.\d+)?(?:[eE][+-]?\d+)?)(?:\s+\S.*)?$")


@runtime_checkable
class CsvExportSource(Protocol):
    """A page that can hand over what it is showing.

    ``Ctrl+E`` asks the *current* page rather than the window: §9.7.4 puts Export in the title bar
    and scopes it to the view, because "export" on a page of live readings and "export" on a trend
    of 70,000 rows are the same word for two very different documents.
    """

    def csv_rows(self) -> Sequence[Sequence[str]]:
        """Header row first, then the data. Empty means there is nothing to export."""
        ...


def to_machine_text(text: str) -> str:
    """One on-screen value, as it should leave the application.

    Undoes §9.5.3's typesetting: U+2212 becomes an ordinary hyphen-minus, the hair space goes, the
    thousands separators go, and a unit is dropped. An em dash — §11.1's *no value* — becomes an
    empty string rather than a dash, because a dash in a cell reads as a reading.

    **Raw device text is exempt and must not be passed through here.** §9.5.3 rule 4 says so: what
    the receiver emitted is reproduced verbatim, and "correcting" its sign would make the copy
    disagree with the transcript it came from.
    """
    stripped = text.strip()
    if not stripped or stripped == EM_DASH:
        return ""

    plain = stripped.replace(MINUS_SIGN, "-").replace(HAIR_SPACE, " ")

    matched = _NUMBER_AND_UNIT.match(plain)
    if matched is None:
        return plain

    return matched.group(1).replace(",", "")


def to_csv(rows: Sequence[Sequence[str]]) -> str:
    """Render rows as CSV.

    ``\\r\\n`` line endings, which is what RFC 4180 says and what every spreadsheet on every
    platform reads without being asked. ``newline=""`` on the buffer for the same reason the
    standard library insists on it: without it the writer's endings are translated again on
    Windows and every row gains a blank one.
    """
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    for row in rows:
        writer.writerow(list(row))
    return buffer.getvalue()


def machine_rows(rows: Sequence[Sequence[str]], *, header: bool = True) -> list[list[str]]:
    """Put every cell through :func:`to_machine_text`, leaving the header alone.

    The header is words and stays words; the body is numbers and stops being typeset.
    """
    out: list[list[str]] = []
    for index, row in enumerate(rows):
        if header and index == 0:
            out.append([str(cell) for cell in row])
        else:
            out.append([to_machine_text(str(cell)) for cell in row])
    return out


def suggested_filename(view: str, stamp: str) -> str:
    """``smartclock-timing-20260831-231726.csv``.

    The view is in the name because §9.7.4 scopes Export to the current page, and a folder of files
    called ``export.csv`` is a folder nobody can use a week later.
    """
    safe = re.sub(r"[^a-z0-9]+", "-", view.lower()).strip("-") or "view"
    return f"smartclock-{safe}-{stamp}.csv"
