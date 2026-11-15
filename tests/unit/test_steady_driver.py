"""M3.7 — nonlinear steady driver (Theory §5)."""

from __future__ import annotations

import logging

import numpy as np
import pytest
from handmade import TYPES, make_problem
from scipy.optimize import brentq
from scipy.sparse import csr_matrix

from thermalfea.core.constants import STEFAN_BOLTZMANN as SIGMA
from thermalfea.core.errors import ConvergenceError, SolverError
from thermalfea.core.functions import Expression
from thermalfea.model.bcs import (
    Convection,
    FixedTemperature,
    HeatFlux,
    HeatGeneration,
    RadiationAmbient,
)
from thermalfea.model.settings import SolutionSettings
from thermalfea.solver import steady
from thermalfea.solver.nonlinear import ARMIJO, S_MIN, Assembled, NewtonResult, newton
from thermalfea.solver.steady import solve_steady, steady_solution

L = 0.1


def strip(etype: str, n: int, bcs, **kw):
    """The '1D' model of the verification cases: a strip L x L/10, long sides adiabatic."""
    return make_problem(etype, size=(L, L / 10), cells=(n, 1), bcs=bcs, **kw)


def scalar(k=0.0, f=0.0, extra=lambda x: 0.0, tangent_extra=lambda x: 0.0):
    """assemble_fn of a one-DOF problem: r(x) = f - k x + extra(x), tangent k + tangent_extra(x)."""

    def assemble(u: np.ndarray) -> Assembled:
        x = float(u[0])
        return Assembled(
            K=csr_matrix(np.array([[float(k)]])), F=np.array([float(f)]),
            K_tan=csr_matrix(np.array([[tangent_extra(x)]])), r_extra=np.array([extra(x)]),
        )

    return assemble


NO_FIXED = (np.empty(0, dtype=int), np.empty(0))


# ------------------------------------------------------------------- newton, directly


