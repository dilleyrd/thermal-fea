"""Nodal history items (held item 14; conventions C2, C3, C10; task M11.76).

A nodal history is a saved result item (:class:`~thermalfea.model.result_items.HistoryItem`,
Data §3a): the positions of some nodes and the field to plot. It lives in the Results
section of the tree beside the contours, with a panel that holds

* the node list (node number, coordinates, the displayed value), each with ✕;
* "Pick nodes" (the pick icon): a pick of the one pick workflow (C2) in Node mode that
  starts from the item's nodes; Ctrl+click adds or removes one, "Use nodes" or Enter
  stores them in one undo step, Cancel or Esc changes nothing;
* the quantity, "Plot" and the eye toggle "Show the nodes in the view".

The item stores *positions* (node numbers change when the mesh is regenerated); each is
matched to the nearest node of the results' mesh when shown. The nodes are marked in the
view with their numbers ("node 412", overlay layer ``"history:<name>"``), the same
numbers as the chart's legend. The chart is drawn from the item: a new solve, or a change
of the nodes, draws it again.

Results > Nodal history... adds an item with the nodes selected in the view (or none, and
then starts picking) and opens its panel.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError, ThermalFEAError
from thermalfea.core.forms import copy_name, unique_name
from thermalfea.core.units import from_si, unit_label
from thermalfea.gui.document import Document
from thermalfea.gui.icons import icon_button
from thermalfea.gui.pick import PickStrip, count_text, manager_for
from thermalfea.gui.scene import NODE_DIM, OverlayMarker, SceneView
from thermalfea.model.result_items import HistoryItem
from thermalfea.post.plots import history_data, nearest_nodes

#: Tree address section of the nodal history items.
HISTORY_ADDRESS = "history"
#: Base name of a new nodal history.
HISTORY_NAME = "Nodal history"


def history_layer(name: str) -> str:
    """The viewport overlay layer of a history's node markers."""
    return f"history:{name}"


