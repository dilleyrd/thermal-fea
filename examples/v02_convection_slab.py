"""V-02 — slab with a fixed face and a convecting face.

Slab L = 0.1 m, T(0) = 400 K, convection at x = L with h = 100 W/(m^2 K), T_inf = 300 K.
T(L) = T_inf + (T0 - T_inf) / (1 + h L / k); heat flow = k (T0 - T(L)) / L.
10 elements; tolerance 1e-10.
"""

from __future__ import annotations

import common

from thermalfea.model.bcs import Convection, FixedTemperature

L, T0, T_INF, H, N = 0.1, 400.0, 300.0, 100.0, 10
TOL = 1e-10


def run(etype: str) -> dict:
    model, built = common.rectangle("V-02 convection slab", etype, 0.0, 0.0, L, L / 10, N, 1)
    model.bcs += [
        FixedTemperature("hot", "left", T=T0),
        Convection("conv", "right", h=H, T_inf=T_INF),
    ]
    case = common.solve(model, built)

    t_end = T_INF + (T0 - T_INF) / (1.0 + H * L / common.K)
    x = case.nodes[:, 0]
    heat = common.K * (T0 - t_end) / L * (L / 10)  # W through the strip, unit thickness
    return {
        "error": case.max_relative_error(T0 + (t_end - T0) * x / L),
        "end_error": abs(case.T[case.node_at(L, 0.0)] - t_end) / t_end,
        "heat_error": abs(-case.heat("conv") - heat) / heat,
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
