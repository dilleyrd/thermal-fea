"""Radiation from a boundary to large surroundings (Theory §5).

With ``T = N T_e`` at each integration point, the residual contribution is

    r_rad = - sum_gp eps sigma (T^4 - T_inf^4) N^T g |J_s| w

and the tangent contribution is

    K_rad = sum_gp 4 eps sigma T^3 N^T N g |J_s| w

Temperatures are absolute (kelvin). The term is always nonlinear.
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from ..core import registry
from ..core.constants import STEFAN_BOLTZMANN
from ..model.bcs import RadiationAmbient
from ..solver.assembler import Assembler
from ..solver.terms import State
from .batches import FacetBatch
from .evaluate import at_points
from .surface_loads import FacetTerm


class RadiationAmbientTerm(FacetTerm):
    """Grey-body radiation ``q_n = eps sigma (T^4 - T_inf^4)`` on the selected curves.

    The emissivity ``eps(t, x, y, T)`` (dimensionless) and the temperature of the
    surroundings ``T_inf(t, x, y, T)`` [K] are evaluated at the integration points.
    """

    is_linear = False

    def __init__(self, bc: RadiationAmbient) -> None:
        super().__init__(bc.name, bc.selection)
        self.emissivity = bc.emissivity
        self.T_inf = bc.T_inf
        self.is_time_dependent = bc.emissivity.depends_on_time or bc.T_inf.depends_on_time

    def _eps_sigma(self, s: State, batch: FacetBatch, temperature: ndarray) -> ndarray:
        eps = at_points(self.emissivity, s.t, batch.geom.xgp, temperature)
        return STEFAN_BOLTZMANN * eps

    def _net_flux(self, s: State, batch: FacetBatch) -> ndarray:
        """Heat flux leaving the body at the integration points [W/m^2], shape (f, gp)."""
        temperature = self.temperature(s, batch)
        ambient = at_points(self.T_inf, s.t, batch.geom.xgp, temperature)
        return self._eps_sigma(s, batch, temperature) * (temperature**4 - ambient**4)

    def conductance(self, s: State, asm: Assembler) -> None:
        """Add ``K_rad`` to the tangent (it is not part of ``K``)."""
        for b in self._batches:
            temperature = self.temperature(s, b)
            weight = 4.0 * self._eps_sigma(s, b, temperature) * temperature**3 * b.g * b.geom.dS
            asm.add_tangent(b.dofs, np.einsum("fp,pn,pm->fnm", weight, b.geom.N, b.geom.N))

    def load(self, s: State, asm: Assembler) -> None:
        """Add ``r_rad`` to the residual (it is not part of ``F``)."""
        for b in self._batches:
            weight = -self._net_flux(s, b) * b.g * b.geom.dS
            asm.add_residual(b.dofs, np.einsum("fp,pn->fn", weight, b.geom.N))

    def boundary_heat(self, s: State) -> float:
        """Heat entering the body [W]: ``-sum_gp eps sigma (T^4 - T_inf^4) g |J_s| w``."""
        return -float(sum((self._net_flux(s, b) * b.g * b.geom.dS).sum() for b in self._batches))

    def breakpoints(self) -> list[float]:
        """Breakpoints of the emissivity and of the surroundings temperature."""
        return sorted({*self.emissivity.breakpoints(), *self.T_inf.breakpoints()})


registry.set_bc_term_factory(RadiationAmbient, RadiationAmbientTerm)
