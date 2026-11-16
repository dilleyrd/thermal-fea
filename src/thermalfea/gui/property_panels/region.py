"""Property panel of a region assignment (Plan M8.6).

:class:`RegionPanel` is a :class:`~thermalfea.gui.property_panels.form.FormPanel` whose
``material`` field is a combo box listing the names of the materials currently in the
model. The form spec only says the field is a name (``str``); the list of choices is
dynamic, so the combo is filled on every refresh. Choosing a name goes through the same
``FormPanel._apply`` path as every other field, i.e. one ``Document.edit`` per change.
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QWidget

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec, FormSpec
from thermalfea.gui.addressing import Address, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.scene import SceneView

_MATERIAL = "material"


class RegionPanel(FormPanel):
    """Form of a :class:`~thermalfea.model.model.RegionAssignment`.

    Parameters
    ----------
    spec : FormSpec
        The region form (its ``material`` field is shown as a combo box).
    document : Document
    address : tuple
        Address ``("regions", i)`` of the region.
    view : SceneView, optional
        Viewport used by the selection field for picking.
    parent : QWidget, optional
    """

    def __init__(
        self,
        spec: FormSpec,
        document: Document,
        address: Address,
        view: SceneView | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(spec, document, address, view, parent)

    def _make_editor(self, f: FieldSpec) -> tuple[QWidget, None]:
        if f.name != _MATERIAL:
            return super()._make_editor(f)
        combo = QComboBox()
        self._choices[_MATERIAL] = ()
        combo.activated.connect(lambda i: self._apply(_MATERIAL, self._choices[_MATERIAL][i]))
        combo.setToolTip(f.tooltip)
        return combo, None

    def refresh(self) -> None:
        """Fill the material list from the model, then reload every editor."""
        self._fill_materials()
        super().refresh()

    def material_names(self) -> tuple[str, ...]:
        """The names offered by the material combo box."""
        return self._choices.get(_MATERIAL, ())

    def _fill_materials(self) -> None:
        combo = self.editors.get(_MATERIAL)
        if not isinstance(combo, QComboBox):
            return
        model = self.document.model
        names = list(model.materials)
        try:
            current = resolve(model, self.address).material
        except ModelError:
            current = None
        if current and current not in names:  # keep a dangling name visible, not silently
            names.append(current)
        self._choices[_MATERIAL] = tuple(names)
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        combo.blockSignals(False)
