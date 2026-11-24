"""Property panel of a named selection (M11.54).

:class:`SelectionPanel` shows what a selection is and who uses it: its name (renamed on
Enter through :func:`~thermalfea.model.selections.rename_selection`, one undo step), its
kind and entities, the parts a boundary bounds, and its users as link-like buttons that
select the user in the model tree. "Add from viewport" and "Remove from viewport" are
checkable: switching one on starts picking entities of the selection's dimension in the
viewport, switching it off confirms and rewrites the selection's tags and fingerprints in
one undo step. "Delete" is disabled while the selection is used and for ``all``.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.units import from_si, unit_label
from thermalfea.gui.addressing import Address
from thermalfea.gui.document import Document
from thermalfea.model.model import Model
from thermalfea.model.selections import (
    ALL_SELECTION,
    Selection,
    StaleSelectionError,
    selection_users,
)
from thermalfea.model.selections import resolve as resolve_selection
from thermalfea.model.vocabulary import entity_word

_DIM_MODE = {0: "point", 1: "curve", 2: "surface"}
_RED = "color: #c0392b;"
_MEASURE = {1: ("length", "length"), 2: ("area", "area")}


class SelectionPanel(QWidget):
    """Panel of one selection.

    Parameters
    ----------
    controller : PropertyController
        Gives ``document``, ``view`` and ``tree`` (and the toolbar sync, if any).
    address : tuple
        ``("selections", name)``.
    parent : QWidget, optional
    """

    def __init__(self, controller: Any, address: Address, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.document: Document = controller.document
        self.view = controller.view
        self.tree = controller.tree
        self.address = address
        self.name = str(address[1])
        self._connected = False
        self._mode_button: QPushButton | None = None
        self._picked: list[int] = []

        col = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(self.name)
        self.name_edit.setReadOnly(self.name == ALL_SELECTION)
        self.name_edit.returnPressed.connect(self.rename)
        form.addRow("Name", self.name_edit)
        self.kind_label = QLabel()
        form.addRow("Kind", self.kind_label)
        self.entities_label = QLabel()
        self.entities_label.setWordWrap(True)
        form.addRow("Entities", self.entities_label)
        self.bounds_label = QLabel()
        self.bounds_label.setWordWrap(True)
        form.addRow("Bounds parts", self.bounds_label)
        col.addLayout(form)
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        col.addWidget(self.message_label)

        col.addWidget(QLabel("Used by"))
        self.users_box = QVBoxLayout()
        col.addLayout(self.users_box)
        self.add_button = QPushButton("Add from viewport")
        self.remove_button = QPushButton("Remove from viewport")
        for button in (self.add_button, self.remove_button):
            button.setCheckable(True)
            col.addWidget(button)
        self.add_button.toggled.connect(lambda on: self._toggle(self.add_button, on, True))
        self.remove_button.toggled.connect(lambda on: self._toggle(self.remove_button, on, False))
        self.delete_button = QPushButton("Delete")
        self.delete_button.clicked.connect(self.delete)
        col.addWidget(self.delete_button)
        col.addStretch(1)

        self.document.model_changed.connect(self.refresh)
        self.document.geometry_built.connect(self.refresh)
        self.refresh()

    # ----------------------------------------------------------------------- display
    def _selection(self) -> Selection | None:
        return self.document.model.selections.get(self.name)

    def _current(self, selection: Selection) -> list[int] | None:
        """Tags of the selection in the current build, ``None`` when stale or unbuilt."""
        built = self.document.built
        if built is None:
            return None
        try:
            return resolve_selection(selection, built)
        except StaleSelectionError:
            return None

    def refresh(self) -> None:
        """Re-read the selection, its users and the build."""
        selection = self._selection()
        if selection is None:
            return
        model = self.document.model
        built = self.document.built
        units = model.display_units
        role = entity_word(selection.dim, model).capitalize()
        n = len(selection.tags)
        geometric = _DIM_MODE[selection.dim] + ("" if n == 1 else "s")
        self.kind_label.setText(f"{role} · {n} {geometric}")
        current = self._current(selection)
        shown = current if current is not None else list(selection.tags)
        text = ", ".join(f"#{t}" for t in shown) or "none"
        if selection.dim in _MEASURE and built is not None:
            fps = (
                [built.entities(selection.dim)[t] for t in current]
                if current is not None
                else selection.fingerprints
            )
            quantity, label = _MEASURE[selection.dim]
            total = float(from_si(sum(fp.measure for fp in fps), quantity, units))
            text += f" · total {label} {total:.4g} {unit_label(quantity, units)}"
        if current is None and built is not None:
            text += " · stale"
        self.entities_label.setText(text)
        self.bounds_label.setText(self._bounded_parts(selection, current))
        self.bounds_label.setVisible(bool(self.bounds_label.text()))
        self._fill_users(model)

        users = selection_users(model, self.name)
        fixed = self.name == ALL_SELECTION
        self.delete_button.setEnabled(not fixed and not users)
        self.delete_button.setToolTip(
            "The selection all cannot be deleted"
            if fixed
            else f"In use by {', '.join(u.label for u in users)}"
            if users
            else "Delete this selection"
        )
        can_edit = not fixed and self.view is not None and built is not None
        for button in (self.add_button, self.remove_button):
            button.setEnabled(can_edit or button.isChecked())
            button.setToolTip(
                "The selection all cannot be edited"
                if fixed
                else "No viewport is attached"
                if self.view is None
                else "Build the geometry first"
                if built is None
                else "Switch on, pick in the viewport, switch off to apply"
            )

    def _bounded_parts(self, selection: Selection, current: list[int] | None) -> str:
        """The parts a boundary bounds (names of the regions whose surfaces it touches)."""
        model = self.document.model
        built = self.document.built
        if built is None or current is None or entity_word(selection.dim, model) != "boundary":
            return ""
        surfaces: set[int] = set()
        for tag in current:
            surfaces.update(built.curve_surfaces.get(tag, []))
        names: list[str] = []
        for region in model.regions:
            sel = model.selections.get(region.selection)
            if sel is None:
                continue
            try:
                part = resolve_selection(sel, built)
            except StaleSelectionError:
                continue
            label = getattr(region, "name", "") or region.selection
            if surfaces & set(part) and label not in names:
                names.append(label)
        return ", ".join(names) or "none"

    def _fill_users(self, model: Model) -> None:
        while self.users_box.count():
            item = self.users_box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.user_buttons: list[QPushButton] = []
        users = selection_users(model, self.name)
        if not users:
            self.users_box.addWidget(QLabel("unused"))
        for use in users:
            button = QPushButton(use.label)
            button.setFlat(True)
            button.setStyleSheet("text-align: left; color: #1a5fb4;")
            button.clicked.connect(lambda _c=False, a=use.address: self.tree.select_address(a))
            self.users_box.addWidget(button)
            self.user_buttons.append(button)

    def show_message(self, text: str, error: bool = True) -> None:
        """Show a refusal (red) or a note under the form."""
        self.message_label.setStyleSheet(_RED if error else "")
        self.message_label.setText(text)

    # ------------------------------------------------------------------------ actions
    def rename(self) -> bool:
        """Rename on Enter: one undo step; a refusal shows a red message, model unchanged."""
        try:
            changed = self.tree.rename(self.address, self.name_edit.text())
        except ModelError as exc:
            self.show_message(str(exc))
            return False
        if not changed:
            self.name_edit.setText(self.name)
        return changed

    def delete(self) -> bool:
        """Delete the selection (refused while used or for ``all``)."""
        try:
            return self.tree.delete_selection_item(self.address)
        except ModelError as exc:
            self.show_message(str(exc))
            return False

    # ------------------------------------------------------------------------ picking
    def _toggle(self, button: QPushButton, on: bool, adding: bool) -> None:
        other = self.remove_button if adding else self.add_button
        if on:
            if other.isChecked():
                other.setChecked(False)  # applies what the other mode picked
            self._mode_button = button
            self._picked = []
            self._start_picking()
        elif self._mode_button is button:
            self._stop_picking()
            self._mode_button = None
            self._apply(adding)

    def _start_picking(self) -> None:
        selection = self._selection()
        if self.view is None or selection is None:
            return
        self._set_mode(_DIM_MODE[selection.dim])
        if not self._connected:
            self.view.selection_changed.connect(self.on_picked)
            self._connected = True
        self.show_message("Pick entities in the viewport, then switch the button off.", False)

    def _stop_picking(self) -> None:
        if self.view is None:
            return
        if self._connected:
            self.view.selection_changed.disconnect(self.on_picked)
            self._connected = False
        self._set_mode("none")

    def _set_mode(self, mode: str) -> None:
        self.view.set_selection_mode(mode)  # type: ignore[union-attr, arg-type]
        sync = getattr(self.controller, "_sync_toolbar", None)
        if sync is not None:
            try:
                sync(mode)
            except AttributeError:  # a controller without a window toolbar
                pass

    def on_picked(self, dim: int, tags: list[int]) -> None:
        """Slot of ``selection_changed``: remember the entities of the selection's dimension."""
        selection = self._selection()
        if selection is None or dim != selection.dim:
            return
        self._picked = [int(t) for t in tags]
        self.show_message(f"{len(self._picked)} picked", False)

    def picked(self) -> list[int]:
        """The tags picked so far."""
        return list(self._picked)

    def _apply(self, adding: bool) -> bool:
        """Store the new entities of the selection in one undo step."""
        picked, self._picked = self._picked, []
        selection = self._selection()
        if selection is None or not picked:
            return False
        current = self._current(selection)
        base = current if current is not None else []
        if adding:
            tags = list(dict.fromkeys([*base, *picked]))
        else:
            if current is None:
                self.show_message(f"{self.name}: stale; pick it again with Add from viewport")
                return False
            tags = [t for t in base if t not in picked]
        name, dim = self.name, selection.dim

        def mutate(model: Model) -> None:
            if name == ALL_SELECTION:
                raise ModelError(f"the selection {ALL_SELECTION!r} cannot be edited")
            if self.document.built is None:
                raise ModelError("build the geometry before selecting entities")
            make = {0: api.select_points, 1: api.select_curves, 2: api.select_surfaces}[dim]
            make(model, self.document.built, name, tags=tags)

        try:
            changed = self.document.edit(f"Edit selection {name}", mutate)
        except ModelError as exc:
            self.show_message(str(exc))
            return False
        self.show_message("", False)
        return changed
