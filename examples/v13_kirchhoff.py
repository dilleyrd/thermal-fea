"""V-13 — slab with temperature-dependent conductivity (Kirchhoff transformation).

Slab L = 0.1 m, T(0) = 400 K, T(L) = 300 K, k(T) = k0 (1 + beta (T - 300)), k0 = 50,
beta = 0.01. With U(T) = (T - 300) + beta (T - 300)^2 / 2, U is linear in x; T(x) follows
from the quadratic. Flux = k0 (U(400) - U(300)) / L. 40 elements; tolerance 1e-4.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea.core.functions import Expression
from thermalfea.model.bcs import FixedTemperature

L, T0, TL, K0, BETA, N = 0.1, 400.0, 300.0, 50.0, 0.01, 40
TOL = 1e-4


def kirchhoff(t: float) -> float:
    return (t - 300.0) + BETA * (t - 300.0) ** 2 / 2.0


def run(etype: str) -> dict:
    conductivity = Expression(f"{K0}*(1 + {BETA}*(T - 300))")
    model, built = common.rectangle(
        "V-13 Kirchhoff", etype, 0.0, 0.0, L, L / 10, N, 1, k=conductivity
    )
    model.bcs += [FixedTemperature("hot", "left", T=T0), FixedTemperature("cold", "right", T=TL)]
    case = common.solve(model, built)

    x = case.nodes[:, 0]
    u = kirchhoff(T0) + (kirchhoff(TL) - kirchhoff(T0)) * x / L
    exact = 300.0 + (-1.0 + np.sqrt(1.0 + 2.0 * BETA * u)) / BETA
    flux = K0 * (kirchhoff(T0) - kirchhoff(TL)) / L
    heat = flux * (L / 10)
    return {
        "error": case.max_relative_error(exact),
        "heat_error": abs(case.heat("hot") - heat) / heat,
        "iterations": case.iterations,
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
