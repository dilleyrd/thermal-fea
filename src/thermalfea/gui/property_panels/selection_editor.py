"""Editor of a selection field (held item 12, conventions C1, C2, C6; task M11.70).

A load, part, contact, stream or mesh setting applies to geometry through named
selections. The field shows that on one row:

    Boundary   [ cooled · 1 boundary        ▾ ]   ✓ ↶   +  ✎

* **The dropdown** lists the model's selections the field accepts, with their sizes.
  Choosing another one does **not** change the object (C1): the dropdown is marked, a
  note says the change is not applied, and ✓ **Update** applies it (one undo step) while ↶
  **Revert** goes back. The chosen selection is highlighted in the view.
* **+ New** picks a new selection (C2): a strip under the row says what to click and
  counts the picked entities; the **Name** box starts empty (owner's decision) and
  "Create and use" (Enter) stays disabled until something is picked and the name is
  valid and unused. It creates the selection and uses it in one undo step. Cancel or Esc
  changes nothing.
* **✎ Edit** changes the entities of the current selection, starting from them; the strip
  says which other objects use it. "Save" rewrites the selection; "Save as new" stores
  the picked entities under a new name and uses that instead, leaving the others alone.

A ``selection_list`` field (a stream's walls, structured parts) lists its selections, each
with ✎ and ✕, above the same row; adding or removing waits for Update like the dropdown.

The toolbar follows the pick (C2): the field's kind of entity while picking (Boundary for
a field that accepts boundaries or points), restored afterwards. The editor works against
the ``SceneView`` protocol and the :class:`~thermalfea.gui.document.Document` only; a form
(:class:`~thermalfea.gui.property_panels.form.FormPanel`) stores the value when
:attr:`SelectionEditor.value_changed` fires and creates selections through
:attr:`SelectionEditor.apply_handler`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.gui.document import Document
from thermalfea.gui.icons import icon_button
from thermalfea.gui.pick import PickStrip, count_text, manager_for
from thermalfea.gui.scene import SceneView
from thermalfea.model.model import Model
from thermalfea.model.selections import (
    ALL_SELECTION,
    StaleSelectionError,
    check_new_selection_name,
    selection_users,
)
from thermalfea.model.selections import resolve as resolve_selection
from thermalfea.model.vocabulary import entity_word

_DIM_MODE = {0: "point", 1: "curve", 2: "surface"}
NONE_TEXT = "(none)"
ADD_TEXT = "(add a selection…)"
_PENDING_STYLE = "QComboBox { border: 2px solid #e0a000; border-radius: 3px; }"
_NOTE_STYLE = "color: #8a5a00;"
_ERROR_STYLE = "color: #b00020;"
#: Status-bar note when a panel with an unapplied selection change is left (decision A).
DISCARDED_TEXT = "Selection change not applied"


@dataclass
class SelectionRequest:
    """Entities to store as a named selection.

    Attributes
    ----------
    dim : int
        Geometry dimension of the entities.
    tags : list of int
        Entity tags in the current build.
    name : str
        Name of the selection to create.
    replace : str
        Name of an existing selection whose entities this request may replace (when no
        other object uses it). Empty: none.
    swap : str
        For a list field: the entry the new selection takes the place of ("Save as new"
        from an entry). Empty: the new selection is appended.
    """

    dim: int
    tags: list[int]
    name: str
    replace: str = ""
    swap: str = ""


def used_selection_names(model: Model) -> set[str]:
    """Names a new selection must avoid: selections, ``all`` and mesh/per-region keys."""
    mesh = model.mesh_settings
    names = set(model.selections) | {ALL_SELECTION}
    for table in (mesh.curve_sizes, mesh.point_sizes, mesh.curve_divisions):
        names |= set(table)
    names |= set(model.initial_condition.per_region or {})
    return names


def check_request_name(
    model: Model, request: SelectionRequest, owner: tuple | None = None
) -> None:
    """Validate ``request.name`` against ``model`` (call inside the edit mutation).

    The name must pass ``check_new_selection_name``, unless it equals ``request.replace``,
    that selection exists, and every user of it is the object at ``owner`` (with no
    ``owner``, it must have no user at all). ``request.name`` is set to the stripped name.

    Raises
    ------
    ModelError
        If the name is refused.
    """
    name = request.name.strip()
    if name and name == request.replace and name in model.selections:
        allowed = {owner} if owner is not None else set()
        if {use.address for use in selection_users(model, name)} <= allowed:
            request.name = name
            return
    request.name = check_new_selection_name(model, name)


def store_selection(model: Model, built: BuiltGeometry | None, request: SelectionRequest) -> str:
    """Create or replace the selection of ``request`` in ``model``; return its name.

    Raises
    ------
    ModelError
        If there is no built geometry or a tag does not exist.
    """
    if built is None:
        raise ModelError("build the geometry before selecting entities")
    make: Callable[..., object] = {
        0: api.select_points,
        1: api.select_curves,
        2: api.select_surfaces,
    }[request.dim]
    make(model, built, request.name, tags=request.tags)
    return request.name


def selection_label(model: Model, name: str) -> str:
    """``"cooled · 1 boundary"``: a selection's name and size for the dropdown."""
    selection = model.selections.get(name)
    if selection is None:
        return f"{name} · missing"
    n = len(selection.tags)
    return f"{name} · {n} {entity_word(selection.dim, model, plural=n != 1)}"


