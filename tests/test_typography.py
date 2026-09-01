"""§9.5's type ramp, and the faces it is set in.

`docs/platform-decisions.md` D4 (issue #4). §9.5's split is load-bearing rather than decorative:
everything the receiver emits is monospace, everything the application says is not, and that is
what tells "what the machine said" from "what the app says about it" in an application whose whole
job is faithful reporting.
"""

from __future__ import annotations

import itertools

from smartclock_monitor.themes.typography import MONO_FAMILY, RAMP, UI_FAMILY, Type


def test_the_ui_face_is_named_and_not_the_desktop_s_default() -> None:
    """D4, settled: **the face is named.**

    It used to begin with ``""`` — Qt's "whatever the system resolves as the UI font" — on the
    reasoning that this is what every other application does. Sound for an application with slack
    in its layout, and this one has little: a face is a set of glyph widths, so deferring the face
    defers the widths to a machine nobody has measured.

    It cost a CI failure. A page measured to fit here overflowed on a runner that resolved a wider
    face at the same point size, and no local run could have seen it. An empty first entry is
    therefore the specific thing this forbids, rather than a style preference.
    """
    assert UI_FAMILY[0], "the first UI family entry is empty, which defers the face to the desktop"
    assert UI_FAMILY[0] == "Noto Sans"
    assert all(name for name in UI_FAMILY), "an empty entry anywhere means the same thing"


def test_the_device_face_leads_with_the_one_that_ports() -> None:
    """Cascadia Mono is SIL OFL 1.1 and is already bundled in WinZ3805A with its licence notice, so
    the device-literal half of §9.5's split survives the move unchanged. It is not inbox on Linux,
    hence the fallbacks — but it stays first, because it is the shared decision."""
    assert MONO_FAMILY[0] == "Cascadia Mono"
    assert "monospace" in MONO_FAMILY, "a generic last resort, so the split never silently fails"


def test_every_ramp_step_is_distinguishable_from_its_neighbours() -> None:
    """§9.5.2. A ramp whose steps collide conveys no hierarchy, and the collision is what changing
    the face could have caused — x-height and optical sizing differ between faces even where the
    point size does not."""
    ordered = sorted({style.size for _, style in RAMP})

    assert len(ordered) == len({style.size for _, style in RAMP})
    for smaller, larger in itertools.pairwise(ordered):
        assert larger - smaller >= 1, f"{smaller}pt and {larger}pt are not distinguishable"


def test_device_text_is_the_only_monospace_step() -> None:
    """The split is what makes the distinction readable, so exactly one side of it is monospace."""
    monospace = {name for name, style in RAMP if style.monospace}

    assert Type.DEVICE.monospace is True
    assert monospace <= {"Device"}, f"{monospace} is monospace and should not be"


def test_the_readouts_are_tabular() -> None:
    """§9.5.3: a changing readout must not jitter horizontally. Proportional figures move the
    decimal point every second, which reads as instability in the *receiver*."""
    assert Type.READOUT.tabular is True
    assert Type.READOUT_SMALL.tabular is True
