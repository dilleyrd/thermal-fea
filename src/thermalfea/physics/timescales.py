"""Time scales of a thermal problem (Theory §6.1).

* Suggested initial step: ``dt0 = h_min^2 / (4 alpha_max)``, ``alpha = k / (rho c)``,
  ``h_min`` the smallest element edge length.
* Oscillation warning: if consistent capacitance is used and ``dt < h^2 rho c / (6 k)``
  for more than 5 % of the elements, a warning recommends lumped capacitance or a finer
  mesh.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray

from ..core.registry import element
from .batches import ElementBatch, element_batches
from .properties import conductivity_matrix, volumetric_heat_capacity

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem

log = logging.getLogger(__name__)

OSCILLATION_FRACTION = 0.05


def _edges_and_diffusivity(
    problem: CompiledProblem, batch: ElementBatch, nodal_T: ndarray
) -> tuple[ndarray, ndarray]:
    """Shortest edge [m] and largest diffusivity [m^2/s] of every element of a batch."""
    mesh = problem.mesh
    et = element(batch.etype)
    ends = mesh.nodes[batch.conn[:, np.asarray(et.facets)[:, :2]]]  # (e, n_edges, 2, dim)
    h = np.linalg.norm(ends[:, :, 1] - ends[:, :, 0], axis=-1).min(axis=1)
    T_gp = np.einsum("pn,en->ep", batch.geom.N, nodal_T[batch.conn])
    D = conductivity_matrix(batch.region.material, batch.region.material_angle, T_gp, mesh.dim)
    k_max = np.linalg.eigvalsh(D).max(axis=(-1, -2))
    rho_c = volumetric_heat_capacity(batch.region.material, T_gp).min(axis=1)
    return h, k_max / rho_c


def _nodal(problem: CompiledProblem, T: ndarray) -> ndarray:
    return np.asarray(T, dtype=float)[problem.dofs.field_dofs("T")]


def suggested_dt(problem: CompiledProblem, T: ndarray) -> float:
    """Suggested initial time step ``h_min^2 / (4 alpha_max)`` [s].

    Parameters
    ----------
    problem : CompiledProblem
    T : ndarray, shape (n_dofs,)
        Temperatures at which the properties are evaluated [K].
    """
    nodal_T = _nodal(problem, T)
    h_min, alpha_max = np.inf, 0.0
    for batch in element_batches(problem):
        h, alpha = _edges_and_diffusivity(problem, batch, nodal_T)
        h_min = min(h_min, float(h.min()))
        alpha_max = max(alpha_max, float(alpha.max()))
    return h_min**2 / (4.0 * alpha_max)


def oscillation_fraction(problem: CompiledProblem, T: ndarray, dt: float) -> float:
    """Fraction of the elements with ``dt < h^2 rho c / (6 k)``.

    Parameters
    ----------
    problem : CompiledProblem
    T : ndarray, shape (n_dofs,)
        Temperatures at which the properties are evaluated [K].
    dt : float
        Time step [s].
    """
    nodal_T = _nodal(problem, T)
    below = total = 0
    for batch in element_batches(problem):
        h, alpha = _edges_and_diffusivity(problem, batch, nodal_T)
        below += int(np.count_nonzero(dt < h**2 / (6.0 * alpha)))
        total += h.size
    return below / total if total else 0.0


def warn_if_oscillation_likely(
    problem: CompiledProblem, T: ndarray, dt: float, lumped: bool
) -> bool:
    """Log the oscillation warning of Theory §6.1 when it applies; return whether it did."""
    if lumped:
        return False
    fraction = oscillation_fraction(problem, T, dt)
    if fraction <= OSCILLATION_FRACTION:
        return False
    log.warning(
        "the time step of %.3g s is below h^2 rho c / (6 k) in %.0f %% of the elements; "
        "with consistent capacitance the temperatures may oscillate near sudden changes. "
        "Use lumped capacitance or a finer mesh.",
        dt, 100.0 * fraction,
    )
    return True
