"""Form specifications of materials and region assignments (Plan M8.6).

They are registered with :func:`thermalfea.core.forms.register_form` when
:mod:`thermalfea.model.model` is imported, so the property panels get their fields without
any GUI code. Quantities come from :data:`thermalfea.core.units.QUANTITIES`:

* conductivities ``k`` and ``k2`` -> ``conductivity`` [W/(m K)];
* density ``rho`` -> ``density`` [kg/m^3];
* specific heat ``cp`` -> ``specific_heat`` [J/(kg K)];
* thickness -> ``length`` [m].

The material angle is stored in radians (Data §4) and has the quantity ``angle``.
The ``material`` field of a region is a name of a model material; the region panel
(:class:`thermalfea.gui.property_panels.region.RegionPanel`) offers the names in a combo box.
"""

from __future__ import annotations

from ..core.forms import FieldSpec, FormSpec, register_form
from ..materials.material import Material
from .model import RegionAssignment

_SURFACES = (2,)

MATERIAL_FORM = FormSpec(
    "Material",
    [
        FieldSpec(
            "k", "Conductivity (along axis)", "function", quantity="conductivity",
            minimum=0.0, variables=("T",),
            tooltip=(
                "Conductivity in every direction of an isotropic material, or along the "
                "material axis of a directional one. Each part sets the axis by its "
                "Material angle."
            ),
        ),  # fmt: skip
        FieldSpec(
            "rho", "Density", "function", quantity="density", minimum=0.0,
            variables=("T",),
            tooltip="Density of the solid.",
        ),  # fmt: skip
        FieldSpec(
            "cp", "Specific heat", "function", quantity="specific_heat", minimum=0.0,
            variables=("T",),
            tooltip="Specific heat capacity of the solid.",
        ),  # fmt: skip
        FieldSpec(
            "k2", "Conductivity (across axis)", "function",
            quantity="conductivity", minimum=0.0, optional=True, variables=("T",),
            tooltip=(
                "Conductivity at right angles to the material axis, in the model plane. "
                "Leave empty for an isotropic material."
            ),
        ),  # fmt: skip
    ],
    category="material",
    description=(
        "Thermal properties of a solid. For a directional material (laminations, fibers, "
        "layered boards) fill in both conductivities; the axis direction is the Material "
        "angle of each part that uses the material."
    ),
)

REGION_FORM = FormSpec(
    "Part",
    [
        FieldSpec(
            "name", "Name", "str",
            tooltip="Name of the part, unique in the model (shown in the tree and the view).",
        ),  # fmt: skip
        FieldSpec(
            "selection", "Selection", "selection", selection_dims=_SURFACES,
            tooltip="Named selection of parts (surfaces) the material is assigned to.",
        ),  # fmt: skip
        FieldSpec(
            "material", "Material", "str",
            tooltip="Name of a material in the model.",
        ),  # fmt: skip
        FieldSpec(
            "thickness", "Thickness", "float", quantity="length", minimum=0.0,
            tooltip="Thickness of a planar model; ignored for axisymmetric models.",
        ),  # fmt: skip
        FieldSpec(
            "material_angle", "Material angle", "float", quantity="angle",
            tooltip=(
                "Angle of the material axis, counter-clockwise from x (r in axisymmetric "
                "models). Used only when the material has a conductivity across the axis."
            ),
        ),  # fmt: skip
    ],
    category="region",
    description="A part: the material and thickness of the surfaces of a selection.",
)

register_form(Material, MATERIAL_FORM)
register_form(RegionAssignment, REGION_FORM)
