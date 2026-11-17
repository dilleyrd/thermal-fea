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


def _temperature(name: str, label: str) -> FieldSpec:
    return FieldSpec(name, label, "function", quantity="temperature", minimum=0.0)


BC_FORMS: dict[str, FormSpec] = {
    "fixed_temperature": FormSpec(
        "Fixed Temperature",
        [_sel((0, 1), "curves or points"), _temperature("T", "Temperature")],
        description="Prescribed temperature on curves or points.",
    ),
    "heat_flux": FormSpec(
        "Heat Flux",
        [_sel(_CURVES, "curves"), FieldSpec("q", "Heat flux", "function", quantity="heat_flux")],
        description="Heat flux on curves, positive into the body.",
    ),
    "heat_flow": FormSpec(
        "Heat Flow",
        [_sel(_CURVES, "curves"), FieldSpec("P", "Heat flow", "function", quantity="power")],
        description="Total heat flow spread uniformly over curves, positive into the body.",
    ),
    "heat_generation": FormSpec(
        "Heat Generation",
        [
            _sel(_SURFACES, "surfaces"),
            FieldSpec("Q", "Heat generation", "function", quantity="heat_gen"),
        ],
        description="Volumetric heat generation in surfaces.",
    ),
    "heat_power": FormSpec(
        "Heat Power",
        [_sel(_SURFACES, "surfaces"), FieldSpec("P", "Power", "function", quantity="power")],
        description="Total power generated uniformly in surfaces.",
    ),
    "convection": FormSpec(
        "Convection",
        [
            _sel(_CURVES, "curves"),
            FieldSpec("h", "Heat-transfer coefficient", "function", quantity="htc"),
            _temperature("T_inf", "Fluid temperature"),
        ],
        description="Convection to a fluid at a given temperature.",
    ),
    "correlation_convection": FormSpec(
        "Correlation Convection",
        [
            _sel(_CURVES, "curves"),
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
                tooltip="key=value pairs, e.g. theta_deg=30, C=0.5, n=0.25.",
            ),
        ],
        description="Convection whose coefficient comes from a correlation.",
    ),
    "radiation_ambient": FormSpec(
        "Radiation to Ambient",
        [
            _sel(_CURVES, "curves"),
            FieldSpec("emissivity", "Emissivity", "function", minimum=0.0, maximum=1.0),
            _temperature("T_inf", "Ambient temperature"),
        ],
        description="Radiation from curves to surroundings.",
    ),
    "symmetry": FormSpec(
        "Symmetry", [_sel(_CURVES, "curves")], description="Symmetry line (no effect)."
    ),
    "adiabatic": FormSpec(
        "Adiabatic", [_sel(_CURVES, "curves")], description="Insulated boundary (no effect)."
    ),
}
