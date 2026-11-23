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

#: The exception of ``sphere_forced`` (docs/theory.md §8 table).
PROPERTIES_AT_T_INF = "All fluid properties at T∞, except μ_s at T_s."


def properties_at(correlation: str) -> str:
    """The sentence naming the temperature of the fluid properties of a correlation."""
    return PROPERTIES_AT_T_INF if correlation == "sphere_forced" else PROPERTIES_AT


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
    "square_corner_crossflow": CorrelationInfo(
        title="Square cylinder, a corner facing the flow, gas",
        formula="Nu = 0.304 Re^0.59 Pr^⅓",
        validity="6000 ≤ Re ≤ 60000",
        length="D = diagonal (width across the flow)",
        inputs=("length", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "square_face_crossflow": CorrelationInfo(
        title="Square cylinder, a face facing the flow, gas",
        formula="Nu = 0.158 Re^0.66 Pr^⅓",
        validity="5000 ≤ Re ≤ 60000",
        length="D = side",
        inputs=("length", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "hexagon_face_crossflow": CorrelationInfo(
        title="Hexagonal cylinder, a face facing the flow, gas",
        formula="Re ≤ 20400: Nu = 0.164 Re^0.638 Pr^⅓; else Nu = 0.039 Re^0.78 Pr^⅓",
        validity="5200 ≤ Re ≤ 105000",
        length="D = corner-to-corner width across the flow",
        inputs=("length", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "hexagon_corner_crossflow": CorrelationInfo(
        title="Hexagonal cylinder, a corner facing the flow, gas",
        formula="Nu = 0.150 Re^0.638 Pr^⅓",
        validity="4500 ≤ Re ≤ 90700",
        length="D = face-to-face width across the flow",
        inputs=("length", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "plate_front_crossflow": CorrelationInfo(
        title="Thin plate across the flow, upstream face, gas",
        formula="Nu = 0.667 Re^0.500 Pr^⅓",
        validity="10000 ≤ Re ≤ 50000",
        length="D = plate height across the flow",
        inputs=("length", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "plate_back_crossflow": CorrelationInfo(
        title="Thin plate across the flow, downstream face, gas",
        formula="Nu = 0.191 Re^0.667 Pr^⅓",
        validity="7000 ≤ Re ≤ 80000",
        length="D = plate height across the flow",
        inputs=("length", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "sphere_forced": CorrelationInfo(
        title="Sphere in a free stream (Whitaker)",
        formula=(
            "Nu = 2 + (0.4 Re^½ + 0.06 Re^⅔) Pr^0.4 (μ/μ_s)^¼. "
            "**All properties at T∞**, except μ_s at T_s"
        ),
        validity="0.71 ≤ Pr ≤ 380, 3.5 ≤ Re ≤ 7.6e4, 1.0 ≤ μ/μ_s ≤ 3.2",
        length="diameter",
        inputs=("length", "velocity"),
        source="docs/theory.md §8, correlation table",
    ),
    "slot_jet": CorrelationInfo(
        title=(
            "Single slot nozzle impinging on the surface, average over |x| ≤ x_r from the "
            "jet's centre line (Martin)"
        ),
        formula=(
            "Nu / Pr^0.42 = 3.06 / (0.5/A_r + H/W + 2.78) · Re^m, "
            "m = 0.695 − [1/(4 A_r) + (H/(2W))^1.33 + 3.06]^(−1), A_r = W/(2 x_r); "
            "Re = V 2W/ν with V the jet exit velocity"
        ),
        validity="3000 ≤ Re ≤ 9e4, 2 ≤ H/W ≤ 10, 0.025 ≤ A_r ≤ 0.125",
        length="2W",
        inputs=("velocity", "W", "H", "x_r"),
        source="docs/theory.md §8, correlation table",
    ),
    "round_jet": CorrelationInfo(
        title=(
            "Single round nozzle impinging on the surface, average over r ≤ r_r from the "
            "jet's axis (Martin)"
        ),
        formula=(
            "Nu / Pr^0.42 = G · 2 Re^½ (1 + 0.005 Re^0.55)^½, "
            "G = 2 A_r^½ (1 − 2.2 A_r^½) / (1 + 0.2 (H/D − 6) A_r^½), A_r = D²/(4 r_r²); "
            "Re = V D/ν with V the jet exit velocity"
        ),
        validity="2000 ≤ Re ≤ 4e5, 2 ≤ H/D ≤ 12, 0.004 ≤ A_r ≤ 0.04",
        length="D (nozzle)",
        inputs=("velocity", "D", "H", "r_r"),
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
    "vplate_natural_laminar": CorrelationInfo(
        title=(
            "Vertical plate, laminar (Churchill–Chu; slightly more accurate than 9.26 "
            "for Ra ≤ 1e9)"
        ),
        formula="Nu = 0.68 + 0.670 Ra^¼ / [1+(0.492/Pr)^(9/16)]^(4/9)",
        validity="Ra ≤ 1e9",
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
    "sphere_natural": CorrelationInfo(
        title="Sphere (Churchill)",
        formula="Nu = 2 + 0.589 Ra^¼ / [1+(0.469/Pr)^(9/16)]^(4/9)",
        validity="Pr ≥ 0.7, Ra ≤ 1e11",
        length="diameter",
        inputs=("length",),
        source="docs/theory.md §8, correlation table",
    ),
    "vchannel_natural": CorrelationInfo(
        title=(
            "Vertical channel between two parallel isothermal plates, both at T_s "
            "(Bar-Cohen–Rohsenow)"
        ),
        formula=(
            "Nu_S = [576/(Ra_S S/L)² + 2.87/(Ra_S S/L)^½]^(−½), Ra_S = Ra with L → S; "
            "h = Nu_S k_f / S"
        ),
        validity=NOT_STATED,
        length="S (plate spacing); L = channel height",
        inputs=("length", "S"),
        source="docs/theory.md §8, correlation table",
    ),
    "vchannel_one_side_natural": CorrelationInfo(
        title=(
            "Vertical channel, this plate at T_s, the opposite plate adiabatic "
            "(Bar-Cohen–Rohsenow)"
        ),
        formula=(
            "Nu_S = [144/(Ra_S S/L)² + 2.87/(Ra_S S/L)^½]^(−½), Ra_S and h as above"
        ),
        validity=NOT_STATED,
        length="S; L = channel height",
        inputs=("length", "S"),
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
