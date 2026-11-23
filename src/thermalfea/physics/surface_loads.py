"""Boundary (facet) loads: heat flux, total heat flow and convection (Theory §2).

For a facet with shape functions ``N`` and measure ``|J_s|``:

* flux: ``F_e = sum_gp q N^T g |J_s| w`` (``q`` positive into the body);
* convection: ``K_e = sum_gp h N^T N g |J_s| w``,
  ``F_e = sum_gp h T_inf N^T g |J_s| w``;
* total heat flow ``P`` [W] on a boundary set: the uniform flux ``q = P / A`` with
  ``A = sum over the set of integral g ds``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray

from ..core import registry
from ..core.errors import ModelError
from ..model.bcs import Convection, HeatFlow, HeatFlux
from ..solver.assembler import Assembler
from ..solver.terms import BaseTerm, State
from .batches import FacetBatch, facet_batches
from .evaluate import at_points, interpolate

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem


class FacetTerm(BaseTerm):
    """Base of the terms that integrate over the facets of a curve selection."""

    def __init__(self, name: str, selection: str) -> None:
        super().__init__(name)
        self.selection = selection
        self._batches: list[FacetBatch] = []

    def setup(self, problem: CompiledProblem) -> None:
        """Resolve the selection to facet batches."""
        _, tags = problem.selection_tags(self.selection, (problem.mesh.dim - 1,))
        self._batches = facet_batches(problem, tags)
        if not self._batches:
            raise ModelError(f"selection {self.selection!r} contains no element edges")

    def area(self) -> float:
        """``A = integral of g ds`` over the selection [m^2]."""
        return float(sum((b.g * b.geom.dS).sum() for b in self._batches))

    @staticmethod
    def temperature(s: State, batch: FacetBatch) -> ndarray:
        """Temperature at the integration points of a batch [K], shape (f, gp)."""
        return interpolate(batch.geom.N, s.u[batch.dofs])


class _FluxTerm(FacetTerm):
    """Shared machinery: a flux ``q`` [W/m^2] into the body, integrated over facets."""

    def _flux(self, s: State, batch: FacetBatch) -> ndarray:
        raise NotImplementedError

    def load(self, s: State, asm: Assembler) -> None:
        """Add ``sum_gp q N^T g |J_s| w`` to ``F``."""
        for b in self._batches:
            weight = self._flux(s, b) * b.g * b.geom.dS
            asm.add_vector(b.dofs, np.einsum("fp,pn->fn", weight, b.geom.N))

    def boundary_heat(self, s: State) -> float:
        """Heat entering the body through the selection [W]."""
        return float(sum((self._flux(s, b) * b.g * b.geom.dS).sum() for b in self._batches))


class HeatFluxTerm(_FluxTerm):
    """Heat flux ``q(t, x, y, T)`` [W/m^2] on the selected curves, positive into the body."""

    def __init__(self, bc: HeatFlux) -> None:
        super().__init__(bc.name, bc.selection)
        self.q = bc.q
        self.is_linear = not bc.q.depends_on_T
        self.is_time_dependent = bc.q.depends_on_time

    def _flux(self, s: State, batch: FacetBatch) -> ndarray:
        return at_points(self.q, s.t, batch.geom.xgp, self.temperature(s, batch))

    def breakpoints(self) -> list[float]:
        """Breakpoints of the flux function."""
        return self.q.breakpoints()


class HeatFlowTerm(_FluxTerm):
    """Total heat flow ``P(t)`` [W] spread uniformly over the selected curves.

    ``P`` is a total for the whole selection, so it is evaluated as a function of time
    only; a dependence on temperature is refused.
    """

    def __init__(self, bc: HeatFlow) -> None:
        super().__init__(bc.name, bc.selection)
        if bc.P.depends_on_T:
            raise ModelError(
                f"{bc.name}: a total heat flow cannot depend on temperature; use a heat "
                "flux [W/m^2] instead"
            )
        if bc.P.depends_on_position:
            raise ModelError(
                f"{bc.name}: a total heat flow is spread uniformly, so it may depend on "
                "time only; use Heat Flux for a value that varies with position"
            )
        self.P = bc.P
        self.is_time_dependent = bc.P.depends_on_time
        self._area = 0.0

    def setup(self, problem: CompiledProblem) -> None:
        """Resolve the selection and compute its area ``A``."""
        super().setup(problem)
        self._area = self.area()
        if not self._area > 0.0:
            raise ModelError(f"selection {self.selection!r} has no area")

    def _flux(self, s: State, batch: FacetBatch) -> ndarray:
        return np.full(batch.g.shape, float(self.P(t=s.t)) / self._area)

    def breakpoints(self) -> list[float]:
        """Breakpoints of the heat-flow function."""
        return self.P.breakpoints()


class ConvectionTerm(FacetTerm):
    """Convection ``q_n = h (T - T_inf)`` on the selected curves.

    ``h(t, x, y, T)`` [W/(m^2 K)] and ``T_inf(t, x, y, T)`` [K] are evaluated at the
    integration points; the wall temperature passed to them is the current iterate.
    """

    def __init__(self, bc: Convection) -> None:
        super().__init__(bc.name, bc.selection)
        self.h = bc.h
        self.T_inf = bc.T_inf
        self.is_linear = not (bc.h.depends_on_T or bc.T_inf.depends_on_T)
        self.is_time_dependent = bc.h.depends_on_time or bc.T_inf.depends_on_time

    def coefficient(self, s: State, batch: FacetBatch) -> ndarray:
        """Heat-transfer coefficient at the integration points [W/(m^2 K)], shape (f, gp)."""
        return at_points(self.h, s.t, batch.geom.xgp, self.temperature(s, batch))

    def ambient(self, s: State, batch: FacetBatch) -> ndarray:
        """Fluid temperature at the integration points [K], shape (f, gp)."""
        return at_points(self.T_inf, s.t, batch.geom.xgp, self.temperature(s, batch))

    def conductance(self, s: State, asm: Assembler) -> None:
        """Add ``sum_gp h N^T N g |J_s| w`` to ``K``."""
        for b in self._batches:
            weight = self.coefficient(s, b) * b.g * b.geom.dS
            asm.add_matrix(b.dofs, np.einsum("fp,pn,pm->fnm", weight, b.geom.N, b.geom.N))

    def load(self, s: State, asm: Assembler) -> None:
        """Add ``sum_gp h T_inf N^T g |J_s| w`` to ``F``."""
        for b in self._batches:
            weight = self.coefficient(s, b) * self.ambient(s, b) * b.g * b.geom.dS
            asm.add_vector(b.dofs, np.einsum("fp,pn->fn", weight, b.geom.N))

    def boundary_heat(self, s: State) -> float:
        """Heat entering the body [W]: ``-sum_gp h (T - T_inf) g |J_s| w``."""
        total = 0.0
        for b in self._batches:
            difference = self.temperature(s, b) - self.ambient(s, b)
            total -= float((self.coefficient(s, b) * difference * b.g * b.geom.dS).sum())
        return total

    def breakpoints(self) -> list[float]:
        """Breakpoints of the coefficient and of the fluid temperature."""
        return sorted({*self.h.breakpoints(), *self.T_inf.breakpoints()})


registry.set_bc_term_factory(HeatFlux, HeatFluxTerm)
registry.set_bc_term_factory(HeatFlow, HeatFlowTerm)
registry.set_bc_term_factory(Convection, ConvectionTerm)
