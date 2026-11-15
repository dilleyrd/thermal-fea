"""Turns a model, its built geometry and a mesh into a :class:`CompiledProblem`.

The compiler knows no physics. It builds the DOF map, the per-region properties, the
conduction term, and then one or more terms (and constraints) per active boundary
condition by calling the factory registered for its class (Plan §7 rules 5 and 6).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..core import registry
from ..core.errors import ModelError
from ..core.mesh import Mesh
from ..model.bcs import BoundaryCondition
from ..model.model import Model
from ..model.selections import Selection, StaleSelectionError, resolve
from ..physics import (
    builtin,  # noqa: F401  (registers the built-in term factories)
    timescales,
)
from ..physics.capacitance import CapacitanceTerm
from ..physics.conduction import ConductionTerm
from .dofs import DofMap
from .problem import TEMPERATURE, CompiledProblem, RegionData

if TYPE_CHECKING:  # the builder imports gmsh; the solver must not (Plan §3)
    from ..geometry.builder import BuiltGeometry

log = logging.getLogger(__name__)


def selection_tags(problem: CompiledProblem, name: str, dims: tuple[int, ...]) -> tuple[int, list]:
    """Shortcut for :meth:`CompiledProblem.selection_tags`."""
    return problem.selection_tags(name, dims)


def _resolve(selection: Selection, built: BuiltGeometry | None) -> list[int]:
    if built is None:  # trust the tags that api.build refreshed
        return list(selection.tags)
    try:
        return resolve(selection, built)
    except StaleSelectionError as exc:
        raise ModelError(str(exc)) from None


def _regions(model: Model, built: BuiltGeometry | None, mesh: Mesh) -> dict[int, RegionData]:
    regions: dict[int, RegionData] = {}
    for assignment in model.regions:
        selection = model.selections.get(assignment.selection)
        if selection is None:
            raise ModelError(f"region refers to unknown selection {assignment.selection!r}")
        if selection.dim != mesh.dim:
            raise ModelError(
                f"region selection {assignment.selection!r} must contain entities of "
                f"dimension {mesh.dim}"
            )
        material = model.materials.get(assignment.material)
        if material is None:
            raise ModelError(
                f"region {assignment.selection!r} uses unknown material {assignment.material!r}"
            )
        for tag in _resolve(selection, built):
            if tag in regions:
                raise ModelError(
                    f"a surface is assigned twice: by regions {regions[tag].name!r} and "
                    f"{assignment.selection!r}"
                )
            regions[tag] = RegionData(
                material, assignment.thickness, assignment.material_angle, assignment.selection
            )
    return regions


def _setup(problem: CompiledProblem, item: object) -> None:
    try:
        item.setup(problem)  # type: ignore[attr-defined]
    except ModelError as exc:
        raise ModelError(f"{item.name}: {exc}") from None  # type: ignore[attr-defined]


def attach(problem: CompiledProblem, bc: BoundaryCondition) -> None:
    """Add the terms and constraints of one boundary condition to a problem.

    The factories registered for the condition's class are called, and every term and
    constraint they return is set up and appended. Inactive conditions, and classes
    registered without factories, add nothing.

    Parameters
    ----------
    problem : CompiledProblem
        Compiled from a model, or assembled by hand with ``named_entities``.
    bc : BoundaryCondition
    """
    if not bc.active:
        return
    info = registry.bc_info(type(bc))
    for factory, target in (
        (info.term_factory, problem.terms),
        (info.constraint_factory, problem.constraints),
    ):
        if factory is None:
            continue
        made = factory(bc)
        for item in made if isinstance(made, (list, tuple)) else [made]:
            _setup(problem, item)
            target.append(item)


def compile(  # noqa: A001
    model: Model, built: BuiltGeometry | None, mesh: Mesh
) -> CompiledProblem:
    """Compile a model into the list of terms the drivers solve.

    Parameters
    ----------
    model : Model
    built : BuiltGeometry or None
        The build of ``model`` that ``mesh`` was generated from. With ``None`` the tags
        stored in the model's selections are used as they are; they are current after
        :func:`thermalfea.api.build`.
    mesh : Mesh

    Returns
    -------
    CompiledProblem
        With the DOF map (field ``"T"``), the conduction term, and the terms and
        constraints of every active boundary condition, all set up.

    Raises
    ------
    ModelError
        If the model is inconsistent (missing material, stale selection, ...).
    """
    dofs = DofMap()
    dofs.add_field(TEMPERATURE, mesh.n_nodes)
    problem = CompiledProblem(
        mesh=mesh,
        dofs=dofs,
        regions=_regions(model, built, mesh),
        settings=model.solution,
        model=model,
        built=built,
    )
    conduction = ConductionTerm()
    _setup(problem, conduction)
    problem.terms.append(conduction)
    if model.solution.kind == "transient":
        lumped = model.solution.lumped_capacitance
        thermal_mass = CapacitanceTerm(lumped=lumped)
        _setup(problem, thermal_mass)
        problem.terms.append(thermal_mass)
        problem.suggest_dt = lambda T: timescales.suggested_dt(problem, T)
        problem.check_dt = lambda T, dt: timescales.warn_if_oscillation_likely(
            problem, T, dt, lumped
        )
    for bc in model.bcs:
        attach(problem, bc)
    log.debug(
        "compiled %d term(s), %d constraint(s); linear=%s",
        len(problem.terms), len(problem.constraints), problem.is_linear,
    )
    return problem
