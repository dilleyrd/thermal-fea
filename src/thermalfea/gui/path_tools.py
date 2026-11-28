"""Path plot items (held item 15; conventions C1, C2, C3, C8, C10; task M11.77).

A path plot is a saved result item (:class:`~thermalfea.model.result_items.PathItem`,
Data §3a) in the Results section of the tree, after Ansys Mechanical (path by two points
or edges, sampling points, snap to nodes), Abaqus/CAE (point and edge list paths; x-value
choice) and COMSOL (cut line; line graph along a boundary selection). Its panel has two
boxes:

**Path**, defined by
  * *Two points* — A and B typed, or picked with the pick icon beside each; "Snap to the
    nearest nodes"; the number of samples;
  * *Along boundaries* — a boundary selection (the selection field, with its Update rule)
    whose curves join end to end; the samples are the mesh nodes on them (refused with a
    message when the curves do not form one chain);
  * *Points* — a table of points, typed or picked, with + and ✕;
  and "Run from B to A".

**Plot**: the quantity; the times (empty: the displayed step; several are overlaid on one
chart); the horizontal axis — distance along the path, x or y (r or z in an axisymmetric
model); "Plot". The chart is drawn from the item, so changing the item or a new solve
draws it again.

The path of every visible item is drawn in the view with its ends labelled A and B (overlay
layer ``"path:<name>"``). Results > Path plot... adds an item and opens its panel.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from numpy import ndarray
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError, ThermalFEAError
from thermalfea.core.forms import FieldSpec, copy_name, unique_name
from thermalfea.core.units import UnitSettings, from_si, to_si, unit_label
from thermalfea.gui.document import Document
from thermalfea.gui.icons import icon_button
from thermalfea.gui.pick import PickStrip, manager_for
from thermalfea.gui.property_panels.sections import Box, SectionBox
from thermalfea.gui.property_panels.selection_editor import SelectionEditor
from thermalfea.gui.scene import OverlayMarker, OverlayPolyline, SceneView
from thermalfea.model.result_items import PathItem
from thermalfea.model.selections import StaleSelectionError
from thermalfea.model.selections import resolve as resolve_selection
from thermalfea.post.path import polyline_points, values_at
from thermalfea.post.plots import (
    FIELDS,
    HistoryData,
    field_display_values,
    nearest_nodes,
    step_time_text,
)

#: Tree address section of the path plot items.
PATH_ADDRESS = "path"
#: Base name of a new path plot.
PATH_NAME = "Path"
#: ``(kind, text)`` of "Defined by" (C8).
PATH_KINDS = (("two_points", "Two points"), ("boundaries", "Along boundaries"),
              ("points", "Points"))  # fmt: skip
_JOIN_TOL = 1e-9  # m: curve ends closer than this join


def path_layer(name: str) -> str:
    """The viewport overlay layer of a path plot's drawing."""
    return f"path:{name}"


# ------------------------------------------------------------------ path geometry
def chain_polylines(lines: list[ndarray], tol: float = _JOIN_TOL) -> ndarray:
    """Join curve polylines end to end into one polyline.

    Raises
    ------
    ModelError
        When the curves do not form one chain.
    """
    if not lines:
        raise ModelError("the path needs a boundary selection")
    pieces = [np.asarray(line, dtype=float)[:, :2] for line in lines]
    chain = pieces.pop(0)
    scale = max(float(np.ptp(np.vstack([chain, *pieces]), axis=0).max()), 1.0)
    while pieces:
        for i, piece in enumerate(pieces):
            if np.linalg.norm(piece[0] - chain[-1]) <= tol * scale:
                chain = np.vstack([chain, piece[1:]])
            elif np.linalg.norm(piece[-1] - chain[-1]) <= tol * scale:
                chain = np.vstack([chain, piece[::-1][1:]])
            elif np.linalg.norm(piece[-1] - chain[0]) <= tol * scale:
                chain = np.vstack([piece[:-1], chain])
            elif np.linalg.norm(piece[0] - chain[0]) <= tol * scale:
                chain = np.vstack([piece[::-1][:-1], chain])
            else:
                continue
            pieces.pop(i)
            break
        else:
            raise ModelError("the boundaries of the path do not join end to end")
    return chain


