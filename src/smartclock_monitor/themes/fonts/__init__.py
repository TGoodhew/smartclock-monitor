"""The bundled typefaces, and why they are bundled rather than named and hoped for.

§9.5's split is load-bearing: everything the receiver emits is monospace and everything the
application says is not, which is what tells "what the machine said" from "what the app says about
it". D4 settled the faces — Noto Sans for prose, Cascadia Mono for device literals.

**Naming a face does not pin its metrics; shipping it does.** D4 said as much when it was settled,
and the cost of not doing it arrived three times in one evening. A machine without Noto Sans falls
through the fallback chain to whatever it has, glyph widths go with it, and every layout measured
against one desktop is wrong on another: a window minimum rejected by CI at 1100, again at 1160, and
a theme picker that came back 50 px wide because it had been measured in a font nothing would draw
it in. Those were fixed by making the layout compute its own minimums, which is right anyway — but
the reason they kept happening is here.

Bundling also makes the figures honest. §9.4.5's contrast floors and §9.5.2's type ramp were
re-derived for this port against a specimen; a ramp checked in one face and rendered in another is a
measurement of something nobody sees.

**Both are redistributable, and the licences travel with them.** Cascadia Mono is SIL OFL 1.1 —
the name table opens with Microsoft's generic boilerplate and then states that the OFL applies, and
reproduces it. Noto Sans is OFL 1.1 by its own name table; the Apache 2.0 file at the root of
`notofonts.github.io` covers that repository's tooling rather than the fonts. OFL clause 2 permits
bundling provided the copyright notice and licence accompany the font, so ``*-LICENSE.txt`` sits
beside each one and ships with them.

**A missing or unreadable font is not an error.** The families stay first in §9.5's fallback chains,
so a desktop that has them installed is no worse off, and one where loading fails renders in the
next fallback exactly as it did before any of this. Nothing here may stop the application starting
over a typeface.
"""

from __future__ import annotations

from importlib import resources
from typing import Final

#: The files bundled, in the order they are registered. Regular and SemiBold for the prose face
#: because §9.5.2's ramp uses weights 400 and 600; Cascadia only at 400, which is the one weight
#: §9.5's device-literal style asks for.
BUNDLED: Final[tuple[str, ...]] = (
    "NotoSans-Regular.ttf",
    "NotoSans-SemiBold.ttf",
    "CascadiaMono-Regular.ttf",
)

#: Where they live. This module *is* that package — the loader lives beside the files it loads
#: rather than next to them, because a sibling module named for the directory shadows it: Python
#: resolves ``themes.fonts`` to a regular module before a namespace package, so ``resources.files``
#: found nothing and every face silently failed to register.
PACKAGE: Final = __name__


def load() -> tuple[str, ...]:
    """Register the bundled faces with Qt. Returns the family names actually registered.

    Call once, **before the first window is built**: a widget measured before its font exists is
    measured in the default one, which is the whole class of defect this exists to end.

    Never raises. A font that will not load leaves the application rendering in §9.5's next
    fallback, which is where it was before it was bundled — a worse-looking window is not a reason
    to fail to start, and a receiver is still perfectly monitorable in DejaVu Sans.
    """
    from PySide6.QtGui import QFontDatabase

    families: list[str] = []
    for name in BUNDLED:
        try:
            data = (resources.files(PACKAGE) / name).read_bytes()
        except (OSError, ModuleNotFoundError):
            continue

        identifier = QFontDatabase.addApplicationFontFromData(data)
        if identifier == -1:
            continue
        families.extend(QFontDatabase.applicationFontFamilies(identifier))

    # Ordered and de-duplicated: Regular and SemiBold of one face report the same family, and a
    # caller reporting "Noto Sans, Noto Sans" would look like a bug in the loader.
    return tuple(dict.fromkeys(families))
