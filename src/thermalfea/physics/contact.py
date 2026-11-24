"""Thermal contact resistance across an interface (Theory §11).

Along a contact curve the mesh has duplicated nodes, one set per side
(:mod:`thermalfea.core.contact_split`). For each pair of matching edge elements with
contact conductance ``h_c`` [W/(m^2 K)] the term adds, over the 2n interface DOFs
``[side A; side B]``,

    K_c = sum_gp h_c g |J_s| w [[N^T N, -N^T N], [-N^T N, N^T N]].

Side A is the side of the lower region id (the parent element of the interface facets);
the geometry factor ``g`` is taken there.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray

from ..core.errors import ModelError
from ..model.bcs import Contact
from ..solver.assembler import Assembler
from ..solver.terms import BaseTerm, State
from .batches import FIELD, FacetBatch, facet_batches
from .evaluate import at_points, interpolate

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem

#: Key of ``CompiledProblem.cache`` holding the partner arrays of the opened interfaces
#: (entity tag -> far-side node of every near-side node), set by the compiler.
PARTNERS = "contact_partners"
#: ``problem.cache`` key of the node origin of an opened mesh (``SplitMesh.origin``): for
#: every node, the node of the unopened mesh it was copied from.
ORIGIN = "contact_origin"


class ContactTerm(BaseTerm):
    """Contact conductance on the interface curves of one :class:`Contact`.

    Parameters
    ----------
    contact : Contact
        ``conductance`` [W/(m^2 K)] may depend on time and position, not on temperature
        (Theory §11 does not say which side's temperature would apply).
    """

    symmetric = True
    is_linear = True

    def __init__(self, contact: Contact) -> None:
        super().__init__(contact.name)
        if contact.conductance.depends_on_T:
            raise ModelError(
                f"contact {contact.name!r}: the conductance cannot depend on temperature; "
                "give a constant or a function of time and position"
            )
        self.selection = contact.selection
        self.h = contact.conductance
        self.is_time_dependent = contact.conductance.depends_on_time
        self._sides: list[tuple[FacetBatch, ndarray]] = []

    def setup(self, problem: CompiledProblem) -> None:
        """Pair the facets of the contact curves with the DOFs on the far side."""
        mesh = problem.mesh
        _, tags = problem.selection_tags(self.selection, (mesh.dim - 1,))
        partners = problem.cache.get(PARTNERS, {})
        self._sides = []
        for tag in tags:
            partner = partners.get(int(tag))
            if partner is None:
                raise ModelError(
                    f"the mesh was not opened along curve {tag} (contact interfaces are "
                    "opened by the compiler)"
                )
            for batch in facet_batches(problem, [tag]):
                far = partner[batch.conn]
                if np.any(far < 0):
                    raise ModelError(f"curve {tag} has facets without a far side")
                self._sides.append((batch, problem.dofs.node_dofs(FIELD, far)))
        if not self._sides:
            raise ModelError(f"selection {self.selection!r} contains no element edges")

    def _weight(self, s: State, batch: FacetBatch) -> ndarray:
        """``h_c g |J_s| w`` at the integration points [W/K], shape (f, gp)."""
        return at_points(self.h, s.t, batch.geom.xgp) * batch.g * batch.geom.dS

    def conductance(self, s: State, asm: Assembler) -> None:
        """Add ``K_c`` to ``K``."""
        for batch, far in self._sides:
            N = batch.geom.N
            nn = np.einsum("fp,pn,pm->fnm", self._weight(s, batch), N, N)
            block = np.concatenate(
                [np.concatenate([nn, -nn], axis=2), np.concatenate([-nn, nn], axis=2)], axis=1
            )
            asm.add_matrix(np.concatenate([batch.dofs, far], axis=1), block)

    def heat_across(self, s: State) -> float:
        """Heat passing from side A to side B [W]: ``sum_gp h_c (T_A - T_B) g |J_s| w``."""
        total = 0.0
        for batch, far in self._sides:
            jump = interpolate(batch.geom.N, s.u[batch.dofs] - s.u[far])
            total += float((self._weight(s, batch) * jump).sum())
        return total

    def results(self, s: State) -> dict[str, ndarray]:
        """Named result values: ``contact_heat:<name>`` [W], from side A to side B."""
        return {f"contact_heat:{self.name}": np.array([self.heat_across(s)])}

    def breakpoints(self) -> list[float]:
        """Breakpoints of the conductance function."""
        return self.h.breakpoints()
