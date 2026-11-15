"""Capacitance (thermal mass) matrices, consistent and lumped (Theory §2, §3).

Consistent: ``C_e = sum_gp rho c N^T N g |J| w``.

Lumped (option):

* linear elements: row-sum, ``C_ii = sum_j C_ij``;
* quadratic elements: HRZ lumping,
  ``C_ii = C_ii(consistent) * (sum_ij C_ij) / (sum_k C_kk)``.
  Row-sum is never used for quadratic elements (it gives zero or negative corner terms).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray

from ..core.registry import element
from ..solver.assembler import Assembler
from ..solver.terms import BaseTerm, State
from .batches import ElementBatch, element_batches
from .evaluate import interpolate
from .kernel import ElemGeom
from .properties import volumetric_heat_capacity

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem


def capacitance(geom: ElemGeom, rho_c: ndarray, g: ndarray) -> ndarray:
    """Consistent capacitance matrices of a block of elements.

    Parameters
    ----------
    geom : ElemGeom
        Integration data of the block.
    rho_c : ndarray, shape (e, gp)
        Volumetric heat capacity ``rho c`` at each integration point [J/(m^3 K)].
    g : ndarray, shape (e, gp)
        Geometry factor (thickness [m], ``2 pi r`` [m], or 1).

    Returns
    -------
    ndarray, shape (e, n, n)
        ``C_e = sum_gp rho c N^T N g |J| w`` [J/K].
    """
    return np.einsum("ep,pn,pm->enm", rho_c * g * geom.dV, geom.N, geom.N, optimize=True)


def lump(Ce: ndarray, order: int) -> ndarray:
    """Diagonal (lumped) form of consistent capacitance matrices.

    Parameters
    ----------
    Ce : ndarray, shape (e, n, n)
        Consistent matrices [J/K].
    order : int
        Polynomial order of the element: 1 uses row-sum, higher orders use HRZ lumping.

    Returns
    -------
    ndarray, shape (e, n, n)
        Diagonal matrices with the same total as ``Ce`` [J/K].
    """
    if order == 1:
        diagonal = Ce.sum(axis=2)
    else:
        own = np.einsum("enn->en", Ce)
        diagonal = own * (Ce.sum(axis=(1, 2)) / own.sum(axis=1))[:, None]
    out = np.zeros_like(Ce)
    index = np.arange(Ce.shape[1])
    out[:, index, index] = diagonal
    return out


class CapacitanceTerm(BaseTerm):
    """Thermal mass of every region: adds ``C_e`` to ``C``.

    ``rho c`` is evaluated at each integration point from the temperature in the state
    the driver passes (Theory §6 uses ``T_theta`` for this).

    Parameters
    ----------
    lumped : bool
        Assemble the lumped (diagonal) form instead of the consistent one.
    """

    def __init__(self, lumped: bool = False, name: str = "capacitance") -> None:
        super().__init__(name)
        self.lumped = lumped
        self._batches: list[ElementBatch] = []

    def setup(self, problem: CompiledProblem) -> None:
        """Collect the element batches and decide whether the term is linear."""
        self._batches = element_batches(problem)
        materials = [b.region.material for b in self._batches]
        self.is_linear = not any(m.rho.depends_on_T or m.cp.depends_on_T for m in materials)

    def element_matrices(self, s: State, batch: ElementBatch) -> ndarray:
        """Capacitance matrices of one batch at the state's temperature [J/K]."""
        temperature = interpolate(batch.geom.N, s.u[batch.dofs])
        rho_c = volumetric_heat_capacity(batch.region.material, temperature)
        Ce = capacitance(batch.geom, rho_c, batch.g)
        return lump(Ce, element(batch.etype).order) if self.lumped else Ce

    def capacitance(self, s: State, asm: Assembler) -> None:
        """Assemble ``C`` at the state's temperature."""
        for b in self._batches:
            asm.add_matrix(b.dofs, self.element_matrices(s, b))
