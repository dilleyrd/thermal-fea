"""Form specification of a thermal contact (Plan M10.1), without Qt.

``CONTACT_FORM`` is registered with :func:`thermalfea.core.forms.register_form` when
:mod:`thermalfea.model.model` is imported, so the contact panel gets its fields from here.
The conductance is in W/(m^2 K) (quantity ``htc`` of :data:`thermalfea.core.units.QUANTITIES`).
The name is never part of a form.
"""

from __future__ import annotations

from ..core.forms import FieldSpec, FormSpec, register_form
from .bcs import Contact

CONTACT_FORM = FormSpec(
    "Thermal contact",
    [
        FieldSpec(
            "selection", "Interface curves", "selection", selection_dims=(1,),
            tooltip="Curve selection; every curve must lie between two regions.",
        ),  # fmt: skip
        FieldSpec(
            "conductance", "Contact conductance", "function", quantity="htc", minimum=0.0,
            tooltip="Conductance of the interface. It may depend on time and position, "
            "but not on temperature.",
        ),  # fmt: skip
    ],
    category="contact",
    description="A thermal contact resistance between two regions along interface curves.",
)

register_form(Contact, CONTACT_FORM)
