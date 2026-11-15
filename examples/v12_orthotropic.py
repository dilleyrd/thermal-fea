"""V-12 — orthotropic square with a manufactured solution.

Square 1 x 1, k1 = 50, k2 = 5 W/(m K), material angle 30 degrees. The manufactured
solution T = 300 + 50 x^2 + 30 x y + 20 y^2 is imposed on all edges, with the constant
generation Q = -div(D grad T) computed from D. Mesh size 0.05, quadratic elements;
tolerance 1e-9.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea import api
from thermalfea.core.functions import Expression
from thermalfea.model.bcs import FixedTemperature, HeatGeneration

K1, K2, ANGLE, SIZE = 50.0, 5.0, np.radians(30.0), 0.05
SOLUTION = "300 + 50*x**2 + 30*x*y + 20*y**2"
TYPES = ("T6", "Q8")
TOL = 1e-9


def generation() -> float:
    """Q = -div(D grad T) for T = 300 + 50 x^2 + 30 x y + 20 y^2 and constant D."""
    c, s = np.cos(ANGLE), np.sin(ANGLE)
    rotation = np.array([[c, -s], [s, c]])
    d = rotation @ np.diag([K1, K2]) @ rotation.T
    # grad T = (100 x + 30 y, 30 x + 40 y); its Hessian is [[100, 30], [30, 40]]
    hessian = np.array([[100.0, 30.0], [30.0, 40.0]])
    return -float(np.sum(d * hessian))


def run(etype: str) -> dict:
    n = round(1.0 / SIZE)
    model, built = common.rectangle(
        "V-12 orthotropic", etype, 0.0, 0.0, 1.0, 1.0, n, n, k=K1, k2=K2
    )
    model.regions[0].material_angle = float(ANGLE)
    api.select_curves(model, built, "edges", where=lambda c: True)
    model.bcs += [
        FixedTemperature("manufactured", "edges", T=Expression(SOLUTION)),
        HeatGeneration("source", "all", Q=generation()),
    ]
    case = common.solve(model, built)
    x, y = case.nodes.T
    return {
        "error": case.max_relative_error(300.0 + 50.0 * x**2 + 30.0 * x * y + 20.0 * y**2),
        "Q": generation(),
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0], TYPES)