def test_newton_converges_quadratically_and_records_history(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # radiative balance of a lumped body: 1000 W in, eps sigma A T^4 out
    c = 0.8 * SIGMA
    assemble = scalar(f=1000.0, extra=lambda x: -c * x**4, tangent_extra=lambda x: 4 * c * x**3)
    exact = (1000.0 / c) ** 0.25
    with caplog.at_level(logging.INFO, logger="thermalfea.solver.nonlinear"):
        result = newton(assemble, np.array([500.0]), NO_FIXED, SolutionSettings())
    assert isinstance(result, NewtonResult) and result.converged
    assert result.T[0] == pytest.approx(exact, rel=1e-12)
    assert 3 <= result.iterations <= 8
    assert len(result.history) == result.iterations
    assert [h.iteration for h in result.history] == list(range(1, result.iterations + 1))
    assert all(h.step == 1.0 for h in result.history)
    assert result.history[-1].max_dT <= 1e-4
    assert result.residual == result.history[-1].residual <= 1e-6 * result.reference
    residuals = [h.residual for h in result.history]
    assert residuals == sorted(residuals, reverse=True)
    # one log line per iteration with the residual, max dT and the line-search factor
    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == result.iterations
    assert all("residual" in ln and "max dT" in ln and "line-search factor" in ln for ln in lines)
    assert result.system is not None
    assert abs(result.system.residual(result.T)[0]) == pytest.approx(result.residual)


def test_convergence_needs_both_the_residual_and_the_step_tests() -> None:
    # exact tangent on a linear residual: solved in one step, but that step is large, so
    # the temperature-change test fails and a second iteration confirms
    assemble = scalar(k=1.0, f=400.0)
    result = newton(assemble, np.array([300.0]), NO_FIXED, SolutionSettings())
    assert result.iterations == 2
    assert result.history[0].max_dT == pytest.approx(100.0) and result.history[0].residual == 0.0
    assert result.history[1].max_dT == 0.0
    # with a loose ttol the first iteration is enough
    loose = newton(assemble, np.array([300.0]), NO_FIXED, SolutionSettings(ttol=1e3))
    assert loose.iterations == 1


def test_iteration_limit_raises() -> None:
    # tangent ten times too stiff: linear convergence, ratio 0.9 per iteration
    assemble = scalar(k=1.0, f=400.0, tangent_extra=lambda x: 9.0)
    with pytest.raises(ConvergenceError, match="no convergence in 30 iterations"):
        newton(assemble, np.array([300.0]), NO_FIXED, SolutionSettings())
    result = newton(assemble, np.array([300.0]), NO_FIXED, SolutionSettings(max_iterations=400))
    assert result.T[0] == pytest.approx(400.0, abs=1e-2) and result.iterations > 30


def test_line_search_rescues_a_diverging_newton_step() -> None:
    # r = -atan(x - 500): plain Newton diverges when |x - 500| > 1.39
    def residual(x: float) -> float:
        return -np.arctan(x - 500.0)

    def tangent(x: float) -> float:
        return 1.0 / (1.0 + (x - 500.0) ** 2)

    # written as F = 1 W balanced by a residual-only part, so that F_ref = 1 W
    assemble = scalar(f=1.0, extra=lambda x: residual(x) - 1.0, tangent_extra=tangent)
    result = newton(assemble, np.array([503.0]), NO_FIXED, SolutionSettings())
    assert result.T[0] == pytest.approx(500.0, abs=1e-6)
    steps = [h.step for h in result.history]
    assert min(steps) < 1.0 and steps[-1] == 1.0
    assert all(s in (1.0, 0.5, 0.25, 0.125, 0.0625, 0.03125) for s in steps)
    # sufficient decrease held at every accepted step
    norms = [abs(residual(503.0))] + [h.residual for h in result.history]
    for before, after, s in zip(norms, norms[1:], steps, strict=False):
        assert after <= (1.0 - ARMIJO * s) * before or s == S_MIN
    with pytest.raises(ConvergenceError):
        newton(assemble, np.array([503.0]), NO_FIXED, SolutionSettings(line_search=False))


def test_non_positive_temperature_halves_the_step() -> None:
    # tangent half the true one: the full step from 1000 K lands at -200 K
    assemble = scalar(k=1.0, f=400.0, tangent_extra=lambda x: -0.5)
    result = newton(assemble, np.array([1000.0]), NO_FIXED, SolutionSettings())
    assert result.history[0].step == 0.5
    assert result.T[0] == pytest.approx(400.0)
    assert all(h.residual >= 0 for h in result.history)
    # the same happens with the line search switched off
    off = newton(assemble, np.array([1000.0]), NO_FIXED, SolutionSettings(line_search=False))
    assert off.history[0].step == 0.5
    # a hopeless tangent: even the shortest step goes below zero
    hopeless = scalar(k=1.0, f=400.0, tangent_extra=lambda x: -0.99)
    with pytest.raises(ConvergenceError, match="zero or negative"):
        newton(hopeless, np.array([1000.0]), NO_FIXED, SolutionSettings())


def test_prescribed_dofs_are_set_and_never_moved() -> None:
    # two DOFs coupled by a conductance of 2 W/K; DOF 0 prescribed at 350 K; DOF 1 radiates
    c = 1e-8

    def assemble(u: np.ndarray) -> Assembled:
        k = csr_matrix(2.0 * np.array([[1.0, -1.0], [-1.0, 1.0]]))
        return Assembled(
            K=k, F=np.zeros(2),
            K_tan=csr_matrix(np.diag([0.0, 4 * c * u[1] ** 3])),
            r_extra=np.array([0.0, -c * (u[1] ** 4 - 300.0**4)]),
        )

    result = newton(assemble, np.array([999.0, 320.0]), (np.array([0]), np.array([350.0])),
                    SolutionSettings())
    assert result.T[0] == 350.0
    t1 = result.T[1]
    assert 2.0 * (350.0 - t1) == pytest.approx(c * (t1**4 - 300.0**4), rel=1e-9)
    assert result.reference >= 2.0 * (350.0 - t1)  # F_ref includes the reaction at DOF 0


# ----------------------------------------------------------------------- steady driver


@pytest.mark.parametrize("etype", TYPES)
def test_linear_problem_takes_exactly_one_solve(
    etype: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    h, t0, t_inf, k = 100.0, 400.0, 300.0, 50.0
    problem = strip(etype, 10, (
        FixedTemperature("hot", "left", T=t0),
        Convection("conv", "right", h=h, T_inf=t_inf),
    ))
    assert problem.is_linear
    calls = []
    original = steady.assemble
    monkeypatch.setattr(steady, "assemble", lambda *a, **kw: calls.append(1) or original(*a, **kw))
    with caplog.at_level(logging.INFO, logger="thermalfea"):
        result = steady_solution(problem)
    assert len(calls) == 1 and result.iterations == 1 and result.converged
    assert result.history == []  # no iteration
    assert any("one solve" in r.getMessage() for r in caplog.records)
    # V-02: T(L) = T_inf + (T0 - T_inf) / (1 + h L / k)
    x = problem.mesh.nodes[:, 0]
    t_end = t_inf + (t0 - t_inf) / (1.0 + h * L / k)
    exact = t0 + (t_end - t0) * x / L
    assert np.max(np.abs(result.T - exact) / exact) < 1e-10
    assert result.residual <= 1e-9 * result.reference
    np.testing.assert_array_equal(solve_steady(problem), result.T)
    assert isinstance(solve_steady(problem), np.ndarray)


@pytest.mark.parametrize("etype", TYPES)
def test_temperature_dependent_conductivity_kirchhoff(etype: str) -> None:
    """V-13: k = k0 (1 + beta (T - 300)); U = (T-300) + beta (T-300)^2 / 2 is linear in x."""
    k0, beta = 50.0, 0.01
    problem = strip(etype, 40, (
        FixedTemperature("hot", "left", T=400.0), FixedTemperature("cold", "right", T=300.0),
    ), k=Expression(f"{k0}*(1 + {beta}*(T - 300))"))
    assert not problem.is_linear
    result = steady_solution(problem)
    assert result.converged and 2 <= result.iterations <= 15
    x = problem.mesh.nodes[:, 0]
    u = (100.0 + beta * 100.0**2 / 2.0) * (1.0 - x / L)
    exact = 300.0 + (-1.0 + np.sqrt(1.0 + 2.0 * beta * u)) / beta
    assert np.max(np.abs(result.T - exact) / exact) < 1e-4
    assert result.residual <= 1e-6 * result.reference


@pytest.mark.parametrize("etype", TYPES)
def test_radiating_bar(etype: str) -> None:
    """V-14 (NAFEMS T2): k (1000 - T) / L = eps sigma (T^4 - 300^4); target 927.0 K."""
    k, eps = 55.6, 0.98
    problem = strip(etype, 10, (
        FixedTemperature("hot", "left", T=1000.0),
        RadiationAmbient("rad", "right", emissivity=eps, T_inf=300.0),
    ), k=k)
    result = steady_solution(problem)
    root = brentq(lambda t: k * (1000.0 - t) / L - eps * SIGMA * (t**4 - 300.0**4), 300.0, 1000.0)
    end = result.T[np.isclose(problem.mesh.nodes[:, 0], L)]
    np.testing.assert_allclose(end, root, rtol=1e-9)
    assert abs(root - 927.0) < 0.1
    assert np.all(np.abs(end - 927.0) < 0.1)
    assert result.converged and result.iterations <= 10
    assert all(h.step == 1.0 for h in result.history)


def test_nonlinear_convection_coefficient_modified_newton() -> None:
    """h(T) = 5 + 0.05 (T - 300): the tangent omits dh/dT, yet the iteration converges."""
    k = 50.0
    problem = strip("Q4", 10, (
        FixedTemperature("hot", "left", T=400.0),
        Convection("conv", "right", h=Expression("5 + 0.05*(T - 300)"), T_inf=300.0),
    ), k=k)
    result = steady_solution(problem)
    ts = brentq(lambda t: k * (400.0 - t) / L - (5 + 0.05 * (t - 300.0)) * (t - 300.0), 300, 400)
    end = result.T[np.isclose(problem.mesh.nodes[:, 0], L)]
    np.testing.assert_allclose(end, ts, rtol=1e-8)
    assert result.converged


def test_temperature_dependent_generation_and_flux() -> None:
    problem = strip("T6", 10, (
        FixedTemperature("cold", "right", T=300.0),
        HeatFlux("flux", "left", q=5000.0),
        HeatGeneration("gen", "all", Q=Expression("1e5*(1 - (T - 300)/1000)")),
    ))
    result = steady_solution(problem)
    assert result.converged and not problem.is_linear
    assert result.T.min() == pytest.approx(300.0) and result.T.max() > 310.0
    assert result.residual <= 1e-6 * result.reference


def test_starting_temperature() -> None:
    problem = strip("Q4", 4, (FixedTemperature("a", "left", T=400.0),
                              FixedTemperature("b", "right", T=300.0)))
    _, values = problem.prescribed(0.0)
    np.testing.assert_array_equal(steady.starting_temperature(problem, values), 350.0)
    np.testing.assert_array_equal(
        steady.starting_temperature(problem, np.empty(0)), steady.DEFAULT_START_TEMPERATURE
    )
    # an explicit T0 is honoured and gives the same answer
    rad = strip("Q4", 4, (FixedTemperature("hot", "left", T=1000.0),
                          RadiationAmbient("rad", "right", emissivity=0.98, T_inf=300.0)), k=55.6)
    a = steady_solution(rad).T
    b = steady_solution(rad, T0=np.full(rad.dofs.n_dofs, 500.0)).T
    np.testing.assert_allclose(a, b, rtol=1e-7)


def test_no_temperature_reference_is_a_solver_error() -> None:
    problem = strip("Q4", 4, (HeatFlux("in", "left", q=100.0), HeatFlux("out", "right", q=-100.0)))
    with pytest.raises(SolverError, match="singular"):
        solve_steady(problem)


def test_radiation_only_reference_from_a_poor_start_converges() -> None:
    """Flux in, radiation out, no prescribed temperature: start at 293 K, end near 1100 K."""
    q, eps = 5.0e4, 0.8
    problem = strip("Q4", 4, (
        HeatFlux("in", "left", q=q),
        RadiationAmbient("rad", "right", emissivity=eps, T_inf=300.0),
    ))
    result = steady_solution(problem)
    surface = (q / (eps * SIGMA) + 300.0**4) ** 0.25
    end = result.T[np.isclose(problem.mesh.nodes[:, 0], L)]
    np.testing.assert_allclose(end, surface, rtol=1e-8)
    hot = result.T[np.isclose(problem.mesh.nodes[:, 0], 0.0)]
    np.testing.assert_allclose(hot, surface + q * L / 50.0, rtol=1e-8)
    assert result.T.min() > 0.0
