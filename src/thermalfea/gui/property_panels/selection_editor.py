"""Editor of a selection-name field: choose an existing selection or pick in the viewport.

"Pick in viewport" switches the :class:`~thermalfea.gui.scene.SceneView` to the selection
mode of the field's geometry dimension and collects its ``selection_changed(dim, tags)``;
"Apply" stores the picked entities as a named selection of the model (with fingerprints,
through ``thermalfea.api.select_*``) in one undo step. The editor works against the
``SceneView`` protocol and the :class:`~thermalfea.gui.document.Document` only.

A field of kind ``selection`` holds one name (``str``); a ``selection_list`` field holds
a list of names, to which Apply and the combo box append.
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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec, unique_name
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.gui.document import Document
from thermalfea.gui.scene import SceneView
from thermalfea.model.model import Model
from thermalfea.model.selections import (
    ALL_SELECTION,
    check_new_selection_name,
    selection_users,
)
from thermalfea.model.vocabulary import entity_word

_DIM_MODE = {0: "point", 1: "curve", 2: "surface"}
_DIM_NAME = {0: "point", 1: "curve", 2: "surface"}  # the pickable dimensions (storage keys)
NONE_TEXT = "(none)"


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
        Name of the field's current selection; typing exactly this name replaces that
        selection's entities (when no other object uses it). Empty: no replacement.
    """

    dim: int
    tags: list[int]
    name: str
    replace: str = ""


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


