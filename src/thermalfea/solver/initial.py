"""Initial temperature field of a transient analysis (Data §3).

Four kinds of :class:`~thermalfea.model.model.InitialCondition`:

* ``uniform``: one temperature everywhere;
* ``expression``: a function of position, evaluated at every node;
* ``per_region``: one temperature per region selection;
* ``from_results``: the last step of another results file on the same mesh.

Prescribed nodes take their boundary-condition value at the start time afterwards
(``solver.transient.initial_state``).
"""

from __future__ import annotations

import logging
from pathlib import Path

import h5py
import numpy as np
from numpy import ndarray

from ..core.errors import ModelError
from ..model.model import InitialCondition
from ..physics.evaluate import at_points
from .problem import TEMPERATURE, CompiledProblem

log = logging.getLogger(__name__)

#: Uniform temperature [K] used when a problem has no model to take one from (20 degC).
DEFAULT_INITIAL_TEMPERATURE = 293.15


def _per_region(problem: CompiledProblem, values: dict[str, float]) -> ndarray:
    mesh = problem.mesh
    total = np.zeros(mesh.n_nodes)
    count = np.zeros(mesh.n_nodes)
    assigned: set[int] = set()
    for name, value in values.items():
        _, tags = problem.selection_tags(name, (mesh.dim,))
        assigned.update(tags)
        for block in (b for tag in tags for b in mesh.region_elements(tag)):
            nodes = np.unique(block.conn)
            total[nodes] += float(value)
            count[nodes] += 1.0
    missing = sorted({int(r) for b in mesh.blocks for r in np.unique(b.region)} - assigned)
    if missing:
        raise ModelError(
            f"the per-region initial condition gives no temperature for region(s) {missing}"
        )
    # a node on an interface takes the mean of the regions that share it
    return total / count


def _from_results(problem: CompiledProblem, path: str | None) -> ndarray:
    from ..post.results import Results  # imported here: post depends on the solver

    if not path:
        raise ModelError("the initial condition 'from_results' needs a results file")
    from .results_writer import _mesh_difference  # imported here: it needs the writer module

    source = Results(Path(path))
    mesh = problem.mesh
    if source.n_steps == 0:
        raise ModelError(f"the results in {path} hold no steps to take an initial condition from")
    try:
        with h5py.File(path, "r") as f:
            width = f["steps"]["fields"][TEMPERATURE].shape[1]
            diff = _mesh_difference(f, mesh, width, mesh.n_nodes)
    except (OSError, KeyError) as exc:
        raise ModelError(f"cannot read the mesh of the results in {path} ({exc})") from exc
    if diff is not None:
        raise ModelError(
            f"the results in {path} were computed on a different mesh ({diff}; the "
            f"file has {source.mesh.n_nodes} nodes, this mesh has {mesh.n_nodes}). An initial "
            "condition taken from results needs the same mesh."
        )
    log.info("initial condition: last step (t = %g s) of %s", source.times[-1], path)
    return source.temperature(-1)


def nodal_initial_temperature(problem: CompiledProblem, ic: InitialCondition) -> ndarray:
    """Evaluate an initial condition at the nodes.

    Parameters
    ----------
    problem : CompiledProblem
    ic : InitialCondition

    Returns
    -------
    ndarray, shape (n_nodes,)
        Temperatures [K].

    Raises
    ------
    ModelError
        If the initial condition is incomplete or cannot be applied to this mesh.
    """
    mesh = problem.mesh
    if ic.kind in ("uniform", "expression"):
        if ic.value is None:
            raise ModelError(f"the initial condition '{ic.kind}' needs a value")
        if ic.value.depends_on_T:
            raise ModelError("an initial temperature cannot depend on T")
        if ic.kind == "uniform":
            return np.full(mesh.n_nodes, float(ic.value()))
        return np.array(at_points(ic.value, 0.0, mesh.nodes))
    if ic.kind == "per_region":
        if not ic.per_region:
            raise ModelError("the initial condition 'per_region' needs a temperature per region")
        return _per_region(problem, ic.per_region)
    return _from_results(problem, ic.results_path)


def initial_temperature(problem: CompiledProblem) -> ndarray:
    """Initial solution vector of a problem from its model's initial condition.

    Parameters
    ----------
    problem : CompiledProblem

    Returns
    -------
    ndarray, shape (n_dofs,)
        Initial temperatures [K] at the temperature DOFs. A problem assembled without a
        model starts at :data:`DEFAULT_INITIAL_TEMPERATURE`.
    """
    T = np.full(problem.dofs.n_dofs, DEFAULT_INITIAL_TEMPERATURE)
    if problem.model is not None:
        nodal = nodal_initial_temperature(problem, problem.model.initial_condition)
        if not np.all(np.isfinite(nodal)):
            raise ModelError("the initial condition gives a non-finite temperature")
        T[problem.dofs.field_dofs(TEMPERATURE)] = nodal
    return T
