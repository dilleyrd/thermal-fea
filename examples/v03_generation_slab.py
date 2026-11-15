"""V-03 — slab with uniform heat generation.

Slab L = 0.1 m, both faces at 300 K, Q = 1e6 W/m^3.
T(x) = 300 + Q / (2 k) x (L - x). 20 elements; tolerance 1e-3 for linear elements and
1e-10 for quadratic ones.
"""

from __future__ import annotations

import common

from thermalfea.model.bcs import FixedTemperature, HeatGeneration

L, TW, Q, N = 0.1, 300.0, 1.0e6, 20


def tolerance(etype: str) -> float:
    return 1e-3 if etype in common.LINEAR else 1e-10


def run(etype: str) -> dict:
    model, built = common.rectangle("V-03 generation slab", etype, 0.0, 0.0, L, L / 10, N, 1)
    model.bcs += [
        FixedTemperature("left", "left", T=TW),
        FixedTemperature("right", "right", T=TW),
        HeatGeneration("gen", "all", Q=Q),
    ]
    case = common.solve(model, built)
    x = case.nodes[:, 0]
    generated = Q * L * (L / 10)
    return {
        "error": case.max_relative_error(TW + Q / (2.0 * common.K) * x * (L - x)),
        "heat_error": abs(case.heat("gen") - generated) / generated,
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