class SelectionEditor(QWidget):
    """Selection field editor.

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
    name_hint : str
        Base name of the selection Apply creates.
    apply_handler : callable or None
        ``handler(SelectionRequest)`` replaces the default Apply (one ``document.edit``
        that only creates the selection); a form uses it to also set its field in the
        same undo step.
    mode_sync : callable or None
        ``mode_sync(mode)`` shows the selection mode in the main window's toolbar.

    Signals
    -------
    value_changed(object)
        The user chose an existing selection: a name, or the whole list of names.
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
        self._name_hint = spec.name
        self._name_dirty = False
        self._error = ""
        self.apply_handler: Callable[[SelectionRequest], str | None] | None = None
        #: ``sync(mode)`` shows the selection mode in the toolbar (set by whoever creates the
        #: editor in a window; ``None`` leaves the toolbar alone).
        self.mode_sync: Callable[[str], None] | None = None
        self._is_list = spec.kind == "selection_list"
        self._value: str | list[str] = [] if self._is_list else ""
        self._picked: tuple[int, list[int]] = (-1, [])
        self._connected = False

        col = QVBoxLayout(self)
        col.setContentsMargins(0, 0, 0, 0)
        self.current_label = QLabel(NONE_TEXT)
        self.current_label.setWordWrap(True)
        col.addWidget(self.current_label)
        self.combo = QComboBox()
        col.addWidget(self.combo)
        row = QHBoxLayout()
        self.pick_button = QPushButton("Pick in viewport")
        self.pick_button.setCheckable(True)
        self.apply_button = QPushButton("Apply")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("selection name")
        self.name_edit.setToolTip("New name")
        self.name_edit.textEdited.connect(self._on_name_edited)
        row.addWidget(self.pick_button)
        row.addWidget(QLabel("New name"))
        row.addWidget(self.name_edit)
        row.addWidget(self.apply_button)
        if self._is_list:
            self.clear_button = QPushButton("Clear")
            row.addWidget(self.clear_button)
            self.clear_button.clicked.connect(self.clear)
        col.addLayout(row)
        self.status_label = QLabel("")
        col.addWidget(self.status_label)

        self.combo.activated.connect(self._on_activated)
        self.pick_button.toggled.connect(self.set_picking)
        self.apply_button.clicked.connect(self.apply)
        document.geometry_built.connect(self.refresh)
        document.model_changed.connect(self.refresh)
        self.refresh()

    @property
    def name_hint(self) -> str:
        """Base of the suggested selection name; a new hint resets the typed name."""
        return self._name_hint

    @name_hint.setter
    def name_hint(self, hint: str) -> None:
        if hint != self._name_hint:
            self._name_hint = hint
            self._name_dirty = False  # another object: forget what was typed
            self._error = ""
            if hasattr(self, "name_edit"):
                self.name_edit.setText(self.suggest_name())

    # --------------------------------------------------------------------- value
    def value(self) -> str | list[str]:
        """The current selection name (or names)."""
        return list(self._value) if self._is_list else self._value

    def set_value(self, value: str | list[str] | None) -> None:
        """Show ``value`` without emitting :attr:`value_changed`."""
        if self._is_list:
            self._value = list(value or [])  # type: ignore[arg-type]
        else:
            self._value = str(value or "")
        self._update_labels()
        self.refresh()

    def _update_labels(self) -> None:
        names = self._value if self._is_list else [self._value] if self._value else []
        self.current_label.setText(", ".join(names) if names else NONE_TEXT)

    def allowed_names(self) -> list[str]:
        """Names of the model's selections the field accepts."""
        dims = self.spec.selection_dims
        return [
            name
            for name, sel in self.document.model.selections.items()
            if dims is None or sel.dim in dims
        ]

    def refresh(self) -> None:
        """Re-read the available selections and whether picking is possible."""
        self.combo.blockSignals(True)
        self.combo.clear()
        self.combo.addItem("(add existing...)" if self._is_list else NONE_TEXT)
        for name in self.allowed_names():
            self.combo.addItem(name)
        if not self._is_list and self._value:
            index = self.combo.findText(str(self._value))
            self.combo.setCurrentIndex(max(index, 0))
        self.combo.blockSignals(False)
        built = self.document.built is not None and self.view is not None
        self.pick_button.setEnabled(built)
        self.pick_button.setToolTip(
            "Pick entities in the viewport, then press Apply."
            if built
            else "Build the geometry first: there is nothing to pick yet."
            if self.view is not None
            else "No viewport is attached."
        )
        if not built and self.pick_button.isChecked():
            self.pick_button.setChecked(False)
        if not self._name_dirty:
            self.name_edit.setText(self.suggest_name())
        self._update_apply()

    def choose(self, name: str) -> None:
        """Choose an existing selection (what the combo box does); emits the new value."""
        if self._is_list:
            if name and name not in self._value:
                self._value = [*self._value, name]  # type: ignore[misc]
            else:
                return
        else:
            self._value = name
        self._update_labels()
        self.value_changed.emit(self.value())

    def clear(self) -> None:
        """Remove every name from a list field (emits the new value)."""
        self._value = []
        self._update_labels()
        self.value_changed.emit(self.value())

    def _on_activated(self, index: int) -> None:
        text = self.combo.itemText(index)
        self.choose(text if index > 0 else "")

    # ------------------------------------------------------------------- picking
    def _mode(self) -> str:
        dims = self.spec.selection_dims or (1,)
        return _DIM_MODE[dims[0]]

    def set_picking(self, on: bool) -> None:
        """Start or stop collecting the viewport selection."""
        if self.pick_button.isChecked() != on:
            self.pick_button.setChecked(on)  # re-enters through the toggled signal
            return
        if self.view is None:
            return
        if on and self.document.built is not None:
            self._set_mode(self._mode())
            if not self._connected:
                self.view.selection_changed.connect(self.on_picked)
                self._connected = True
        else:
            if self._connected:
                self.view.selection_changed.disconnect(self.on_picked)
                self._connected = False
            self._set_mode("none")

    def _set_mode(self, mode: str) -> None:
        """Set the viewport's selection mode and, if given, the toolbar that shows it."""
        self.view.set_selection_mode(mode)  # type: ignore[arg-type]
        if self.mode_sync is not None:
            self.mode_sync(mode)

    def on_picked(self, dim: int, tags: list[int]) -> None:
        """Slot of ``selection_changed``: remember the entities of an accepted dimension."""
        dims = self.spec.selection_dims
        if dims is not None and dim not in dims:
            return
        if dim not in _DIM_NAME:
            return
        self._picked = (int(dim), [int(t) for t in tags])
        self._error = ""
        self._update_apply()

    def picked(self) -> tuple[int, list[int]]:
        """The ``(dim, tags)`` collected so far."""
        return self._picked[0], list(self._picked[1])

    def _update_apply(self) -> None:
        dim, tags = self._picked
        self.apply_button.setEnabled(bool(tags) and self.document.built is not None)
        self.status_label.setStyleSheet("color: #c0392b;" if self._error else "")
        if self._error:
            self.status_label.setText(self._error)
            return
        if not tags:
            self.status_label.setText("Nothing picked")
            return
        word = entity_word(dim, self.document.model, plural=len(tags) != 1)
        self.status_label.setText(f"{len(tags)} {word} picked")

    # --------------------------------------------------------------------- apply
    def suggest_name(self) -> str:
        """An unused name built from :attr:`name_hint` (never collides)."""
        used = used_selection_names(self.document.model)
        if self.name_hint not in used:
            return self.name_hint
        return unique_name(self.name_hint, used, start=2)

    def target_name(self) -> str:
        """The name Apply will use: what is typed in the "New name" box."""
        return self.name_edit.text().strip()

    def _on_name_edited(self, _text: str) -> None:
        self._name_dirty = True

    def show_error(self, message: str) -> None:
        """Show a refusal in red in the status line (kept until the next pick or success)."""
        self._error = message
        self._update_apply()

    def error_text(self) -> str:
        """The refusal message shown, if any."""
        return self._error

    def apply(self) -> str | None:
        """Store the picked entities as a selection; return its name (``None``: nothing).

        The name is the one typed in :attr:`name_edit` (suggested unused name by default).
        It must pass :func:`~thermalfea.model.selections.check_new_selection_name`, with
        one exception: on a single ``selection`` field, the name of the field's current
        selection may be typed again to replace that selection's entities, provided no
        other object uses it (see :func:`check_request_name`). The check runs inside the
        same ``Document.edit`` mutation that stores the selection (and, with a form's
        ``apply_handler``, assigns the field), so a refusal records no undo step and
        leaves the model unchanged; the message is shown by :meth:`show_error` and the
        typed name is kept. A ``selection_list`` field always creates a new selection.

        Returns
        -------
        str or None
            The stored name, or ``None`` if nothing was picked or the name was refused.
        """
        dim, tags = self._picked
        if not tags:
            return None
        replace = "" if self._is_list else str(self._value)
        request = SelectionRequest(dim, list(tags), self.target_name(), replace)
        try:
            if self.apply_handler is not None:
                stored = self.apply_handler(request)
            else:
                stored = self._default_apply(request)
        except ModelError as exc:
            self.show_error(str(exc))
            return None
        if stored is None:
            return None  # refused; the handler (or the default) reported why
        if self._is_list:
            if stored not in self._value:
                self._value = [*self._value, stored]  # type: ignore[misc]
        else:
            self._value = stored
        self._error = ""
        self._name_dirty = False
        self._update_labels()
        self.refresh()
        return stored

    def _default_apply(self, request: SelectionRequest) -> str | None:
        """Store the selection alone (no field to assign) in one undo step."""

        def mutate(model: Model) -> None:
            check_request_name(model, request)
            store_selection(model, self.document.built, request)

        self.document.edit(f"Create selection {request.name}", mutate)
        return request.name