class HistoryController(QObject):
    """The nodal history items: tree provider, edits, view markers and charts.

    Parameters
    ----------
    window : MainWindow
    document : Document
    view : SceneView
    results_controller : ResultController
        Gives the current results.
    charts : ChartController
        Opens the chart windows.

    Signals
    -------
    objects_changed
        Items were added, removed or renamed (the tree rebuilds).
    """

    objects_changed = Signal()

    def __init__(
        self, window: Any, document: Document, view: SceneView, results_controller: Any,
        charts: Any,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.view = view
        self.results_controller = results_controller
        self.charts = charts
        self.tree: Any = None
        self._names: list[str] = []
        self._charts: dict[str, Any] = {}
        self._layers: set[str] = set()
        document.model_changed.connect(self._on_changed)
        document.results_changed.connect(self._on_changed)

    # ------------------------------------------------------------------- items
    def items(self) -> list[HistoryItem]:
        """The model's nodal history items."""
        return [i for i in self.document.model.result_items if isinstance(i, HistoryItem)]

    def get(self, name: str) -> HistoryItem | None:
        """The item called ``name``, or ``None``."""
        return next((i for i in self.items() if i.name == name), None)

    def _all_names(self) -> list[str]:
        return [i.name for i in self.document.model.result_items]

    def _edit(self, text: str, change: Callable[[list[Any]], list[Any]]) -> bool:
        def mutate(model: Any) -> None:
            model.result_items = change(list(model.result_items))

        return self.document.edit(text, mutate)

    def add(self, points: list[tuple[float, float]] | None = None) -> str:
        """Add an item with ``points`` [m] (one undo step), select it; return its name."""
        name = unique_name(HISTORY_NAME, self._all_names())
        item = HistoryItem(name, [(float(x), float(y)) for x, y in (points or [])])
        self._edit(f"Add {name}", lambda items: [*items, item])
        if self.tree is not None:
            self.tree.select_address((HISTORY_ADDRESS, name))
        return name

    def _replace(self, name: str, text: str, **changes: Any) -> bool:
        def change(items: list[Any]) -> list[Any]:
            out = []
            for i in items:
                if isinstance(i, HistoryItem) and i.name == name:
                    i = HistoryItem(**{**i.__dict__, **changes})
                out.append(i)
            return out

        return self._edit(text, change)

    def set_points(self, name: str, points: list[tuple[float, float]]) -> bool:
        """Store the item's node positions (one undo step)."""
        clean = [(float(x), float(y)) for x, y in points]
        return self._replace(name, f"Set the nodes of {name}", points=clean)

    def set_visible(self, name: str, visible: bool) -> bool:
        """The eye toggle: show or hide the item's node markers."""
        return self._replace(name, f"{'Show' if visible else 'Hide'} {name}", visible=visible)

    def rename(self, address: tuple, new_name: str) -> bool:
        """Rename an item (inline rename in the tree)."""
        name, new = address[1], new_name.strip()
        if not new:
            raise ModelError("a name cannot be empty")
        if new == name:
            return False
        if new in self._all_names():
            raise ModelError(f"the name {new!r} is already used")
        if name in self._charts:
            self._charts[new] = self._charts.pop(name)
        return self._replace(name, f"Rename {name}", name=new)

    def duplicate(self, name: str) -> str:
        """Copy an item under a new name (one undo step)."""
        item = self.get(name)
        if item is None:
            raise ModelError(f"there is no nodal history {name!r}")
        copy = HistoryItem(**{**item.__dict__, "name": copy_name(name, self._all_names())})
        self._edit(f"Duplicate {name}", lambda items: [*items, copy])
        return copy.name

    def delete(self, name: str) -> bool:
        """Delete an item (one undo step); its chart closes."""
        chart = self._charts.pop(name, None)
        if chart is not None:
            chart.close()
        return self._edit(
            f"Delete {name}",
            lambda items: [i for i in items if not (isinstance(i, HistoryItem) and i.name == name)],
        )

    # ------------------------------------------------------------------- nodes
    def mesh(self) -> Any:
        """The mesh the node numbers belong to: the results' mesh, else the document's."""
        results = self.results_controller.results
        return results.mesh if results is not None else self.document.mesh

    def nodes_of(self, item: HistoryItem) -> list[int]:
        """The node numbers nearest the item's positions (empty without a mesh)."""
        mesh = self.mesh()
        if mesh is None or not item.points:
            return []
        return [int(n) for n in nearest_nodes(mesh, item.points)]

    def points_of(self, nodes: list[int]) -> list[tuple[float, float]]:
        """The positions [m] of node numbers of the current mesh."""
        mesh = self.mesh()
        if mesh is None:
            return []
        return [(float(mesh.nodes[n, 0]), float(mesh.nodes[n, 1])) for n in nodes]

    # ------------------------------------------------------------------- view
    def _on_changed(self) -> None:
        names = [i.name for i in self.items()]
        if names != self._names:
            self._names = names
            self.objects_changed.emit()
        self._draw_markers()
        for name, chart in list(self._charts.items()):
            try:
                gone = self.get(name) is None or not chart.isVisible()
            except RuntimeError:  # the chart window was closed and deleted
                gone = True
            if gone:
                self._charts.pop(name, None)
            elif chart.redraw is not None:
                try:
                    chart.redraw()
                except (ThermalFEAError, OSError, KeyError, ValueError):
                    chart.mark_out_of_date()

    def _draw_markers(self) -> None:
        mesh = self.mesh()
        wanted: set[str] = set()
        for item in self.items():
            layer = history_layer(item.name)
            if not item.visible or mesh is None:
                continue
            wanted.add(layer)
            markers = [
                OverlayMarker(float(mesh.nodes[n, 0]), float(mesh.nodes[n, 1]), f"node {n}")
                for n in self.nodes_of(item)
            ]
            self.view.set_overlay(layer, markers)
        for layer in self._layers - wanted:
            self.view.set_overlay(layer, [])
        self._layers = wanted

    # ------------------------------------------------------------------ chart
    def plot(self, name: str) -> Any:
        """Open (or draw again) the item's chart; ``None`` without results or nodes."""
        item = self.get(name)
        if item is None or not item.points or self.results_controller.results is None:
            return None
        chart = self._charts.get(name)
        try:
            alive = chart is not None and chart.isVisible()
        except RuntimeError:  # closed and deleted
            alive = False
            self._charts.pop(name, None)
        if alive and chart.redraw is not None:
            chart.redraw()
            chart.raise_()
            return chart

        def draw(window: Any, name: str = name) -> None:
            current = self.get(name)
            results = self.results_controller.results
            if current is None or results is None or not current.points:
                raise ThermalFEAError("the nodal history has no nodes or there are no results")
            window.show_history(history_data(results, points=current.points))

        chart = self.charts._open_renewable(draw)
        if chart is not None:
            self._charts[name] = chart
        return chart

    def request(self, selected_nodes: list[int]) -> str:
        """Results > Nodal history...: add an item with the selected nodes, open its panel."""
        name = self.add(self.points_of(selected_nodes))
        if not selected_nodes:  # nothing selected: pick the nodes in the new item's panel
            for panel in self.window.findChildren(HistoryPanel):
                if panel.name == name:
                    panel.start_pick()
                    break
        return name

    # ------------------------------------------------------ tree provider API
    def tree_items(self) -> list[tuple[str, tuple, bool]]:
        """The children of the Results node: ``(text, address, renameable)``."""
        return [(i.name, (HISTORY_ADDRESS, i.name), True) for i in self.items()]

    def tree_summary(self, address: tuple) -> str:
        """``history · 2 nodes`` (and "hidden" when its eye is off)."""
        item = self.get(address[1]) if len(address) > 1 else None
        if item is None:
            return ""
        n = len(item.points)
        text = f"history · {n} node{'s' if n != 1 else ''}"
        return text if item.visible else f"{text} · hidden"

    def owns(self, address: tuple) -> bool:
        """Whether an address is a nodal history's."""
        return bool(address) and address[0] == HISTORY_ADDRESS

    def tree_actions(self, address: tuple | None) -> list[tuple[str, Callable[[], object], Any]]:
        """Context-menu actions of the Results node (``None``) or of one item."""
        if address is None:
            return [("Add nodal history", lambda: self.add(), ("add_result", "history"))]
        name = address[1]
        out: list[tuple[str, Callable[[], object], Any]] = [
            ("Plot", lambda: self.plot(name), ("plot_history", address)),
        ]
        if self.tree is not None:
            out.append(("Rename", lambda: self.tree.begin_rename(address), ("rename", address)))
        out.append(("Duplicate", lambda: self.duplicate(name), ("duplicate", address)))
        out.append(("Delete", lambda: self.delete(name), ("delete", address)))
        return out


class HistoryPanel(QWidget):
    """Panel of a nodal history item: nodes, pick, quantity, Plot and the eye toggle."""

    def __init__(self, controller: HistoryController, name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self.name = name
        self.picking = False
        self._picked: list[int] = []
        self._connected = False
        column = QVBoxLayout(self)
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: bold;")
        column.addWidget(self.title_label)
        column.addWidget(QLabel("The history of a field at chosen nodes, plotted against time."))
        self.visible_check = QCheckBox("Show the nodes in the view")
        self.visible_check.toggled.connect(self._on_visible)
        column.addWidget(self.visible_check)
        self.nodes_box = QVBoxLayout()
        column.addLayout(self.nodes_box)
        self.pick_button = icon_button("pick", "Pick the nodes in the view")
        self.pick_button.setText("Pick nodes")
        self.pick_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.pick_button.clicked.connect(lambda _c=False: self.start_pick())
        column.addWidget(self.pick_button)
        self.strip = PickStrip("Use nodes")
        self.strip.confirmed.connect(self.confirm_pick)
        self.strip.cancelled.connect(self.cancel_pick)
        column.addWidget(self.strip)
        row = QHBoxLayout()
        row.addWidget(QLabel("Quantity"))
        self.field_combo = QComboBox()
        self.field_combo.addItem("Temperature", "T")
        row.addWidget(self.field_combo, 1)
        column.addLayout(row)
        self.plot_button = QPushButton("Plot")
        self.plot_button.clicked.connect(lambda _c=False: self.controller.plot(self.name))
        column.addWidget(self.plot_button)
        column.addStretch(1)
        controller.document.model_changed.connect(self.refresh)
        controller.document.results_changed.connect(self.refresh)
        self.refresh()

    # ----------------------------------------------------------------- display
    def refresh(self) -> None:
        """Show the item's nodes and state."""
        item = self.controller.get(self.name)
        if item is None:
            return
        self.title_label.setText(f"Nodal history: {self.name}")
        self.visible_check.blockSignals(True)
        self.visible_check.setChecked(item.visible)
        self.visible_check.blockSignals(False)
        while self.nodes_box.count():
            widget = self.nodes_box.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        mesh = self.controller.mesh()
        nodes = self.controller.nodes_of(item)
        units = self.controller.document.model.display_units
        unit = unit_label("length", units)
        for k, n in enumerate(nodes):
            line = QWidget()
            layout = QHBoxLayout(line)
            layout.setContentsMargins(0, 0, 0, 0)
            x, y = (float(from_si(v, "length", units)) for v in mesh.nodes[n, :2])
            layout.addWidget(QLabel(f"node {n} · ({x:.4g}, {y:.4g}) {unit}"), 1)
            remove = icon_button("remove", f"Remove node {n}")
            remove.clicked.connect(lambda _c=False, k=k: self._remove(k))
            layout.addWidget(remove)
            self.nodes_box.addWidget(line)
        if not item.points:
            self.nodes_box.addWidget(QLabel("No nodes yet: pick them in the view."))
        elif not nodes:
            self.nodes_box.addWidget(QLabel(f"{len(item.points)} nodes (no mesh yet)"))
        has_results = self.controller.results_controller.results is not None
        self.plot_button.setEnabled(has_results and bool(item.points))
        self.pick_button.setEnabled(mesh is not None and not self.picking)

    def _on_visible(self, on: bool) -> None:
        self.controller.set_visible(self.name, bool(on))

    def _remove(self, k: int) -> None:
        item = self.controller.get(self.name)
        if item is not None:
            points = [p for i, p in enumerate(item.points) if i != k]
            self.controller.set_points(self.name, points)

    # ----------------------------------------------------------------- picking
    def start_pick(self) -> bool:
        """Pick the nodes in the view, starting from the item's nodes (C2)."""
        view = self.controller.view
        item = self.controller.get(self.name)
        if view is None or item is None or self.controller.mesh() is None:
            return False
        manager_for(view).start(
            self, "node", cancel=self.cancel_pick, confirm=self.confirm_pick, strip=self.strip
        )
        self.picking = True
        self._picked = self.controller.nodes_of(item)
        view.highlight(NODE_DIM, list(self._picked))
        if not self._connected:
            view.selection_changed.connect(self._on_picked)
            self._connected = True
        self.strip.show_pick(
            "Click the nodes in the view (Ctrl+click adds or removes one).",
            count_text(len(self._picked), "node"),
        )
        self.refresh()
        return True

    def _on_picked(self, dim: int, tags: list[int]) -> None:
        if self.picking and dim == NODE_DIM:
            self._picked = [int(t) for t in tags]
            self.strip.set_count(count_text(len(self._picked), "node"))

    def confirm_pick(self) -> bool:
        """Store the picked nodes (one undo step) and end the pick."""
        if not self.picking:
            return False
        points = self.controller.points_of(self._picked)
        self._end_pick()
        return self.controller.set_points(self.name, points)

    def cancel_pick(self) -> None:
        """End the pick without changing the item."""
        if self.picking:
            self._end_pick()

    def _end_pick(self) -> None:
        self.picking = False
        view = self.controller.view
        if self._connected and view is not None:
            view.selection_changed.disconnect(self._on_picked)
            self._connected = False
        self.strip.hide_pick()
        if view is not None:
            manager_for(view).finish(self)
        self.refresh()


def attach_history(window: Any, document: Document, view: SceneView, results: Any,
                   charts: Any) -> HistoryController:
    """Install the nodal history items: tree provider, panel and Results > Nodal history."""
    controller = HistoryController(window, document, view, results, charts)
    tree = window.tree_widget
    if hasattr(tree, "add_provider"):
        controller.tree = tree
        tree.add_provider(controller)
    props = getattr(tree, "property_controller", None)
    if props is not None:
        props.history_controller = controller
    charts.history_items = controller
    controller._on_changed()
    return controller


__all__ = [
    "HISTORY_ADDRESS", "HistoryController", "HistoryPanel", "attach_history", "history_layer",
]
