"""Form specifications of the built-in boundary conditions (Plan M8.4).

They are passed to ``registry.register_bc(..., form=...)`` in :mod:`thermalfea.model.bcs`.
Quantities come from :data:`thermalfea.core.units.QUANTITIES`; a physical quantity that is
missing there (a velocity) is left without one and so is shown in SI without conversion.
The ``correlation`` and ``fluid`` choices are free text until the load panels of M8.8.
"""

from __future__ import annotations

from ..core.forms import FieldSpec, FormSpec

_CURVES = (1,)
_SURFACES = (2,)


def _sel(dims: tuple[int, ...], what: str) -> FieldSpec:
    return FieldSpec(
        "selection", "Selection", "selection", selection_dims=dims,
        tooltip=f"Named selection of {what} the condition applies to.",
    )  # fmt: skip


def _temperature(
    name: str, label: str, variables: tuple[str, ...] | None = None
) -> FieldSpec:
    return FieldSpec(
        name, label, "function", quantity="temperature", minimum=0.0, variables=variables
    )


BC_FORMS: dict[str, FormSpec] = {
    "fixed_temperature": FormSpec(
        "Fixed Temperature",
        [_sel((0, 1), "boundaries or points"), _temperature("T", "Temperature", ("t", "x", "y"))],
        description="Prescribed temperature on boundaries or points.",
    ),
    "heat_flux": FormSpec(
        "Heat Flux",
        [
            _sel(_CURVES, "boundaries"),
            FieldSpec("q", "Heat flux", "function", quantity="heat_flux"),
        ],
        description="Heat flux on boundaries, positive into the body.",
    ),
    "heat_flow": FormSpec(
        "Heat Flow",
        [
            _sel(_CURVES, "boundaries"),
            FieldSpec("P", "Heat flow", "function", quantity="power", variables=("t",)),
        ],
        description="Total heat flow spread uniformly over boundaries, positive into the body.",
    ),
    "heat_generation": FormSpec(
        "Heat Generation",
        [
            _sel(_SURFACES, "parts"),
            FieldSpec("Q", "Heat generation", "function", quantity="heat_gen"),
        ],
        description="Volumetric heat generation in parts.",
    ),
    "heat_power": FormSpec(
        "Heat Power",
        [
            _sel(_SURFACES, "parts"),
            FieldSpec("P", "Power", "function", quantity="power", variables=("t",)),
        ],
        description="Total power generated uniformly in parts.",
    ),
    "convection": FormSpec(
        "Convection",
        [
            _sel(_CURVES, "boundaries"),
            FieldSpec("h", "Heat-transfer coefficient", "function", quantity="htc"),
            _temperature("T_inf", "Fluid temperature"),
        ],
        description="Convection to a fluid at a given temperature.",
    ),
    "correlation_convection": FormSpec(
        "Correlation Convection",
        [
            _sel(_CURVES, "boundaries"),
            FieldSpec("correlation", "Correlation", "str", tooltip="Correlation identifier."),
            FieldSpec("fluid", "Fluid", "str", tooltip="Name of a library fluid."),
            _temperature("T_inf", "Fluid temperature"),
            FieldSpec(
                "velocity", "Velocity", "function", quantity="velocity", optional=True,
                tooltip="Free-stream velocity.",
            ),
            FieldSpec(
                "char_length", "Characteristic length", "float", quantity="length",
                minimum=0.0, optional=True, tooltip="Empty: taken from the geometry.",
            ),
            FieldSpec(
                "face_direction", "Face direction", "choice", choices=("up", "down", None),
                optional=True, tooltip="Orientation of a horizontal plate; empty: automatic.",
            ),
            FieldSpec(
                "wall_T_mode", "Wall temperature", "choice", choices=("local", "average"),
                tooltip="Wall temperature used for the film properties.",
            ),
            FieldSpec("multiplier", "Multiplier", "float", minimum=0.0),
            FieldSpec(
                "params", "Extra inputs", "dict",
                tooltip=(
                    "key=value pairs, e.g. theta_deg=30, S=0.01, W=0.01, H=0.05, C=0.5, n=0.25 "
                    "(also D, x_r, r_r)."
                ),
            ),
        ],
        description="Convection whose coefficient comes from a correlation.",
    ),
    "radiation_ambient": FormSpec(
        "Radiation to Ambient",
        [
            _sel(_CURVES, "boundaries"),
            FieldSpec("emissivity", "Emissivity", "function", minimum=0.0, maximum=1.0),
            _temperature("T_inf", "Ambient temperature"),
        ],
        description="Radiation from boundaries to surroundings.",
    ),
    "symmetry": FormSpec(
        "Symmetry", [_sel(_CURVES, "boundaries")], description="Symmetry line (no effect)."
    ),
    "adiabatic": FormSpec(
        "Adiabatic", [_sel(_CURVES, "boundaries")], description="Insulated boundary (no effect)."
    ),
}
