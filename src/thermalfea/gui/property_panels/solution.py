"""Property panel of the analysis settings (Plan M8.9; layout of M11.68).

:class:`SolutionPanel` is a :class:`~thermalfea.gui.property_panels.form.FormPanel` for
:class:`~thermalfea.model.settings.SolutionSettings`, laid out in framed boxes by purpose
(held item 11 with conventions C5 and C12 and the owner's decisions C and G):

=================  ==============================================================
box                fields
=================  ==============================================================
Analysis           Geometry type, Analysis type
Time               End time
Time stepping      Adaptive time step, Largest time step; under "More": Initial
                   time step, Smallest time step, Time-step tolerance, Largest
                   temperature change per step
Integration        (advanced, collapsed; the title names the method) Time
                   integration, Lumped capacitance
Results to store   Output steps, Store every n-th step, Output times
Convergence        (advanced, collapsed) Residual tolerance, Temperature tolerance,
                   Maximum iterations, Line search
=================  ==============================================================

Only the fields that matter are shown: a steady analysis shows the Analysis and Convergence
boxes; "Time-step tolerance" only with an adaptive time step; "Store every n-th step" only
when the output is ``every_n`` and the output times only when it is ``times``.

"Time integration" is a choice of the named methods of :data:`THETA_METHODS` (Theory §6),
not a number box; the model still stores the number ``theta``. A stored value that is none
of them (a script may set any 0 < theta <= 1) is shown as a fourth entry "Custom (θ = …)"
and kept unchanged until another method is chosen.

Below the boxes are the "Validate" and "Solve" buttons. They call the solve controller
(``validate()`` and ``solve()``), so the panel needs no solver knowledge. "Solve" is enabled
when the controller says a solve can start.
"""

from __future__ import annotations

import math
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget

from thermalfea.core.forms import FieldSpec, FormSpec
from thermalfea.gui.addressing import Address
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.sections import Box
from thermalfea.gui.scene import SceneView
from thermalfea.model.solution_forms import (
    OUTPUT_EVERY_FIELD,
    OUTPUT_TIMES_FIELD,
    TRANSIENT_ONLY_FIELDS,
)

#: ``(text, Model.analysis value)`` of the "Geometry type" choice.
GEOMETRY_TYPES = (("Planar", "planar"), ("Axisymmetric", "axisymmetric"))

#: ``(text, theta, tooltip)`` of the "Time integration" choice (Theory §6).
THETA_METHODS = (
    ("Backward Euler (θ = 1, default)", 1.0,
     "Always stable and never oscillates; first-order accurate in time."),
    ("Galerkin (θ = 2/3)", 2.0 / 3.0,
     "Between backward Euler and Crank-Nicolson."),
    ("Crank-Nicolson (θ = 1/2)", 0.5,
     "Second-order accurate in time; may oscillate after a sudden change (a thermal shock)."),
)  # fmt: skip
#: Short names of :data:`THETA_METHODS` for the title of the collapsed Integration box.
THETA_SHORT = ("Backward Euler", "Galerkin", "Crank-Nicolson")
_THETA = "theta"
_ADAPTIVE = "auto_timestep"
_TIME_TOL = "time_tol"

ANALYSIS_BOX = "Analysis"
INTEGRATION_BOX = "Integration"
CONVERGENCE_BOX = "Convergence"

#: The boxes of the panel, in order (held item 11, C12, decision G).
SOLUTION_BOXES: tuple[Box, ...] = (
    Box(ANALYSIS_BOX, "Geometry and the kind of analysis.", ("kind",)),
    Box("Time", "How long the analysis runs.", ("end_time",)),
    Box(
        "Time stepping",
        "The solver sizes each step to keep its error estimate within the tolerance.",
        (_ADAPTIVE, "dt_max"),
        more=("initial_dt", "dt_min", _TIME_TOL, "max_dT_per_step"),
    ),
    Box(
        INTEGRATION_BOX, "How each step is calculated.", (_THETA, "lumped_capacitance"),
        advanced=True,
    ),
    Box(
        "Results to store", "Which time steps are kept for viewing.",
        ("output", OUTPUT_EVERY_FIELD, OUTPUT_TIMES_FIELD),
    ),
    Box(
        CONVERGENCE_BOX, "Iteration within each step; the defaults suit most models.",
        ("rtol", "ttol", "max_iterations", "line_search"), advanced=True,
    ),
)  # fmt: skip


def theta_method_index(theta: float) -> int | None:
    """Index in :data:`THETA_METHODS` of the method with this theta, or ``None``."""
    for i, (_text, value, _tip) in enumerate(THETA_METHODS):
        if math.isclose(theta, value, rel_tol=0.0, abs_tol=1e-12):
            return i
    return None


def theta_method_name(theta: float) -> str:
    """Short name of the method of ``theta`` ("Backward Euler", ..., or "Custom θ = 0.6")."""
    index = theta_method_index(theta)
    return THETA_SHORT[index] if index is not None else f"Custom θ = {float(theta):g}"


