"""Property panel of the mesh settings (Plan M8.7).

:class:`MeshPanel` is a :class:`~thermalfea.gui.property_panels.form.FormPanel` for
:class:`~thermalfea.model.settings.MeshSettings`, in framed boxes (C5, C12; M11.71-M11.72):

* **Element size**: global size, boundary sizes and point sizes (value-per-selection
  tables);
* **Element type**: order and shape; under "More" the algorithm and smoothing passes;
* **Structured mesh**: the structured parts and the boundary divisions;
* **Refinements**: a value-per-selection table of
  :class:`~thermalfea.model.settings.Refinement` rows (selection, size min/max, distance
  min/max); every change is one ``Document.edit`` that replaces the whole list, and a row
  that breaks the size or distance order is refused with a message under it;
* the "Generate mesh" button, which calls the callable given to the panel (the mesh
  controller's ``generate``); it is enabled only when a current built geometry exists;
* **Statistics and quality**: node and element counts per element type, the quality
  summary, a histogram of one quality measure (from
  :func:`thermalfea.meshing.quality.report`) and the "Color elements by quality" check box,
  which colors the mesh in the viewport by the chosen measure.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FormSpec
from thermalfea.core.units import UnitSettings, to_si
from thermalfea.gui.addressing import Address, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.mesh_tools import can_generate
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.function_editor import parse_number
from thermalfea.gui.property_panels.quality_histogram import QualityHistogram
from thermalfea.gui.property_panels.sections import Box, SectionBox
from thermalfea.gui.property_panels.selection_table import Column, SelectionTable
from thermalfea.gui.scene import SceneView
from thermalfea.meshing import quality
from thermalfea.model.settings import MeshSettings, Refinement

_BAD_BRUSH = QColor("#ffd0d0")
_ERROR_STYLE = "color: #b00020;"
NO_MESH_TEXT = "No mesh"

#: Refinement table columns: (attribute of :class:`Refinement`, header).
REFINEMENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("selection", "Selection"),
    ("size_min", "Size min"),
    ("size_max", "Size max"),
    ("dist_min", "Dist min"),
    ("dist_max", "Dist max"),
)

#: Human names of the quality measures (attribute names of the quality report).
MEASURE_LABELS: dict[str, str] = {
    "min_angle": "Minimum angle [deg]",
    "aspect_ratio": "Aspect ratio",
    "jacobian_ratio": "Jacobian ratio",
}

#: Human names of the keys of :meth:`QualityReport.summary`.
SUMMARY_LABELS: dict[str, str] = {
    "min_angle_min": "Minimum angle, smallest [deg]",
    "min_angle_mean": "Minimum angle, mean [deg]",
    "aspect_ratio_max": "Aspect ratio, largest",
    "aspect_ratio_mean": "Aspect ratio, mean",
    "jacobian_ratio_min": "Jacobian ratio, smallest",
    "jacobian_ratio_mean": "Jacobian ratio, mean",
}


def parse_refinement(cells: list[str], units: UnitSettings | None = None) -> Refinement:
    """Parse the cells of one refinement row (selection, then four lengths).

    Parameters
    ----------
    cells : list of str
        Text of the columns of :data:`REFINEMENT_COLUMNS`.
    units : UnitSettings, optional
        The lengths are typed in its length unit; default: metres. The result is in m.

    Raises
    ------
    ValueError
        With a message the user can read, if a number is invalid or the sizes or distances
        are out of order (the same rules the mesher applies).
    """
    selection = cells[0].strip()
    if not selection:
        raise ValueError("enter the name of a boundary or point selection")
    numbers: list[float] = []
    for text in cells[1:]:
        try:
            value = parse_number(text)
        except ValueError:
            raise ValueError(f"{text.strip()!r} is not a number") from None
        if not math.isfinite(value):
            raise ValueError(f"{text.strip()!r} is not a finite number")
        numbers.append(float(to_si(value, "length", units)) if units else float(value))
    check_refinement(tuple(numbers))
    size_min, size_max, dist_min, dist_max = numbers
    return Refinement(selection, size_min, size_max, dist_min, dist_max)


def check_refinement(values: tuple[float, ...]) -> None:
    """Check the four lengths of a refinement row (the rules the mesher applies).

    Raises
    ------
    ValueError
        If the sizes or the distances are out of order.
    """
    size_min, size_max, dist_min, dist_max = values
    if not 0.0 < size_min <= size_max:
        raise ValueError("sizes need 0 < size min <= size max")
    if not 0.0 <= dist_min < dist_max:
        raise ValueError("distances need 0 <= dist min < dist max")


def _default_selection(model: Any) -> str:
    """Name of the first curve or point selection of a model ("" if there is none)."""
    for name, selection in model.selections.items():
        if selection.dim in (0, 1):
            return name
    return ""


class MeshPanel(FormPanel):
    """Form of the mesh settings, with the refinements, statistics and quality views.

    Parameters
    ----------
    spec : FormSpec
        The mesh form (:data:`thermalfea.model.mesh_forms.MESH_FORM`).
    document : Document
    address : tuple
        Address ``("mesh_settings",)``.
    view : SceneView, optional
        Viewport that is colored by quality; without one coloring is disabled.
    parent : QWidget, optional
    generate : callable, optional
        ``generate() -> bool``, called by the "Generate mesh" button.
    """

    _extras_built = False
    #: Held items 13 and 18 (C5, C12): the structured parts and the divisions along
    #: boundaries belong together (a structured part needs matching divisions on opposite
    #: sides).
    boxes = (
        Box(
            "Element size",
            "Target size of the elements, and local sizes along boundaries and at points.",
            ("global_size", "curve_sizes", "point_sizes"),
        ),
        Box(
            "Element type",
            "Order and shape of the elements.",
            ("order", "element_shape"),
            more=("algorithm", "smoothing_passes"),
        ),
        Box(
            "Structured mesh",
            "Parts meshed as regular grids (3 or 4 sides), and the number of elements "
            "along boundaries.",
            ("structured_surfaces", "curve_divisions"),
        ),
    )

    def __init__(
        self,
        spec: FormSpec,
        document: Document,
        address: Address,
        view: SceneView | None = None,
        parent: QWidget | None = None,
        generate: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(spec, document, address, view, parent)
        self._generate = generate
        self._report: quality.QualityReport | None = None
        self._report_mesh: object | None = None
        self._build_extras()
        self._extras_built = True
        document.mesh_changed.connect(self._on_mesh_changed)
        document.stale_changed.connect(self._refresh_generate)
        document.geometry_built.connect(self._refresh_generate)
        self._refresh_extras()

    # ------------------------------------------------------------------ building
    def _build_extras(self) -> None:
        column = QVBoxLayout()
        title = self.spec.title

        refinements = SectionBox(
            Box(
                "Refinements",
                "Smaller elements near a boundary or point, growing with distance.",
            ),
            title,
        )
        self.table = SelectionTable(
            self.document, self.view, (0, 1),
            [Column(name, label, "length", minimum=0.0) for name, label in
             REFINEMENT_COLUMNS[1:]],
            self._units, unique=False, row_check=check_refinement,
        )  # fmt: skip
        self.table.rows_changed.connect(self._on_refinements_changed)
        refinements.form.addRow(self.table)
        self.sections[refinements.box.title] = refinements
        column.addWidget(refinements)

        self.generate_button = QPushButton("Generate mesh")
        self.generate_button.clicked.connect(lambda _checked=False: self._on_generate())
        column.addWidget(self.generate_button)

        stats = SectionBox(
            Box(
                "Statistics and quality",
                "Size of the mesh and how well its elements are shaped.",
            ),
            title,
        )
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        self.stats_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        stats.form.addRow(self.stats_label)
        self.measure_combo = QComboBox()
        for measure in quality.MEASURES:
            self.measure_combo.addItem(MEASURE_LABELS[measure], measure)
        self.measure_combo.currentIndexChanged.connect(lambda _i: self._on_measure_changed())
        stats.form.addRow(self.measure_combo)
        self.histogram = QualityHistogram()
        stats.form.addRow(self.histogram)
        self.color_box = QCheckBox("Color elements by quality")
        self.color_box.toggled.connect(lambda _on: self._apply_color())
        stats.form.addRow(self.color_box)
        self.sections[stats.box.title] = stats
        column.addWidget(stats)

        outer = self.layout()
        outer.insertLayout(outer.count() - 1, column)  # before the trailing stretch

    # ------------------------------------------------------------------- refresh
    def refresh(self) -> None:
        """Reload the settings form and the extra widgets from the model."""
        super().refresh()
        if self._extras_built:
            self._refresh_extras()

    def _refresh_extras(self) -> None:
        self._load_table()
        self._refresh_results()
        self._refresh_generate()

    def _refresh_generate(self) -> None:
        self.generate_button.setEnabled(can_generate(self.document))
        if self.document.built is None:
            self.generate_button.setToolTip("Build the geometry before meshing.")
        elif self.document.geometry_stale:
            self.generate_button.setToolTip("Rebuild the geometry before meshing.")
        else:
            self.generate_button.setToolTip("Mesh the geometry with these settings.")

    def _refresh_results(self) -> None:
        report = self._quality()
        measure = self._measure()
        self.color_box.setEnabled(report is not None)
        if report is None:
            self.stats_label.setText(NO_MESH_TEXT)
            self.histogram.set_values(None, MEASURE_LABELS[measure])
            return
        self.stats_label.setText(self._stats_text(report))
        self.histogram.set_values(getattr(report, measure), MEASURE_LABELS[measure])

    def _quality(self) -> quality.QualityReport | None:
        """The quality report of the document's mesh (computed once per mesh)."""
        mesh = self.document.mesh
        if mesh is None:
            return None
        if mesh is not self._report_mesh:
            self._report_mesh = mesh
            self._report = quality.report(mesh)
        return self._report

    def _measure(self) -> str:
        return str(self.measure_combo.currentData())

    @staticmethod
    def _stats_text(report: quality.QualityReport) -> str:
        lines = [f"Nodes: {report.n_nodes}", f"Elements: {report.n_elements}"]
        lines += [f"  {etype}: {count}" for etype, count in report.counts.items()]
        for key, value in report.summary().items():
            lines.append(f"{SUMMARY_LABELS.get(key, key)}: {value:.4g}")
        return "\n".join(lines)

    # ----------------------------------------------------------------- generate
    def _on_generate(self) -> None:
        if self._generate is not None:
            self._generate()

    # ------------------------------------------------------------------ coloring
    def _on_mesh_changed(self) -> None:
        self._refresh_results()
        if self.color_box.isChecked():
            self._apply_color()

    def _on_measure_changed(self) -> None:
        self._refresh_results()
        if self.color_box.isChecked():
            self._apply_color()

    def _apply_color(self) -> None:
        """Show the mesh colored by the chosen measure, or plainly when unchecked."""
        mesh = self.document.mesh
        if self.view is None or mesh is None:
            return
        if not self.color_box.isChecked():
            self.view.set_mesh(mesh, color_by=None)
            return
        values = quality.values_in_block_order(mesh, self._quality(), self._measure())
        self.view.set_mesh(mesh, color_by=values)

    # --------------------------------------------------------------- refinements
    def _settings(self, model: Any) -> MeshSettings:
        settings = resolve(model, self.address)
        assert isinstance(settings, MeshSettings)
        return settings

    def _load_table(self) -> None:
        try:
            refinements = list(self._settings(self.document.model).refinements)
        except ModelError:
            refinements = []
        rows = [
            (r.selection, tuple(float(getattr(r, name)) for name, _ in REFINEMENT_COLUMNS[1:]))
            for r in refinements
        ]
        if self.table.units != self._units:
            self.table.set_units(self._units)
        if rows != self.table.rows():  # an unrelated edit keeps a pending row
            self.table.set_rows(rows)

    def _on_refinements_changed(self, rows: list) -> None:
        """Store the table's rows as the refinement list (one undo step)."""
        refinements = [Refinement(name, *values) for name, values in rows]

        def mutate(model: Any) -> None:
            self._settings(model).refinements = refinements

        self.document.edit("Edit refinements", mutate)
