"""V-15 - slab with natural convection from a vertical plate correlation.

Slab L = 0.1 m, k = 50 W/(m K), T(0) = 400 K; the face x = L exchanges heat with air at
300 K through `vplate_natural` (height 0.5 m). The surface temperature is the root of
k (400 - T_s) / L = h(T_s) (T_s - 300) with h from the same correlation. Tolerance 1e-5.
"""

from __future__ import annotations

import common
from scipy.optimize import brentq

from thermalfea.convection import correlations
from thermalfea.materials import library
from thermalfea.model.bcs import CorrelationConvection, FixedTemperature

L, K, T0, T_INF, HEIGHT, N = 0.1, common.K, 400.0, 300.0, 0.5, 10
TOL = 1e-5


def h_of(T_s: float) -> float:
    """Heat-transfer coefficient of the vertical plate at wall temperature ``T_s`` [W/(m^2 K)]."""
    p = library.fluid("Air").props(0.5 * (T_s + T_INF))
    Ra = correlations.rayleigh(p.beta, T_s - T_INF, HEIGHT, p.Pr, p.rho, p.mu)
    return float(correlations.nu_vplate_natural(Ra, p.Pr) * p.k / HEIGHT)


def root() -> float:
    """Surface temperature from the scalar heat balance [K]."""
    return brentq(
        lambda t: K * (T0 - t) / L - h_of(t) * (t - T_INF), T_INF, T0, xtol=1e-13, rtol=1e-14
    )


def run(etype: str) -> dict:
    model, built = common.rectangle("V-15 natural convection", etype, 0.0, 0.0, L, L / 10, N, 1)
    model.bcs += [
        FixedTemperature("hot", "left", T=T0),
        CorrelationConvection(
            "natural", "right", correlation="vplate_natural", fluid="Air", T_inf=T_INF,
            char_length=HEIGHT,
        ),
    ]
    case = common.solve(model, built)
    surface = float(case.T[case.node_at(L, 0.0)])
    reference = root()
    return {
        "T_surface": surface,
        "error": abs(surface - reference) / reference,
        "h": h_of(surface),
        "iterations": case.iterations,
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
