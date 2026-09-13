"""What the GPS receiver inside the instrument calls itself — ``:DIAG:IDEN:GPS?`` (#62).

**Nothing here assigns meaning to position**, and that is a reading of the hardware rather than
caution. The Z3801A User's Guide describes the answer as *"the model number, serial number, and
revision of the internal GPS receiver"*, in that order. The bench Z3805A answers with ten quoted
fields of which seven are ``--``, and the serial number — the one the documentation is most
specific about — is among the empty ones:

    "--","SFTW P/N # 4850266","SOFTWARE VER # 005","--","--",
    "MODEL # FURUNO GT-80","--","--","--","--"

The three that are populated **label themselves**. So this keeps them in receiver order, in the
receiver's own words, and a firmware that fills two more slots gains two more lines rather than
shifting what the existing ones mean. It is the same rule §8.5 applies to an undocumented value:
where nothing documents what a position means, nothing may assume it.
"""

from __future__ import annotations

from typing import Final

#: What this firmware puts in a field it has nothing for.
EMPTY: Final = "--"


def parse(line: str | None) -> tuple[str, ...]:
    """The populated fields, in order. **Never raises** (§11.1).

    An unparseable answer is an empty tuple, which renders as "nothing to show" rather than as a
    card of dashes — there is no field here that is *pending*, so §11.1's em dash would be the
    wrong symbol.
    """
    if not line:
        return ()

    found: list[str] = []
    for raw in line.split(","):
        value = raw.strip().strip('"').strip()
        if value and value != EMPTY:
            found.append(value)
    return tuple(found)
