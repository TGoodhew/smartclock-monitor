"""§10.13's Settings page.

**The page states plainly what is not there yet.** §9.11's rule against a control that looks like it
works and does nothing applies to a settings page more than to most, so a switch whose surface does
not exist on this platform is written as a sentence rather than drawn as a toggle nobody has wired
up. §10.13's own "Not on this page, and why" table is where that habit comes from.

Three of §10.13's rows are not switches here, and each says why on screen:

- **Use the Windows accent colour** has nothing to read on Linux or macOS. §9.4.2's guarantee is
  that the brand accent is chosen for hue separation from the severity colours, and there is no
  cross-platform contract that would preserve it.
- **Start in the notification area** and **Keep running when I close the window** both need a
  notification area, and D5 (issue #6) settled that this port ships none. §10.3.1's hide is only
  safe where there is a way back to the window, and without an icon there is not — so close means
  close, and neither switch exists rather than being drawn and disabled.
- **Tell me when the receiver loses GPS lock** went with them. P1-9 exists "precisely for the user
  who is not looking", and a message shown only inside the window they are not looking at does not
  serve that — so the honest answer is to remove it rather than to keep the switch and weaken what
  it promises.

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
        layout.addWidget(self._build_appearance())
        layout.addWidget(self._build_quitting())
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
        # §8.5's own wording, verbatim — it is the one place a user is told what they are opting
        # into, and paraphrasing a safety notice is how the guarantee drifts.
        self._undocumented = self._switch(
            "Undocumented read-only queries",
            "Enable undocumented read-only queries. These are present in the receiver's command "
            "parser but absent from the published manual. They may return errors or nonsense. "
            "No setting is changed.",
            holder_layout,
        )
        return holder

    def _build_quitting(self) -> QFrame:
        holder, holder_layout = card("Quitting")

        # §10.3.1: **the application must be quittable from its own surface.** That argument was
        # written against a notification area this port does not have, and it survives the removal
        # unchanged — a window's close button is a surface, but so is a button that says what it
        # does, and the two cost nothing together.
        self._quit = QPushButton("Exit")
        self._quit.setProperty("role", "destructive")
        self._quit.setAccessibleName("Quit the application")
        self._quit.clicked.connect(lambda: self._exit())
        holder_layout.addWidget(self._quit)

        note = label(
            "Closing the window stops the application and stops polling. There is no notification "
            "area to hide into on these desktops, and a hidden window with no icon could not be "
            "got back.",
            "tertiary",
        )
        holder_layout.addWidget(note)
        return holder

    #: Called when the user presses Exit. Set by whoever owns the page — quitting is not something
    #: a page decides.
    on_exit: Callable[[], None] | None = None

    def _exit(self) -> None:
        if self.on_exit is not None:
            self.on_exit()

    def _build_appearance(self) -> QFrame:
        holder, holder_layout = card("Appearance")
        self._on_top = self._switch(
            "Keep the window above others",
            "Off by default: a window that outranks everything else is a decision about the "
            "desktop rather than about this application, and there is usually a spectrum "
            "analyser to look at too.",
            holder_layout,
        )
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
            "Start in the notification area and Keep running when I close the window both need "
            "a notification area. D5 settled that this port ships none, so closing the window "
            "stops the application (issue #6).",
            "Tell me when the receiver loses GPS lock went with them: P1-9 exists for the user "
            "who is not looking, and a message inside the window they are not looking at does "
            "not serve that.",
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
            self._undocumented.setChecked(self._preferences.undocumented_queries)
            self._on_top.setChecked(self._preferences.always_on_top)
        finally:
            self._settling = False

    def _collect(self) -> None:
        if self._settling:
            return

        from dataclasses import replace

        self._preferences = replace(
            self._preferences,
            advanced_console=self._console.isChecked(),
            undocumented_queries=self._undocumented.isChecked(),
            always_on_top=self._on_top.isChecked(),
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
    def undocumented_switch(self) -> QCheckBox:
        return self._undocumented

    @property
    def on_top_switch(self) -> QCheckBox:
        return self._on_top

    @property
    def exit_button(self) -> QPushButton:
        return self._quit
