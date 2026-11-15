"""V-01 — slab with two fixed faces.

Slab L = 0.1 m, T(0) = 400 K, T(L) = 300 K, k = 50 W/(m K). T(x) is linear and the flux is
q = k dT / L everywhere. 10 elements along x; tolerance 1e-10.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea.model.bcs import FixedTemperature

L, T0, TL, N = 0.1, 400.0, 300.0, 10
TOL = 1e-10


def run(etype: str) -> dict:
    model, built = common.rectangle("V-01 slab", etype, 0.0, 0.0, L, L / 10, N, 1)
    model.bcs += [FixedTemperature("hot", "left", T=T0), FixedTemperature("cold", "right", T=TL)]
    case = common.solve(model, built)

    x = case.nodes[:, 0]
    q_exact = common.K * (T0 - TL) / L
    (_, q), = case.flux().values()
    flux_error = max(
        float(np.max(np.abs(q[:, 0] - q_exact))), float(np.max(np.abs(q[:, 1])))
    ) / q_exact
    area = L / 10  # height of the strip times unit thickness
    return {
        "error": case.max_relative_error(T0 + (TL - T0) * x / L),
        "flux_error": flux_error,
        "heat_error": abs(case.heat("hot") - q_exact * area) / (q_exact * area),
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
