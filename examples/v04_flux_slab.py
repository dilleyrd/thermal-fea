"""V-04 — slab with a heat flux on one face.

Slab L = 0.1 m, flux q = 5000 W/m^2 in at x = 0, T(L) = 300 K. T(0) = 300 + q L / k.
10 elements; tolerance 1e-10.
"""

from __future__ import annotations

import common

from thermalfea.model.bcs import FixedTemperature, HeatFlux

L, TL, Q, N = 0.1, 300.0, 5000.0, 10
TOL = 1e-10


def run(etype: str) -> dict:
    model, built = common.rectangle("V-04 flux slab", etype, 0.0, 0.0, L, L / 10, N, 1)
    model.bcs += [HeatFlux("flux", "left", q=Q), FixedTemperature("cold", "right", T=TL)]
    case = common.solve(model, built)
    x = case.nodes[:, 0]
    t0 = TL + Q * L / common.K
    return {
        "error": case.max_relative_error(t0 + (TL - t0) * x / L),
        "face_error": abs(case.T[case.node_at(0.0, 0.0)] - t0) / t0,
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
