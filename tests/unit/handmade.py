"""Problems assembled by hand on ``rect_mesh`` meshes, for physics tests without gmsh.

``make_problem`` returns a :class:`CompiledProblem` with one region, a conduction term and
the named entity sets ``bottom``, ``right``, ``top``, ``left`` (curves) and ``all`` (the
surface). Boundary conditions are added with :func:`thermalfea.solver.compile.attach`,
which uses the registered factories exactly as ``compile`` does.
"""

from __future__ import annotations

import numpy as np

from thermalfea.core.functions import Function
from thermalfea.core.meshgen import BOTTOM, LEFT, RIGHT, TOP, distort, rect_mesh
from thermalfea.materials.material import Material
from thermalfea.model.bcs import BoundaryCondition
from thermalfea.physics.conduction import ConductionTerm
from thermalfea.solver.assembler import Assembler
from thermalfea.solver.compile import attach
from thermalfea.solver.dofs import DofMap
from thermalfea.solver.problem import CompiledProblem, RegionData
from thermalfea.solver.terms import State

TYPES = ["T3", "Q4", "T6", "Q8"]
REGION = 1


def make_problem(
    etype: str = "Q4",
    size: tuple[float, float] = (2.0, 1.0),
    cells: tuple[int, int] = (4, 2),
    origin: tuple[float, float] = (0.0, 0.0),
    k: Function | float = 50.0,
    rho: Function | float = 7800.0,
    cp: Function | float = 500.0,
    k2: Function | float | None = None,
    angle: float = 0.0,
    thickness: float = 1.0,
    axisymmetric: bool = False,
    distortion: float = 0.0,
    bcs: tuple[BoundaryCondition, ...] = (),
) -> CompiledProblem:
    mesh = rect_mesh(*origin, *size, *cells, etype, region=REGION)
    if distortion:
        mesh = distort(mesh, distortion, seed=7)
    mesh.axisymmetric = axisymmetric
    dofs = DofMap()
    dofs.add_field("T", mesh.n_nodes)
    problem = CompiledProblem(
        mesh=mesh,
        dofs=dofs,
        regions={REGION: RegionData(Material("m", k, rho, cp, k2=k2), thickness, angle, "all")},
        named_entities={
            "bottom": (1, [BOTTOM]),
            "right": (1, [RIGHT]),
            "top": (1, [TOP]),
            "left": (1, [LEFT]),
            "all": (2, [REGION]),
        },
    )
    conduction = ConductionTerm()
    conduction.setup(problem)
    problem.terms.append(conduction)
    for bc in bcs:
        attach(problem, bc)
    return problem


def make_state(problem: CompiledProblem, u: np.ndarray | float = 300.0, t: float = 0.0) -> State:
    u = np.broadcast_to(np.asarray(u, dtype=float), (problem.dofs.n_dofs,)).copy()
    return State(u=u, u_prev=u.copy(), t=t, dt=None, dofs=problem.dofs)


def assemble(problem: CompiledProblem, s: State, terms=None) -> Assembler:
    """Run ``conductance`` and ``load`` of the given terms (default: all) into an assembler."""
    asm = Assembler(problem.dofs.n_dofs)
    for term in problem.terms if terms is None else terms:
        term.conductance(s, asm)
        term.load(s, asm)
    return asm
