"""Shared support for the verification tests.

Each case of ``docs/verification.md`` is a runnable script ``examples/vNN_*.py`` with a
``run(etype) -> dict`` function; its test loads the script with :func:`load` and asserts
the tolerances of the verification document. The energy-balance limits of V-34 are
checked on every case with :func:`check_balance`.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
from numpy import ndarray

from thermalfea.core.mesh import Mesh
from thermalfea.materials.material import Material
from thermalfea.physics.conduction import ConductionTerm
from thermalfea.solver.dofs import DofMap
from thermalfea.solver.problem import CompiledProblem, RegionData

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
TYPES = ["T3", "Q4", "T6", "Q8"]

#: V-34: relative energy imbalance allowed on linear steady cases, and on all others.
BALANCE_LINEAR_STEADY = 1e-8
BALANCE = 1e-3


def load(name: str) -> ModuleType:
    """Import ``examples/<name>.py`` (the examples import their ``common`` module by name)."""
    if str(EXAMPLES) not in sys.path:
        sys.path.insert(0, str(EXAMPLES))
    return importlib.import_module(name)


def check_balance(result: dict, linear_steady: bool = True) -> None:
    """V-34: imbalance < 1e-3 of throughput (< 1e-8 for linear steady cases)."""
    limit = BALANCE_LINEAR_STEADY if linear_steady else BALANCE
    assert result["imbalance"] < limit, f"energy imbalance {result['imbalance']:.3e}"


class NodeConstraint:
    """Prescribed values at given nodes, for problems assembled by hand."""

    is_time_dependent = False

    def __init__(self, name: str, nodes: ndarray, values: ndarray) -> None:
        self.name = name
        self.nodes = np.asarray(nodes, dtype=np.int64)
        self._values = np.asarray(values, dtype=float)
        self._dofs = self.nodes

    def setup(self, problem: CompiledProblem) -> None:
        self._dofs = problem.dofs.node_dofs("T", self.nodes)

    def values(self, t: float) -> tuple[ndarray, ndarray]:
        return self._dofs, self._values

    def breakpoints(self) -> list[float]:
        return []


def conduction_problem(mesh: Mesh, k: float, nodes: ndarray, values: ndarray) -> CompiledProblem:
    """A problem with one region of conductivity ``k`` and prescribed node temperatures.

    Built from the library pieces only: ``DofMap``, ``ConductionTerm`` and the constraint
    protocol. Works for any registered element type and any space dimension.
    """
    dofs = DofMap()
    dofs.add_field("T", mesh.n_nodes)
    regions = {int(r): RegionData(Material("solid", k, 7800.0, 500.0))
               for b in mesh.blocks for r in np.unique(b.region)}
    problem = CompiledProblem(mesh=mesh, dofs=dofs, regions=regions)
    conduction = ConductionTerm()
    conduction.setup(problem)
    problem.terms.append(conduction)
    constraint = NodeConstraint("boundary", nodes, values)
    constraint.setup(problem)
    problem.constraints.append(constraint)
    return problem


def boundary_nodes(mesh: Mesh) -> ndarray:
    """Sorted indices of the nodes on any facet block."""
    return np.unique(np.concatenate([fb.conn.ravel() for fb in mesh.facets]))
