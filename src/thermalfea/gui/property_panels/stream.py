"""Property panel of a flow stream (Plan M8.12).

:class:`StreamPanel` is the generated form of :class:`~thermalfea.model.bcs.Stream`
(:data:`thermalfea.model.flow_forms.STREAM_FORM`) with three additions:

* the fluid is a combo box of the library fluids;
* "Pick path points": while the toggle is on, each ``point_picked`` click of the viewport
  appends ``(x, y)`` to the stream's ``path``, one undo step per point;
* "Clear path" empties the path (one undo step).

Walls are picked by the selection-list field of the form (the normal selection editor).
Clicks are ignored while the toggle is off: the viewport signal is connected only then.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec, FormSpec
from thermalfea.gui.addressing import Address, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.scene import SceneView
from thermalfea.materials import library


class StreamPanel(FormPanel):
    """Form of a stream with fluid choices and path picking in the viewport.

    Parameters
    ----------
    spec : FormSpec
        The form of ``Stream``.
    document : Document
    address : tuple
        Address ``("streams", i)``.
    view : SceneView, optional
        Viewport: its ``point_picked`` clicks add path points while the toggle is on.
    parent : QWidget, optional

    Attributes
    ----------
    pick_button : QPushButton
        Checkable "Pick path points" toggle (disabled without a viewport).
    clear_button : QPushButton
        "Clear path".
    path_label : QLabel
        Number of path points.
    """

    _ready = False

    def __init__(
        self,
        spec: FormSpec,
        document: Document,
        address: Address,
        view: SceneView | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(spec, document, address, view, parent)
        self._connected = False

        box = QGroupBox("Path")
        outer = QVBoxLayout(box)
        self.pick_button = QPushButton("Pick path points")
        self.pick_button.setCheckable(True)
        self.pick_button.setEnabled(view is not None)
        self.pick_button.setToolTip("While on, each click in the viewport adds a path point.")
        self.clear_button = QPushButton("Clear path")
        self.path_label = QLabel()
        row = QHBoxLayout()
        row.addWidget(self.pick_button)
        row.addWidget(self.clear_button)
        outer.addLayout(row)
        outer.addWidget(self.path_label)
        self.pick_button.toggled.connect(self.set_path_picking)
        self.clear_button.clicked.connect(lambda _checked=False: self.clear_path())

        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        layout.insertWidget(layout.count() - 1, box)  # before the stretch
        self._ready = True
        self.refresh()

    # ------------------------------------------------------------------ form hooks
    def field_choices(self, field: FieldSpec) -> tuple[str, ...] | None:
        """Offer the library fluids for the fluid field."""
        if field.name == "fluid":
            return tuple(library.fluid_names())
        return None

    def refresh(self) -> None:
        """Reload the form and the path count."""
        super().refresh()
        if not self._ready:
            return
        try:
            stream = self.current_object()
        except ModelError:
            return
        count = len(stream.path or [])
        self.path_label.setText(f"{count} path point{'s' if count != 1 else ''}")

    # --------------------------------------------------------------- path picking
    def set_path_picking(self, on: bool) -> None:
        """Start (``True``) or stop collecting viewport clicks as path points."""
        if self.view is None:
            return
        if on:
            self.view.set_selection_mode("none")  # type: ignore[arg-type]
            if not self._connected:
                self.view.point_picked.connect(self._on_point_picked)
                self._connected = True
        elif self._connected:
            self.view.point_picked.disconnect(self._on_point_picked)
            self._connected = False

    def _on_point_picked(self, x: float, y: float, _z: float) -> None:
        if not self.pick_button.isChecked():
            return
        self.add_path_point(x, y)

    def add_path_point(self, x: float, y: float) -> bool:
        """Append ``(x, y)`` to the path through ``document.edit``; ``False`` if rejected."""
        point = (float(x), float(y))

        def mutate(model: Any) -> None:
            stream = resolve(model, self.address)
            self._set_attribute(model, "path", [*(stream.path or []), point])

        try:
            changed = self.document.edit("Add path point", mutate)
        except ModelError as exc:
            self._set_error("path", str(exc))
            return False
        self._set_error("path", "")
        return changed

    def clear_path(self) -> bool:
        """Empty the path (one undo step); ``False`` if it was already empty."""
        def mutate(model: Any) -> None:
            self._set_attribute(model, "path", [])

        return self.document.edit("Clear path", mutate)


