"""M3.1 — terms and problem compilation (Data §13)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pytest

from thermalfea import api
from thermalfea.core import registry
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Function, Table
from thermalfea.core.meshgen import rect_mesh
from thermalfea.materials.material import Material
from thermalfea.model import bcs
from thermalfea.model.model import Model, RegionAssignment
from thermalfea.physics.batches import element_batches, facet_batches
from thermalfea.physics.conduction import ConductionTerm, conduction
from thermalfea.physics.kernel import geometry, gfactor
from thermalfea.solver.assembler import Assembler
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.compile import selection_tags
from thermalfea.solver.dofs import DofMap
from thermalfea.solver.problem import CompiledProblem, RegionData
from thermalfea.solver.terms import BaseTerm, Constraint, State, Term


def hand_problem(etype: str = "Q4", k=50.0, thickness: float = 1.0, **mesh_kw) -> CompiledProblem:
    """A problem assembled by hand on a rect_mesh, without a model or gmsh."""
    mesh = rect_mesh(0.0, 0.0, 2.0, 1.0, 4, 2, etype, **mesh_kw)
    dofs = DofMap()
    dofs.add_field("T", mesh.n_nodes)
    problem = CompiledProblem(
        mesh=mesh, dofs=dofs,
        regions={1: RegionData(Material("m", k, 7800.0, 500.0), thickness=thickness)},
    )
    term = ConductionTerm()
    term.setup(problem)
    problem.terms.append(term)
    return problem


def state(problem: CompiledProblem, value: float = 300.0) -> State:
    u = np.full(problem.dofs.n_dofs, value)
    return State(u=u, u_prev=u.copy(), t=0.0, dt=None, dofs=problem.dofs)


# --------------------------------------------------------------------- Term interface


def test_base_term_is_a_do_nothing_term() -> None:
    term = BaseTerm("nothing")
    assert isinstance(term, Term)
    assert (term.name, term.is_linear, term.is_time_dependent, term.symmetric) == (
        "nothing", True, False, True)
    problem = hand_problem()
    asm = Assembler(problem.dofs.n_dofs)
    s = state(problem)
    term.setup(problem)
    term.conductance(s, asm)
    term.load(s, asm)
    term.capacitance(s, asm)
    assert asm.matrix().nnz == 0 and not asm.vector().any()
    assert asm.tangent().nnz == 0 and not asm.residual().any()
    assert term.breakpoints() == [] and term.boundary_heat(s) is None and term.results(s) == {}


def test_assembler_tangent_and_residual_channels_are_separate() -> None:
    asm = Assembler(3)
    conn = np.array([[0, 1]])
    asm.add_matrix(conn, np.array([[[1.0, -1.0], [-1.0, 1.0]]]))
    asm.add_tangent(conn, np.array([[[5.0, 0.0], [0.0, 7.0]]]))
    asm.add_vector(conn, np.array([[1.0, 2.0]]))
    asm.add_residual(conn, np.array([[10.0, 20.0]]))
    np.testing.assert_array_equal(asm.matrix().toarray()[:2, :2], [[1.0, -1.0], [-1.0, 1.0]])
    np.testing.assert_array_equal(asm.tangent().toarray()[:2, :2], [[5.0, 0.0], [0.0, 7.0]])
    np.testing.assert_array_equal(asm.vector(), [1.0, 2.0, 0.0])
    np.testing.assert_array_equal(asm.residual(), [10.0, 20.0, 0.0])
    asm.reset()
    assert asm.tangent().nnz == 0 and not asm.residual().any() and asm.matrix().nnz == 0


# -------------------------------------------------------------------- ConductionTerm


@pytest.mark.parametrize("etype", ["T3", "Q4", "T6", "Q8"])
def test_conduction_term_equals_the_kernel(etype: str) -> None:
    problem = hand_problem(etype, k=50.0, thickness=0.25)
    (term,) = problem.terms
    assert isinstance(term, Term)
    assert term.is_linear and term.symmetric and not term.is_time_dependent
    asm = Assembler(problem.dofs.n_dofs)
    term.conductance(state(problem), asm)

    mesh = problem.mesh
    (block,) = mesh.blocks
    geom = geometry(block, mesh.nodes)
    d = np.broadcast_to(50.0 * np.eye(mesh.dim), (*geom.dV.shape, mesh.dim, mesh.dim))
    ref = Assembler(mesh.n_nodes)
    ref.add_matrix(block.conn, conduction(geom, d, gfactor(geom.xgp, False, 0.25, mesh.dim)))
    np.testing.assert_allclose(asm.matrix().toarray(), ref.matrix().toarray(), atol=1e-12)
    assert asm.tangent().nnz == 0 and not asm.vector().any()


def test_conduction_term_with_temperature_dependent_conductivity() -> None:
    k_of_t = Table([300.0, 400.0], [50.0, 100.0], "T")
    problem = hand_problem("Q4", k=k_of_t)
    (term,) = problem.terms
    assert not term.is_linear
    assert not problem.is_linear

    def matrix(temp: float) -> np.ndarray:
        asm = Assembler(problem.dofs.n_dofs)
        term.conductance(state(problem, temp), asm)
        return asm.matrix().toarray()

    np.testing.assert_allclose(matrix(400.0), 2.0 * matrix(300.0), rtol=1e-13)
    np.testing.assert_allclose(matrix(350.0), 1.5 * matrix(300.0), rtol=1e-13)
    # evaluated at the integration points: a linear T field gives k varying in space
    s = state(problem)
    s.u[:] = 300.0 + 50.0 * problem.mesh.nodes[:, 0]  # 300 .. 400 K across x
    asm = Assembler(problem.dofs.n_dofs)
    term.conductance(s, asm)
    energy = s.u @ asm.matrix() @ s.u
    # integral of k(T) |grad T|^2 dA with k = 50 + 25 x, grad = 50, over 2 x 1
    assert energy == pytest.approx(50.0**2 * (50.0 * 2.0 + 25.0 * 2.0), rel=1e-12)


def test_two_regions_axisymmetric_and_batches() -> None:
    problem = hand_problem("T6")
    mesh = problem.mesh
    mesh.axisymmetric = True
    mesh.blocks[0].region[: mesh.n_elements // 2] = 2
    problem.regions[2] = RegionData(Material("other", 5.0, 1.0, 1.0), thickness=9.0)
    problem.cache.clear()
    batches = element_batches(problem)
    assert sorted(b.region_id for b in batches) == [1, 2]
    assert sum(b.conn.shape[0] for b in batches) == mesh.n_elements
    assert element_batches(problem, [2])[0].region.material.name == "other"
    assert element_batches(problem)[0] is batches[0]  # cached
    for b in batches:  # axisymmetric: g = 2 pi r, thickness ignored
        np.testing.assert_allclose(b.g, 2 * np.pi * b.geom.xgp[..., 0])
    volume = sum((b.g * b.geom.dV).sum() for b in batches)
    assert volume == pytest.approx(np.pi * 2.0**2 * 1.0, rel=1e-12)
    (right,) = facet_batches(problem, [2])
    assert (right.g * right.geom.dS).sum() == pytest.approx(2 * np.pi * 2.0 * 1.0, rel=1e-12)

    problem.regions.pop(2)
    problem.cache.clear()
    with pytest.raises(ModelError, match="region 2 has no material"):
        element_batches(problem)


def test_facet_batches_use_the_thickness_of_the_parent_region() -> None:
    problem = hand_problem("Q4", thickness=0.25)
    (bottom,) = facet_batches(problem, [1])
    np.testing.assert_array_equal(bottom.g, 0.25)
    assert (bottom.g * bottom.geom.dS).sum() == pytest.approx(0.25 * 2.0)
    assert bottom.dofs.shape == bottom.conn.shape
    assert facet_batches(problem, [99]) == []


# ----------------------------------------------------------------- CompiledProblem


@dataclass
class FakeConstraint:
    name: str
    idx: list
    vals: list
    is_time_dependent: bool = False

    def setup(self, problem) -> None:
        pass

    def values(self, t: float):
        return np.array(self.idx), np.array(self.vals) + t

    def breakpoints(self) -> list[float]:
        return [5.0]


def test_problem_flags_and_breakpoints() -> None:
    problem = hand_problem()
    assert problem.is_linear and not problem.is_time_dependent and problem.symmetric
    assert problem.breakpoints() == []

    class Odd(BaseTerm):
        is_linear = False
        is_time_dependent = True
        symmetric = False

        def breakpoints(self) -> list[float]:
            return [10.0, 2.0, 10.0]

    problem.terms.append(Odd("odd"))
    assert not problem.is_linear and problem.is_time_dependent and not problem.symmetric
    problem.constraints.append(FakeConstraint("c", [0], [1.0]))
    assert isinstance(problem.constraints[0], Constraint)
    assert problem.breakpoints() == [2.0, 5.0, 10.0]
    problem.terms.pop()
    assert not problem.is_time_dependent
    problem.constraints[0].is_time_dependent = True
    assert problem.is_time_dependent


def test_prescribed_merges_constraints_and_later_wins(caplog: pytest.LogCaptureFixture) -> None:
    problem = hand_problem()
    assert problem.prescribed(0.0)[0].size == 0
    problem.constraints += [
        FakeConstraint("first", [3, 1, 5], [30.0, 10.0, 50.0]),
        FakeConstraint("second", [5, 7], [55.0, 70.0]),
        FakeConstraint("same", [1], [10.0]),  # same value: no warning
    ]
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        idx, vals = problem.prescribed(0.0)
    np.testing.assert_array_equal(idx, [1, 3, 5, 7])
    np.testing.assert_array_equal(vals, [10.0, 30.0, 55.0, 70.0])
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "'second'" in warnings[0] and "'first'" in warnings[0] and "1 shared" in warnings[0]
    np.testing.assert_array_equal(problem.prescribed(2.0)[1], [12.0, 32.0, 57.0, 72.0])


# ----------------------------------------------------------------------------- compile


def plate_model() -> tuple[Model, object, object]:
    model = api.new_model()
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 0.4, 0.5, id="left")
    geo.rectangle(0.4, 0.0, 0.6, 0.5, id="right")
    model.mesh_settings.global_size = 0.1
    built = api.build(model)
    api.select_surfaces(model, built, "L", where=lambda s: s.center[0] < 0.4)
    api.select_surfaces(model, built, "R", where=lambda s: s.center[0] > 0.4)
    api.select_curves(model, built, "bottom", where=lambda c: abs(c.center[1]) < 1e-9)
    api.assign_region(model, "L", material="Copper (pure)", thickness=0.02)
    api.assign_region(model, "R", material="Silicon", thickness=0.01)
    return model, built, api.mesh(model, built)


def test_compile_builds_dofs_regions_and_conduction() -> None:
    model, built, mesh = plate_model()
    problem = compile_problem(model, built, mesh)
    assert problem.mesh is mesh and problem.model is model and problem.built is built
    assert problem.settings is model.solution
    assert problem.dofs.fields == ["T"] and problem.dofs.n_dofs == mesh.n_nodes
    assert [type(t) for t in problem.terms] == [ConductionTerm]
    assert problem.constraints == []
    assert problem.is_linear and not problem.is_time_dependent
    left, right = model.selections["L"].tags[0], model.selections["R"].tags[0]
    assert problem.regions[left].material.name == "Copper (pure)"
    assert (problem.regions[left].thickness, problem.regions[left].name) == (0.02, "L")
    assert problem.regions[right].material.name == "Silicon"

    asm = Assembler(problem.dofs.n_dofs)
    problem.terms[0].conductance(state(problem), asm)
    k = asm.matrix()
    assert abs(k - k.T).max() < 1e-12
    assert np.abs(k @ np.ones(mesh.n_nodes)).max() < 1e-10
    u = 300.0 + 100.0 * mesh.nodes[:, 1]  # grad = (0, 100)
    expected = 100.0**2 * (401.0 * 0.4 * 0.5 * 0.02 + 148.0 * 0.6 * 0.5 * 0.01)
    assert u @ k @ u == pytest.approx(expected, rel=1e-12)

    assert selection_tags(problem, "bottom", (1,)) == (1, model.selections["bottom"].tags)
    with pytest.raises(ModelError, match="unknown selection"):
        selection_tags(problem, "nope", (1,))
    with pytest.raises(ModelError, match="dimension 1 is needed"):
        selection_tags(problem, "L", (1,))


def test_compile_calls_registered_factories_for_active_bcs_only() -> None:
    """A load class registered with factories is compiled with no change to the compiler."""
    made: list[str] = []

    @dataclass
    class TestLoad(bcs.BoundaryCondition):
        value: Function

    class TestTerm(BaseTerm):
        is_time_dependent = True

        def __init__(self, bc: TestLoad) -> None:
            super().__init__(bc.name)
            self.bc = bc

        def setup(self, problem: CompiledProblem) -> None:
            made.append(f"setup:{self.name}")
            self.tags = selection_tags(problem, self.bc.selection, (1,))[1]

    class TestConstraint:
        is_time_dependent = False

        def __init__(self, bc: TestLoad) -> None:
            self.name = bc.name

        def setup(self, problem: CompiledProblem) -> None:
            made.append(f"constraint:{self.name}")

        def values(self, t: float):
            return np.array([0]), np.array([1.0])

        def breakpoints(self) -> list[float]:
            return []

    registry.register_bc("test_load", TestLoad, term_factory=lambda bc: [TestTerm(bc)])
    registry.set_bc_constraint_factory(TestLoad, TestConstraint)
    try:
        model, built, mesh = plate_model()
        model.bcs += [
            TestLoad("on", "bottom", 1.0),
            TestLoad("off", "bottom", 1.0, active=False),
            bcs.Adiabatic("adi", "bottom"),  # registered without factories: contributes nothing
        ]
        problem = compile_problem(model, built, mesh)
        assert [t.name for t in problem.terms] == ["conduction", "on"]
        assert [c.name for c in problem.constraints] == ["on"]
        assert made == ["setup:on", "constraint:on"]
        assert problem.terms[1].tags == model.selections["bottom"].tags
        assert problem.is_time_dependent

        model.bcs.append(TestLoad("bad", "missing-selection", 1.0))
        with pytest.raises(ModelError, match="bad: unknown selection 'missing-selection'"):
            compile_problem(model, built, mesh)
    finally:
        registry._CLASSES["bc"].pop("test_load")
        registry._BCS.pop("test_load")


def test_reregistering_a_bc_keeps_its_factories() -> None:
    info = registry.bc_info(bcs.Adiabatic)
    marker = object()
    info.form = marker
    registry.register_bc("adiabatic", bcs.Adiabatic)
    assert registry.bc_info("adiabatic").form is marker
    info.form = None


def test_compile_errors() -> None:
    model, built, mesh = plate_model()
    model.regions.pop()
    with pytest.raises(ModelError, match="has no material assigned"):
        compile_problem(model, built, mesh)

    model, built, mesh = plate_model()
    model.regions.append(RegionAssignment("L", "Silicon"))
    with pytest.raises(ModelError, match="assigned twice.*'L'"):
        compile_problem(model, built, mesh)

    model, built, mesh = plate_model()
    model.regions[0].material = "Unobtainium"
    with pytest.raises(ModelError, match="unknown material 'Unobtainium'"):
        compile_problem(model, built, mesh)

    model, built, mesh = plate_model()
    model.regions[0].selection = "bottom"
    with pytest.raises(ModelError, match="must contain entities of dimension 2"):
        compile_problem(model, built, mesh)

    model, built, mesh = plate_model()
    model.regions[0].selection = "nope"
    with pytest.raises(ModelError, match="unknown selection 'nope'"):
        compile_problem(model, built, mesh)

    model, built, mesh = plate_model()
    model.materials["Silicon"] = Material("Silicon", 1.0, 1.0, 1.0, k2=2.0)
    with pytest.raises(ModelError, match="orthotropic"):
        problem = compile_problem(model, built, mesh)
        problem.terms[0].conductance(state(problem), Assembler(problem.dofs.n_dofs))
