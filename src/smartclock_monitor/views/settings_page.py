"""§10.13's Settings page.

**The page states plainly what is not there yet.** §9.11's rule against a control that looks like it
works and does nothing applies to a settings page more than to most, so a switch whose surface does
not exist on this platform is written as a sentence rather than drawn as a toggle nobody has wired
up. §10.13's own "Not on this page, and why" table is where that habit comes from.

Two of §10.13's rows are not switches here, and each says why on screen:

- **Use the Windows accent colour** has nothing to read on Linux or macOS. §9.4.2's guarantee is
  that the brand accent is chosen for hue separation from the severity colours, and there is no
  cross-platform contract that would preserve it — the same argument as `docs/platform-decisions.md`
  D3 makes about high contrast.
- **Start in the notification area** needs a tray, which is issue #6's decision and not settled.

**Poll cadences are deliberately not offered**, and that is a refusal rather than a gap. §7.3 fixes
them at 1 s and 10 s and §12 gives the poller sole ownership of both, so a switch here would
contradict two sections rather than implement one. Making them user-visible is an amendment to §7.3
and §12 and has to be argued there first.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QCheckBox, QFrame, QPushButton, QVBoxLayout, QWidget

from smartclock_monitor.services.polling import Reading
from smartclock_monitor.services.preferences import Preferences
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette
from smartclock_monitor.views.pages import Page, card, label


class SettingsPage(Page):
    """§10.13."""

    title = "Settings"

    def __init__(self, palette: Palette = LIGHT, parent: QWidget | None = None) -> None:
        super().__init__(palette, parent)
        self._preferences = Preferences()
        self._on_change: Callable[[Preferences], None] | None = None
        self._settling = False

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.MEDIUM)
        layout.addWidget(self._build_advanced())
        layout.addWidget(self._build_alerts())
        layout.addWidget(self._build_background())
        layout.addWidget(self._build_not_here())
        layout.addStretch(1)

        self._redraw()

    # -- The cards -------------------------------------------------------------------------------

    def _switch(self, text: str, explanation: str, layout: QVBoxLayout) -> QCheckBox:
        box = QCheckBox(text)
        box.setAccessibleName(text)
        box.toggled.connect(lambda _v: self._collect())
        layout.addWidget(box)
        note = label(explanation, "tertiary")
        note.setWordWrap(True)
        layout.addWidget(note)
        return box

    def _build_advanced(self) -> QFrame:
        holder, holder_layout = card("Advanced")
        holder_layout.addWidget(
            label(
                "For working out what the receiver is doing, rather than for using it.",
                "caption",
            )
        )
        self._console = self._switch(
            "Advanced Console",
            "Adds a page offering every command in the catalog as a picker, with a transcript of "
            "everything sent and received. It adds no command the application could not already "
            "send — the catalog is the same allowlist every other page uses.",
            holder_layout,
        )
        holder_layout.addWidget(
            label(
                "Undocumented read-only queries (§8.5) are not built yet, so there is no switch "
                "for them here rather than one that toggles nothing.",
                "tertiary",
            )
        )
        return holder

    def _build_alerts(self) -> QFrame:
        holder, holder_layout = card("Alerts")
        self._alert = self._switch(
            "Tell me when the receiver loses GPS lock",
            "On by default, because it exists precisely for the user who is not looking.",
            holder_layout,
        )
        return holder

    def _build_background(self) -> QFrame:
        holder, holder_layout = card("Running in the background")
        self._keep_running = self._switch(
            "Keep running when I close the window",
            "On by default: a receiver is left docked for weeks, and a close that stopped polling "
            "would stop it exactly when the window was being got out of the way.",
            holder_layout,
        )
        self._quit = QPushButton("Exit")
        self._quit.setAccessibleName("Quit the application")
        holder_layout.addWidget(self._quit)
        return holder

    def _build_not_here(self) -> QFrame:
        holder, holder_layout = card("Not here, and why")
        for text in (
            "Poll cadences are fixed by §7.3 at 1 s and 10 s, and §12 gives the poller sole "
            "ownership of them. A switch here would contradict two sections rather than "
            "implement one.",
            "Use the Windows accent colour has nothing to read on this platform, and §9.4.2's "
            "accent is chosen for hue separation from the severity colours — a setting that "
            "abandoned that would make the guarantee depend on a control panel.",
            "Start in the notification area needs a tray, which is not settled for these "
            "desktops (issue #6).",
            "The display time zone is set on the clock itself and on the Time page, which is "
            "one preference with two places to set it rather than duplicated state.",
        ):
            line = label(text, "tertiary")
            line.setWordWrap(True)
            holder_layout.addWidget(line)
        return holder

    # -- Reading and writing ---------------------------------------------------------------------

    def set_preferences(self, preferences: Preferences) -> None:
        self._preferences = preferences
        self._redraw()

    @property
    def preferences(self) -> Preferences:
        return self._preferences

    def on_change(self, handler: Callable[[Preferences], None] | None) -> None:
        self._on_change = handler

    def _redraw(self) -> None:
        # Guarded, because setChecked emits toggled and would otherwise report a change nobody
        # made — and, worse, write the defaults over a file that was being read at the time.
        self._settling = True
        try:
            self._console.setChecked(self._preferences.advanced_console)
            self._alert.setChecked(self._preferences.alert_on_lock_loss)
            self._keep_running.setChecked(self._preferences.keep_running_when_closed)
        finally:
            self._settling = False

    def _collect(self) -> None:
        if self._settling:
            return

        from dataclasses import replace

        self._preferences = replace(
            self._preferences,
            advanced_console=self._console.isChecked(),
            alert_on_lock_loss=self._alert.isChecked(),
            keep_running_when_closed=self._keep_running.isChecked(),
        )
        if self._on_change is not None:
            self._on_change(self._preferences)

    def show_reading(self, reading: Reading) -> None:
        del reading

    # -- What a test may read --------------------------------------------------------------------

    @property
    def console_switch(self) -> QCheckBox:
        return self._console

    @property
    def alert_switch(self) -> QCheckBox:
        return self._alert

    @property
    def keep_running_switch(self) -> QCheckBox:
        return self._keep_running

    @property
    def exit_button(self) -> QPushButton:
        return self._quit