def project_on(chain: ndarray, points: ndarray) -> ndarray:
    """Arc length along ``chain`` of the closest point to each of ``points``."""
    a, b = chain[:-1], chain[1:]
    seg = b - a
    length = np.linalg.norm(seg, axis=1)
    start = np.concatenate([[0.0], np.cumsum(length)])[:-1]
    out = np.empty(len(points))
    for k, p in enumerate(points):
        t = np.clip(np.einsum("ij,ij->i", p - a, seg) / np.maximum(length**2, 1e-300), 0, 1)
        d = np.linalg.norm(a + t[:, None] * seg - p, axis=1)
        j = int(np.argmin(d))
        out[k] = start[j] + t[j] * length[j]
    return out


def path_points(item: PathItem, mesh: Any, built: Any, model: Any) -> tuple[ndarray, ndarray]:
    """The sample positions [m] of a path and their arc length [m] along it.

    Raises
    ------
    ModelError
        For a path that is not complete (fewer than two points, no selection, a chain that
        does not join).
    """
    if item.kind == "boundaries":
        selection = model.selections.get(item.selection)
        if selection is None or built is None:
            raise ModelError("choose a boundary selection for the path")
        try:
            tags = resolve_selection(selection, built)
        except StaleSelectionError:
            raise ModelError(f"the selection {item.selection!r} is stale") from None
        chain = chain_polylines([built.curve_polylines[t] for t in tags])
        nodes = None
        if mesh is not None and item.selection in getattr(mesh, "node_sets", {}):
            nodes = np.asarray(mesh.node_sets[item.selection], dtype=int)
        if nodes is not None and nodes.size >= 2:  # noqa: PLR2004
            xy = np.asarray(mesh.nodes[nodes, :2], dtype=float)
            s = project_on(chain, xy)
            order = np.argsort(s)
            xy, s = xy[order], s[order]
        else:
            s, xy = polyline_points(chain, max(int(item.samples), 2))
    else:
        points = [tuple(p) for p in item.points]
        if len(points) < 2:  # noqa: PLR2004
            raise ModelError("the path needs at least two points")
        if item.kind == "two_points":
            points = points[:2]
            if item.snap and mesh is not None:
                index = nearest_nodes(mesh, points)
                points = [tuple(map(float, mesh.nodes[i, :2])) for i in index]
        s, xy = polyline_points(points, max(int(item.samples), 2))
    if item.reverse:
        xy, s = xy[::-1], (s[-1] - s)[::-1]
    return np.asarray(xy, dtype=float), np.asarray(s, dtype=float)


def path_chart_data(
    item: PathItem, results: Any, mesh: Any, built: Any, model: Any, shown_step: int
) -> HistoryData:
    """The chart of a path item: one curve per time against distance, x or y."""
    xy, s = path_points(item, mesh, built, model)
    units = getattr(results, "display_units", None) or UnitSettings()
    if item.field not in FIELDS:
        raise ModelError(f"unknown path quantity {item.field!r}")
    name = FIELDS[item.field][3]
    times = np.asarray(results.times, dtype=float)
    steps = (
        [int(np.argmin(np.abs(times - t))) for t in item.times] if item.times else [shown_step]
    )
    axisym = getattr(model, "axisymmetric", False)
    axis_names = {"x": "r" if axisym else "x", "y": "z" if axisym else "y"}
    length = unit_label("length", units)
    if item.axis == "distance":
        horizontal, xlabel = s, f"Distance along the path [{length}]"
    else:
        column = 0 if item.axis == "x" else 1
        horizontal, xlabel = xy[:, column], f"{axis_names[item.axis]} [{length}]"
    horizontal = np.asarray(from_si(horizontal, "length", units), dtype=float)
    series: dict[str, ndarray] = {}
    unit = ""
    for step in steps:
        values, unit = field_display_values(item.field, values_at(results, step, xy, item.field),
                                            units)  # fmt: skip
        series[step_time_text(results, float(times[step]), units)] = np.asarray(values, float)
    return HistoryData(
        times=horizontal, series=series, ylabel=f"{name} [{unit}]",
        title=f"{name} along {item.name}", xlabel=xlabel,
    )  # fmt: skip


