"""Body loads: volumetric heat generation and total power (Theory §2).

``F_e = sum_gp Q N^T g |J| w``. A total power ``P`` [W] applied to a region is converted
to the uniform generation ``Q = P / V`` with ``V = integral of g dA`` over the region.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from ..core import registry
from ..core.errors import ModelError
from ..model.bcs import HeatGeneration, HeatPower
from ..solver.assembler import Assembler
from ..solver.terms import BaseTerm, State
from .batches import ElementBatch, element_batches
from .evaluate import at_points, interpolate

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem


class _BodyLoadTerm(BaseTerm):
    """Shared machinery: a generation rate ``Q`` [W/m^3] integrated over regions."""

    def __init__(self, name: str, selection: str) -> None:
        super().__init__(name)
        self.selection = selection
        self._batches: list[ElementBatch] = []

    def setup(self, problem: CompiledProblem) -> None:
        """Resolve the surface selection to element batches."""
        _, tags = problem.selection_tags(self.selection, (problem.mesh.dim,))
        self._batches = element_batches(problem, tags)
        if not self._batches:
            raise ModelError(f"selection {self.selection!r} contains no elements")

    def _rate(self, s: State, batch: ElementBatch) -> np.ndarray:
        """Generation rate [W/m^3] at the integration points of a batch, shape (e, gp)."""
        raise NotImplementedError

    def load(self, s: State, asm: Assembler) -> None:
        """Add ``sum_gp Q N^T g |J| w`` to ``F``."""
        for b in self._batches:
            weight = self._rate(s, b) * b.g * b.geom.dV
            asm.add_vector(b.dofs, np.einsum("ep,pn->en", weight, b.geom.N))

    def boundary_heat(self, s: State) -> float:
        """Total heat generated [W]."""
        return float(sum((self._rate(s, b) * b.g * b.geom.dV).sum() for b in self._batches))


class HeatGenerationTerm(_BodyLoadTerm):
    """Volumetric heat generation ``Q(t, x, y, T)`` [W/m^3] in the selected surfaces."""

    def __init__(self, bc: HeatGeneration) -> None:
        super().__init__(bc.name, bc.selection)
        self.Q = bc.Q
        self.is_linear = not bc.Q.depends_on_T
        self.is_time_dependent = bc.Q.depends_on_time

    def _rate(self, s: State, batch: ElementBatch) -> np.ndarray:
        temperature = interpolate(batch.geom.N, s.u[batch.dofs])
        return at_points(self.Q, s.t, batch.geom.xgp, temperature)

    def breakpoints(self) -> list[float]:
        """Breakpoints of the generation function."""
        return self.Q.breakpoints()


class HeatPowerTerm(_BodyLoadTerm):
    """Total power ``P(t)`` [W] spread uniformly over the selected surfaces.

    ``P`` is a total for the whole selection, so it is evaluated as a function of time
    only; a dependence on position or temperature is not meaningful and is refused.
    """

    def __init__(self, bc: HeatPower) -> None:
        super().__init__(bc.name, bc.selection)
        if bc.P.depends_on_T:
            raise ModelError(
                f"{bc.name}: a total power cannot depend on temperature; use a heat "
                "generation [W/m^3] instead"
            )
        self.P = bc.P
        self.is_time_dependent = bc.P.depends_on_time
        self._volume = 0.0

    def setup(self, problem: CompiledProblem) -> None:
        """Resolve the selection and compute its volume ``V = integral of g dA``."""
        super().setup(problem)
        self._volume = float(sum((b.g * b.geom.dV).sum() for b in self._batches))
        if not self._volume > 0.0:
            raise ModelError(f"selection {self.selection!r} has no volume")

    def _rate(self, s: State, batch: ElementBatch) -> np.ndarray:
        return np.full(batch.g.shape, float(self.P(t=s.t)) / self._volume)

    def breakpoints(self) -> list[float]:
        """Breakpoints of the power function."""
        return self.P.breakpoints()


registry.set_bc_term_factory(HeatGeneration, HeatGenerationTerm)
registry.set_bc_term_factory(HeatPower, HeatPowerTerm)
