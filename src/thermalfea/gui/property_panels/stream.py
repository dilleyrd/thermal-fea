"""Property panel of a flow stream (Plan M8.12).

:class:`StreamPanel` is the generated form of :class:`~thermalfea.model.bcs.Stream`
(:data:`thermalfea.model.flow_forms.STREAM_FORM`) with three additions:

* the fluid is a combo box of the library fluids;
* "Pick path" starts a pick of the one pick workflow (convention C2,
  :mod:`thermalfea.gui.pick`): each click in the view adds a point of a new path, drawn in
  the view as numbered markers joined by a line (overlay layer ``"stream_path"``) and
  counted in the strip; "Use path" or Enter (from two points on) stores the path in one
  undo step, Cancel or Esc changes nothing;
* "Clear path" empties the path (one undo step).

Walls are picked by the selection-list field of the form (the normal selection editor).
Clicks are ignored while no path pick runs: the viewport signal is connected only then.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec, FormSpec
from thermalfea.gui.addressing import Address, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.pick import PickStrip, manager_for
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.scene import OverlayMarker, OverlayPolyline, SceneView
from thermalfea.materials import library

#: Viewport overlay layer of the path being picked.
PATH_LAYER = "stream_path"


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
        Viewport: its ``point_picked`` clicks add path points while a path pick runs.
    parent : QWidget, optional

    Attributes
    ----------
    pick_button : QPushButton
        "Pick path" (disabled without a viewport and while picking).
    clear_button : QPushButton
        "Clear path".
    path_label : QLabel
        Number of path points.
    strip : PickStrip
        Shown while picking: instruction, count, "Use path" and Cancel.
    pending : list of (float, float)
        The points picked so far (stored only on confirm).
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
        self.picking = False
        self.pending: list[tuple[float, float]] = []

        box = QGroupBox("Path")
        outer = QVBoxLayout(box)
        self.pick_button = QPushButton("Pick path")
        self.pick_button.setEnabled(view is not None)
        self.pick_button.setToolTip("Click the points of a new path in the view, inlet first.")
        self.clear_button = QPushButton("Clear path")
        self.path_label = QLabel()
        row = QHBoxLayout()
        row.addWidget(self.pick_button)
        row.addWidget(self.clear_button)
        outer.addLayout(row)
        outer.addWidget(self.path_label)
        self.strip = PickStrip("Use path")
        self.strip.confirmed.connect(self.confirm_path)
        self.strip.cancelled.connect(self.cancel_path)
        outer.addWidget(self.strip)
        self.pick_button.clicked.connect(lambda _checked=False: self.start_path())
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
    def start_path(self) -> bool:
        """Start picking a new path (one pick at a time); ``False`` without a viewport."""
        if self.view is None:
            return False
        manager_for(self.view).start(
            self, "none", cancel=self.cancel_path, confirm=self.confirm_path, strip=self.strip
        )
        self.picking = True
        self.pending = []
        if not self._connected:
            self.view.point_picked.connect(self._on_point_picked)
            self._connected = True
        self.strip.show_pick(
            "Click the points of the path in the view, from the inlet to the outlet.",
            self._count(),
        )
        self.strip.set_confirm_enabled(False)
        self.pick_button.setEnabled(False)
        self._draw_pending()
        return True

    def confirm_path(self) -> bool:
        """Store the picked points as the path (one undo step); needs at least two."""
        if not self.picking or len(self.pending) < 2:
            return False
        points = list(self.pending)
        self._end_path()

        def mutate(model: Any) -> None:
            self._set_attribute(model, "path", points)

        try:
            changed = self.document.edit("Set path", mutate)
        except ModelError as exc:
            self._set_error("path", str(exc))
            return False
        self._set_error("path", "")
        return changed

    def cancel_path(self) -> None:
        """End the path pick without changing the stream."""
        if self.picking:
            self._end_path()

    def _end_path(self) -> None:
        self.picking = False
        self.pending = []
        if self._connected and self.view is not None:
            self.view.point_picked.disconnect(self._on_point_picked)
            self._connected = False
        self.strip.hide_pick()
        self.pick_button.setEnabled(self.view is not None)
        self._draw_pending()
        if self.view is not None:
            manager_for(self.view).finish(self)

    def _count(self) -> str:
        n = len(self.pending)
        return f"{n} path point{'' if n == 1 else 's'}" + (" (two needed)" if n < 2 else "")

    def _draw_pending(self) -> None:
        if self.view is None:
            return
        items: list[Any] = []
        if len(self.pending) >= 2:
            items.append(OverlayPolyline(list(self.pending)))
        items += [OverlayMarker(x, y, str(i + 1)) for i, (x, y) in enumerate(self.pending)]
        self.view.set_overlay(PATH_LAYER, items)

    def _on_point_picked(self, x: float, y: float, _z: float) -> None:
        if not self.picking:
            return
        self.pending.append((float(x), float(y)))
        self.strip.set_count(self._count())
        self.strip.set_confirm_enabled(len(self.pending) >= 2)
        self._draw_pending()

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


