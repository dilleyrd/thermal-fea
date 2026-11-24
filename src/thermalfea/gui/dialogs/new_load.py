"""Dialogs asking for the values a new correlation convection or radiation load needs (M11.9).

A load that is added with empty or zero values (no correlation, no fluid, ambient 0 K,
emissivity 0) cannot be solved and the model would not say why until validation. So adding
a :class:`~thermalfea.model.bcs.CorrelationConvection` or a
:class:`~thermalfea.model.bcs.RadiationAmbient` from the GUI opens one of these dialogs.
Every field starts empty: no value is invented. "OK" is enabled only when every field is
filled and valid; it emits :attr:`load_requested` with the new load (name and selection are
set by the caller) and closes. The dialogs are shown non-modally (``show()``).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermalfea.convection.correlations import CORRELATIONS
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import unit_label
from thermalfea.core.functions import Constant
from thermalfea.core.units import UnitSettings
from thermalfea.gui.property_panels.network import parse_number
from thermalfea.materials import library
from thermalfea.model.bcs import BoundaryCondition, CorrelationConvection, RadiationAmbient

#: The correlation that needs no fluid (the user power law).
NO_FLUID = "power_law"


def boundary_correlations() -> tuple[str, ...]:
    """Correlations offered for a boundary condition (internal-flow ones are streams')."""
    return tuple(cid for cid, info in CORRELATIONS.items() if info.kind != "internal")


class NewLoadDialog(QDialog):
    """Base of the dialogs: empty fields, an OK button that waits for valid entries.

    Parameters
    ----------
    parent : QWidget, optional
    units : UnitSettings, optional
        Display units of the entries; default SI.

    Signals
    -------
    load_requested(object)
        The load to add (name ``"Load"`` and an empty selection; the caller sets both).

    Attributes
    ----------
    ok_button : QPushButton
        Enabled only when :meth:`build_load` succeeds.
    ambient_edit : QLineEdit
        The ambient temperature as typed, in the display temperature unit.
    message_label : QLabel
        What is still missing or wrong ("" when the entry is complete).
    """

    load_requested = Signal(object)
    title = "New load"
    intro = ""

    def __init__(self, parent: QWidget | None = None, units: UnitSettings | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.units = units if units is not None else UnitSettings()
        self.setWindowTitle(self.title)
        self.ambient_edit = QLineEdit()
        self.message_label = QLabel("")
        self.message_label.setStyleSheet("color: #b00020;")
        self.message_label.setWordWrap(True)
        self.form = QFormLayout()
        self.add_fields()
        self.form.addRow(
            f"Ambient temperature [{unit_label('temperature', self.units)}]", self.ambient_edit
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.ok_button: QPushButton = buttons.button(QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(self.intro))
        layout.addLayout(self.form)
        layout.addWidget(self.message_label)
        layout.addWidget(buttons)
        self.ambient_edit.textChanged.connect(self.update_state)
        self.update_state()

    def add_fields(self) -> None:
        """Add the fields of the kind (before the ambient temperature)."""
        raise NotImplementedError

    def build_load(self) -> BoundaryCondition:
        """The load described by the entries.

        Raises
        ------
        ValueError
            With a message if a value is missing or not valid.
        """
        raise NotImplementedError

    def ambient(self) -> float:
        """The ambient temperature [K] from the entry (must be above absolute zero)."""
        text = self.ambient_edit.text().strip()
        if not text:
            raise ValueError("enter the ambient temperature")
        value = parse_number(
            text, minimum=0.0, quantity="temperature", units=self.units
        )
        if value is None or not value > 0.0:
            raise ValueError("the ambient temperature must be above 0 K")
        return float(value)

    def update_state(self, *_args: object) -> None:
        """Enable OK when the entry is complete and valid; say what is missing otherwise."""
        try:
            self.build_load()
        except (ValueError, ModelError) as exc:
            self.ok_button.setEnabled(False)
            self.message_label.setText(str(exc))
        else:
            self.ok_button.setEnabled(True)
            self.message_label.setText("")

    def submit(self) -> bool:
        """Emit :attr:`load_requested` and close if the entries are valid.

        Returns
        -------
        bool
            ``True`` when the load was emitted.
        """
        try:
            load = self.build_load()
        except (ValueError, ModelError) as exc:
            self.message_label.setText(str(exc))
            return False
        self.load_requested.emit(load)
        self.close()
        return True


class NewCorrelationConvectionDialog(NewLoadDialog):
    """Asks for the correlation, the fluid and the ambient temperature.

    Attributes
    ----------
    correlation_box, fluid_box : QComboBox
        The correlations (not the internal-flow ones) and the library fluids; the first
        entry of each is empty. The fluid may stay empty for the user power law, which needs
        none.
    """

    title = "New correlation convection"
    intro = "Choose the correlation and the fluid and enter the ambient temperature."

    def add_fields(self) -> None:
        self.correlation_box = QComboBox()
        self.correlation_box.addItem("")
        self.correlation_box.addItems(list(boundary_correlations()))
        self.fluid_box = QComboBox()
        self.fluid_box.addItem("")
        self.fluid_box.addItems(library.fluid_names())
        self.form.addRow("Correlation", self.correlation_box)
        self.form.addRow("Fluid", self.fluid_box)
        self.correlation_box.currentIndexChanged.connect(self.update_state)
        self.fluid_box.currentIndexChanged.connect(self.update_state)

    def build_load(self) -> CorrelationConvection:
        correlation = self.correlation_box.currentText()
        if not correlation:
            raise ValueError("choose a correlation")
        fluid = self.fluid_box.currentText()
        if not fluid and correlation != NO_FLUID:
            raise ValueError("choose a fluid")
        return CorrelationConvection(
            name="Load", selection="", correlation=correlation, fluid=fluid,
            T_inf=Constant(self.ambient()),
        )


class NewRadiationDialog(NewLoadDialog):
    """Asks for the emissivity and the ambient temperature.

    Attributes
    ----------
    emissivity_edit : QLineEdit
        The emissivity as typed (above 0 and at most 1).
    """

    title = "New radiation"
    intro = "Enter the emissivity and the ambient temperature."

    def add_fields(self) -> None:
        self.emissivity_edit = QLineEdit()
        self.form.addRow("Emissivity (0 < e <= 1)", self.emissivity_edit)
        self.emissivity_edit.textChanged.connect(self.update_state)

    def build_load(self) -> RadiationAmbient:
        text = self.emissivity_edit.text().strip()
        if not text:
            raise ValueError("enter the emissivity")
        value = parse_number(text, minimum=0.0)
        if value is None or not 0.0 < value <= 1.0:
            raise ValueError("the emissivity must be above 0 and at most 1")
        return RadiationAmbient(
            name="Load", selection="", emissivity=Constant(float(value)),
            T_inf=Constant(self.ambient()),
        )


#: Registry tag of a load class -> the dialog that asks for its values.
LOAD_DIALOGS: dict[str, type[NewLoadDialog]] = {
    "correlation_convection": NewCorrelationConvectionDialog,
    "radiation_ambient": NewRadiationDialog,
}
