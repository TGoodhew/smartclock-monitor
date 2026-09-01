"""§10.5's *Manage…* dialog: PRN 1–32, include or exclude.

**It sends the difference, not the state.** A dialog that sent the whole list every time would put
a tier C command on the wire for a user who opened it, looked, and closed it — and §8.3's
confirmations exist precisely so a tier C command is something a user meant.

**The two strong variants are reachable and both carry their own sentence.** §8.3's amendment note
is why that is stated rather than assumed: ``:IGN:NONE`` shared the PRN form's sentence — *"Exclude
the selected satellites from tracking?"* — for a command that **clears** the exclusion list, so a
user confirming it would reasonably believe they were excluding satellites while making every one
eligible again.

**An unread exclusion list opens empty and sends nothing.** §11.1's rule is that what could not be
read says nothing: a satellite wrongly marked excluded sends someone looking for a setting they
never made, and applying an empty list read from a failed query would *create* that setting.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from smartclock_device.commands import catalog
from smartclock_device.commands.scpi_command import ScpiCommand
from smartclock_monitor.themes.qss import stylesheet
from smartclock_monitor.themes.spacing import Spacing
from smartclock_monitor.themes.tokens import LIGHT, Palette

#: How many PRNs go in a row. Eight by four reads as a block rather than a list, which is what a
#: user scanning for one number wants.
_COLUMNS = 8


class ManageSatellitesDialog(QDialog):
    """§10.5's Manage dialog."""

    def __init__(
        self,
        excluded: frozenset[int],
        *,
        known: bool = True,
        palette: Palette = LIGHT,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._was_excluded = frozenset(excluded)
        self._known = known
        self._boxes: dict[int, QCheckBox] = {}

        self.setWindowTitle("Manage satellites")
        self.setModal(True)
        self.setStyleSheet(stylesheet(palette))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(Spacing.LARGE, Spacing.LARGE, Spacing.LARGE, Spacing.LARGE)
        layout.setSpacing(Spacing.MEDIUM)

        heading = QLabel("Tick a satellite to exclude it from tracking.")
        heading.setWordWrap(True)
        layout.addWidget(heading)

        if not known:
            warning = QLabel(
                "The receiver's exclusion list could not be read, so nothing is shown as "
                "excluded. Applying from here would set a list rather than change one."
            )
            warning.setWordWrap(True)
            warning.setProperty("role", "caption")
            layout.addWidget(warning)

        layout.addLayout(self._build_grid())
        layout.addLayout(self._build_buttons())

    def _build_grid(self) -> QGridLayout:
        grid = QGridLayout()
        grid.setHorizontalSpacing(Spacing.MEDIUM)
        grid.setVerticalSpacing(Spacing.SMALL)

        for index, prn in enumerate(range(catalog.FIRST_PRN, catalog.LAST_PRN + 1)):
            box = QCheckBox(str(prn))
            box.setAccessibleName(f"Exclude PRN {prn}")
            box.setChecked(prn in self._was_excluded)
            box.setEnabled(self._known)
            self._boxes[prn] = box
            grid.addWidget(box, index // _COLUMNS, index % _COLUMNS)

        return grid

    def _build_buttons(self) -> QHBoxLayout:
        row = QHBoxLayout()

        self._exclude_all = QPushButton("Exclude all")
        self._exclude_all.setProperty("role", "destructive")
        self._exclude_all.setAccessibleName("Exclude every satellite")
        self._exclude_all.clicked.connect(lambda: self._choose_bulk(True))

        self._include_all = QPushButton("Clear exclusions")
        self._include_all.setAccessibleName("Make every satellite eligible again")
        self._include_all.clicked.connect(lambda: self._choose_bulk(False))

        row.addWidget(self._exclude_all)
        row.addWidget(self._include_all)
        row.addStretch(1)

        self._apply = QPushButton("Apply")
        self._apply.setProperty("role", "destructive")
        self._apply.clicked.connect(self.accept)
        self._cancel = QPushButton("Cancel")
        self._cancel.setDefault(True)
        self._cancel.clicked.connect(self.reject)
        row.addWidget(self._apply)
        row.addWidget(self._cancel)

        for button in (self._exclude_all, self._include_all, self._apply):
            button.setEnabled(self._known)

        return row

    def _choose_bulk(self, exclude: bool) -> None:
        """The two bulk buttons only *set the boxes*; Apply is still what sends.

        So the dialog has one send path and one confirmation, and a user who presses *Exclude all*
        and then thinks better of it can press Cancel — which they could not if the button sent.
        """
        for box in self._boxes.values():
            box.setChecked(exclude)

    # -- What the caller reads ------------------------------------------------------------------

    @property
    def excluded(self) -> frozenset[int]:
        return frozenset(prn for prn, box in self._boxes.items() if box.isChecked())

    def commands(self) -> list[tuple[ScpiCommand, object]]:
        """The commands that would make the receiver match this dialog.

        **Empty where nothing changed**, which is not the same as cancelling.

        The whole-list forms are preferred where they apply, because ``:IGN:ALL`` and ``:IGN:NONE``
        each say in one command what a list of thirty-two would say in one long one — and each
        carries its own §8.3 sentence, which is more specific than the PRN form's.
        """
        if not self._known:
            return []

        wanted = self.excluded
        if wanted == self._was_excluded:
            return []

        if not wanted:
            return [(catalog.CLEAR_EXCLUSIONS, None)]
        if len(wanted) == catalog.LAST_PRN - catalog.FIRST_PRN + 1:
            return [(catalog.EXCLUDE_ALL_SATELLITES, None)]

        # Clear first, then set: the receiver holds a list, and sending only the additions would
        # leave a satellite excluded that the user has just un-ticked.
        return [
            (catalog.CLEAR_EXCLUSIONS, None),
            (catalog.EXCLUDE_SATELLITES, sorted(wanted)),
        ]

    def box_for(self, prn: int) -> QCheckBox | None:
        return self._boxes.get(prn)

    @property
    def apply_button(self) -> QPushButton:
        return self._apply

    @property
    def cancel_button(self) -> QPushButton:
        return self._cancel


def parse_exclusions(answer: str | None) -> tuple[frozenset[int], bool]:
    """Read ``:GPS:SAT:TRAC:IGN?``'s answer. Returns the set and whether it was understood.

    **The bool is the point.** An unreadable answer and an empty list are different facts, and
    §11.1's rule is that what could not be read says nothing — a satellite wrongly marked excluded
    sends someone looking for a setting they never made.
    """
    if answer is None:
        return frozenset(), False

    text = answer.strip()
    if not text:
        return frozenset(), False

    prns: set[int] = set()
    for piece in text.split(","):
        cleaned = piece.strip().lstrip("+")
        if not cleaned:
            continue
        try:
            value = int(cleaned)
        except ValueError:
            # A field this build does not understand. The rest of the answer is still good, and
            # discarding all of it would turn one odd token into "nothing is excluded".
            continue
        if catalog.FIRST_PRN <= value <= catalog.LAST_PRN:
            prns.add(value)

    return frozenset(prns), True


def ask_to_manage(
    excluded: frozenset[int],
    *,
    known: bool = True,
    palette: Palette = LIGHT,
    parent: QWidget | None = None,
) -> list[tuple[ScpiCommand, object]] | None:
    """Show the dialog. Returns the commands to send, or ``None`` if the user cancelled.

    An empty list is a real answer — the user opened it, looked, and changed nothing — and is not
    the same as ``None``.
    """
    dialog = ManageSatellitesDialog(excluded, known=known, palette=palette, parent=parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.commands()
