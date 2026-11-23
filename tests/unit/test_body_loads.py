"""M3.2 — body loads (Theory §2)."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, assemble, make_problem, make_state

from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Expression, Table
from thermalfea.model.bcs import HeatGeneration, HeatPower
from thermalfea.physics.body_loads import HeatGenerationTerm, HeatPowerTerm
from thermalfea.solver.terms import Term

W, H = 2.0, 1.0


def load_vector(problem, s=None) -> np.ndarray:
    term = problem.terms[-1]
    return assemble(problem, s or make_state(problem), [term]).vector()


@pytest.mark.parametrize("etype", TYPES)
def test_uniform_generation_totals_q_times_volume(etype: str) -> None:
    problem = make_problem(etype, thickness=0.25, distortion=0.15,
                           bcs=(HeatGeneration("gen", "all", Q=1.0e6),))
    term = problem.terms[-1]
    assert isinstance(term, HeatGenerationTerm) and isinstance(term, Term)
    assert term.is_linear and not term.is_time_dependent and term.breakpoints() == []
    f = load_vector(problem)
    total = 1.0e6 * W * H * 0.25
    assert f.sum() == pytest.approx(total, rel=1e-13)
    assert term.boundary_heat(make_state(problem)) == pytest.approx(total, rel=1e-13)
    # a load contributes nothing to K, the tangent or the residual channel
    asm = assemble(problem, make_state(problem), [term])
    assert asm.matrix().nnz == 0 and asm.tangent().nnz == 0 and not asm.residual().any()


@pytest.mark.parametrize("etype", TYPES)
def test_axisymmetric_generation_uses_ring_volume(etype: str) -> None:
    problem = make_problem(etype, origin=(0.5, 0.0), axisymmetric=True, thickness=99.0,
                           bcs=(HeatGeneration("gen", "all", Q=2.0),))
    volume = np.pi * (2.5**2 - 0.5**2) * H
    assert load_vector(problem).sum() == pytest.approx(2.0 * volume, rel=1e-12)


@pytest.mark.parametrize("etype", TYPES)
def test_load_vector_is_consistent(etype: str) -> None:
    """F . v equals the integral of Q v for any field v the elements can represent."""
    problem = make_problem(etype, bcs=(HeatGeneration("gen", "all", Q=Expression("3 + 2*x")),))
    f = load_vector(problem)
    x, y = problem.mesh.nodes.T
    # integral of (3 + 2x) over 2 x 1 = 6 + 4 = 10; with v = y: (3 + 2x) y -> 10 * 0.5
    assert f.sum() == pytest.approx(10.0, rel=1e-12)
    assert f @ y == pytest.approx(5.0, rel=1e-12)
    assert f @ x == pytest.approx(3 * 2.0 + 2 * 8.0 / 3.0, rel=1e-12)


def test_generation_evaluated_with_t_x_y_and_temperature() -> None:
    bc = HeatGeneration("gen", "all", Q=Expression("100*t + 10*x + y + T"))
    problem = make_problem("Q8", bcs=(bc,))
    term = problem.terms[-1]
    assert not term.is_linear and term.is_time_dependent
    assert not problem.is_linear and problem.is_time_dependent
    s = make_state(problem, 300.0, t=2.0)
    # integral over 2 x 1 of (200 + 10x + y + 300) = 2*(500) + 10*2 + 1 = 1021
    assert load_vector(problem, s).sum() == pytest.approx(1021.0, rel=1e-12)
    # temperature is interpolated to the integration points: T = 300 + 50 x
    s = make_state(problem, 300.0 + 50.0 * problem.mesh.nodes[:, 0], t=0.0)
    assert load_vector(problem, s).sum() == pytest.approx(2 * 300 + 50 * 2 + 20 + 1, rel=1e-12)


def test_table_generation_breakpoints_and_time() -> None:
    bc = HeatGeneration("gen", "all", Q=Table([0.0, 10.0, 20.0], [0.0, 100.0, 100.0], "t"))
    problem = make_problem("T3", bcs=(bc,))
    term = problem.terms[-1]
    assert term.breakpoints() == [0.0, 10.0, 20.0] and problem.breakpoints() == [0.0, 10.0, 20.0]
    assert term.is_linear and term.is_time_dependent
    assert load_vector(problem, make_state(problem, t=5.0)).sum() == pytest.approx(50.0 * 2.0)


@pytest.mark.parametrize("axisymmetric", [False, True])
@pytest.mark.parametrize("etype", TYPES)
def test_heat_power_totals_exactly_p(etype: str, axisymmetric: bool) -> None:
    problem = make_problem(etype, origin=(0.5, 0.0), thickness=0.3, axisymmetric=axisymmetric,
                           distortion=0.15, bcs=(HeatPower("p", "all", P=750.0),))
    term = problem.terms[-1]
    assert isinstance(term, HeatPowerTerm) and term.is_linear
    f = load_vector(problem)
    assert f.sum() == pytest.approx(750.0, rel=1e-13)
    assert term.boundary_heat(make_state(problem)) == pytest.approx(750.0, rel=1e-13)
    if not axisymmetric:  # uniform Q = P / V: the same vector as a generation of P / V
        other = make_problem(etype, origin=(0.5, 0.0), thickness=0.3, distortion=0.15,
                             bcs=(HeatGeneration("g", "all", Q=750.0 / (W * H * 0.3)),))
        np.testing.assert_allclose(f, load_vector(other), rtol=1e-12, atol=1e-12)


def test_heat_power_of_time() -> None:
    bc = HeatPower("p", "all", P=Table([0.0, 10.0], [0.0, 500.0], "t"))
    problem = make_problem("Q4", bcs=(bc,))
    term = problem.terms[-1]
    assert term.is_time_dependent and term.breakpoints() == [0.0, 10.0]
    assert load_vector(problem, make_state(problem, t=4.0)).sum() == pytest.approx(200.0)


def test_errors() -> None:
    with pytest.raises(ModelError, match="cannot depend on temperature"):
        make_problem("Q4", bcs=(HeatPower("p", "all", P=Expression("T")),))
    with pytest.raises(ModelError, match="gen: selection 'bottom' has dimension 1"):
        make_problem("Q4", bcs=(HeatGeneration("gen", "bottom", Q=1.0),))
    with pytest.raises(ModelError, match="gen: unknown selection 'nope'"):
        make_problem("Q4", bcs=(HeatGeneration("gen", "nope", Q=1.0),))
    problem = make_problem("Q4")
    problem.named_entities["elsewhere"] = (2, [42])
    from thermalfea.solver.compile import attach

    with pytest.raises(ModelError, match="contains no elements"):
        attach(problem, HeatGeneration("gen", "elsewhere", Q=1.0))
    n_terms = len(problem.terms)
    attach(problem, HeatGeneration("off", "all", Q=1.0, active=False))
    assert len(problem.terms) == n_terms


def test_total_power_refuses_a_position_dependent_function() -> None:
    with pytest.raises(ModelError, match="spread uniformly.*time only.*Heat Generation"):
        make_problem("Q4", bcs=(HeatPower("p", "all", P=Expression("100 + x")),))
    make_problem("Q4", bcs=(HeatPower("p", "all", P=Expression("100 + t")),))  # time is fine
