"""V-32 — mesh convergence on a manufactured solution.

T = 300 + 50 sin(pi x) sin(pi y) on the unit square, with
Q = 2 pi^2 k 50 sin(pi x) sin(pi y) given to the solver as an expression and T = 300 on all
edges. Sizes 0.1, 0.05, 0.025. Required order of the L2 error: at least 1.9 for T3 and Q4,
at least 2.8 for T6 and Q8.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea import api
from thermalfea.core.functions import Expression
from thermalfea.model.bcs import FixedTemperature, HeatGeneration

SIZES = (0.1, 0.05, 0.025)
SOURCE = f"2*pi**2*{common.K}*50*sin(pi*x)*sin(pi*y)"


def required_order(etype: str) -> float:
    return 1.9 if etype in common.LINEAR else 2.8


def exact(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    return 300.0 + 50.0 * np.sin(np.pi * x) * np.sin(np.pi * y)


def solve_size(etype: str, size: float) -> common.Case:
    n = round(1.0 / size)
    model, built = common.rectangle("V-32 convergence", etype, 0.0, 0.0, 1.0, 1.0, n, n)
    api.select_curves(model, built, "edges", where=lambda c: True)
    model.bcs += [
        FixedTemperature("edges", "edges", T=300.0),
        HeatGeneration("source", "all", Q=Expression(SOURCE)),
    ]
    return common.solve(model, built)


def run(etype: str) -> dict:
    cases = [solve_size(etype, size) for size in SIZES]
    errors = [common.l2_error(case, exact) for case in cases]
    orders = [
        float(np.log(errors[i] / errors[i + 1]) / np.log(SIZES[i] / SIZES[i + 1]))
        for i in range(len(SIZES) - 1)
    ]
    return {
        "order": min(orders),
        "order_fine": orders[-1],
        "l2_coarse": errors[0],
        "l2_fine": errors[-1],
        "imbalance": max(abs(case.imbalance) for case in cases),
        "case": cases[-1],
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
