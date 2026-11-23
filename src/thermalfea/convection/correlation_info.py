"""Display text of the convection correlations: formula, validity range and inputs.

The texts are copied from ``docs/theory.md`` §8 (the correlation table) and
§8.1 (internal duct flow), keeping the notation of that document. Nothing
here is computed; the numbers come from :mod:`thermalfea.convection.correlations`. The
module has no Qt dependency, so a GUI, a report or a script can show the same text.

``CORRELATION_INFO`` has one entry for every ID in
:data:`thermalfea.convection.correlations.CORRELATIONS`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Shown when the theory document gives no validity range for a correlation.
NOT_STATED = "Not stated in the theory document."

#: The relation every Nusselt-number correlation shares (docs/theory.md §8).
H_FROM_NU = "h = Nu · k_f / L_c"

#: Film temperature rule (docs/theory.md §8).
PROPERTIES_AT = "Fluid properties at the film temperature T_film = (T_s + T∞)/2."


@dataclass(frozen=True)
class CorrelationInfo:
    """Display text of one correlation.

    Attributes
    ----------
    title : str
        The "Situation" column of the theory table.
    formula : str
        The formula as written in the theory document (plain text).
    validity : str
        The validity range as written in the theory document, or :data:`NOT_STATED`.
    length : str
        The characteristic length L_c named in the theory table.
    inputs : tuple of str
        Names of the ``thermalfea.api.htc`` keyword inputs the correlation needs (the
        keywords checked in :func:`thermalfea.convection.calculator.htc`). Temperatures and
        the fluid are always needed (the fluid not for ``power_law``) and are not listed.
    needs_fluid : bool
        ``False`` only for the user power law.
    source : str
        Where in ``docs/theory.md`` the texts were copied from.
    """

    title: str
    formula: str
    validity: str
    length: str
    inputs: tuple[str, ...]
    needs_fluid: bool = True
    source: str = ""


_DUCT_FORMULA = (
    "Re = ṁ D_h /(A μ), D_h = 4A/P_wet. Properties at the bulk fluid temperature.\n"
    "Laminar (Re ≤ 2300): Nu_lam from the table (constant wall T: circular 3.66, parallel "
    "plates both heated 7.54, parallel plates one side insulated 4.86, square 2.98; "
    "constant flux: 4.36, 8.23, 5.39, 3.61).\n"
    "Turbulent (Re ≥ 4000): Gnielinski "
    "Nu = (f/8)(Re − 1000) Pr / [1 + 12.7 (f/8)^½ (Pr^⅔ − 1)], f = (0.790 ln Re − 1.64)⁻².\n"
    "Transition (2300 < Re < 4000): linear interpolation in Re between Nu_lam and "
    "Nu_Gnielinski(Re = 4000).\n"
    "Optional: Dittus–Boelter, Nu = 0.023 Re^0.8 Pr^n, n = 0.4 if wall hotter than fluid, "
    "else 0.3."
)

_DUCT_VALIDITY = (
    "Gnielinski: 0.5 ≤ Pr ≤ 2000, 3000 ≤ Re ≤ 5e6. Dittus–Boelter: 0.6 ≤ Pr ≤ 160 and "
    "Re ≥ 1e4. (The validity column of the §8 table is empty for this entry; the ranges are "
    "those stated in §8.1.)"
)

CORRELATION_INFO: dict[str, CorrelationInfo] = {
    "plate_forced_avg": CorrelationInfo(
        title="Flat plate, parallel flow, average",
        formula="Re ≤ 5e5: Nu = 0.664 Re^½ Pr^⅓; else Nu = (0.037 Re^0.8 − 871) Pr^⅓",
        validity="Pr ≥ 0.6; when Re > 5e5 also Pr ≤ 60 and Re ≤ 1e8",
        length="plate length",
        inputs=("length", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "plate_forced_local": CorrelationInfo(
        title="Flat plate, local at distance x from leading edge",
        formula="Re_x ≤ 5e5: Nu_x = 0.332 Re_x^½ Pr^⅓; else Nu_x = 0.0296 Re_x^0.8 Pr^⅓",
        validity="Pr ≥ 0.6; when Re_x > 5e5 also Pr ≤ 60 and Re_x ≤ 1e8",
        length="x",
        inputs=("x", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "cylinder_crossflow": CorrelationInfo(
        title="Cylinder in cross flow (Churchill–Bernstein)",
        formula=(
            "Nu = 0.3 + 0.62 Re^½ Pr^⅓ [1+(0.4/Pr)^⅔]^(−¼) [1+(Re/282000)^⅝]^(⅘)"
        ),
        validity="Re·Pr ≥ 0.2",
        length="diameter",
        inputs=("length", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "duct_internal": CorrelationInfo(
        title="Internal flow, circular or by hydraulic diameter",
        formula=_DUCT_FORMULA,
        validity=_DUCT_VALIDITY,
        length="D_h",
        inputs=("mass_flow", "area", "wetted_perimeter"),
        source="docs/theory.md §8.1",
    ),
    "vplate_natural": CorrelationInfo(
        title="Vertical plate (Churchill–Chu)",
        formula="Nu = {0.825 + 0.387 Ra^(1/6) / [1+(0.492/Pr)^(9/16)]^(8/27)}²",
        validity="all Ra",
        length="height",
        inputs=("length",),
        source="docs/theory.md §8, correlation table",
    ),
    "inclined_natural": CorrelationInfo(
        title="Plate inclined θ from vertical",
        formula="as `vplate_natural` with g → g cos θ",
        validity="0 ≤ θ ≤ 60°; for the other face [I] makes no recommendation (see below)",
        length="length",
        inputs=("length", "theta_deg"),
        source="docs/theory.md §8, correlation table",
    ),
    "hplate_up_natural": CorrelationInfo(
        title="Horizontal, hot face up or cold face down",
        formula="Ra ≤ 1e7: Nu = 0.54 Ra^¼; else Nu = 0.15 Ra^⅓",
        validity="1e4 ≤ Ra ≤ 1e11; when Ra ≤ 1e7 also Pr ≥ 0.7",
        length="area/perimeter",
        inputs=("length",),
        source="docs/theory.md §8, correlation table",
    ),
    "hplate_down_natural": CorrelationInfo(
        title="Horizontal, hot face down or cold face up",
        formula="Nu = 0.52 Ra^(1/5)",
        validity="1e4 ≤ Ra ≤ 1e9, Pr ≥ 0.7",
        length="area/perimeter",
        inputs=("length",),
        source="docs/theory.md §8, correlation table",
    ),
    "hcyl_natural": CorrelationInfo(
        title="Horizontal cylinder (Churchill–Chu)",
        formula="Nu = {0.60 + 0.387 Ra^(1/6) / [1+(0.559/Pr)^(9/16)]^(8/27)}²",
        validity="Ra ≤ 1e12",
        length="diameter",
        inputs=("length",),
        source="docs/theory.md §8, correlation table",
    ),
    "power_law": CorrelationInfo(
        title="User form",
        formula="h = C · |T_s − T∞|ⁿ",
        validity=NOT_STATED,
        length="—",
        inputs=("C", "n"),
        needs_fluid=False,
        source="docs/theory.md §8, correlation table",
    ),
}
"""Display text by correlation ID, in the order of the theory table."""
