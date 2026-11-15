"""V-05 — hollow cylinder, axisymmetric.

r_i = 0.05 m, r_o = 0.1 m, T_i = 400 K, T_o = 300 K.
T(r) = T_i - (T_i - T_o) ln(r / r_i) / ln(r_o / r_i); heat flow per height =
2 pi k (T_i - T_o) / ln(r_o / r_i). 40 radial elements; tolerance 1e-3 for linear elements
and 1e-5 for quadratic ones.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea.model.bcs import FixedTemperature

RI, RO, TI, TO, N = 0.05, 0.1, 400.0, 300.0, 40
HEIGHT = (RO - RI) / 10


def tolerance(etype: str) -> float:
    return 1e-3 if etype in common.LINEAR else 1e-5


def run(etype: str) -> dict:
    model, built = common.rectangle(
        "V-05 hollow cylinder", etype, RI, 0.0, RO - RI, HEIGHT, N, 1, analysis="axisymmetric"
    )
    model.bcs += [
        FixedTemperature("inner", "left", T=TI),
        FixedTemperature("outer", "right", T=TO),
    ]
    case = common.solve(model, built)
    r = case.nodes[:, 0]
    per_height = 2.0 * np.pi * common.K * (TI - TO) / np.log(RO / RI)
    return {
        "error": case.max_relative_error(TI - (TI - TO) * np.log(r / RI) / np.log(RO / RI)),
        "heat_error": abs(case.heat("inner") / HEIGHT - per_height) / per_height,
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
