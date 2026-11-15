"""Conduction element matrices (Theory §2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray

from ..solver.assembler import Assembler
from ..solver.terms import BaseTerm, State
from .batches import ElementBatch, element_batches
from .kernel import ElemGeom
from .properties import conductivity_matrix

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem


def conduction(geom: ElemGeom, D: ndarray, g: ndarray) -> ndarray:
    """Conduction matrices ``K_e = sum_gp B^T D B g |J| w`` of a block of elements.

    Parameters
    ----------
    geom : ElemGeom
        Integration data of the block.
    D : ndarray, shape (e, gp, dim, dim)
        Conductivity matrix at each integration point [W/(m K)].
    g : ndarray, shape (e, gp)
        Geometry factor at each integration point (thickness [m], ``2 pi r`` [m], or 1).

    Returns
    -------
    ndarray, shape (e, n, n)
        Element conduction matrices [W/K].
    """
    return np.einsum(
        "epin,epij,epjm,ep->enm", geom.dNdx, D, geom.dNdx, g * geom.dV, optimize=True
    )


class ConductionTerm(BaseTerm):
    """Conduction in every region of the problem: adds ``K_e`` to ``K`` (Theory §2).

    Conductivity is evaluated at each integration point from the interpolated
    temperature ``N T_e``. The term is linear when no material's conductivity depends on
    temperature.
    """

    def __init__(self, name: str = "conduction") -> None:
        super().__init__(name)
        self._batches: list[ElementBatch] = []

    def setup(self, problem: CompiledProblem) -> None:
        """Collect the element batches and decide whether the term is linear."""
        self._batches = element_batches(problem)
        self._dim = problem.mesh.dim
        materials = [b.region.material for b in self._batches]
        self.is_linear = not any(
            m.k.depends_on_T or (m.k2 is not None and m.k2.depends_on_T) for m in materials
        )

    def conductance(self, s: State, asm: Assembler) -> None:
        """Assemble the conduction matrices at the current iterate."""
        for b in self._batches:
            temperature = np.einsum("pn,en->ep", b.geom.N, s.u[b.dofs])
            D = conductivity_matrix(
                b.region.material, b.region.material_angle, temperature, self._dim
            )
            asm.add_matrix(b.dofs, conduction(b.geom, D, b.g))
