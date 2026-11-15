"""M3.3 — surface loads (Theory §2): total applied heat equals q times area."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, assemble, make_problem, make_state

from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Expression, Table
from thermalfea.model.bcs import Convection, HeatFlow, HeatFlux
from thermalfea.physics.surface_loads import ConvectionTerm, HeatFlowTerm, HeatFluxTerm
from thermalfea.solver.terms import Term

W, H, X0 = 2.0, 1.0, 0.5  # rectangle x in [0.5, 2.5], y in [0, 1]
SIDES = {"bottom": W, "top": W, "left": H, "right": H}
RADIUS = {"left": X0, "right": X0 + W}


def problem_with(bc, etype: str, axisymmetric: bool = False, thickness: float = 0.25, **kw):
    return make_problem(etype, origin=(X0, 0.0), thickness=thickness,
                        axisymmetric=axisymmetric, bcs=(bc,), **kw)


def area(side: str, axisymmetric: bool, thickness: float = 0.25) -> float:
    if not axisymmetric:
        return SIDES[side] * thickness
    if side in RADIUS:  # cylinder surface 2 pi r H
        return 2 * np.pi * RADIUS[side] * H
    return np.pi * ((X0 + W) ** 2 - X0**2)  # annulus


def run(problem, s=None):
    return assemble(problem, s or make_state(problem), [problem.terms[-1]])


# -------------------------------------------------------------------------------- flux


@pytest.mark.parametrize("axisymmetric", [False, True])
@pytest.mark.parametrize("side", list(SIDES))
@pytest.mark.parametrize("etype", TYPES)
def test_flux_total_equals_q_times_area(etype: str, side: str, axisymmetric: bool) -> None:
    q = 5000.0
    problem = problem_with(HeatFlux("flux", side, q=q), etype, axisymmetric)
    term = problem.terms[-1]
    assert isinstance(term, HeatFluxTerm) and isinstance(term, Term)
    assert term.is_linear and not term.is_time_dependent
    asm = run(problem)
    expected = q * area(side, axisymmetric)
    assert asm.vector().sum() == pytest.approx(expected, rel=1e-13)
    assert term.boundary_heat(make_state(problem)) == pytest.approx(expected, rel=1e-13)
    assert term.area() == pytest.approx(area(side, axisymmetric), rel=1e-13)
    assert asm.matrix().nnz == 0 and asm.tangent().nnz == 0 and not asm.residual().any()
    # only the nodes of that side are loaded
    loaded = np.flatnonzero(asm.vector())
    axis, value = {"bottom": (1, 0.0), "top": (1, H), "left": (0, X0), "right": (0, X0 + W)}[side]
    np.testing.assert_allclose(problem.mesh.nodes[loaded, axis], value)


@pytest.mark.parametrize("etype", TYPES)
def test_flux_function_of_position_time_and_temperature(etype: str) -> None:
    bc = HeatFlux("flux", "bottom", q=Expression("10*x + 100*t + T"))
    problem = problem_with(bc, etype, thickness=1.0)
    term = problem.terms[-1]
    assert not term.is_linear and term.is_time_dependent
    s = make_state(problem, 300.0, t=2.0)
    # integral over x in [0.5, 2.5] of (10 x + 200 + 300) = 10*3 + 500*2
    assert run(problem, s).vector().sum() == pytest.approx(1030.0, rel=1e-12)
    # consistent load vector: F . v = integral of q v along the edge, v = x
    x = problem.mesh.nodes[:, 0]
    linear = problem_with(HeatFlux("f", "bottom", q=Expression("3 + 2*x")), etype, thickness=1.0)
    f = run(linear).vector()
    exact = 3 * (2.5**2 - 0.5**2) / 2 + 2 * (2.5**3 - 0.5**3) / 3
    assert f @ x == pytest.approx(exact, rel=1e-12)


def test_flux_breakpoints() -> None:
    bc = HeatFlux("flux", "left", q=Table([0.0, 5.0], [0.0, 10.0], "t"))
    problem = problem_with(bc, "Q4")
    assert problem.terms[-1].breakpoints() == [0.0, 5.0]
    assert run(problem, make_state(problem, t=2.5)).vector().sum() == pytest.approx(5.0 * 0.25)


# --------------------------------------------------------------------------- heat flow


@pytest.mark.parametrize("axisymmetric", [False, True])
@pytest.mark.parametrize("etype", TYPES)
def test_heat_flow_totals_exactly_p(etype: str, axisymmetric: bool) -> None:
    problem = problem_with(HeatFlow("flow", "right", P=120.0), etype, axisymmetric)
    term = problem.terms[-1]
    assert isinstance(term, HeatFlowTerm) and term.is_linear
    f = run(problem).vector()
    assert f.sum() == pytest.approx(120.0, rel=1e-13)
    assert term.boundary_heat(make_state(problem)) == pytest.approx(120.0, rel=1e-13)
    # uniform flux q = P / A: identical to a HeatFlux of that value
    q = 120.0 / area("right", axisymmetric)
    same = problem_with(HeatFlux("flux", "right", q=q), etype, axisymmetric)
    np.testing.assert_allclose(f, run(same).vector(), rtol=1e-12, atol=1e-12)


def test_heat_flow_over_two_curves_is_shared_by_area() -> None:
    problem = make_problem("Q4", origin=(X0, 0.0), thickness=0.5)
    problem.named_entities["both"] = (1, [1, 2])  # bottom (length 2) and right (length 1)
    from thermalfea.solver.compile import attach

    attach(problem, HeatFlow("flow", "both", P=Table([0.0, 10.0], [0.0, 300.0], "t")))
    term = problem.terms[-1]
    assert term.is_time_dependent and term.breakpoints() == [0.0, 10.0]
    f = run(problem, make_state(problem, t=10.0)).vector()
    nodes = problem.mesh.nodes
    on_bottom = np.isclose(nodes[:, 1], 0.0) & ~np.isclose(nodes[:, 0], X0 + W)
    assert f.sum() == pytest.approx(300.0)
    # uniform flux q = P / A = 200 W/m^2: the bottom (2 m) carries 200 W, the right 100 W.
    # The shared corner node takes half of the last bottom element (0.5 m long): 25 W.
    assert f[on_bottom].sum() == pytest.approx(200.0 - 25.0, rel=1e-12)
    assert term.area() == pytest.approx(3.0 * 0.5)


# -------------------------------------------------------------------------- convection


@pytest.mark.parametrize("axisymmetric", [False, True])
@pytest.mark.parametrize("etype", TYPES)
def test_convection_matrix_and_vector(etype: str, axisymmetric: bool) -> None:
    h, t_inf = 750.0, 280.0
    problem = problem_with(Convection("conv", "top", h=h, T_inf=t_inf), etype, axisymmetric)
    term = problem.terms[-1]
    assert isinstance(term, ConvectionTerm)
    assert term.is_linear and term.symmetric and not term.is_time_dependent
    asm = run(problem)
    k, f = asm.matrix(), asm.vector()
    a = area("top", axisymmetric)
    assert k.sum() == pytest.approx(h * a, rel=1e-13)  # 1^T K 1 = integral of h
    assert f.sum() == pytest.approx(h * t_inf * a, rel=1e-13)
    assert abs(k - k.T).max() < 1e-12 * h
    # at T = T_inf the surface is in equilibrium: F - K T = 0
    u = np.full(problem.dofs.n_dofs, t_inf)
    np.testing.assert_allclose(f - k @ u, 0.0, atol=1e-9 * h * t_inf)
    assert term.boundary_heat(make_state(problem, t_inf)) == pytest.approx(0.0, abs=1e-9)
    # uniform wall temperature: heat leaving = h A (T - T_inf)
    s = make_state(problem, 400.0)
    assert term.boundary_heat(s) == pytest.approx(-h * a * (400.0 - t_inf), rel=1e-13)
    assert (f - k @ s.u).sum() == pytest.approx(term.boundary_heat(s), rel=1e-12)
    assert asm.tangent().nnz == 0 and not asm.residual().any()
    # positive semi-definite, and only the top nodes are coupled
    assert np.linalg.eigvalsh(k.toarray()).min() > -1e-9 * h
    rows = np.unique(k.nonzero()[0])
    np.testing.assert_allclose(problem.mesh.nodes[rows, 1], H)


@pytest.mark.parametrize("etype", TYPES)
def test_convection_heat_flow_matches_residual_for_a_varying_field(etype: str) -> None:
    problem = problem_with(Convection("conv", "right", h=100.0, T_inf=300.0), etype)
    term = problem.terms[-1]
    s = make_state(problem, 350.0 + 40.0 * problem.mesh.nodes[:, 1])  # 350 .. 390 along the edge
    asm = run(problem, s)
    expected = -100.0 * (370.0 - 300.0) * H * 0.25
    assert term.boundary_heat(s) == pytest.approx(expected, rel=1e-13)
    assert (asm.vector() - asm.matrix() @ s.u).sum() == pytest.approx(expected, rel=1e-12)


def test_convection_with_functions() -> None:
    bc = Convection("conv", "bottom", h=Expression("10 + T/100"),
                    T_inf=Table([0.0, 10.0], [300.0, 400.0], "t"))
    problem = problem_with(bc, "Q8", thickness=1.0)
    term = problem.terms[-1]
    assert not term.is_linear and term.is_time_dependent
    assert term.breakpoints() == [0.0, 10.0]
    assert not problem.is_linear
    s = make_state(problem, 500.0, t=5.0)  # h = 15, T_inf = 350
    asm = run(problem, s)
    assert asm.matrix().sum() == pytest.approx(15.0 * W, rel=1e-13)
    assert asm.vector().sum() == pytest.approx(15.0 * 350.0 * W, rel=1e-13)
    assert term.boundary_heat(s) == pytest.approx(-15.0 * 150.0 * W, rel=1e-13)
    linear = problem_with(Convection("c", "bottom", h=Expression("10 + x"), T_inf=300.0), "T6")
    assert linear.terms[-1].is_linear


# ------------------------------------------------------------------------------ errors


def test_errors() -> None:
    with pytest.raises(ModelError, match="cannot depend on temperature"):
        problem_with(HeatFlow("flow", "top", P=Expression("T")), "Q4")
    with pytest.raises(ModelError, match="flux: selection 'all' has dimension 2"):
        problem_with(HeatFlux("flux", "all", q=1.0), "Q4")
    with pytest.raises(ModelError, match="conv: unknown selection"):
        problem_with(Convection("conv", "nope", h=1.0, T_inf=300.0), "Q4")
    problem = make_problem("Q4")
    problem.named_entities["nowhere"] = (1, [77])
    from thermalfea.solver.compile import attach

    with pytest.raises(ModelError, match="contains no element edges"):
        attach(problem, HeatFlux("flux", "nowhere", q=1.0))
