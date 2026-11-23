"""HTC calculator tool window (Plan M8.12): h of one correlation at single values.

:class:`HtcCalculator` is a non-modal window (Tools > HTC calculator...). The user picks a
correlation and a library fluid, types the surface and fluid temperatures [K] and the inputs
listed in ``CORRELATION_INFO[id].inputs`` (only those are shown). The formula, validity and
characteristic length come from :data:`thermalfea.convection.correlation_info.CORRELATION_INFO`;
h and the other numbers come from :func:`thermalfea.api.htc`. Nothing is computed here and no
default input is invented: an empty input gives a message and no result. A
:class:`~thermalfea.core.errors.ModelError` is shown as text, never raised.

Attributes ``result`` (the last :class:`~thermalfea.convection.calculator.HtcResult` or
``None``) and ``message`` (the last complaint, ``""`` when none) are kept for tests.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermalfea import api
from thermalfea.convection.calculator import HtcResult
from thermalfea.convection.correlation_info import (
    CORRELATION_INFO,
    H_FROM_NU,
    properties_at,
)
from thermalfea.convection.correlations import CORRELATIONS
from thermalfea.core.errors import ModelError
from thermalfea.gui.property_panels.network import parse_number
from thermalfea.materials import library

#: Label and unit of the correlation inputs (SI; no unit conversion here).
INPUT_LABELS: dict[str, tuple[str, str]] = {
    "length": ("Characteristic length", "m"),
    "velocity": ("Velocity", "m/s"),
    "x": ("Distance from leading edge", "m"),
    "theta_deg": ("Inclination from vertical", "deg"),
    "mass_flow": ("Mass flow", "kg/s"),
    "area": ("Flow area", "m^2"),
    "wetted_perimeter": ("Wetted perimeter", "m"),
    "C": ("Coefficient C", "-"),
    "n": ("Exponent n", "-"),
}


def _g(value: float) -> str:
    return f"{value:.6g}"


class HtcCalculator(QWidget):
    """Non-modal window computing one heat-transfer coefficient with ``api.htc``.

    Parameters
    ----------
    parent : QWidget, optional

    Attributes
    ----------
    correlation_box : QComboBox
        Correlation identifiers (:data:`CORRELATIONS`).
    fluid_box : QComboBox
        Library fluids; disabled for correlations that need no fluid.
    t_surface_edit, t_inf_edit : QLineEdit
        Surface and fluid temperatures [K].
    input_edits : dict of str to QLineEdit
        One per input of any correlation; only the rows of the chosen correlation are shown.
    result : HtcResult or None
        The last successful calculation.
    message : str
        The last complaint ("" when none).
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("HTC calculator")
        self.result: HtcResult | None = None
        self.message = ""
        self.correlation_box = QComboBox()
        self.correlation_box.addItems(list(CORRELATIONS))
        self.fluid_box = QComboBox()
        self.fluid_box.addItems(list(library.fluids()))
        self.t_surface_edit = QLineEdit()
        self.t_inf_edit = QLineEdit()
        self.input_edits: dict[str, QLineEdit] = {}
        self.input_labels: dict[str, QLabel] = {}

        self.title_label = QLabel("")
        self.title_label.setStyleSheet("font-weight: bold;")
        self.formula_label = self._text_label()
        self.validity_label = self._text_label()
        self.length_label = self._text_label()
        info = QGroupBox("Correlation")
        info_layout = QVBoxLayout(info)
        for label in (self.title_label, self.formula_label, self.validity_label, self.length_label):
            info_layout.addWidget(label)

        self.form = QFormLayout()
        self.form.addRow("Correlation", self.correlation_box)
        self.form.addRow("Fluid", self.fluid_box)
        self.form.addRow("Surface temperature [K]", self.t_surface_edit)
        self.form.addRow("Fluid temperature [K]", self.t_inf_edit)
        for key, (label, unit) in INPUT_LABELS.items():
            edit = QLineEdit()
            text = f"{label} [{unit}]"
            row_label = QLabel(text)
            self.input_edits[key] = edit
            self.input_labels[key] = row_label
            self.form.addRow(row_label, edit)
        self.calculate_button = QPushButton("Calculate")
        self.result_label = self._text_label()
        self.message_label = QLabel("")
        self.message_label.setStyleSheet("color: #b00020;")
        self.message_label.setWordWrap(True)

        outer = QVBoxLayout(self)
        outer.addWidget(info)
        outer.addLayout(self.form)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.calculate_button)
        outer.addLayout(buttons)
        outer.addWidget(self.result_label)
        outer.addWidget(self.message_label)
        outer.addStretch(1)

        self.correlation_box.currentIndexChanged.connect(lambda _i: self._on_correlation())
        self.fluid_box.currentIndexChanged.connect(lambda _i: self.calculate())
        for edit in (self.t_surface_edit, self.t_inf_edit, *self.input_edits.values()):
            edit.textChanged.connect(lambda _t: self.calculate())
        self.calculate_button.clicked.connect(lambda _c=False: self.calculate())
        self._on_correlation()
        self.resize(560, 640)

    @staticmethod
    def _text_label() -> QLabel:
        label = QLabel()
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        return label

    # ----------------------------------------------------------------- inputs
    @property
    def correlation(self) -> str:
        """Identifier of the chosen correlation."""
        return self.correlation_box.currentText()

    def visible_inputs(self) -> list[str]:
        """Names of the input fields shown for the chosen correlation (in form order)."""
        return [key for key, edit in self.input_edits.items() if not edit.isHidden()]

    def _on_correlation(self) -> None:
        info = CORRELATION_INFO.get(self.correlation)
        needed = info.inputs if info is not None else ()
        for key, edit in self.input_edits.items():
            shown = key in needed
            self.form.setRowVisible(edit, shown)
            self.input_labels[key].setVisible(shown)
        if info is None:
            self.title_label.setText(f"Unknown correlation {self.correlation!r}")
            for label in (self.formula_label, self.validity_label, self.length_label):
                label.setText("")
            self.fluid_box.setEnabled(False)
        else:
            self.title_label.setText(info.title)
            self.formula_label.setText(f"Formula ({H_FROM_NU}):\n{info.formula}")
            self.validity_label.setText(f"Validity: {info.validity}")
            self.length_label.setText(
                f"Characteristic length: {info.length}. {properties_at(self.correlation)}"
            )
            self.fluid_box.setEnabled(info.needs_fluid)
        self.calculate()

    @staticmethod
    def _number(edit: QLineEdit, label: str) -> float:
        """The number typed in ``edit``; ``ValueError`` (naming ``label``) if none."""
        if not edit.text().strip():
            raise ValueError(f"enter the {label}")
        try:
            value = parse_number(edit.text())
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from None
        return float(value or 0.0)

    # ------------------------------------------------------------ calculation
    def calculate(self) -> HtcResult | None:
        """Compute h for the current entries; sets :attr:`result` and :attr:`message`.

        Returns
        -------
        HtcResult or None
            ``None`` (with :attr:`message` set) when an entry is missing or invalid, or
            ``api.htc`` refuses the inputs.
        """
        self.result = None
        self.message = ""
        info = CORRELATION_INFO.get(self.correlation)
        if info is not None:
            try:
                self.result = self._compute(info.inputs, info.needs_fluid)
            except ValueError as exc:
                self.message = str(exc)
            except ModelError as exc:
                self.message = f"Cannot compute h: {exc}"
        self._show()
        return self.result

    def _compute(self, input_names: tuple[str, ...], needs_fluid: bool) -> HtcResult:
        t_surface = self._number(self.t_surface_edit, "surface temperature")
        t_inf = self._number(self.t_inf_edit, "fluid temperature")
        values: dict[str, float] = {}
        for key in input_names:
            label, unit = INPUT_LABELS.get(key, (key, "-"))
            name = label if unit == "-" else f"{label} [{unit}]"
            values[key] = self._number(self.input_edits[key], name)
        fluid: str | None = None
        if needs_fluid:
            fluid = self.fluid_box.currentText()
            if not fluid:
                raise ValueError("choose a fluid")
        return api.htc(self.correlation, fluid, t_surface, t_inf, **values)

    def _show(self) -> None:
        self.message_label.setText(self.message)
        result = self.result
        if result is None:
            self.result_label.setText("")
            return
        lines = [f"h = {_g(result.h)} W/(m^2 K)"]
        for name, value in (
            ("Nu", result.Nu), ("Re", result.Re), ("Ra", result.Ra), ("Pr", result.Pr)
        ):
            if value is not None:
                lines.append(f"{name} = {_g(value)}")
        lines.append(f"Regime: {result.regime}")
        lines.append(f"T_film = {_g(result.T_film)} K")
        if result.length is not None:
            lines.append(f"Length used = {_g(result.length)} m")
        lines.extend(f"Warning: {w}" for w in result.warnings)
        self.result_label.setText("\n".join(lines))
