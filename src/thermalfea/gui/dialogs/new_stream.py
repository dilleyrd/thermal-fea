"""Dialog asking for the values a first stream of a model needs (Plan M8.12).

When the model has no stream, nothing in the model can supply the required values (fluid,
flow area, wetted perimeter, cross-section, inlet temperature), so :class:`NewStreamDialog`
asks for them. The fields start empty: no number is invented. It is shown non-modally
(``show()``); "Create" emits :attr:`NewStreamDialog.stream_requested` with the new
:class:`~thermalfea.model.bcs.Stream` and closes, and an incomplete or invalid entry is
reported in the dialog without closing it.
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
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.forms import unit_label
from thermalfea.core.units import UnitSettings
from thermalfea.gui.property_panels.network import parse_number
from thermalfea.materials import library
from thermalfea.model.bcs import Stream

CROSS_SECTIONS = ("circular", "parallel_plates", "parallel_plates_one_side", "square")


class NewStreamDialog(QDialog):
    """Non-modal dialog that builds the first stream of a model.

    Parameters
    ----------
    parent : QWidget, optional
    units : UnitSettings, optional
        Display units of the entries (flow area, wetted perimeter, inlet temperature);
        default SI.

    Signals
    -------
    stream_requested(object)
        The :class:`Stream` to add (name "Stream"; the caller gives it a unique name).

    Attributes
    ----------
    fluid_box : QComboBox
        Library fluids; the first entry is empty.
    cross_box : QComboBox
        Cross-sections; the first entry is empty.
    flow_area_edit, wetted_edit, inlet_edit : QLineEdit
        Flow area, wetted perimeter and inlet temperature as typed, in the display units.
    message_label : QLabel
        The last complaint about the entry ("" when none).
    """

    stream_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None, units: UnitSettings | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.units = units if units is not None else UnitSettings()
        self.setWindowTitle("New stream")
        self.fluid_box = QComboBox()
        self.fluid_box.addItem("")
        self.fluid_box.addItems(list(library.fluids()))
        self.cross_box = QComboBox()
        self.cross_box.addItem("")
        self.cross_box.addItems(list(CROSS_SECTIONS))
        self.flow_area_edit = QLineEdit()
        self.wetted_edit = QLineEdit()
        self.inlet_edit = QLineEdit()
        self.message_label = QLabel("")
        self.message_label.setStyleSheet("color: #b00020;")
        self.message_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Fluid", self.fluid_box)
        form.addRow(f"Flow area [{unit_label('area', self.units)}]", self.flow_area_edit)
        form.addRow(f"Wetted perimeter [{unit_label('length', self.units)}]", self.wetted_edit)
        form.addRow("Cross-section", self.cross_box)
        form.addRow(
            f"Inlet temperature [{unit_label('temperature', self.units)}]", self.inlet_edit
        )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        buttons.accepted.connect(self.submit)
        buttons.rejected.connect(self.close)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("The model has no stream yet. Enter the values of the first one."))
        layout.addLayout(form)
        layout.addWidget(self.message_label)
        layout.addWidget(buttons)

    def build_stream(self) -> Stream:
        """The stream described by the entries.

        Raises
        ------
        ValueError
            With a message if a value is missing or not a number.
        """
        fluid = self.fluid_box.currentText()
        if not fluid:
            raise ValueError("choose a fluid")
        cross = self.cross_box.currentText()
        if not cross:
            raise ValueError("choose a cross-section")
        return Stream(
            name="Stream",
            fluid=fluid,
            mode="in_plane",
            walls=[],
            flow_area=parse_number(
                self._text(self.flow_area_edit, "flow area"), minimum=0.0,
                quantity="area", units=self.units,
            ),
            wetted_perimeter=parse_number(
                self._text(self.wetted_edit, "wetted perimeter"), minimum=0.0,
                quantity="length", units=self.units,
            ),
            cross_section=cross,  # type: ignore[arg-type]
            T_inlet=parse_number(
                self._text(self.inlet_edit, "inlet temperature"), minimum=0.0,
                quantity="temperature", units=self.units,
            ),
        )

    @staticmethod
    def _text(edit: QLineEdit, what: str) -> str:
        text = edit.text().strip()
        if not text:
            raise ValueError(f"enter the {what}")
        return text

    def submit(self) -> bool:
        """Emit :attr:`stream_requested` and close if the entries are complete.

        Returns
        -------
        bool
            ``True`` when the stream was emitted.
        """
        try:
            stream = self.build_stream()
        except ValueError as exc:
            self.message_label.setText(str(exc))
            return False
        self.message_label.setText("")
        self.stream_requested.emit(stream)
        self.close()
        return True
