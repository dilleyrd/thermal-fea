"""M4.1 — capacitance, consistent and lumped (Theory §2, §3)."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, make_problem, make_state

from thermalfea import api
from thermalfea.core.functions import Expression
from thermalfea.core.registry import element
from thermalfea.physics.capacitance import CapacitanceTerm, capacitance, lump
from thermalfea.physics.conduction import ConductionTerm
from thermalfea.physics.kernel import geometry, gfactor
from thermalfea.solver.assembler import Assembler
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.terms import Term

RHO, CP = 7800.0, 500.0
W, H, X0 = 2.0, 1.0, 0.5


def assemble_c(problem, lumped: bool, u=300.0) -> np.ndarray:
    term = CapacitanceTerm(lumped=lumped)
    term.setup(problem)
    asm = Assembler(problem.dofs.n_dofs)
    term.capacitance(make_state(problem, u), asm)
    assert asm.vector().sum() == 0.0 and asm.tangent().nnz == 0
    return asm.matrix().toarray()


@pytest.mark.parametrize("axisymmetric", [False, True])
@pytest.mark.parametrize("lumped", [False, True])
@pytest.mark.parametrize("etype", TYPES)
def test_total_equals_integral_of_rho_c_g(etype: str, lumped: bool, axisymmetric: bool) -> None:
    problem = make_problem(etype, origin=(X0, 0.0), thickness=0.25, axisymmetric=axisymmetric,
                           distortion=0.15)
    c = assemble_c(problem, lumped)
    volume = np.pi * ((X0 + W) ** 2 - X0**2) * H if axisymmetric else W * H * 0.25
    assert c.sum() == pytest.approx(RHO * CP * volume, rel=1e-12)
    np.testing.assert_allclose(c, c.T, atol=1e-9 * c.max())
    if lumped:
        assert np.count_nonzero(c - np.diag(np.diag(c))) == 0  # diagonal
        assert np.all(np.diag(c) > 0.0)  # and positive
    else:
        assert np.count_nonzero(c - np.diag(np.diag(c))) > 0
        assert np.linalg.eigvalsh(c).min() > 0.0  # positive definite


@pytest.mark.parametrize("etype", TYPES)
def test_element_matrices(etype: str) -> None:
    problem = make_problem(etype, distortion=0.15)
    (block,) = problem.mesh.blocks
    geom = geometry(block, problem.mesh.nodes)
    g = gfactor(geom.xgp, False, 1.0, problem.mesh.dim)
    rho_c = np.full(geom.dV.shape, RHO * CP)
    ce = capacitance(geom, rho_c, g)
    et = element(etype)
    assert ce.shape == (block.conn.shape[0], et.n_nodes, et.n_nodes)
    area = geom.dV.sum(axis=1)
    np.testing.assert_allclose(ce.sum(axis=(1, 2)), RHO * CP * area, rtol=1e-13)
    np.testing.assert_allclose(ce, np.swapaxes(ce, 1, 2), atol=1e-9)

    lumped = lump(ce, et.order)
    assert lumped.shape == ce.shape
    diagonal = np.einsum("enn->en", lumped)
    np.testing.assert_allclose(diagonal.sum(axis=1), RHO * CP * area, rtol=1e-13)  # same total
    assert np.all(diagonal > 0.0)
    off = lumped.copy()
    off[:, np.arange(et.n_nodes), np.arange(et.n_nodes)] = 0.0
    assert not off.any()
    if et.order == 1:  # row-sum
        np.testing.assert_allclose(diagonal, ce.sum(axis=2), rtol=1e-14)
    else:  # HRZ: proportional to the consistent diagonal
        own = np.einsum("enn->en", ce)
        ratio = diagonal / own
        np.testing.assert_allclose(ratio, np.broadcast_to(ratio[:, :1], ratio.shape), rtol=1e-13)
        # why row-sum is never used here: it gives zero corner terms for a straight-sided
        # quadratic triangle and negative ones for a quadratic quadrilateral
        straight = make_problem(etype)
        (sblock,) = straight.mesh.blocks
        sgeom = geometry(sblock, straight.mesh.nodes)
        row_sum = capacitance(sgeom, np.ones(sgeom.dV.shape), np.ones(sgeom.dV.shape)).sum(axis=2)
        corners = row_sum[:, : len(et.facets)]
        assert np.all(corners < 1e-12 * row_sum.max())
        assert np.all(np.einsum("enn->en", lump(ce, et.order)) > 0.0)  # HRZ stays positive


def test_unit_square_q4_consistent_matrix_is_the_textbook_one() -> None:
    problem = make_problem("Q4", size=(1.0, 1.0), cells=(1, 1), rho=36.0, cp=1.0)
    c = assemble_c(problem, lumped=False)
    nodes = problem.mesh.nodes
    order = [int(np.argmin(np.linalg.norm(nodes - p, axis=1)))
             for p in ([0, 0], [1, 0], [1, 1], [0, 1])]
    expected = np.array([[4, 2, 1, 2], [2, 4, 2, 1], [1, 2, 4, 2], [2, 1, 2, 4]], dtype=float)
    np.testing.assert_allclose(c[np.ix_(order, order)], expected, rtol=1e-13)
    np.testing.assert_allclose(np.diag(assemble_c(problem, lumped=True)), 9.0)


def test_t3_lumped_is_a_third_of_the_element_mass_per_node() -> None:
    problem = make_problem("T3", size=(1.0, 1.0), cells=(1, 1), rho=6.0, cp=1.0)
    c = assemble_c(problem, lumped=True)
    # two triangles of area 1/2: the two shared corners get 2 * (3/3), the others 1
    assert sorted(np.diag(c)) == pytest.approx([1.0, 1.0, 2.0, 2.0])


def test_rho_c_at_the_state_temperature() -> None:
    problem = make_problem("Q8", rho=Expression("8000 - T"), cp=Expression("400 + T"))
    term = CapacitanceTerm()
    term.setup(problem)
    assert isinstance(term, Term) and not term.is_linear and term.symmetric
    assert assemble_c(problem, False, 300.0).sum() == pytest.approx(7700.0 * 700.0 * W * H)
    assert assemble_c(problem, True, 500.0).sum() == pytest.approx(7500.0 * 900.0 * W * H)
    constant = CapacitanceTerm()
    constant.setup(make_problem("Q8"))
    assert constant.is_linear and not constant.is_time_dependent


def test_capacitance_term_only_adds_to_c() -> None:
    problem = make_problem("T6")
    term = CapacitanceTerm()
    term.setup(problem)
    s = make_state(problem)
    asm = Assembler(problem.dofs.n_dofs)
    term.conductance(s, asm)
    term.load(s, asm)
    assert asm.matrix().nnz == 0 and not asm.vector().any()
    assert term.boundary_heat(s) is None and term.breakpoints() == []


def test_compile_adds_capacitance_for_transient_models_only() -> None:
    model = api.new_model()
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 1.0)
    model.mesh_settings.global_size = 0.25
    built = api.build(model)
    api.assign_region(model, "all", material="Copper (pure)")
    mesh = api.mesh(model, built)
    assert [type(t) for t in compile_problem(model, built, mesh).terms] == [ConductionTerm]
    model.solution.kind = "transient"
    model.solution.lumped_capacitance = True
    problem = compile_problem(model, built, mesh)
    assert [type(t) for t in problem.terms] == [ConductionTerm, CapacitanceTerm]
    assert problem.terms[1].lumped is True
    asm = Assembler(problem.dofs.n_dofs)
    problem.terms[1].capacitance(make_state(problem), asm)
    assert asm.matrix().sum() == pytest.approx(8933.0 * 385.0 * 1.0)
    model.solution.lumped_capacitance = False
    assert compile_problem(model, built, mesh).terms[1].lumped is False
