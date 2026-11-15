"""V-17 — slab cooled by convection (one-dimensional transient series solution).

Slab of half-thickness L = 0.05 m (symmetry at x = 0), initial 400 K, convection at x = L
with h = 500 W/(m^2 K) to 300 K.

    theta* = sum_{n=1..20} C_n exp(-zeta_n^2 Fo) cos(zeta_n x / L)
    zeta_n tan(zeta_n) = Bi  (roots by brentq in ((n-1) pi, (n-1/2) pi))
    C_n = 4 sin(zeta_n) / (2 zeta_n + sin(2 zeta_n)),   Fo = alpha t / L^2

Centre and surface are checked at Fo = 0.2 and 1.0. 40 elements, automatic time step;
tolerance 2e-3.
"""

from __future__ import annotations

import common
import numpy as np
from scipy.optimize import brentq

from thermalfea.model.bcs import Convection

L, H, T_INF, T_INIT, N = 0.05, 500.0, 300.0, 400.0, 40
ALPHA = common.K / (common.RHO * common.CP)
FOURIER = (0.2, 1.0)
TOL = 2e-3


def series(x_over_l: float, fo: float) -> float:
    """Dimensionless temperature theta* = (T - T_inf) / (T_i - T_inf)."""
    bi = H * L / common.K
    zeta = np.array([
        brentq(lambda z: z * np.tan(z) - bi, (n - 1) * np.pi + 1e-12, (n - 0.5) * np.pi - 1e-12)
        for n in range(1, 21)
    ])
    c = 4.0 * np.sin(zeta) / (2.0 * zeta + np.sin(2.0 * zeta))
    return float(np.sum(c * np.exp(-(zeta**2) * fo) * np.cos(zeta * x_over_l)))


def run(etype: str) -> dict:
    model, built = common.rectangle("V-17 slab convection", etype, 0.0, 0.0, L, L / 10, N, 1)
    model.bcs.append(Convection("conv", "right", h=H, T_inf=T_INF))
    times = [fo * L**2 / ALPHA for fo in FOURIER]
    common.transient(model, T_INIT, end_time=times[-1], output="times", output_times=times)
    case = common.solve(model, built)

    errors = []
    for fo, time in zip(FOURIER, times, strict=True):
        T = case.T_at(time)
        for x, position in ((0.0, 0.0), (L, 1.0)):
            exact = T_INF + (T_INIT - T_INF) * series(position, fo)
            errors.append(abs(T[case.node_at(x, 0.0)] - exact) / exact)
    return {
        "error": max(errors),
        "steps": int(case.results.iterations.size),
        "imbalance": case.worst_imbalance,
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
