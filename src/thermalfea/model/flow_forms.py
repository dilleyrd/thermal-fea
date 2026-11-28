"""Form specification of a flow stream (Plan M8.12), without Qt.

``STREAM_FORM`` is registered with :func:`thermalfea.core.forms.register_form` when
:mod:`thermalfea.model.model` is imported, so the stream editor gets its fields from here.
Quantities come from :data:`thermalfea.core.units.QUANTITIES`:

* roughness -> ``length`` [m];
* inlet temperature -> ``temperature`` [K];
* mass flow -> ``mass_flow`` [kg/s];
* film coefficient override -> ``htc`` [W/(m^2 K)];
* flow area -> ``area`` [m^2]; wetted perimeter and path -> ``length`` [m].

The name is never part of a form.
"""

from __future__ import annotations

from ..core.forms import FieldSpec, FormSpec, register_form
from .bcs import STREAM_CROSS_SECTIONS, STREAM_NU_OPTIONS, Stream

_MODES = ("in_plane", "through_plane")
_CROSS_SECTIONS = STREAM_CROSS_SECTIONS
_NU_OPTIONS = STREAM_NU_OPTIONS

STREAM_FORM = FormSpec(
    "Stream",
    [
        FieldSpec(
            "fluid", "Fluid", "str",
            tooltip="Name of a library fluid.",
        ),  # fmt: skip
        FieldSpec(
            "mode", "Mode", "choice", choices=_MODES,
            tooltip="In-plane: the stream runs along a path in the model plane; "
            "through-plane: it flows perpendicular to the plane (planar models).",
        ),  # fmt: skip
        FieldSpec(
            "walls", "Walls", "selection_list", selection_dims=(1,),
            tooltip="Boundary selections wetted by the stream.",
        ),  # fmt: skip
        FieldSpec(
            "flow_area", "Flow area", "float", quantity="area", minimum=0.0,
            tooltip="Flow cross-section.",
        ),  # fmt: skip
        FieldSpec(
            "wetted_perimeter", "Wetted perimeter", "float", quantity="length", minimum=0.0,
            tooltip="Wetted perimeter.",
        ),  # fmt: skip
        FieldSpec(
            "cross_section", "Cross-section", "choice", choices=_CROSS_SECTIONS,
            tooltip="Shape of the flow cross-section.",
        ),  # fmt: skip
        FieldSpec(
            "diameter_ratio", "Diameter ratio D_i/D_o", "float", minimum=0.0, optional=True,
            tooltip="Annulus cross-sections only: inner over outer diameter "
            "(0.05 to 1 for annulus_inner, 0 to 1 for annulus_outer).",
        ),  # fmt: skip
        FieldSpec(
            "T_inlet", "Inlet temperature", "function", quantity="temperature", minimum=0.0,
            tooltip="Fluid temperature at the inlet.",
        ),  # fmt: skip
        FieldSpec(
            "roughness", "Wall roughness", "float", quantity="length", minimum=0.0,
            tooltip="Absolute wall roughness.",
        ),  # fmt: skip
        FieldSpec(
            "mass_flow", "Mass flow", "function", quantity="mass_flow", minimum=0.0,
            optional=True,
            tooltip="Empty: the mass flow comes from a network branch.",
        ),  # fmt: skip
        FieldSpec(
            "path", "Path", "xy_list", quantity="length",
            tooltip="Polyline from inlet to outlet as 'x, y; x, y' (in-plane streams).",
        ),  # fmt: skip
        FieldSpec(
            "n_cells", "Number of cells", "int", minimum=1, optional=True,
            tooltip="Empty: one fluid cell per wall edge along the path.",
        ),  # fmt: skip
        FieldSpec(
            "nu_option", "Nusselt option", "choice", choices=_NU_OPTIONS,
            tooltip="Choice of the duct Nusselt correlation.",
        ),  # fmt: skip
        FieldSpec(
            "h_multiplier", "Coefficient multiplier", "float", minimum=0.0,
            tooltip="Factor applied to the computed heat-transfer coefficient.",
        ),  # fmt: skip
        FieldSpec(
            "h_override", "Coefficient override", "function", quantity="htc", minimum=0.0,
            optional=True,
            tooltip="Empty: the duct correlation is used. Otherwise a function of time.",
        ),  # fmt: skip
    ],
    category="flow",
    description="A one-dimensional fluid stream wetting some walls of the model.",
)

register_form(Stream, STREAM_FORM)