class SolutionPanel(FormPanel):
    """Form of the analysis settings in boxes, with the Validate and Solve buttons.

    Parameters
    ----------
    spec : FormSpec
        The solution form (:data:`thermalfea.model.solution_forms.SOLUTION_FORM`).
    document : Document
    address : tuple
        Address ``("solution",)``.
    view : SceneView, optional
    parent : QWidget, optional
    controller : object, optional
        The solve controller: ``validate()``, ``solve()``, ``can_solve() -> bool`` and a
        ``state_changed`` signal. Without one the buttons are disabled.

    Attributes
    ----------
    analysis_combo : QComboBox
        "Geometry type", the first row of the Analysis box.
    validate_button, solve_button : QPushButton
    """

    boxes = SOLUTION_BOXES
    _extras_built = False

    def __init__(
        self,
        spec: FormSpec,
        document: Document,
        address: Address,
        view: SceneView | None = None,
        parent: QWidget | None = None,
        controller: Any = None,
    ) -> None:
        super().__init__(spec, document, address, view, parent)
        self._controller = controller
        # "Geometry type" belongs to the model, not to SolutionSettings: the first row of
        # the Analysis box, written through one undoable edit of ``Model.analysis``
        self.analysis_combo = QComboBox()
        for label, value in GEOMETRY_TYPES:
            self.analysis_combo.addItem(label, value)
        self.analysis_combo.setToolTip(
            "Planar: a section with a thickness. Axisymmetric: x is the radius, the axis "
            "x = 0 is the axis of symmetry."
        )
        self.analysis_combo.activated.connect(lambda _i: self._on_geometry_type())
        self.sections[ANALYSIS_BOX].form.insertRow(
            0, QLabel("Geometry type"), self.analysis_combo
        )
        self.sections[ANALYSIS_BOX].align_labels()
        outer = self.layout()
        row = QHBoxLayout()
        self.validate_button = QPushButton("Validate")
        self.validate_button.clicked.connect(lambda _checked=False: self._on_validate())
        self.solve_button = QPushButton("Solve")
        self.solve_button.clicked.connect(lambda _checked=False: self._on_solve())
        row.addWidget(self.validate_button)
        row.addWidget(self.solve_button)
        row.addStretch(1)
        outer.insertLayout(outer.count() - 1, row)  # before the trailing stretch
        self._extras_built = True
        for signal in (
            document.mesh_changed,
            document.geometry_built,
            document.stale_changed,
        ):
            signal.connect(self._refresh_buttons)
        state = getattr(controller, "state_changed", None)
        if state is not None:
            state.connect(self._refresh_buttons)
        self._update_visibility()
        self._sync_geometry_type()
        self._refresh_buttons()

    # ------------------------------------------------------------- time integration
    def _make_editor(self, f: FieldSpec) -> tuple[QWidget, QLabel | None]:
        if f.name != _THETA:
            return super()._make_editor(f)
        combo = QComboBox()
        combo.activated.connect(lambda i: self._on_theta(i))
        return combo, None

    def _load(self, f: FieldSpec, value: Any) -> None:
        if f.name != _THETA:
            super()._load(f, value)
            return
        combo = self.editors[_THETA]
        assert isinstance(combo, QComboBox)
        combo.blockSignals(True)
        combo.clear()
        for i, (text, theta, tip) in enumerate(THETA_METHODS):
            combo.addItem(text, theta)
            combo.setItemData(i, tip, Qt.ItemDataRole.ToolTipRole)
        index = theta_method_index(float(value))
        if index is None:  # a value set elsewhere stays visible, never silently replaced
            combo.addItem(f"Custom (θ = {float(value):g})", float(value))
            combo.setItemData(combo.count() - 1, "Set outside the window; kept unchanged.",
                              Qt.ItemDataRole.ToolTipRole)  # fmt: skip
            index = combo.count() - 1
        combo.setCurrentIndex(index)
        combo.blockSignals(False)
        self.sections[INTEGRATION_BOX].set_summary(theta_method_name(float(value)))

    def _on_theta(self, index: int) -> None:
        combo = self.editors[_THETA]
        assert isinstance(combo, QComboBox)
        self._apply(_THETA, float(combo.itemData(index)))

    # ------------------------------------------------------------------ refresh
    def refresh(self) -> None:
        """Reload the editors and show the fields that suit the analysis kind."""
        super().refresh()
        if self._extras_built:
            self._update_visibility()
            self._sync_geometry_type()

    def _sync_geometry_type(self) -> None:
        index = self.analysis_combo.findData(self.document.model.analysis)
        self.analysis_combo.blockSignals(True)
        self.analysis_combo.setCurrentIndex(max(index, 0))
        self.analysis_combo.blockSignals(False)

    def _on_geometry_type(self) -> None:
        value = self.analysis_combo.currentData()
        self.document.edit("Edit Geometry type", lambda m: setattr(m, "analysis", value))

    def _update_visibility(self) -> None:
        try:
            settings = self.current_object()
        except Exception:  # the object is gone; the panel is disabled by refresh()
            return
        transient = settings.kind == "transient"
        for field in self.spec.fields:
            name = field.name
            shown = transient or name not in TRANSIENT_ONLY_FIELDS
            if name == OUTPUT_EVERY_FIELD:
                shown = shown and settings.output == "every_n"
            elif name == OUTPUT_TIMES_FIELD:
                shown = shown and settings.output == "times"
            elif name == _TIME_TOL:
                shown = shown and settings.auto_timestep
            self.set_field_visible(name, shown)
        self.update_sections()

    # ------------------------------------------------------------------ buttons
    def _refresh_buttons(self) -> None:
        controller = self._controller
        self.validate_button.setEnabled(
            controller is not None and self.document.built is not None
        )
        self.solve_button.setEnabled(controller is not None and bool(controller.can_solve()))

    def _on_validate(self) -> None:
        if self._controller is not None:
            self._controller.validate()

    def _on_solve(self) -> None:
        if self._controller is not None:
            self._controller.solve()
