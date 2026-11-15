"""V-14 — NAFEMS T2: one-dimensional heat transfer with radiation.

Bar L = 0.1 m, k = 55.6 W/(m K), T(0) = 1000 K; the far end radiates to 300 K with
emissivity 0.98. Target: T at the radiating end = 927.0 K, which is also the root of
k (1000 - T) / L = eps sigma (T^4 - 300^4). Tolerance 0.1 K.
"""

from __future__ import annotations

import common
from scipy.optimize import brentq

from thermalfea.core.constants import STEFAN_BOLTZMANN
from thermalfea.model.bcs import FixedTemperature, RadiationAmbient

L, K_T2, T0, T_INF, EPS, N = 0.1, 55.6, 1000.0, 300.0, 0.98, 10
TARGET, TOL_K = 927.0, 0.1


def root() -> float:
    """Temperature of the radiating end from the scalar heat balance [K]."""
    return brentq(
        lambda t: K_T2 * (T0 - t) / L - EPS * STEFAN_BOLTZMANN * (t**4 - T_INF**4), T_INF, T0
    )


def run(etype: str) -> dict:
    model, built = common.rectangle("V-14 NAFEMS T2", etype, 0.0, 0.0, L, L / 10, N, 1, k=K_T2)
    model.bcs += [
        FixedTemperature("hot", "left", T=T0),
        RadiationAmbient("radiation", "right", emissivity=EPS, T_inf=T_INF),
    ]
    case = common.solve(model, built)
    end = float(case.T[case.node_at(L, 0.0)])
    return {
        "T_end": end,
        "error_K": abs(end - TARGET),
        "root_error_K": abs(end - root()),
        "iterations": case.iterations,
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
