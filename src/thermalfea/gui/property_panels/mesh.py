"""Property panel of the mesh settings (Plan M8.7).

:class:`MeshPanel` is a :class:`~thermalfea.gui.property_panels.form.FormPanel` for
:class:`~thermalfea.model.settings.MeshSettings`. Below the generated settings form it shows

* the refinements editor: a table of :class:`~thermalfea.model.settings.Refinement` rows
  (Add, Remove, and editing of each cell); every change is one ``Document.edit`` that
  replaces the whole list, and an invalid entry is marked and not applied;
* the "Generate mesh" button, which calls the callable given to the panel (the mesh
  controller's ``generate``); it is enabled only when a current built geometry exists;
* the statistics (node and element counts per element type, quality summary) and a
  histogram of one quality measure, both read from :func:`thermalfea.meshing.quality.report`;
* the "Colour elements by quality" check box, which colours the mesh in the viewport by the
  chosen measure.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FormSpec
from thermalfea.gui.addressing import Address, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.mesh_tools import can_generate
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.function_editor import parse_number
from thermalfea.gui.property_panels.quality_histogram import QualityHistogram
from thermalfea.gui.scene import SceneView
from thermalfea.meshing import quality
from thermalfea.model.settings import MeshSettings, Refinement

_BAD_BRUSH = QColor("#ffd0d0")
_ERROR_STYLE = "color: #b00020;"
NO_MESH_TEXT = "No mesh"

#: Refinement table columns: (attribute of :class:`Refinement`, header).
REFINEMENT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("selection", "Selection"),
    ("size_min", "Size min [m]"),
    ("size_max", "Size max [m]"),
    ("dist_min", "Dist min [m]"),
    ("dist_max", "Dist max [m]"),
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


def parse_refinement(cells: list[str]) -> Refinement:
    """Parse the cells of one refinement row (selection, then four numbers in metres).

    Parameters
    ----------
    cells : list of str
        Text of the columns of :data:`REFINEMENT_COLUMNS`.

    Raises
    ------
    ValueError
        With a message the user can read, if a number is invalid or the sizes or distances
        are out of order (the same rules the mesher applies).
    """
    selection = cells[0].strip()
    if not selection:
        raise ValueError("enter the name of a curve or point selection")
    numbers: list[float] = []
    for text in cells[1:]:
        try:
            value = parse_number(text)
        except ValueError:
            raise ValueError(f"{text.strip()!r} is not a number") from None
        if not math.isfinite(value):
            raise ValueError(f"{text.strip()!r} is not a finite number")
        numbers.append(float(value))
    size_min, size_max, dist_min, dist_max = numbers
    if not 0.0 < size_min <= size_max:
        raise ValueError("sizes need 0 < size min <= size max")
    if not 0.0 <= dist_min < dist_max:
        raise ValueError("distances need 0 <= dist min < dist max")
    return Refinement(selection, size_min, size_max, dist_min, dist_max)


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
        Viewport that is coloured by quality; without one colouring is disabled.
    parent : QWidget, optional
    generate : callable, optional
        ``generate() -> bool``, called by the "Generate mesh" button.
    """

    _extras_built = False

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
        section = QVBoxLayout()
        self.generate_button = QPushButton("Generate mesh")
        self.generate_button.clicked.connect(lambda _checked=False: self._on_generate())
        section.addWidget(self.generate_button)

        section.addWidget(self._heading("Statistics"))
        self.stats_label = QLabel()
        self.stats_label.setWordWrap(True)
        self.stats_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        section.addWidget(self.stats_label)

        section.addWidget(self._heading("Quality"))
        self.measure_combo = QComboBox()
        for measure in quality.MEASURES:
            self.measure_combo.addItem(MEASURE_LABELS[measure], measure)
        self.measure_combo.currentIndexChanged.connect(lambda _i: self._on_measure_changed())
        section.addWidget(self.measure_combo)
        self.histogram = QualityHistogram()
        section.addWidget(self.histogram)
        self.colour_box = QCheckBox("Colour elements by quality")
        self.colour_box.toggled.connect(lambda _on: self._apply_colour())
        section.addWidget(self.colour_box)

        section.addWidget(self._heading("Refinements"))
        self.table = QTableWidget(0, len(REFINEMENT_COLUMNS))
        self.table.setHorizontalHeaderLabels([header for _, header in REFINEMENT_COLUMNS])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemChanged.connect(self._on_item_changed)
        section.addWidget(self.table)
        buttons = QHBoxLayout()
        add = QPushButton("Add")
        add.clicked.connect(lambda _checked=False: self._add_refinement())
        remove = QPushButton("Remove")
        remove.clicked.connect(lambda _checked=False: self._remove_refinement())
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        section.addLayout(buttons)
        self.refinement_error = QLabel()
        self.refinement_error.setWordWrap(True)
        self.refinement_error.setStyleSheet(_ERROR_STYLE)
        self.refinement_error.setVisible(False)
        section.addWidget(self.refinement_error)

        outer = self.layout()
        outer.insertLayout(outer.count() - 1, section)  # before the trailing stretch

    @staticmethod
    def _heading(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: bold; margin-top: 6px;")
        return label

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
        self.colour_box.setEnabled(report is not None)
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

    # ------------------------------------------------------------------ colouring
    def _on_mesh_changed(self) -> None:
        self._refresh_results()
        if self.colour_box.isChecked():
            self._apply_colour()

    def _on_measure_changed(self) -> None:
        self._refresh_results()
        if self.colour_box.isChecked():
            self._apply_colour()

    def _apply_colour(self) -> None:
        """Show the mesh coloured by the chosen measure, or plainly when unchecked."""
        mesh = self.document.mesh
        if self.view is None or mesh is None:
            return
        if not self.colour_box.isChecked():
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
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        self.table.setRowCount(len(refinements))
        for row, refinement in enumerate(refinements):
            cells = [
                refinement.selection,
                *(f"{getattr(refinement, name):.10g}" for name, _ in REFINEMENT_COLUMNS[1:]),
            ]
            for col, text in enumerate(cells):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.table.blockSignals(False)
        self._show_refinement_error("")

    def _show_refinement_error(self, message: str) -> None:
        self.refinement_error.setText(message)
        self.refinement_error.setVisible(bool(message))

    def _cells(self, row: int) -> list[str]:
        return [
            item.text() if (item := self.table.item(row, col)) is not None else ""
            for col in range(len(REFINEMENT_COLUMNS))
        ]

    def _edit_refinements(self, text: str, change: Callable[[list[Refinement]], None]) -> None:
        """Replace the refinement list of the settings through one ``Document.edit``."""

        def mutate(model: Any) -> None:
            settings = self._settings(model)
            refinements = list(settings.refinements)
            change(refinements)
            settings.refinements = refinements

        self.document.edit(text, mutate)

    def _mark(self, item: QTableWidgetItem, bad: bool) -> None:
        """Mark a cell as rejected (no signal: setting the colour must not re-validate)."""
        self.table.blockSignals(True)
        item.setBackground(QBrush(_BAD_BRUSH) if bad else QBrush())
        self.table.blockSignals(False)

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        row = item.row()
        try:
            refinement = parse_refinement(self._cells(row))
        except ValueError as exc:
            self._mark(item, bad=True)
            self._show_refinement_error(str(exc))
            return
        self._mark(item, bad=False)
        self._show_refinement_error("")
        self._edit_refinements(
            "Edit refinement", lambda refs: refs.__setitem__(row, refinement)
        )

    def _add_refinement(self) -> None:
        settings = self._settings(self.document.model)
        size = settings.global_size
        refinement = Refinement(
            _default_selection(self.document.model), size, size, 0.0, size
        )
        self._show_refinement_error("")
        self._edit_refinements("Add refinement", lambda refs: refs.append(refinement))

    def _remove_refinement(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        self._show_refinement_error("")
        self._edit_refinements("Remove refinement", lambda refs: refs.__delitem__(row))
