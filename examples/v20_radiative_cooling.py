"""V-20 — radiative cooling of a lumped body.

As V-16, but with radiation (emissivity 0.8) to 300 K instead of convection, and an initial
temperature of 800 K. The reference integrates

    rho c V dT/dt = -eps sigma A (T^4 - T_inf^4)

with ``scipy.integrate.solve_ivp`` (rtol 1e-10). Automatic time step with time_tol = 0.005;
tolerance 2e-3.
"""

from __future__ import annotations

import common
import numpy as np
import v16_lumped_body as v16
from scipy.integrate import solve_ivp

from thermalfea.core.constants import STEFAN_BOLTZMANN
from thermalfea.model.bcs import RadiationAmbient

EPS, T_INF, T_INIT, END = 0.8, 300.0, 800.0, 3000.0
CHECK = (0.25 * END, END)
TOL = 2e-3


def reference(times: tuple[float, ...]) -> np.ndarray:
    """Temperature of the lumped body at the given times [K]."""
    capacity = common.RHO * common.CP * v16.VOLUME

    def rate(t: float, y: np.ndarray) -> np.ndarray:
        return -EPS * STEFAN_BOLTZMANN * v16.AREA * (y**4 - T_INF**4) / capacity

    solution = solve_ivp(rate, (0.0, max(times)), [T_INIT], t_eval=list(times),
                         rtol=1e-10, atol=1e-10)
    return solution.y[0]


def run(etype: str) -> dict:
    model, built = v16.build(etype, "V-20 radiative cooling")
    model.bcs.append(RadiationAmbient("radiation", "skin", emissivity=EPS, T_inf=T_INF))
    common.transient(
        model, T_INIT, end_time=END, time_tol=0.005, output="times", output_times=list(CHECK)
    )
    case = common.solve(model, built)
    exact = reference(CHECK)
    errors = [
        float(np.max(np.abs(case.T_at(t) - value)) / value)
        for t, value in zip(CHECK, exact, strict=True)
    ]
    return {
        "error": max(errors),
        "T_end": float(case.T.mean()),
        "T_ref": float(exact[-1]),
        "imbalance": case.worst_imbalance,
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
