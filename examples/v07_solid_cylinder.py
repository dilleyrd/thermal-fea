"""V-07 — solid cylinder with heat generation and surface convection, axisymmetric.

Radius R = 0.05 m, Q = 1e6 W/m^3, h = 500 W/(m^2 K), T_inf = 300 K.
T(r) = T_inf + Q R / (2 h) + Q (R^2 - r^2) / (4 k). 20 radial elements; tolerance 1e-3.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea.model.bcs import Convection, HeatGeneration

R, Q, H, T_INF, N = 0.05, 1.0e6, 500.0, 300.0, 20
HEIGHT = R / 10
TOL = 1e-3


def run(etype: str) -> dict:
    model, built = common.rectangle(
        "V-07 solid cylinder", etype, 0.0, 0.0, R, HEIGHT, N, 1, analysis="axisymmetric"
    )
    model.bcs += [
        HeatGeneration("gen", "all", Q=Q),
        Convection("conv", "right", h=H, T_inf=T_INF),
    ]
    case = common.solve(model, built)
    r = case.nodes[:, 0]
    generated = Q * np.pi * R**2 * HEIGHT
    return {
        "error": case.max_relative_error(
            T_INF + Q * R / (2.0 * H) + Q * (R**2 - r**2) / (4.0 * common.K)
        ),
        "heat_error": abs(-case.heat("conv") - generated) / generated,
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