def role_label(model: Model, dims: tuple[int, ...] | None) -> str:
    """The field's role as a row label: "Boundary", "Part", "Boundary or point"."""
    words = [entity_word(d, model) for d in sorted(dims or (1,), reverse=True)]
    return " or ".join(words).capitalize()


class SelectionEditor(QWidget):
    """Selection field editor (one name, or a list of names).

    Parameters
    ----------
    document : Document
    view : SceneView or None
        The viewport used for picking; without one picking is disabled.
    spec : FieldSpec
        The field (``kind`` ``selection`` or ``selection_list``; ``selection_dims`` says
        what may be picked).
    parent : QWidget, optional

    Attributes
    ----------
    combo : QComboBox
        The selections the field accepts (a list field: those it does not hold yet).
    update_button, revert_button : QToolButton
        ✓ and ↶, shown while a change waits for Update.
    new_button, edit_button : QToolButton
        + (pick a new selection) and ✎ (edit the current one; single fields).
    strip : PickStrip
        Shown while picking; holds :attr:`name_edit` and "Save as new".
    picking : str or None
        ``"new"`` or ``"edit"`` while a pick runs.
    apply_handler : callable or None
        ``handler(SelectionRequest) -> name or None`` creates the selection and sets the
        field in one undo step (a form's); without one the selection is only created.
    owner_address : tuple or None
        Address of the object the field belongs to (for "also used by").

    Signals
    -------
    value_changed(object)
        Update was pressed: the new name, or the whole list of names.
    """

    value_changed = Signal(object)

    def __init__(
        self,
        document: Document,
        view: SceneView | None,
        spec: FieldSpec,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.document = document
        self.view = view
        self.spec = spec
        self.apply_handler: Callable[[SelectionRequest], str | None] | None = None
        self.owner_address: tuple | None = None
        #: Kept for callers of the earlier editor; the pick manager drives the toolbar now.
        self.mode_sync: Callable[[str], None] | None = None
        #: Kept for callers of the earlier editor; new selections have no default name.
        self.name_hint = spec.name
        self._is_list = spec.kind == "selection_list"
        self._stored: str | list[str] = [] if self._is_list else ""
        self._working: str | list[str] = [] if self._is_list else ""
        self.picking: str | None = None
        self._edit_name = ""
        self._picked: tuple[int, list[int]] = (-1, [])
        self._connected = False
        self._error = ""

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        self.entries = QVBoxLayout()
        self.entries.setContentsMargins(0, 0, 0, 0)
        col.addLayout(self.entries)
        row = QHBoxLayout()
        self.combo = QComboBox()
        row.addWidget(self.combo, 1)
        self.update_button = icon_button("update", "Update: use this selection")
        self.revert_button = icon_button("revert", "Revert: keep the current selection")
        self.new_button = icon_button("add", "New selection: pick it in the view")
        self.edit_button = icon_button("edit", "Edit the entities of this selection")
        for button in (self.update_button, self.revert_button, self.new_button):
            row.addWidget(button)
        if not self._is_list:
            row.addWidget(self.edit_button)
        col.addLayout(row)
        self.pending_label = QLabel("")
        self.pending_label.setStyleSheet(_NOTE_STYLE)
        self.pending_label.setWordWrap(True)
        col.addWidget(self.pending_label)

        self.strip = PickStrip("Create and add" if self._is_list else "Create and use")
        name_row = QWidget()
        name_layout = QHBoxLayout(name_row)
        name_layout.setContentsMargins(0, 0, 0, 0)
        name_layout.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("name of the new selection")
        name_layout.addWidget(self.name_edit, 1)
        self.strip.insert_widget(name_row)
        self.name_error = QLabel("")
        self.name_error.setStyleSheet(_ERROR_STYLE)
        self.name_error.setWordWrap(True)
        self.strip.insert_widget(self.name_error)
        self.save_as_button = self.strip.add_button("Save as new")
        col.addWidget(self.strip)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet(_ERROR_STYLE)
        self.error_label.setWordWrap(True)
        col.addWidget(self.error_label)

        self.combo.activated.connect(self._on_activated)
        self.update_button.clicked.connect(lambda _c=False: self.update())
        self.revert_button.clicked.connect(lambda _c=False: self.revert())
        self.new_button.clicked.connect(lambda _c=False: self.start_new())
        self.edit_button.clicked.connect(lambda _c=False: self.start_edit())
        self.name_edit.textChanged.connect(lambda _t: self._update_strip())
        self.strip.confirmed.connect(self.confirm_pick)
        self.strip.cancelled.connect(self.cancel_pick)
        self.save_as_button.clicked.connect(lambda _c=False: self.save_as_new())
        document.geometry_built.connect(self.refresh)
        document.model_changed.connect(self.refresh)
        self.refresh()

    # --------------------------------------------------------------------- value
    def _copy(self, value: str | list[str] | None) -> str | list[str]:
        if self._is_list:
            return list(value or [])  # type: ignore[arg-type]
        return str(value or "")

    def value(self) -> str | list[str]:
        """The stored value: what the object holds."""
        return self._copy(self._stored)

    def pending_value(self) -> str | list[str]:
        """The value shown, which Update would store."""
        return self._copy(self._working)

    def has_pending(self) -> bool:
        """True while a change waits for Update (C1)."""
        return self._working != self._stored

    def set_value(self, value: str | list[str] | None) -> None:
        """Show the stored ``value`` without emitting; a pending change survives unless the
        stored value itself changed (an undo, another panel)."""
        new = self._copy(value)
        if new != self._stored or not self.has_pending():
            self._working = self._copy(new)
        self._stored = new
        self.refresh()

    def allowed_names(self) -> list[str]:
        """Names of the model's selections the field accepts."""
        dims = self.spec.selection_dims
        return [
            name
            for name, sel in self.document.model.selections.items()
            if dims is None or sel.dim in dims
        ]

    def choose(self, name: str) -> None:
        """Choose a selection (what the dropdown does): a pending change until Update."""
        if self._is_list:
            if not name or name in self._working:
                return
            self._working = [*self._working, name]  # type: ignore[misc]
        else:
            self._working = name
        self._error = ""
        self.refresh()
        self._highlight(name)

    def remove_entry(self, name: str) -> None:
        """Take ``name`` out of a list field (a pending change until Update)."""
        if self._is_list and name in self._working:
            self._working = [n for n in self._working if n != name]
            self.refresh()

    def clear(self) -> None:
        """Empty a list field (a pending change until Update)."""
        if self._is_list:
            self._working = []
            self.refresh()

    def update(self) -> bool:
        """Apply the pending change: emits :attr:`value_changed` (the form stores it)."""
        if not self.has_pending():
            return False
        self.value_changed.emit(self.pending_value())
        return True

    def revert(self) -> None:
        """Drop the pending change and show the stored value again."""
        if self.has_pending():
            self._working = self._copy(self._stored)
            self.refresh()
            names = self._stored if self._is_list else [self._stored]
            self._highlight(names[0] if names else "")

    def _on_activated(self, index: int) -> None:
        name = self.combo.itemData(index)
        if self._is_list and not name:
            return
        self.choose(str(name or ""))

    # ------------------------------------------------------------------- display
    def refresh(self) -> None:
        """Re-read the selections, the build and the pending state."""
        model = self.document.model
        self.combo.blockSignals(True)
        self.combo.clear()
        if self._is_list:
            self.combo.addItem(ADD_TEXT, "")
            for name in self.allowed_names():
                if name not in self._working:
                    self.combo.addItem(selection_label(model, name), name)
            self.combo.setCurrentIndex(0)
            self._fill_entries()
        else:
            self.combo.addItem(NONE_TEXT, "")
            for name in self.allowed_names():
                self.combo.addItem(selection_label(model, name), name)
            if self._working and self.combo.findData(self._working) < 0:
                self.combo.addItem(selection_label(model, str(self._working)), self._working)
            self.combo.setCurrentIndex(max(self.combo.findData(self._working), 0))
        self.combo.blockSignals(False)

        can_pick = self.view is not None and self.document.built is not None
        idle = self.picking is None and not self.has_pending()
        self.new_button.setEnabled(can_pick and idle)
        self.new_button.setToolTip(
            "New selection: pick it in the view"
            if can_pick
            else "Build the geometry first: there is nothing to pick yet."
            if self.view is not None
            else "No viewport is attached."
        )
        stored = "" if self._is_list else str(self._stored)
        self.edit_button.setEnabled(
            can_pick and idle and bool(stored) and stored != ALL_SELECTION
        )
        pending = self.has_pending()
        self.update_button.setVisible(pending)
        self.revert_button.setVisible(pending)
        self.combo.setStyleSheet(_PENDING_STYLE if pending else "")
        if pending:
            self.pending_label.setText(self._pending_text())
        self.pending_label.setVisible(pending)
        self.error_label.setText(self._error)
        self.error_label.setVisible(bool(self._error) and self.picking is None)
        self.updateGeometry()  # the note and the strip change the row's height

    def _pending_text(self) -> str:
        if self._is_list:
            return "Not applied. Update uses this list; Revert goes back."
        new = str(self._working) or NONE_TEXT
        old = str(self._stored) or NONE_TEXT
        return f"Not applied. Update uses {new}; Revert keeps {old}."

    def _fill_entries(self) -> None:
        while self.entries.count():
            item = self.entries.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        model = self.document.model
        can_pick = self.view is not None and self.document.built is not None
        for name in self._working:
            line = QWidget()
            layout = QHBoxLayout(line)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(QLabel(selection_label(model, name)), 1)
            edit = icon_button("edit", f"Edit the entities of {name}")
            edit.setEnabled(
                can_pick and self.picking is None and not self.has_pending()
                and name != ALL_SELECTION
            )
            edit.clicked.connect(lambda _c=False, n=name: self.start_edit(n))
            remove = icon_button("remove", f"Remove {name} from this list")
            remove.clicked.connect(lambda _c=False, n=name: self.remove_entry(n))
            layout.addWidget(edit)
            layout.addWidget(remove)
            line.setObjectName(f"entry_{name}")
            self.entries.addWidget(line)
        if not self._working:
            self.entries.addWidget(QLabel(NONE_TEXT))

    def _highlight(self, name: str) -> None:
        """Show selection ``name`` in the view (nothing for none or a stale one)."""
        if self.view is None or self.document.built is None:
            return
        selection = self.document.model.selections.get(name) if name else None
        if selection is None:
            return
        try:
            tags = resolve_selection(selection, self.document.built)
        except StaleSelectionError:
            return
        self.view.highlight(selection.dim, tags)

    def show_error(self, message: str) -> None:
        """Show a refusal once: in the strip while picking, under the row otherwise."""
        self._error = message
        if self.picking is not None:
            self.name_error.setText(message)
            self.name_error.setVisible(bool(message))
        self.refresh()

    def error_text(self) -> str:
        """The refusal message shown, if any."""
        return self._error

    # ------------------------------------------------------------------- picking
    def _pick_dim(self) -> int:
        dims = self.spec.selection_dims or (1,)
        return 1 if 1 in dims else dims[0]

    def picked(self) -> tuple[int, list[int]]:
        """The ``(dim, tags)`` picked so far."""
        return self._picked[0], list(self._picked[1])

    def start_new(self) -> bool:
        """Start picking a new selection; ``False`` when picking is not possible."""
        if self.view is None or self.document.built is None:
            return False
        self._begin("new")
        dim = self._pick_dim()
        self._picked = (dim, [])
        self.view.highlight(dim, [])
        many = entity_word(dim, self.document.model, plural=True)
        self.strip.confirm_button.setText("Create and add" if self._is_list else "Create and use")
        self.save_as_button.setVisible(False)
        self.name_edit.clear()
        self.name_edit.setPlaceholderText("name of the new selection")
        self.strip.show_pick(
            f"Click the {many} of the new selection in the view "
            "(Ctrl+click adds or removes one).",
            "",
        )
        self._update_strip()
        return True

    def start_edit(self, name: str | None = None) -> bool:
        """Start changing the entities of selection ``name`` (default: the stored one)."""
        name = name if name is not None else ("" if self._is_list else str(self._stored))
        model = self.document.model
        selection = model.selections.get(name) if name else None
        built = self.document.built
        if self.view is None or built is None or selection is None or name == ALL_SELECTION:
            return False
        try:
            tags = resolve_selection(selection, built)
        except StaleSelectionError:
            tags = []
        self._begin("edit")
        self._edit_name = name
        self._picked = (selection.dim, list(tags))
        self.view.highlight(selection.dim, list(tags))
        others = [
            use.label
            for use in selection_users(model, name)
            if use.address != self.owner_address
        ]
        many = entity_word(selection.dim, model, plural=True)
        text = f"Change the {many} of {name} in the view (Ctrl+click adds or removes one)."
        if others:
            text += f" Also used by: {', '.join(others)}."
        self.strip.confirm_button.setText("Save")
        self.save_as_button.setVisible(True)
        self.name_edit.clear()
        self.name_edit.setPlaceholderText("name for Save as new")
        self.strip.show_pick(text, "")
        self._update_strip()
        return True

    def _begin(self, kind: str) -> None:
        assert self.view is not None
        dim = self._pick_dim()
        manager_for(self.view).start(
            self,
            _DIM_MODE[dim],
            cancel=self.cancel_pick,
            confirm=self.confirm_pick,
            strip=self.strip,
        )
        self.picking = kind
        self._error = ""
        self.name_error.setVisible(False)
        if not self._connected:
            self.view.selection_changed.connect(self.on_picked)
            self._connected = True
        self.refresh()

    def on_picked(self, dim: int, tags: list[int]) -> None:
        """Slot of ``selection_changed``: remember the entities of an accepted dimension."""
        if self.picking is None:
            return
        dims = self.spec.selection_dims
        if dim not in _DIM_MODE or (dims is not None and dim not in dims):
            return
        if self.picking == "edit" and dim != self._picked[0]:
            return
        self._picked = (int(dim), [int(t) for t in tags])
        self._update_strip()

    def _name_problem(self) -> str | None:
        """Why the typed name cannot be used ("" for no name yet, ``None`` when fine)."""
        name = self.name_edit.text().strip()
        if not name:
            return ""
        try:
            check_new_selection_name(self.document.model, name)
        except ModelError as exc:
            return str(exc)
        return None

    def _update_strip(self) -> None:
        if self.picking is None:
            return
        dim, tags = self._picked
        model = self.document.model
        self.strip.set_count(
            count_text(len(tags), entity_word(dim, model), entity_word(dim, model, plural=True))
        )
        problem = self._name_problem()
        message = problem or self._error
        self.name_error.setText(message or "")
        self.name_error.setVisible(bool(message))
        name_ok = problem is None
        if self.picking == "new":
            self.strip.set_confirm_enabled(bool(tags) and name_ok)
        else:
            self.strip.set_confirm_enabled(bool(tags))
            self.save_as_button.setEnabled(bool(tags) and name_ok)

    def confirm_pick(self) -> bool:
        """Confirm the pick: create and use (new) or save the entities (edit)."""
        if self.picking == "new":
            return self._create(swap="")
        if self.picking == "edit":
            return self._save_edit()
        return False

    def save_as_new(self) -> bool:
        """Store the picked entities under the typed name and use that selection instead."""
        if self.picking != "edit":
            return False
        return self._create(swap=self._edit_name if self._is_list else "")

    def cancel_pick(self) -> None:
        """End the pick without changing anything (Cancel, Esc, or another pick starts)."""
        if self.picking is None:
            return
        self._end_pick()
        names = self._stored if self._is_list else [self._stored]
        if self.view is not None and self.document.built is not None:
            self.view.highlight(self._pick_dim(), [])
        self._highlight(names[0] if names else "")

    def stop_picking(self) -> None:
        """Stop a running pick (alias of :meth:`cancel_pick`, for panels being replaced)."""
        self.cancel_pick()

    def _end_pick(self) -> None:
        self.picking = None
        self._edit_name = ""
        if self._connected and self.view is not None:
            self.view.selection_changed.disconnect(self.on_picked)
            self._connected = False
        self.strip.hide_pick()
        if self.view is not None:
            manager_for(self.view).finish(self)
        self.refresh()

    def _create(self, swap: str) -> bool:
        dim, tags = self._picked
        if not tags or self._name_problem() is not None:
            return False
        request = SelectionRequest(dim, list(tags), self.name_edit.text().strip(), swap=swap)
        try:
            if self.apply_handler is not None:
                stored = self.apply_handler(request)
            else:
                stored = self._default_apply(request)
        except ModelError as exc:
            self.show_error(str(exc))
            return False
        if stored is None:
            return False  # refused; the handler reported why through show_error
        self._error = ""  # the form reloads the stored value after its edit
        self._end_pick()
        return True

    def _save_edit(self) -> bool:
        dim, tags = self._picked
        name = self._edit_name
        if not tags or not name:
            return False

        def mutate(model: Model) -> None:
            if name == ALL_SELECTION:
                raise ModelError(f"the selection {ALL_SELECTION!r} cannot be edited")
            store_selection(model, self.document.built, SelectionRequest(dim, tags, name))

        try:
            self.document.edit(f"Edit selection {name}", mutate)
        except ModelError as exc:
            self.show_error(str(exc))
            return False
        self._error = ""
        self._end_pick()
        return True

    def _default_apply(self, request: SelectionRequest) -> str | None:
        """Store the selection alone (no field to assign) in one undo step."""

        def mutate(model: Model) -> None:
            check_request_name(model, request)
            store_selection(model, self.document.built, request)

        self.document.edit(f"Create selection {request.name}", mutate)
        return request.name
