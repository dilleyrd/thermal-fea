"""Property panel of a thermal contact (Plan M10.1).

:class:`ContactPanel` is the generated form of :class:`~thermalfea.model.bcs.Contact`
(:data:`thermalfea.model.contact_forms.CONTACT_FORM`). The conductance may depend on time and
position but not on temperature (Theory §11; :class:`thermalfea.physics.contact.ContactTerm`
raises ``ModelError`` otherwise). The form has no restriction for that, so the panel refuses
such a function before it reaches ``document.edit``: the message is shown in the panel's error
label, nothing changes and no undo step is made.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QWidget

from thermalfea.core.forms import FormSpec
from thermalfea.gui.addressing import Address
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.scene import SceneView

CONDUCTANCE_FIELD = "conductance"
TEMPERATURE_MESSAGE = "the conductance cannot depend on temperature"


class ContactPanel(FormPanel):
    """Form of a thermal contact that refuses a temperature-dependent conductance.

    Parameters
    ----------
    spec : FormSpec
        The form of ``Contact``.
    document : Document
    address : tuple
        Address ``("contacts", i)``.
    view : SceneView, optional
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

    def _apply(self, name: str, value: Any) -> bool:
        """Refuse a conductance that depends on temperature; apply everything else."""
        if (
            name == CONDUCTANCE_FIELD
            and not self._refreshing
            and bool(getattr(value, "depends_on_T", False))
        ):
            self._set_error(name, TEMPERATURE_MESSAGE)
            return False
        return super()._apply(name, value)
