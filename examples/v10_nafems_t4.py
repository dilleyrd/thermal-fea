"""V-10 — NAFEMS T4: two-dimensional heat transfer with convection.

Rectangle 0.6 (x) by 1.0 (y), k = 52 W/(m K). Bottom edge 100 degC; left edge adiabatic;
right and top edges convection h = 750 W/(m^2 K) to 0 degC.
Target: T at (0.6, 0.2) = 18.3 degC. Mesh size 0.05, then 0.025; within 0.15 degC at the
fine mesh.

The rectangle is drawn in two parts so that the target point is a mesh node.
"""

from __future__ import annotations

import common

from thermalfea import api
from thermalfea.model.bcs import Adiabatic, Convection, FixedTemperature

W, HGT, K_T4, H, YP = 0.6, 1.0, 52.0, 750.0, 0.2
ZERO_C = 273.15
TARGET_C = 18.3
TOL_C = 0.15
SIZES = (0.05, 0.025)


def run(etype: str, size: float = SIZES[-1]) -> dict:
    model = api.new_model("planar", name="V-10 NAFEMS T4")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, W, YP)
    geo.rectangle(0.0, YP, W, HGT - YP)
    built = api.build(model)
    common.select_sides(model, built, 0.0, 0.0, W, HGT)
    api.select_curves(
        model, built, "cooled",
        tags=[*model.selections["right"].tags, *model.selections["top"].tags],
    )
    api.assign_region(model, "all", material=common.add_material(model, k=K_T4))
    model.bcs += [
        FixedTemperature("base", "bottom", T=100.0 + ZERO_C),
        Convection("cooling", "cooled", h=H, T_inf=ZERO_C),
        Adiabatic("insulated", "left"),
    ]
    common.set_element_type(model, etype)
    model.mesh_settings.global_size = size
    case = common.solve(model, built)
    value = float(case.T[case.node_at(W, YP)] - ZERO_C)
    return {
        "T_degC": value,
        "error_degC": abs(value - TARGET_C),
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    for mesh_size in SIZES:
        title = f"{__doc__.splitlines()[0]} (size {mesh_size})"
        common.main(lambda etype, s=mesh_size: run(etype, s), title)
