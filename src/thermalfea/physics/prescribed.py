"""Prescribed temperatures (Theory §4).

A :class:`FixedTemperature` condition on curves or points becomes a constraint: the nodes
of the selection and the value ``T(t, x, y)`` at each of them. The solver imposes the
values by partitioning; the penalty method is never used.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray

from ..core import registry
from ..core.errors import ModelError
from ..model.bcs import FixedTemperature
from .evaluate import at_points

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem

FIELD = "T"
POINT_DIM = 0


class FixedTemperatureConstraint:
    """Nodes of a selection held at a prescribed temperature.

    Parameters
    ----------
    bc : FixedTemperature
        ``bc.T`` may depend on time and position, not on temperature.
    """

    def __init__(self, bc: FixedTemperature) -> None:
        if bc.T.depends_on_T:
            raise ModelError(f"{bc.name}: a prescribed temperature cannot depend on T")
        self.name = bc.name
        self.selection = bc.selection
        self.T = bc.T
        self.is_time_dependent = bc.T.depends_on_time
        self.nodes: ndarray = np.empty(0, dtype=np.int64)
        self._dofs: ndarray = np.empty(0, dtype=np.int64)
        self._coords: ndarray = np.empty((0, 0))

    def setup(self, problem: CompiledProblem) -> None:
        """Collect the nodes of the selected curves or points."""
        mesh = problem.mesh
        dim, tags = problem.selection_tags(self.selection, (POINT_DIM, mesh.dim - 1))
        if dim == POINT_DIM:
            missing = [t for t in tags if t not in mesh.point_nodes]
            if missing:
                raise ModelError(f"point(s) {missing} of {self.selection!r} have no mesh node")
            nodes = np.array([mesh.point_nodes[t] for t in tags], dtype=np.int64)
        else:
            found = [fb.conn.ravel() for fb in mesh.facets_on(tags)]
            nodes = np.concatenate(found) if found else np.empty(0, dtype=np.int64)
        self.nodes = np.unique(nodes)
        if self.nodes.size == 0:
            raise ModelError(f"selection {self.selection!r} contains no mesh nodes")
        self._dofs = problem.dofs.node_dofs(FIELD, self.nodes)
        self._coords = mesh.nodes[self.nodes]

    def values(self, t: float) -> tuple[ndarray, ndarray]:
        """Return the prescribed DOFs and their temperatures [K] at time ``t`` [s]."""
        return self._dofs, np.array(at_points(self.T, t, self._coords))

    def breakpoints(self) -> list[float]:
        """Breakpoints of the temperature function."""
        return self.T.breakpoints()


registry.set_bc_constraint_factory(FixedTemperature, FixedTemperatureConstraint)
