"""V-16 — lumped body cooled by convection.

Square 0.01 x 0.01 m, k = 400 W/(m K), initial 400 K, convection on all four edges with
h = 20 W/(m^2 K) to 300 K (Bi << 0.1).

    T(t) = T_inf + (T_i - T_inf) exp(-h A t / (rho c V)),  A = 0.04 * 1,  V = 1e-4 * 1

checked at t = tau and 3 tau, tau = rho c V / (h A). Fixed dt = tau / 200, theta = 1 then
1/2. Tolerance 5e-3 (theta = 1) and 1e-4 (theta = 1/2).
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea import api
from thermalfea.model.bcs import Convection

SIDE, K_BODY, H, T_INF, T_INIT = 0.01, 400.0, 20.0, 300.0, 400.0
AREA, VOLUME = 4 * SIDE * 1.0, SIDE * SIDE * 1.0
TAU = common.RHO * common.CP * VOLUME / (H * AREA)
TOL = {1.0: 5e-3, 0.5: 1e-4}


def exact(t: float) -> float:
    return T_INF + (T_INIT - T_INF) * np.exp(-H * AREA * t / (common.RHO * common.CP * VOLUME))


def build(etype: str, name: str = "V-16 lumped body"):
    """The model without loads: a 2 x 2 structured square with its four edges named."""
    model, built = common.rectangle(name, etype, 0.0, 0.0, SIDE, SIDE, 2, 2, k=K_BODY)
    api.select_curves(model, built, "skin", where=lambda c: True)
    return model, built


def run(etype: str, theta: float = 0.5, dt: float = TAU / 200.0, end: float = 3.0 * TAU) -> dict:
    model, built = build(etype)
    model.bcs.append(Convection("conv", "skin", h=H, T_inf=T_INF))
    times = [t for t in (TAU, 3.0 * TAU) if t <= end * (1 + 1e-12)]
    common.transient(
        model, T_INIT, end_time=end, theta=theta, initial_dt=dt, auto_timestep=False,
        output="times", output_times=times,
    )
    case = common.solve(model, built)
    errors = [float(np.max(np.abs(case.T_at(t) - exact(t))) / exact(t)) for t in times]
    return {
        "error": max(errors),
        "error_tau": errors[0],
        "T_mean_end": float(case.T.mean()),
        "imbalance": case.worst_imbalance,
        "case": case,
    }


if __name__ == "__main__":
    for value in (1.0, 0.5):
        title = f"{__doc__.splitlines()[0]} theta={value}"
        common.main(lambda etype, th=value: run(etype, th), title)
