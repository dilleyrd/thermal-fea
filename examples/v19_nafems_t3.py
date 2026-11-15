"""V-19 — NAFEMS T3: one-dimensional transient heat transfer.

Bar L = 0.1 m, k = 35.0 W/(m K), c = 440.5 J/(kg K), rho = 7200 kg/m^3. T(0, t) = 0 degC,
T(L, t) = 100 sin(pi t / 40) degC, initial 0 degC.
Target: T at x = 0.08 m, t = 32 s = 36.60 degC. 20 quadratic elements, dt = 0.5 s,
theta = 1/2 and theta = 1. Tolerance 0.3 degC (theta = 1/2) and 1.0 degC (theta = 1).
"""

from __future__ import annotations

import common

from thermalfea.core.functions import Expression
from thermalfea.model.bcs import FixedTemperature

L, K_T3, CP_T3, RHO_T3, N, DT, END, XP = 0.1, 35.0, 440.5, 7200.0, 20, 0.5, 32.0, 0.08
ZERO_C = 273.15
TARGET_C = 36.60
TOL_C = {0.5: 0.3, 1.0: 1.0}
TYPES = ("T6", "Q8")


def run(etype: str, theta: float = 0.5) -> dict:
    model, built = common.rectangle(
        "V-19 NAFEMS T3", etype, 0.0, 0.0, L, L / 10, N, 1, k=K_T3, rho=RHO_T3, cp=CP_T3
    )
    model.bcs += [
        FixedTemperature("cold", "left", T=ZERO_C),
        FixedTemperature("driven", "right", T=Expression(f"{ZERO_C} + 100*sin(pi*t/40)")),
    ]
    common.transient(
        model, ZERO_C, end_time=END, theta=theta, initial_dt=DT, auto_timestep=False,
        output="times", output_times=[END],
    )
    case = common.solve(model, built)
    value = float(case.T[case.node_at(XP, 0.0)] - ZERO_C)
    return {
        "T_degC": value,
        "error_degC": abs(value - TARGET_C),
        "steps": case.n_steps,
        "imbalance": case.worst_imbalance,
        "case": case,
    }


if __name__ == "__main__":
    for value in (0.5, 1.0):
        title = f"{__doc__.splitlines()[0]} theta={value}"
        common.main(lambda etype, th=value: run(etype, th), title, TYPES)
