"""The display-units dialog (Plan M10.4): a preset chooser and one combo box per quantity.

:class:`UnitsDialog` is used *non-modally* (``show()``, never ``exec()``). Choosing a preset
fills the combo boxes; any combo box can then be changed on its own (the preset chooser
shows "Custom" when the combinations match no preset). :meth:`UnitsDialog.apply` replaces
the unit settings of the model in one undoable ``Document.edit``; nothing stored changes,
because the model keeps every value in SI.
"""

from __future__ import annotations

from dataclasses import fields

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.units import PRESETS, UnitSettings, label_of, units_of
from thermalfea.gui.document import Document

CUSTOM = "Custom"

#: Names shown beside the combo boxes (the order of the dialog).
QUANTITY_NAMES: dict[str, str] = {
    "temperature": "Temperature",
    "length": "Length",
    "area": "Area",
    "angle": "Angle",
    "time": "Time",
    "velocity": "Velocity",
    "conductivity": "Thermal conductivity",
    "htc": "Heat-transfer coefficient",
    "heat_flux": "Heat flux",
    "heat_gen": "Volumetric heat generation",
    "power": "Heat flow / power",
    "density": "Density",
    "specific_heat": "Specific heat",
    "mass_flow": "Mass flow",
    "pressure": "Pressure",
}


class UnitsDialog(QDialog):
    """Choose the display units of the model.

    Parameters
    ----------
    document : Document
        Its ``model.display_units`` is shown and replaced by :meth:`apply`.
    parent : QWidget, optional

    Attributes
    ----------
    preset_combo : QComboBox
        The preset names of :data:`thermalfea.core.units.PRESETS`, then "Custom".
    combos : dict of str to QComboBox
        One per quantity (the field names of ``UnitSettings``); the item data is the unit
        identifier.
    status_label : QLabel
        The last refusal ("" when none).
    """

    def __init__(self, document: Document, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.setWindowTitle("Units")
        self._loading = False
        outer = QVBoxLayout(self)
        outer.addWidget(QLabel(
            "Display units only: the model stores every value in SI, so changing them\n"
            "changes how numbers are shown and typed, never the model or its results."
        ))
        form = QFormLayout()
        self.preset_combo = QComboBox()
        for name in PRESETS:
            self.preset_combo.addItem(name, name)
        self.preset_combo.addItem(CUSTOM, CUSTOM)
        form.addRow("Preset", self.preset_combo)
        self.combos: dict[str, QComboBox] = {}
        known = {f.name for f in fields(UnitSettings)}
        assert set(QUANTITY_NAMES) == known, "the dialog must offer every unit setting"
        for quantity, title in QUANTITY_NAMES.items():
            combo = QComboBox()
            for unit in units_of(quantity):
                combo.addItem(label_of(quantity, unit), unit)
            combo.activated.connect(lambda _i: self._on_combo_activated())
            self.combos[quantity] = combo
            form.addRow(title, combo)
        outer.addLayout(form)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #b00020;")
        self.status_label.setWordWrap(True)
        outer.addWidget(self.status_label)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Apply
            | QDialogButtonBox.StandardButton.Cancel
        )
        outer.addWidget(self.buttons)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        apply_button = self.buttons.button(QDialogButtonBox.StandardButton.Apply)
        apply_button.clicked.connect(lambda _checked=False: self.apply())
        self.preset_combo.activated.connect(lambda _i: self._on_preset_activated())
        self.reload()

    # ----------------------------------------------------------------- showing
    def reload(self) -> None:
        """Show the unit settings of the document's current model."""
        self.set_settings(self.document.model.display_units)

    def set_settings(self, settings: UnitSettings) -> None:
        """Show ``settings`` in the combo boxes (applies nothing)."""
        self._loading = True
        try:
            for quantity, combo in self.combos.items():
                combo.setCurrentIndex(combo.findData(getattr(settings, quantity)))
        finally:
            self._loading = False
        self._sync_preset()

    def settings(self) -> UnitSettings:
        """The unit settings the combo boxes show."""
        return UnitSettings(**{q: str(c.currentData()) for q, c in self.combos.items()})

    def _sync_preset(self) -> None:
        """Select the preset the combo boxes match, else "Custom"."""
        current = self.settings()
        name = CUSTOM
        for preset in PRESETS:
            if current == UnitSettings.preset(preset, current.temperature):
                name = preset
                break
        self.preset_combo.setCurrentIndex(self.preset_combo.findData(name))

    # ------------------------------------------------------------------ choosing
    def set_preset(self, name: str) -> None:
        """Fill the combo boxes from a preset (the current temperature unit is kept by the
        SI presets, see :meth:`UnitSettings.preset`).

        Raises
        ------
        ModelError
            If ``name`` is not a preset.
        """
        self.set_settings(UnitSettings.preset(name, self.settings().temperature))

    def set_unit(self, quantity: str, unit: str) -> None:
        """Choose one unit by identifier (as the user does with a combo box)."""
        combo = self.combos[quantity]
        index = combo.findData(unit)
        if index < 0:
            raise ModelError(f"unknown {quantity.replace('_', ' ')} unit {unit!r}")
        combo.setCurrentIndex(index)
        self._on_combo_activated()

    def _on_preset_activated(self) -> None:
        name = str(self.preset_combo.currentData())
        if name != CUSTOM:
            self.set_preset(name)

    def _on_combo_activated(self) -> None:
        if not self._loading:
            self._sync_preset()

    # ------------------------------------------------------------------ applying
    def apply(self) -> bool:
        """Replace the model's unit settings (one undoable edit).

        Returns
        -------
        bool
            ``True`` if the settings changed.
        """
        new = self.settings()

        def mutate(model: object) -> None:
            model.display_units = new  # type: ignore[attr-defined]

        try:
            changed = self.document.edit("Change units", mutate)
        except ModelError as exc:
            self.status_label.setText(str(exc))
            return False
        self.status_label.setText("")
        return changed

    def accept(self) -> None:
        """Apply the choice and close the dialog."""
        if self.apply() or not self.status_label.text():
            super().accept()