# --------------------------------------------------------------------- controller
class PathController(QObject):
    """The path plot items: tree provider, edits, view drawings and charts."""

    objects_changed = Signal()

    def __init__(self, window: Any, document: Document, view: SceneView, results: Any,
                 charts: Any) -> None:  # fmt: skip
        super().__init__(window)
        self.window = window
        self.document = document
        self.view = view
        self.results_controller = results
        self.charts = charts
        self.tree: Any = None
        self._names: list[str] = []
        self._charts: dict[str, Any] = {}
        self._layers: set[str] = set()
        document.model_changed.connect(self._on_changed)
        document.results_changed.connect(self._on_changed)
        document.geometry_built.connect(self._on_changed)

    def items(self) -> list[PathItem]:
        """The model's path plot items."""
        return [i for i in self.document.model.result_items if isinstance(i, PathItem)]

    def get(self, name: str) -> PathItem | None:
        """The item called ``name``, or ``None``."""
        return next((i for i in self.items() if i.name == name), None)

    def _all_names(self) -> list[str]:
        return [i.name for i in self.document.model.result_items]

    def _edit(self, text: str, change: Callable[[list[Any]], list[Any]]) -> bool:
        def mutate(model: Any) -> None:
            model.result_items = change(list(model.result_items))

        return self.document.edit(text, mutate)

    def add(self, kind: str = "two_points") -> str:
        """Add a path item (one undo step), select it in the tree; return its name."""
        name = unique_name(PATH_NAME, self._all_names())
        item = PathItem(name, kind=kind)  # type: ignore[arg-type]
        self._edit(f"Add {name}", lambda items: [*items, item])
        if self.tree is not None:
            self.tree.select_address((PATH_ADDRESS, name))
        return name

    def update(self, name: str, **changes: Any) -> bool:
        """Change settings of an item (one undo step)."""
        item = self.get(name)
        if item is None:
            raise ModelError(f"there is no path plot {name!r}")
        new = PathItem(**{**item.__dict__, **changes})

        def change(items: list[Any]) -> list[Any]:
            return [new if isinstance(i, PathItem) and i.name == name else i for i in items]

        return self._edit(f"Edit {name}", change)

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
        return self.update(name, name=new)

    def duplicate(self, name: str) -> str:
        """Copy an item under a new name (one undo step)."""
        item = self.get(name)
        if item is None:
            raise ModelError(f"there is no path plot {name!r}")
        copy = PathItem(**{**item.__dict__, "name": copy_name(name, self._all_names())})
        self._edit(f"Duplicate {name}", lambda items: [*items, copy])
        return copy.name

    def delete(self, name: str) -> bool:
        """Delete an item (one undo step); its chart closes."""
        chart = self._charts.pop(name, None)
        if chart is not None:
            chart.close()
        return self._edit(
            f"Delete {name}",
            lambda items: [i for i in items if not (isinstance(i, PathItem) and i.name == name)],
        )

    # ------------------------------------------------------------- geometry
    def mesh(self) -> Any:
        """The results' mesh, else the document's."""
        results = self.results_controller.results
        return results.mesh if results is not None else self.document.mesh

    def points_of(self, item: PathItem) -> tuple[ndarray, ndarray]:
        """Sample positions and arc length of an item (raises ModelError if incomplete)."""
        return path_points(item, self.mesh(), self.document.built, self.document.model)

    def _shown_step(self) -> int:
        ctrl = self.results_controller
        obj = ctrl.get(ctrl.shown)
        return obj.step if obj is not None else max(ctrl.n_steps - 1, 0)

    # --------------------------------------------------------------- view
    def _on_changed(self) -> None:
        names = [i.name for i in self.items()]
        if names != self._names:
            self._names = names
            self.objects_changed.emit()
        self._draw()
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

    def _draw(self) -> None:
        wanted: set[str] = set()
        for item in self.items():
            if not item.visible:
                continue
            try:
                xy, _s = self.points_of(item)
            except ModelError:
                continue
            layer = path_layer(item.name)
            wanted.add(layer)
            line = [(float(x), float(y)) for x, y in xy]
            self.view.set_overlay(layer, [
                OverlayPolyline(line),
                OverlayMarker(line[0][0], line[0][1], "A"),
                OverlayMarker(line[-1][0], line[-1][1], "B"),
            ])  # fmt: skip
        for layer in self._layers - wanted:
            self.view.set_overlay(layer, [])
        self._layers = wanted

    # -------------------------------------------------------------- chart
    def plot(self, name: str) -> Any:
        """Open (or draw again) the item's chart; ``None`` without results."""
        if self.get(name) is None or self.results_controller.results is None:
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
            item = self.get(name)
            results = self.results_controller.results
            if item is None or results is None:
                raise ThermalFEAError("the path plot or the results are gone")
            data = path_chart_data(item, results, self.mesh(), self.document.built,
                                   self.document.model, self._shown_step())  # fmt: skip
            window.show_history(data, "path")

        chart = self.charts._open_renewable(draw)
        if chart is not None:
            self._charts[name] = chart
        return chart

    # ------------------------------------------------- tree provider API
    def tree_items(self) -> list[tuple[str, tuple, bool]]:
        """The children of the Results node."""
        return [(i.name, (PATH_ADDRESS, i.name), True) for i in self.items()]

    def tree_summary(self, address: tuple) -> str:
        """``path · along boundary 'oil wall' · 2 times``."""
        item = self.get(address[1]) if len(address) > 1 else None
        if item is None:
            return ""
        how = {
            "two_points": "two points",
            "boundaries": f"along boundary {item.selection!r}" if item.selection else "boundaries",
            "points": f"{len(item.points)} points",
        }[item.kind]
        times = len(item.times) if item.times else 0
        text = f"path · {how}" + (f" · {times} time{'s' if times != 1 else ''}" if times else "")
        return text if item.visible else f"{text} · hidden"

    def owns(self, address: tuple) -> bool:
        """Whether an address is a path plot's."""
        return bool(address) and address[0] == PATH_ADDRESS

    def tree_actions(self, address: tuple | None) -> list[tuple[str, Callable[[], object], Any]]:
        """Context-menu actions of the Results node (``None``) or of one item."""
        if address is None:
            return [("Add path plot", lambda: self.add(), ("add_result", "path"))]
        name = address[1]
        out: list[tuple[str, Callable[[], object], Any]] = [
            ("Plot", lambda: self.plot(name), ("plot_path", address)),
        ]
        if self.tree is not None:
            out.append(("Rename", lambda: self.tree.begin_rename(address), ("rename", address)))
        out.append(("Duplicate", lambda: self.duplicate(name), ("duplicate", address)))
        out.append(("Delete", lambda: self.delete(name), ("delete", address)))
        return out


