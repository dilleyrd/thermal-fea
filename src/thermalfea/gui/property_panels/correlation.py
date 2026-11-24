"""Property panel of a correlation convection condition (Plan M8.8).

:class:`CorrelationPanel` is the generated form of
:class:`~thermalfea.model.bcs.CorrelationConvection` plus, below it, the text of the chosen
correlation (title, formula, validity range, characteristic length; all from
:data:`thermalfea.convection.correlation_info.CORRELATION_INFO`) and a *preview* of the
heat-transfer coefficient.

The preview calls :func:`thermalfea.api.htc` with the current fields of the condition. Inputs
the condition does not define (the surface temperature, a characteristic length when
``char_length`` is empty, a velocity or fluid temperature that is not a constant, the
distance ``x`` of ``plate_forced_local``, ...) are typed into the preview. Nothing typed in
the preview is stored in the model. A :class:`~thermalfea.core.errors.ModelError` from
``api.htc`` is shown as text, never raised. Temperatures use the model's display units.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QVBoxLayout, QWidget

from thermalfea import api
from thermalfea.convection.calculator import HtcResult
from thermalfea.convection.correlation_info import (
    CORRELATION_INFO,
    H_FROM_NU,
    CorrelationInfo,
    properties_at,
)
from thermalfea.convection.correlations import CORRELATIONS
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec, FormSpec, unit_label
from thermalfea.core.functions import Constant
from thermalfea.core.units import from_si
from thermalfea.gui.addressing import Address
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.form import FormPanel, NumberEdit
from thermalfea.gui.scene import SceneView
from thermalfea.materials import library

#: Preview inputs: name -> field spec. ``T_surface`` and ``T_inf`` are positional arguments
#: of ``api.htc``; the others are its keyword inputs.
_PREVIEW_FIELDS: dict[str, FieldSpec] = {
    "T_surface": FieldSpec(
        "T_surface", "Surface temperature", "float", quantity="temperature", minimum=0.0,
        optional=True, tooltip="Wall temperature T_s for the preview (not stored).",
    ),
    "T_inf": FieldSpec(
        "T_inf", "Fluid temperature", "float", quantity="temperature", minimum=0.0,
        optional=True, tooltip="Used because the fluid temperature is not a constant.",
    ),
    "length": FieldSpec(
        "length", "Characteristic length", "float", quantity="length", minimum=0.0,
        optional=True, tooltip="Used because the condition has no characteristic length.",
    ),
    "x": FieldSpec(
        "x", "Distance from leading edge", "float", quantity="length", minimum=0.0,
        optional=True, tooltip="Distance x along the flow direction.",
    ),
    "velocity": FieldSpec(
        "velocity", "Velocity", "float", quantity="velocity", minimum=0.0, optional=True,
        tooltip="Free-stream velocity.",
    ),
    "theta_deg": FieldSpec(
        "theta_deg", "Inclination from vertical [deg]", "float", optional=True,
        tooltip="Inclination from vertical in degrees.",
    ),
    "S": FieldSpec(
        "S", "Plate spacing S", "float", quantity="length", minimum=0.0, optional=True,
        tooltip="Spacing S of the vertical channel plates.",
    ),
    "W": FieldSpec(
        "W", "Slot width W", "float", quantity="length", minimum=0.0, optional=True,
        tooltip="Width W of the slot nozzle.",
    ),
    "D": FieldSpec(
        "D", "Nozzle diameter D", "float", quantity="length", minimum=0.0, optional=True,
        tooltip="Diameter D of the round nozzle.",
    ),
    "H": FieldSpec(
        "H", "Nozzle-to-surface distance H", "float", quantity="length", minimum=0.0,
        optional=True, tooltip="Distance H from the nozzle to the surface.",
    ),
    "x_r": FieldSpec(
        "x_r", "Half-width x_r", "float", quantity="length", minimum=0.0, optional=True,
        tooltip="Half-width of the region averaged over.",
    ),
    "r_r": FieldSpec(
        "r_r", "Radius r_r", "float", quantity="length", minimum=0.0, optional=True,
        tooltip="Radius of the region averaged over.",
    ),
    "C": FieldSpec("C", "C", "float", optional=True, tooltip="Coefficient C of the power law."),
    "n": FieldSpec("n", "n", "float", optional=True, tooltip="Exponent n of the power law."),
    "mass_flow": FieldSpec(
        "mass_flow", "Mass flow", "float", quantity="mass_flow", minimum=0.0, optional=True,
        tooltip="Mass flow rate through the duct.",
    ),
    "area": FieldSpec(
        "area", "Flow area", "float", quantity="area", minimum=0.0, optional=True,
        tooltip="Flow cross-section.",
    ),
    "wetted_perimeter": FieldSpec(
        "wetted_perimeter", "Wetted perimeter", "float", quantity="length", minimum=0.0,
        optional=True, tooltip="Wetted perimeter P_wet.",
    ),
}

_PRECISION = 6


def _g(value: float) -> str:
    return f"{value:.{_PRECISION}g}"


class CorrelationPanel(FormPanel):
    """Form of a correlation convection condition with formula, validity and h preview.

    Parameters
    ----------
    spec : FormSpec
        The form of ``CorrelationConvection``.
    document : Document
    address : tuple
        Address ``("bcs", i)``.
    view : SceneView, optional
    parent : QWidget, optional

    Attributes
    ----------
    formula_label, validity_label, title_label_info, length_label, result_label : QLabel
        The texts shown below the form.
    preview_edits : dict of str to NumberEdit
        The preview input editors.
    preview_h : float or None
        h [W/(m^2 K)] of the last preview, ``None`` if it could not be computed.
    preview_result : HtcResult or None
        The full result of the last preview.
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
        self.preview_h: float | None = None
        self.preview_result: HtcResult | None = None
        self.preview_edits: dict[str, NumberEdit] = {}

        box = QGroupBox("Correlation")
        info = QVBoxLayout(box)
        self.title_label_info = QLabel()
        self.title_label_info.setStyleSheet("font-weight: bold;")
        self.formula_label = self._text_label()
        self.validity_label = self._text_label()
        self.length_label = self._text_label()
        for label in (
            self.title_label_info, self.formula_label, self.validity_label, self.length_label
        ):
            info.addWidget(label)

        preview = QGroupBox("Preview of h")
        outer = QVBoxLayout(preview)
        self.preview_form = QFormLayout()
        outer.addLayout(self.preview_form)
        for key, field in _PREVIEW_FIELDS.items():
            edit = NumberEdit(field, document.model.display_units)
            edit.committed.connect(lambda _value: self.update_preview())
            self.preview_edits[key] = edit
            self.preview_form.addRow(QLabel(field.label), edit)
        self.result_label = self._text_label()
        outer.addWidget(self.result_label)

        layout = self.layout()
        assert isinstance(layout, QVBoxLayout)
        at = layout.count() - 1  # before the stretch
        layout.insertWidget(at, box)
        layout.insertWidget(at + 1, preview)
        self._ready = True
        self.refresh()

    @staticmethod
    def _text_label() -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    # ------------------------------------------------------------------ form hooks
    def field_choices(self, field: FieldSpec) -> tuple[str, ...] | None:
        """Offer the correlation IDs and the library fluids as lists.

        Internal-flow correlations (``duct_internal``) are left out: they are used by
        streams and are not available as a boundary condition.
        """
        if field.name == "correlation":
            return tuple(cid for cid, info in CORRELATIONS.items() if info.kind != "internal")
        if field.name == "fluid":
            return tuple(library.fluid_names())
        return None

    # --------------------------------------------------------------------- refresh
    @property
    def preview_text(self) -> str:
        """The text of the preview result (the h line, numbers and warnings, or a message)."""
        return self.result_label.text()

    def refresh(self) -> None:
        """Reload the form, then the correlation text and the preview."""
        super().refresh()
        if not self._ready:
            return
        units = self.document.model.display_units
        for key, edit in self.preview_edits.items():
            if edit.settings != units:
                edit.set_settings(units)
            self._unit_label_text(key, edit)
        self._show_info()
        self.update_preview()

    def _unit_label_text(self, key: str, edit: NumberEdit) -> None:
        field = _PREVIEW_FIELDS[key]
        label = self.preview_form.labelForField(edit)
        if isinstance(label, QLabel):
            unit = unit_label(field.quantity, edit.settings)
            label.setText(f"{field.label} [{unit}]" if field.quantity else field.label)

    def _info(self) -> tuple[Any, CorrelationInfo | None]:
        try:
            obj = self.current_object()
        except ModelError:
            return None, None
        return obj, CORRELATION_INFO.get(obj.correlation)

    def _show_info(self) -> None:
        obj, info = self._info()
        if obj is None:
            return
        if info is None:
            self.title_label_info.setText(f"Unknown correlation {obj.correlation!r}")
            for label in (self.formula_label, self.validity_label, self.length_label):
                label.setText("")
            return
        self.title_label_info.setText(info.title)
        self.formula_label.setText(f"Formula ({H_FROM_NU}):\n{info.formula}")
        self.validity_label.setText(f"Validity: {info.validity}")
        self.length_label.setText(
            f"Characteristic length: {info.length}. {properties_at(obj.correlation)}"
        )

    # --------------------------------------------------------------------- preview
    def set_preview_input(self, name: str, value: float | None) -> None:
        """Set a preview input to an SI value (as if typed) and recompute the preview.

        Parameters
        ----------
        name : str
            ``"T_surface"``, ``"T_inf"``, ``"length"``, ``"x"``, ``"velocity"``,
            ``"theta_deg"``, ``"S"``, ``"C"``, ``"n"``, ``"mass_flow"``, ``"area"`` or
            ``"wetted_perimeter"``.
        value : float or None
            The value in SI units (kelvin, metres, ...); ``None`` clears it.
        """
        edit = self.preview_edits[name]
        edit.set_si(value)
        self.update_preview()

    def needed_inputs(self) -> list[str]:
        """Names of the preview inputs shown now (those the condition does not define)."""
        obj, info = self._info()
        if obj is None or info is None:
            return []
        return self._needed_inputs(obj, info)

    def _needed_inputs(self, obj: Any, info: CorrelationInfo) -> list[str]:
        """The preview inputs to type: those the condition does not already define."""
        needed = ["T_surface"]
        if not isinstance(obj.T_inf, Constant):
            needed.append("T_inf")
        for key in info.inputs:
            if key == "length" and obj.char_length is not None:
                continue
            if key == "velocity" and isinstance(obj.velocity, Constant):
                continue
            if key in obj.params and key not in ("length", "velocity"):
                continue
            needed.append(key)
        return needed

    def update_preview(self) -> None:
        """Recompute h with ``api.htc`` from the condition and the preview inputs."""
        self.preview_h = None
        self.preview_result = None
        obj, info = self._info()
        if obj is None or info is None:
            self.result_label.setText("")
            return
        needed = self._needed_inputs(obj, info)
        for key, edit in self.preview_edits.items():
            self.preview_form.setRowVisible(edit, key in needed)
        message = self._input_error(needed)
        if message:
            self.result_label.setText(message)
            return
        T_s = self.preview_edits["T_surface"].si
        if T_s is None:
            self.result_label.setText("Enter a surface temperature to preview h.")
            return
        T_inf = (
            obj.T_inf.value if isinstance(obj.T_inf, Constant) else self.preview_edits["T_inf"].si
        )
        if T_inf is None:
            self.result_label.setText("Enter a fluid temperature to preview h.")
            return
        inputs = self._htc_inputs(obj, info, needed)
        try:
            result = api.htc(
                obj.correlation, obj.fluid if info.needs_fluid else None,
                float(T_s), float(T_inf), **inputs,
            )
        except ModelError as exc:
            self.result_label.setText(f"Cannot compute h: {exc}")
            return
        self.preview_result = result
        self.preview_h = float(result.h)
        self.result_label.setText(self._format(result))

    def _input_error(self, needed: list[str]) -> str:
        for key in needed:
            message = self.preview_edits[key].error_text()
            if message:
                return f"{_PREVIEW_FIELDS[key].label}: {message}"
        return ""

    def _htc_inputs(self, obj: Any, info: CorrelationInfo, needed: list[str]) -> dict[str, Any]:
        """Keyword inputs of ``api.htc``: the condition's values, else the typed ones."""
        inputs: dict[str, Any] = {}
        for key in info.inputs:
            value: float | None
            if key in needed:
                value = self.preview_edits[key].si
            elif key == "length":
                value = obj.char_length
            elif key == "velocity":
                value = obj.velocity.value
            else:
                value = obj.params[key]
            if value is not None:
                inputs[key] = float(value)
        if obj.face_direction is not None:
            inputs["face_direction"] = obj.face_direction
        inputs["multiplier"] = float(obj.multiplier)
        return inputs

    def _format(self, result: HtcResult) -> str:
        units = self.document.model.display_units
        T_film = float(from_si(result.T_film, "temperature", units))
        h = float(from_si(result.h, "htc", units))
        lines = [f"h = {_g(h)} {unit_label('htc', units)}"]
        for name, value in (
            ("Nu", result.Nu), ("Re", result.Re), ("Ra", result.Ra), ("Pr", result.Pr)
        ):
            if value is not None:
                lines.append(f"{name} = {_g(value)}")
        lines.append(f"Regime: {result.regime}")
        lines.append(f"T_film = {_g(T_film)} {unit_label('temperature', units)}")
        if result.length is not None:
            length = float(from_si(result.length, "length", units))
            lines.append(f"Length used = {_g(length)} {unit_label('length', units)}")
        lines.extend(f"Warning: {w}" for w in result.warnings)
        return "\n".join(lines)
