"""V-08 — straight fin modelled in 2D with its real thickness.

L = 0.1 m, thickness 0.004 m, base 400 K, h = 50 W/(m^2 K) on both long faces and the tip,
T_inf = 300 K, k = 200 W/(m K). 1D fin theory with a convecting tip:

    theta / theta_b = [cosh m(L - x) + (h / (m k)) sinh m(L - x)]
                      / [cosh m L + (h / (m k)) sinh m L],   m = sqrt(2 h / (k t))

Mesh size 0.001; tolerance 5e-3 (the 1D theory is approximate; the Biot number is small).
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea import api
from thermalfea.model.bcs import Convection, FixedTemperature

L, THICK, TB, H, T_INF, K_FIN, SIZE = 0.1, 0.004, 400.0, 50.0, 300.0, 200.0, 0.001
TOL = 5e-3


def analytic(x: np.ndarray) -> np.ndarray:
    m = np.sqrt(2.0 * H / (K_FIN * THICK))
    ratio = H / (m * K_FIN)
    theta = (np.cosh(m * (L - x)) + ratio * np.sinh(m * (L - x))) / (
        np.cosh(m * L) + ratio * np.sinh(m * L)
    )
    return T_INF + (TB - T_INF) * theta


def run(etype: str) -> dict:
    model = api.new_model("planar", name="V-08 fin")
    api.Geometry(model).rectangle(0.0, 0.0, L, THICK)
    built = api.build(model)
    common.select_sides(model, built, 0.0, 0.0, L, THICK)
    api.select_curves(
        model, built, "wetted", tags=[
            *model.selections["top"].tags,
            *model.selections["bottom"].tags,
            *model.selections["right"].tags,
        ]
    )
    api.assign_region(model, "all", material=common.add_material(model, k=K_FIN))
    model.bcs += [
        FixedTemperature("base", "left", T=TB),
        Convection("conv", "wetted", h=H, T_inf=T_INF),
    ]
    common.set_element_type(model, etype)
    model.mesh_settings.global_size = SIZE
    case = common.solve(model, built)
    return {
        "error": case.max_relative_error(analytic(case.nodes[:, 0])),
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