# -------------------------------------------------------------------------- panel
class PathPanel(QWidget):
    """Panel of a path plot item: the Path and Plot boxes (held item 15)."""

    def __init__(self, controller: PathController, name: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.controller = controller
        self.name = name
        self.picking: str | None = None  # "A", "B" or "points"
        self._loading = False
        column = QVBoxLayout(self)
        self.title_label = QLabel()
        self.title_label.setStyleSheet("font-weight: bold;")
        column.addWidget(self.title_label)
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b00020;")
        self.error_label.setWordWrap(True)
        column.addWidget(self.error_label)

        # --- Path box
        path_box = SectionBox(Box("Path", "Where the values are taken, from A to B."), "Path")
        self.kind_combo = QComboBox()
        for kind, text in PATH_KINDS:
            self.kind_combo.addItem(text, kind)
        self.kind_combo.activated.connect(
            lambda _i: self._apply(kind=self.kind_combo.currentData())
        )
        path_box.form.addRow("Defined by", self.kind_combo)
        self.point_rows: dict[str, tuple[QLineEdit, QLineEdit, Any]] = {}
        for end in ("A", "B"):
            x_edit, y_edit = QLineEdit(), QLineEdit()
            pick = icon_button("pick", f"Pick point {end} in the view")
            pick.clicked.connect(lambda _c=False, e=end: self.start_pick(e))
            for edit in (x_edit, y_edit):
                edit.editingFinished.connect(lambda e=end: self._on_point_typed(e))
            row = QHBoxLayout()
            row.addWidget(x_edit)
            row.addWidget(y_edit)
            row.addWidget(pick)
            holder = QWidget()
            holder.setLayout(row)
            row.setContentsMargins(0, 0, 0, 0)
            path_box.form.addRow(f"Point {end}", holder)
            self.point_rows[end] = (x_edit, y_edit, holder)
        self.snap_check = QCheckBox("Snap A and B to the nearest nodes")
        self.snap_check.toggled.connect(lambda on: self._apply(snap=bool(on)))
        path_box.form.addRow(self.snap_check)
        self.samples_spin = QSpinBox()
        self.samples_spin.setRange(2, 100000)
        self.samples_spin.editingFinished.connect(
            lambda: self._apply(samples=int(self.samples_spin.value()))
        )
        path_box.form.addRow("Samples", self.samples_spin)
        self.selection_editor = SelectionEditor(
            controller.document, controller.view,
            FieldSpec("selection", "Boundary", "selection", selection_dims=(1,)),
        )  # fmt: skip
        self.selection_editor.owner_address = (PATH_ADDRESS, name)
        self.selection_editor.value_changed.connect(lambda v: self._apply(selection=str(v)))
        self.selection_editor.apply_handler = self._create_selection
        path_box.form.addRow("Boundary", self.selection_editor)
        self.points_label = QLabel("")
        self.points_label.setWordWrap(True)
        add_points = icon_button("pick", "Add points by clicking in the view")
        add_points.setText("Add points")
        add_points.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        add_points.clicked.connect(lambda _c=False: self.start_pick("points"))
        clear_points = icon_button("remove", "Remove every point of the path")
        clear_points.clicked.connect(lambda _c=False: self._apply(points=[]))
        points_row = QHBoxLayout()
        points_row.addWidget(self.points_label, 1)
        points_row.addWidget(add_points)
        points_row.addWidget(clear_points)
        self.points_holder = QWidget()
        self.points_holder.setLayout(points_row)
        points_row.setContentsMargins(0, 0, 0, 0)
        path_box.form.addRow("Points", self.points_holder)
        self.reverse_check = QCheckBox("Run from B to A")
        self.reverse_check.toggled.connect(lambda on: self._apply(reverse=bool(on)))
        path_box.form.addRow(self.reverse_check)
        self.strip = PickStrip("Done")
        self.strip.confirmed.connect(self.end_pick)
        self.strip.cancelled.connect(self.end_pick)
        path_box.form.addRow(self.strip)
        path_box.align_labels()
        column.addWidget(path_box)
        self.path_box = path_box

        # --- Plot box
        plot_box = SectionBox(Box("Plot", "What is plotted, when, and against what."), "Path")
        self.field_combo = QComboBox()
        for key, spec in FIELDS.items():
            self.field_combo.addItem(spec[3], key)
        self.field_combo.activated.connect(
            lambda _i: self._apply(field=self.field_combo.currentData())
        )
        plot_box.form.addRow("Quantity", self.field_combo)
        self.times_edit = QLineEdit()
        self.times_edit.setPlaceholderText("the displayed step")  # C7
        self.times_edit.editingFinished.connect(self._on_times)
        self.times_unit = QLabel("s")
        times_row = QHBoxLayout()
        times_row.addWidget(self.times_edit, 1)
        times_row.addWidget(self.times_unit)
        times_row.setContentsMargins(0, 0, 0, 0)
        times_holder = QWidget()
        times_holder.setLayout(times_row)
        plot_box.form.addRow("Times", times_holder)
        self.axis_combo = QComboBox()
        self.axis_combo.activated.connect(
            lambda _i: self._apply(axis=self.axis_combo.currentData())
        )
        plot_box.form.addRow("Horizontal axis", self.axis_combo)
        self.visible_check = QCheckBox("Show the path in the view")
        self.visible_check.toggled.connect(lambda on: self._apply(visible=bool(on)))
        plot_box.form.addRow(self.visible_check)
        self.plot_button = QPushButton("Plot")
        self.plot_button.clicked.connect(lambda _c=False: self.controller.plot(self.name))
        plot_box.form.addRow(self.plot_button)
        plot_box.align_labels()
        column.addWidget(plot_box)
        column.addStretch(1)

        controller.document.model_changed.connect(self.refresh)
        controller.document.results_changed.connect(self.refresh)
        self.refresh()

    # ---------------------------------------------------------------- loading
    def _units(self) -> UnitSettings:
        return self.controller.document.model.display_units

    def refresh(self) -> None:
        """Show the item."""
        item = self.controller.get(self.name)
        if item is None:
            return
        self._loading = True
        try:
            units = self._units()
            self.title_label.setText(f"Path plot: {self.name}")
            self.kind_combo.setCurrentIndex(max(self.kind_combo.findData(item.kind), 0))
            for i, end in enumerate(("A", "B")):
                x_edit, y_edit, holder = self.point_rows[end]
                if i < len(item.points):
                    x, y = item.points[i]
                    x_edit.setText(f"{float(from_si(x, 'length', units)):.6g}")
                    y_edit.setText(f"{float(from_si(y, 'length', units)):.6g}")
                else:
                    x_edit.clear()
                    y_edit.clear()
                for edit, axis in ((x_edit, "x"), (y_edit, "y")):
                    edit.setPlaceholderText(f"{axis} [{unit_label('length', units)}]")
                self._set_row_visible(holder, item.kind == "two_points")
            self._set_row_visible(self.snap_check, item.kind == "two_points")
            self.snap_check.setChecked(item.snap)
            self._set_row_visible(self.samples_spin, item.kind != "boundaries")
            self.samples_spin.setValue(int(item.samples))
            self._set_row_visible(self.selection_editor, item.kind == "boundaries")
            self.selection_editor.set_value(item.selection)
            self._set_row_visible(self.points_holder, item.kind == "points")
            n = len(item.points)
            self.points_label.setText(f"{n} point{'s' if n != 1 else ''}")
            self.reverse_check.setChecked(item.reverse)
            self.field_combo.setCurrentIndex(max(self.field_combo.findData(item.field), 0))
            time_unit = unit_label("time", units)
            self.times_unit.setText(time_unit)
            self.times_edit.setText(", ".join(
                f"{float(from_si(t, 'time', units)):g}" for t in (item.times or [])
            ))  # fmt: skip
            axisym = self.controller.document.model.axisymmetric
            self.axis_combo.clear()
            for key, text in (("distance", "Distance along the path"),
                              ("x", "r" if axisym else "x"), ("y", "z" if axisym else "y")):
                self.axis_combo.addItem(text, key)  # fmt: skip
            self.axis_combo.setCurrentIndex(max(self.axis_combo.findData(item.axis), 0))
            self.visible_check.setChecked(item.visible)
            try:
                self.controller.points_of(item)
                problem = ""
            except ModelError as exc:
                problem = str(exc)
            self.error_label.setText(problem)
            self.error_label.setVisible(bool(problem))
            has = self.controller.results_controller.results is not None
            self.plot_button.setEnabled(has and not problem)
        finally:
            self._loading = False

    def _set_row_visible(self, widget: QWidget, shown: bool) -> None:
        form = self.path_box.form
        form.setRowVisible(widget, shown)

    # --------------------------------------------------------------- editing
    def _apply(self, **changes: Any) -> None:
        if self._loading:
            return
        try:
            self.controller.update(self.name, **changes)
        except ModelError as exc:
            self.error_label.setText(str(exc))
            self.error_label.setVisible(True)

    def _on_point_typed(self, end: str) -> None:
        x_edit, y_edit, _holder = self.point_rows[end]
        try:
            x = float(to_si(float(x_edit.text()), "length", self._units()))
            y = float(to_si(float(y_edit.text()), "length", self._units()))
        except ValueError:
            return
        self._set_end(end, (x, y))

    def _set_end(self, end: str, point: tuple[float, float]) -> None:
        item = self.controller.get(self.name)
        if item is None:
            return
        points = list(item.points[:2]) + [point] * max(0, 2 - len(item.points[:2]))
        points[0 if end == "A" else 1] = point
        self._apply(points=points)

    def _on_times(self) -> None:
        text = self.times_edit.text().replace(";", ",")
        try:
            times = [float(to_si(float(t), "time", self._units()))
                     for t in text.split(",") if t.strip()]  # fmt: skip
        except ValueError:
            self.error_label.setText(f"{text!r} is not a list of times")
            self.error_label.setVisible(True)
            return
        self._apply(times=times or None)

    def _create_selection(self, request: Any) -> str | None:
        """New boundary selection from the selection field: create it and use it."""
        name = self.selection_editor._default_apply(request)
        if name:
            self._apply(selection=name)
        return name

    # --------------------------------------------------------------- picking
    def start_pick(self, what: str) -> bool:
        """Pick point A, point B, or the polyline's points in the view (C2)."""
        view = self.controller.view
        if view is None:
            return False
        manager_for(view).start(self, "none", cancel=self.end_pick, confirm=self.end_pick,
                                strip=self.strip)  # fmt: skip
        self.picking = what
        view.point_picked.connect(self._on_point_picked)
        text = (f"Click point {what} in the view." if what in ("A", "B")
                else "Click the points of the path in the view, from A to B.")  # fmt: skip
        self.strip.show_pick(text, "")
        return True

    def _on_point_picked(self, x: float, y: float, _z: float) -> None:
        if self.picking in ("A", "B"):
            end = self.picking
            self.end_pick()
            self._set_end(end, (float(x), float(y)))
        elif self.picking == "points":
            item = self.controller.get(self.name)
            if item is not None:
                self._apply(points=[*item.points, (float(x), float(y))])
                n = len(item.points) + 1
                self.strip.set_count(f"{n} point{'s' if n != 1 else ''}")

    def end_pick(self) -> None:
        """End a pick (the points are stored as they are clicked)."""
        if self.picking is None:
            return
        self.picking = None
        view = self.controller.view
        try:
            view.point_picked.disconnect(self._on_point_picked)
        except (RuntimeError, TypeError):
            pass
        self.strip.hide_pick()
        manager_for(view).finish(self)


def attach_paths(window: Any, document: Document, view: SceneView, results: Any,
                 charts: Any) -> PathController:  # fmt: skip
    """Install the path plot items: tree provider, panel and Results > Path plot..."""
    controller = PathController(window, document, view, results, charts)
    tree = window.tree_widget
    if hasattr(tree, "add_provider"):
        controller.tree = tree
        tree.add_provider(controller)
    props = getattr(tree, "property_controller", None)
    if props is not None:
        props.path_controller = controller
    charts.path_items = controller
    # the path is defined in the item's panel now: no Finish / Cancel path plot in the menu
    menu = window.menus.get("results") if hasattr(window, "menus") else None
    for key in ("results.path_finish", "results.path_cancel"):
        action = window.actions.get(key)
        if menu is not None and action is not None:
            menu.removeAction(action)
    controller._on_changed()
    return controller


__all__ = [
    "PATH_ADDRESS", "PathController", "PathPanel", "attach_paths", "chain_polylines",
    "path_chart_data", "path_layer", "path_points", "project_on",
]  # fmt: skip
