"""M4.3 — automatic time stepping (Theory §6.1).

The controller is tested alone with scripted error sequences; V-17 and V-18 exercise it
inside the transient driver.
"""

from __future__ import annotations

import logging
from math import erf, sqrt

import numpy as np
import pytest
from handmade import TYPES, make_problem
from scipy.optimize import brentq

from thermalfea import api
from thermalfea.core.errors import ConvergenceError, ModelError
from thermalfea.core.functions import Table
from thermalfea.model.bcs import Convection, FixedTemperature, HeatGeneration, RadiationAmbient
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics import timescales
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.timestep import StepController, error_estimate
from thermalfea.solver.transient import mandatory_times, solve_transient

RHO, CP, K = 7800.0, 500.0, 50.0
ALPHA = K / (RHO * CP)


def controller(dt0: float = 1.0, mandatory=(), t0: float = 0.0, **settings) -> StepController:
    settings = {"kind": "transient", "end_time": 100.0, **settings}
    return StepController(SolutionSettings(**settings), t0, mandatory, dt0)


def run(c: StepController, errors: list, changes: list | None = None) -> list[tuple]:
    """Feed scripted errors to the controller; return (dt tried, accepted) per attempt."""
    log = []
    for i, e in enumerate(errors):
        dt = c.propose()
        log.append((dt, c.accept(e, None if changes is None else changes[i])))
    return log


# ------------------------------------------------------------------------ error measure


def test_error_estimate() -> None:
    t_prev, t_n = np.array([300.0, 300.0]), np.array([310.0, 320.0])
    # predictor with dt = dt_prev: T_n + (T_n - T_prev) = [320, 340]
    assert error_estimate(np.array([320.0, 340.0]), t_n, t_prev, 2.0, 2.0) == 0.0
    e = error_estimate(np.array([318.0, 340.0]), t_n, t_prev, 2.0, 2.0)
    assert e == pytest.approx(2.0 / 22.0)  # |error|_inf / (max - min of the new solution)
    # dt / dt_prev scales the extrapolation: half a step predicts [315, 330]
    assert error_estimate(np.array([315.0, 330.0]), t_n, t_prev, 1.0, 2.0) == 0.0
    # the temperature range has a floor of 1 K
    flat = error_estimate(np.array([320.5, 320.5]), t_n, t_n, 1.0, 1.0)
    assert flat == pytest.approx(10.5 / 1.0)
    # no previous step: no estimate
    assert error_estimate(t_n, t_n, None, 1.0, None) is None
    assert error_estimate(t_n, t_n, t_prev, 1.0, None) is None


# ---------------------------------------------------------------------- the controller


def test_growth_and_shrink_follow_the_formula() -> None:
    c = controller(dt0=1.0, time_tol=0.02)
    assert c.propose() == 1.0
    assert c.accept(None) and c.t == 1.0 and c.dt == 1.0  # first step: no estimate, no change
    # e = tol: factor 0.9 sqrt(1) = 0.9
    assert c.propose() == 1.0 and c.accept(0.02)
    assert c.dt == pytest.approx(0.9)
    # e = tol / 4: 0.9 * 2 = 1.8
    c.propose()
    c.accept(0.005)
    assert c.dt == pytest.approx(0.9 * 1.8)
    # tiny error: growth is capped at 2
    c.propose()
    c.accept(1e-9)
    assert c.dt == pytest.approx(0.9 * 1.8 * 2.0)
    # zero error: also 2
    c.propose()
    c.accept(0.0)
    assert c.dt == pytest.approx(0.9 * 1.8 * 4.0)
    # e = 4 tol exactly is still accepted; the factor 0.9 sqrt(1/4) = 0.45 is clipped to 0.5
    before = c.dt
    c.propose()
    assert c.accept(0.08) is True
    assert c.dt == pytest.approx(0.5 * before)
    assert (c.accepted, c.rejected) == (6, 0)


def test_step_is_rejected_and_halved_when_the_error_exceeds_four_tol() -> None:
    c = controller(dt0=8.0, time_tol=0.02)
    log = run(c, [None, 0.0801, 0.2, 0.01])
    assert log[0] == (8.0, True)
    assert log[1] == (8.0, False)  # e > 4 tol: rejected, time does not advance
    assert log[2] == (4.0, False)  # halved, rejected again
    assert log[3] == (2.0, True)  # halved again, now accepted
    assert c.t == pytest.approx(10.0) and (c.accepted, c.rejected) == (2, 2)
    assert c.dt == pytest.approx(2.0 * 0.9 * sqrt(2.0))


def test_clamped_to_dt_min_and_dt_max() -> None:
    c = controller(dt0=1.0, dt_max=3.0, dt_min=0.5)
    run(c, [None, 0.0, 0.0, 0.0])
    assert c.dt == 3.0  # 1 -> 2 -> 4 clamped to 3
    c2 = controller(dt0=1.0, dt_min=0.4)
    assert run(c2, [None, 1.0, 1.0, 1.0]) == [(1.0, True), (1.0, False), (0.5, False), (0.4, True)]
    # at the minimum the step is accepted even though it is inaccurate (with a warning)
    assert c2.dt == 0.4
    assert controller(dt0=100.0, dt_max=2.0).propose() == 2.0
    assert controller(dt0=1e-6, dt_min=1e-3).propose() == 1e-3


def test_warning_when_accepting_at_the_minimum_step(caplog: pytest.LogCaptureFixture) -> None:
    c = controller(dt0=1.0, dt_min=1.0)
    c.propose()
    c.accept(None)
    c.propose()
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        assert c.accept(5.0) is True
    assert any("minimum" in r.getMessage() for r in caplog.records)


def test_steps_land_exactly_on_mandatory_times() -> None:
    c = controller(dt0=4.0, mandatory=[10.0, 25.0, 25.0, 250.0, -5.0, 0.0], end_time=30.0)
    assert c.mandatory == [10.0, 25.0, 30.0]  # sorted, distinct, inside (t0, end]; end added
    times = []
    while not c.finished:
        c.propose()
        c.accept(0.02 * 0.81)  # 0.9 sqrt(tol / e) = 1: the step stays 4
        times.append(c.t)
    assert times == pytest.approx([4.0, 8.0, 10.0, 14.0, 18.0, 22.0, 25.0, 29.0, 30.0])
    assert times[2] == 10.0 and times[6] == 25.0 and times[-1] == 30.0  # exactly
    assert c.finished and c.next_mandatory == 30.0


def test_a_step_cut_short_for_a_mandatory_time_does_not_shrink_the_next_one() -> None:
    c = controller(dt0=4.0, mandatory=[5.0], end_time=100.0)
    assert run(c, [None, 0.0]) == [(4.0, True), (1.0, True)]  # second step shortened to 1
    assert c.t == 5.0
    assert c.propose() == 4.0  # back to the step it wanted, not 2 * 1


def test_newton_failure_quarters_the_step_and_raises_below_dt_min() -> None:
    c = controller(dt0=16.0, dt_min=0.5)
    assert c.propose() == 16.0
    c.newton_failed()
    assert c.propose() == 4.0 and c.t == 0.0
    c.newton_failed()
    assert c.propose() == 1.0
    with pytest.raises(ConvergenceError, match="below the minimum"):
        c.newton_failed()  # 0.25 < dt_min
    assert c.newton_failures == 3
    fixed = controller(dt0=1.0, auto_timestep=False)
    fixed.propose()
    with pytest.raises(ConvergenceError, match="failed at t = 0"):
        fixed.newton_failed()


def test_max_dt_per_step_limits_the_change() -> None:
    c = controller(dt0=10.0, max_dT_per_step=5.0)
    # a change of 20 K with a 5 K limit: rejected; next step 10 * 0.9 * 5/20 = 2.25
    assert run(c, [None], [20.0]) == [(10.0, False)]
    assert c.propose() == pytest.approx(2.25)
    assert c.accept(None, 4.5) is True  # within the limit
    # the next step may not grow beyond dt * limit / change, even with no error
    c.propose()
    c.accept(0.0, 4.5)
    assert c.dt == pytest.approx(2.25 * 5.0 / 4.5)
    assert c.rejected == 1


def test_fixed_step_mode_ignores_errors_but_lands_on_mandatory_times() -> None:
    c = controller(dt0=3.0, mandatory=[7.0], end_time=10.0, auto_timestep=False)
    times = []
    while not c.finished:
        c.propose()
        assert c.accept(99.0, 1e9)
        times.append(c.t)
    assert times == [3.0, 6.0, 7.0, 10.0]
    assert c.rejected == 0


def test_bad_arguments() -> None:
    with pytest.raises(ModelError, match="end time"):
        controller(t0=100.0)
    with pytest.raises(ModelError, match="positive"):
        controller(dt0=0.0)


def test_start_time_other_than_zero() -> None:
    c = controller(dt0=2.0, t0=50.0, mandatory=[40.0, 53.0], end_time=60.0)
    assert c.mandatory == [53.0, 60.0]
    assert c.propose() == 2.0 and c.accept(None) and c.t == 52.0
    assert c.propose() == pytest.approx(1.0)


# -------------------------------------------------------- suggestion and oscillation


def transient(problem, lumped: bool = False, **settings):
    term = CapacitanceTerm(lumped=lumped)
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(kind="transient", **settings)
    problem.suggest_dt = lambda T: timescales.suggested_dt(problem, T)
    problem.check_dt = lambda T, dt: timescales.warn_if_oscillation_likely(problem, T, dt, lumped)
    return problem


@pytest.mark.parametrize("etype", TYPES)
def test_suggested_initial_step(etype: str) -> None:
    """dt0 = h_min^2 / (4 alpha_max), h_min the smallest element edge."""
    problem = make_problem(etype, size=(0.1, 0.02), cells=(20, 2))  # edges 0.005 x 0.01
    u = np.full(problem.dofs.n_dofs, 300.0)
    assert timescales.suggested_dt(problem, u) == pytest.approx(0.005**2 / (4 * ALPHA), rel=1e-12)
    ortho = make_problem(etype, size=(0.1, 0.02), cells=(20, 2), k=5.0, k2=200.0)
    alpha_max = 200.0 / (RHO * CP)  # the larger principal conductivity counts
    assert timescales.suggested_dt(ortho, u) == pytest.approx(0.005**2 / (4 * alpha_max))


def test_oscillation_warning(caplog: pytest.LogCaptureFixture) -> None:
    problem = make_problem("Q4", size=(0.1, 0.01), cells=(10, 1))  # h = 0.01
    u = np.full(problem.dofs.n_dofs, 300.0)
    limit = 0.01**2 / (6 * ALPHA)
    assert timescales.oscillation_fraction(problem, u, 0.5 * limit) == 1.0
    assert timescales.oscillation_fraction(problem, u, 2.0 * limit) == 0.0
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        assert timescales.warn_if_oscillation_likely(problem, u, 0.5 * limit, lumped=False)
        assert not timescales.warn_if_oscillation_likely(problem, u, 2.0 * limit, lumped=False)
        assert not timescales.warn_if_oscillation_likely(problem, u, 0.5 * limit, lumped=True)
    messages = [r.getMessage() for r in caplog.records]
    assert len(messages) == 1 and "lumped capacitance or a finer mesh" in messages[0]
    assert "100 %" in messages[0]


def test_driver_uses_the_suggestion_and_warns_once(caplog: pytest.LogCaptureFixture) -> None:
    problem = make_problem("Q4", size=(0.1, 0.01), cells=(10, 1), bcs=(
        FixedTemperature("hot", "left", T=400.0),))
    transient(problem, end_time=50.0)
    with caplog.at_level(logging.INFO, logger="thermalfea"):
        result = solve_transient(problem, T0=300.0)
    suggested = 0.01**2 / (4 * ALPHA)
    assert result.times[1] == pytest.approx(suggested)
    text = [r.getMessage() for r in caplog.records]
    assert sum("initial time step suggested" in m for m in text) == 1
    # h^2/(4 alpha) is below h^2/(6 alpha) ... no: 1/4 > 1/6, so no oscillation warning
    assert not any("oscillate" in m for m in text)
    # an explicit small first step does trigger it, once
    problem.settings.initial_dt = 0.1 * suggested
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        solve_transient(problem, T0=300.0)
    assert sum("oscillate" in r.getMessage() for r in caplog.records) == 1


def test_compile_installs_the_hooks() -> None:
    model = api.new_model()
    api.Geometry(model).rectangle(0.0, 0.0, 0.1, 0.1)
    model.mesh_settings.global_size = 0.02
    model.solution.kind = "transient"
    built = api.build(model)
    api.assign_region(model, "all", material="Copper (pure)")
    problem = compile_problem(model, built, api.mesh(model, built))
    u = np.full(problem.dofs.n_dofs, 300.0)
    alpha = 401.0 / (8933.0 * 385.0)
    assert 0.3 * 0.02**2 / (4 * alpha) < problem.suggest_dt(u) <= 1.01 * 0.02**2 / (4 * alpha)
    assert problem.check_dt(u, 1e-9) is True
    model.solution.kind = "steady"
    steady = compile_problem(model, built, api.mesh(model, built))
    assert steady.suggest_dt is None and steady.check_dt is None


def test_no_initial_step_and_no_suggestion_is_an_error() -> None:
    problem = make_problem("Q4")
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(kind="transient", end_time=1.0)
    with pytest.raises(ModelError, match="cannot suggest one"):
        solve_transient(problem, T0=300.0)
    problem.settings.auto_timestep = False
    with pytest.raises(ModelError, match="fixed-step"):
        solve_transient(problem, T0=300.0)
    problem.settings.initial_dt = -1.0
    with pytest.raises(ModelError, match="must be positive"):
        solve_transient(problem, T0=300.0)


# ----------------------------------------------------------- the controller in the driver


def test_mandatory_times_from_outputs_and_table_breakpoints() -> None:
    ramp = HeatGeneration("gen", "all", Q=Table([0.0, 7.0, 13.0], [0.0, 1e6, 0.0], "t"))
    problem = make_problem("Q4", size=(0.1, 0.01), cells=(10, 1), bcs=(
        FixedTemperature("wall", "left", T=300.0), ramp))
    transient(problem, end_time=20.0, initial_dt=0.5, output="times", output_times=[2.5, 16.0])
    assert sorted(mandatory_times(problem)) == [0.0, 2.5, 7.0, 13.0, 16.0]
    result = solve_transient(problem, T0=300.0)
    for time in (2.5, 7.0, 13.0, 16.0, 20.0):
        assert time in result.times  # landed on exactly
    assert result.times == sorted(result.times) and len(set(result.times)) == len(result.times)
    problem.settings.output = "all"  # output times only matter when output == "times"
    assert sorted(mandatory_times(problem)) == [0.0, 7.0, 13.0]


# --------------------------------------------- M11.16: tolerances local to the time compared


def test_early_output_time_survives_a_long_run() -> None:
    c = controller(dt0=1.0, mandatory=[1e-5, 1e3], end_time=1e8)
    assert c.mandatory == [1e-5, 1e3, 1e8]
    assert c.next_mandatory == 1e-5
    assert c.propose() == 1e-5  # the first step is cut to land on it
    assert c.accept(None, None)
    assert c.t == 1e-5 and c.next_mandatory == 1e3


def test_distinct_small_times_are_kept_and_roundoff_equal_times_merged() -> None:
    c = controller(mandatory=[1e-5, 1e-5 * (1 + 1e-15), 2e-5, 50.0, 50.0 * (1 + 1e-14),
                              50.0 * (1 + 2e-14)], end_time=1e8)
    assert c.mandatory == [1e-5, 2e-5, 50.0, 1e8]
    # a time equal to the end up to round-off is the end
    c = controller(mandatory=[1e8 * (1 - 1e-14), 5.0], end_time=1e8)
    assert c.mandatory == [5.0, 1e8]
    # a time equal to the start up to round-off is dropped; a time at the start is dropped
    c = controller(mandatory=[0.0, 1e-14, 3.0], t0=0.0, end_time=10.0)
    assert c.mandatory == [3.0, 10.0]
    c = controller(mandatory=[1e6 * (1 + 1e-14), 2e6], t0=1e6, end_time=1e8)
    assert c.mandatory == [2e6, 1e8]


def test_early_output_time_is_stored_in_a_long_run() -> None:
    problem = make_problem("Q4", size=(0.1, 0.01), cells=(4, 1), bcs=(
        FixedTemperature("hot", "left", T=400.0),))
    transient(problem, end_time=1e8, initial_dt=1.0, output="times", output_times=[1e-5, 10.0])
    result = solve_transient(problem, T0=300.0)
    assert result.times[0] == 0.0
    assert result.times[1] == pytest.approx(1e-5, rel=1e-12)
    assert 10.0 in result.times and result.times[-1] == 1e8


def test_adaptive_steps_grow_as_the_solution_settles() -> None:
    problem = make_problem("Q4", size=(0.1, 0.01), cells=(20, 1), bcs=(
        FixedTemperature("hot", "left", T=400.0), FixedTemperature("cold", "right", T=300.0)))
    transient(problem, end_time=3000.0)
    result = solve_transient(problem, T0=300.0)
    steps = np.diff(result.times)
    assert steps[0] == pytest.approx(0.005**2 / (4 * ALPHA))
    assert steps.max() > 50 * steps[0]  # large steps once the transient has died out
    assert np.all(steps[1:] <= 2.0 * steps[:-1] * (1 + 1e-9))  # growth limit of 2
    assert result.n_steps < 200
    x = problem.mesh.nodes[:, 0]
    np.testing.assert_allclose(result.T, 400.0 - 1000.0 * x, atol=0.05)
    assert result.factorizations <= result.n_steps + result.rejected


def test_newton_failure_cuts_the_step_and_recovers() -> None:
    problem = make_problem("Q4", size=(0.01, 0.01), cells=(1, 1), k=400.0, bcs=(
        RadiationAmbient("rad", "right", emissivity=1.0, T_inf=300.0),))
    transient(problem, end_time=2000.0, initial_dt=2000.0, max_iterations=3)
    result = solve_transient(problem, T0=3000.0)
    assert result.newton_failures >= 1
    assert result.times[-1] == 2000.0 and result.times[1] < 2000.0
    assert 300.0 < result.T.min() < 3000.0
    problem.settings.dt_min = 1500.0  # no room to cut
    with pytest.raises(ConvergenceError, match="step 1 .*below the minimum"):
        solve_transient(problem, T0=3000.0)


def test_max_dt_per_step_in_the_driver() -> None:
    problem = make_problem("Q4", size=(0.01, 0.01), cells=(1, 1), k=400.0, bcs=tuple(
        Convection(f"c-{s}", s, h=2000.0, T_inf=300.0) for s in ("left", "right")))
    transient(problem, end_time=200.0, initial_dt=50.0, max_dT_per_step=10.0)
    result = solve_transient(problem, T0=400.0)
    changes = [np.abs(b - a).max() for a, b in zip(result.temperatures, result.temperatures[1:],
                                                   strict=False)]
    assert max(changes) <= 10.0 * (1 + 1e-6)
    assert result.rejected >= 1


# -------------------------------------------------------------------------------- V-17


def biot_roots(bi: float, n: int = 20) -> np.ndarray:
    return np.array([
        brentq(lambda z: z * np.tan(z) - bi, (i - 1) * np.pi + 1e-12, (i - 0.5) * np.pi - 1e-12)
        for i in range(1, n + 1)
    ])


def slab_series(x_over_l: float, fo: float, bi: float) -> float:
    zeta = biot_roots(bi)
    c = 4.0 * np.sin(zeta) / (2.0 * zeta + np.sin(2.0 * zeta))
    return float(np.sum(c * np.exp(-(zeta**2) * fo) * np.cos(zeta * x_over_l)))


@pytest.mark.parametrize("etype", TYPES)
def test_v17_convectively_cooled_slab(etype: str) -> None:
    """Half-thickness L = 0.05, symmetry at x = 0, initial 400 K, h = 500, T_inf = 300.

    Series solution with 20 terms; centre and surface at Fo = 0.2 and 1.0; 40 elements,
    automatic time step; tolerance 2e-3.
    """
    half, h, t_inf, t_init = 0.05, 500.0, 300.0, 400.0
    problem = make_problem(etype, size=(half, half / 10), cells=(40, 1), bcs=(
        Convection("conv", "right", h=h, T_inf=t_inf),))
    times = [0.2 * half**2 / ALPHA, 1.0 * half**2 / ALPHA]
    transient(problem, end_time=times[-1], output="times", output_times=times)
    result = solve_transient(problem, T0=t_init)
    x = problem.mesh.nodes[:, 0]
    centre, surface = np.isclose(x, 0.0), np.isclose(x, half)
    bi = h * half / K
    for fo, time in zip((0.2, 1.0), times, strict=True):
        T = result.temperatures[result.times.index(time)]
        for where, position in ((centre, 0.0), (surface, 1.0)):
            exact = t_inf + (t_init - t_inf) * slab_series(position, fo, bi)
            assert np.max(np.abs(T[where] - exact)) / exact < 2e-3
    assert result.n_steps < 400  # the step adapts instead of staying at the first size


# -------------------------------------------------------------------------------- V-18


def graded_slab(etype: str, bcs):
    """Slab L = 0.5 with elements of 0.001 near x = 0, growing geometrically beyond 0.03."""
    edges = list(np.arange(0.0, 0.0301, 0.001))
    size = 0.001
    while edges[-1] < 0.5:
        size *= 1.25
        edges.append(min(edges[-1] + size, 0.5))
    edges = np.array(edges)
    n = edges.size - 1
    problem = make_problem(etype, size=(float(n), 0.001), cells=(n, 1), bcs=bcs)
    nodes = problem.mesh.nodes
    nodes[:, 0] = np.interp(nodes[:, 0], np.arange(n + 1), edges)
    problem.cache.clear()
    for item in (*problem.terms, *problem.constraints):
        item.setup(problem)
    problem.mesh.validate()
    return problem


@pytest.mark.parametrize("etype", TYPES)
def test_v18_semi_infinite_solid(etype: str) -> None:
    """Slab L = 0.5, initial 300 K, T(0) steps to 400 K at t = 0+.

    T(x, t) = 400 - 100 erf(x / (2 sqrt(alpha t))); checked at x = 0.01 and 0.02 at
    t = 30 s. Graded mesh (0.001 near x = 0), lumped capacitance, automatic time step;
    tolerance 1e-2.
    """
    problem = graded_slab(etype, (FixedTemperature("step", "left", T=400.0),))
    transient(problem, lumped=True, end_time=30.0)
    result = solve_transient(problem, T0=300.0)
    assert result.times[-1] == 30.0
    assert result.thetas[0] == 1.0  # the jump of the prescribed temperature at t = 0
    x = problem.mesh.nodes[:, 0]
    for position in (0.01, 0.02):
        exact = 400.0 - 100.0 * erf(position / (2.0 * sqrt(ALPHA * 30.0)))
        here = np.isclose(x, position)
        assert here.any()
        assert np.max(np.abs(result.T[here] - exact)) / exact < 1e-2
    # the far end stays undisturbed
    np.testing.assert_allclose(result.T[np.isclose(x, 0.5)], 300.0, atol=1e-6)


# ------------------------------------------------- M11.19: free DOFs, restart at breakpoints


def test_error_estimate_counts_free_dofs_only() -> None:
    t_prev, t_n = np.array([300.0, 300.0, 300.0]), np.array([310.0, 320.0, 300.0])
    new = np.array([320.0, 340.0, 400.0])  # DOF 2 (prescribed) is far from its prediction
    free = np.array([0, 1])
    assert error_estimate(new, t_n, t_prev, 2.0, 2.0, free=free) == 0.0
    # the spread stays over all DOFs: 320 - ... (max 400 - min 320) = 80
    new2 = np.array([318.0, 340.0, 400.0])
    assert error_estimate(new2, t_n, t_prev, 2.0, 2.0, free=free) == pytest.approx(2.0 / 82.0)
    assert error_estimate(new2, t_n, t_prev, 2.0, 2.0) == pytest.approx(100.0 / 82.0)
    assert error_estimate(new2, t_n, t_prev, 2.0, 2.0, free=np.array([], dtype=int)) == 0.0
    assert error_estimate(new2, t_n, None, 2.0, None, free=free) is None
    assert error_estimate(new2, t_n, None, 2.0, None, free=np.array([], dtype=int)) is None


def test_max_dt_per_step_counts_free_dofs_only() -> None:
    ramp = Table(xs=[0.0, 100.0], ys=[300.0, 400.0], variable="t")  # 1 K/s on the wall
    # a very large heat capacity: the free solid hardly follows the fast wall
    problem = make_problem("Q4", size=(0.1, 0.02), cells=(8, 2), k=50.0, rho=1e9, bcs=(
        FixedTemperature("hot", "left", T=ramp), Convection("air", "right", h=200.0, T_inf=300.0)))
    transient(problem, lumped=True, end_time=100.0, initial_dt=20.0, max_dT_per_step=5.0)
    limited = solve_transient(problem, T0=300.0)
    problem.settings.max_dT_per_step = None
    free_run = solve_transient(problem, T0=300.0)
    x = problem.mesh.nodes[:, 0]
    wall = np.isclose(x, 0.0)
    # the wall moves 20 K in a 20 s step, far above the limit, yet the limit does not bite
    change = limited.temperatures[1] - limited.temperatures[0]
    assert change[wall].max() > 5.0 and np.abs(change[~wall]).max() < 5.0
    assert limited.rejected == 0
    assert limited.n_steps == free_run.n_steps


def test_a_model_without_free_dofs_takes_growing_steps() -> None:
    ramp = Table(xs=[0.0, 50.0], ys=[300.0, 400.0], variable="t")
    problem = make_problem("Q4", size=(0.1, 0.1), cells=(1, 1), bcs=(
        FixedTemperature("a", "left", T=ramp), FixedTemperature("b", "right", T=300.0)))
    transient(problem, end_time=100.0, initial_dt=1.0, auto_timestep=True)
    result = solve_transient(problem, T0=300.0)
    assert result.rejected == 0
    dts = np.diff(result.times)
    assert dts[-1] > dts[0]


def test_a_fast_ramp_of_a_fixed_temperature_takes_fewer_steps() -> None:  # review 2.1-5, D3
    ramp = Table(xs=[0.0, 100.0, 100.001, 400.0], ys=[300.0, 300.0, 400.0, 400.0], variable="t")
    problem = make_problem("Q4", size=(0.1, 0.02), cells=(8, 2), k=50.0, bcs=(
        FixedTemperature("hot", "left", T=ramp), Convection("air", "right", h=200.0, T_inf=280.0)))
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(kind="transient", theta=0.5, initial_dt=10.0,
                                        end_time=400.0, auto_timestep=True)
    result = solve_transient(problem, T0=300.0)
    # before M11.19: 69 steps, 15 rejected (docs/review-2026-11-21-evaluation.md, 2.1-5)
    assert result.n_steps < 69 and result.rejected < 15


def _solid_problem(bcs, **settings):
    problem = make_problem("Q4", size=(0.1, 0.01), cells=(10, 1), bcs=bcs)
    transient(problem, **settings)
    return problem


def _record_errors(monkeypatch):
    from thermalfea.solver import transient as tr

    calls = []
    real = tr.error_estimate

    def wrapper(T_new, T_n, T_prev, dt, dt_prev, **kw):
        e = real(T_new, T_n, T_prev, dt, dt_prev, **kw)
        calls.append({"restart": T_prev is T_n, "dt": dt, "e": e, "free": kw.get("free")})
        return e

    monkeypatch.setattr(tr, "error_estimate", wrapper)
    return calls


def test_the_predictor_restarts_at_a_breakpoint_but_not_at_an_output_time(monkeypatch) -> None:
    ramp = HeatGeneration("gen", "all", Q=Table([0.0, 5.0, 10.0], [0.0, 1e6, 1e6], "t"))
    problem = _solid_problem(
        (FixedTemperature("wall", "left", T=300.0), ramp),
        end_time=12.0, initial_dt=1.0, auto_timestep=True, output="times", output_times=[8.0],
    )
    calls = _record_errors(monkeypatch)
    result = solve_transient(problem, T0=300.0)
    # reconstruct the start time of every accepted call from the accepted steps; the
    # recorded calls include rejected ones, so follow time through the accepted steps only
    starts = {}
    t = 0.0
    it = iter(calls)
    for dt_acc in np.diff(result.times):
        while True:
            c = next(it)
            if np.isclose(c["dt"], dt_acc, rtol=1e-12, atol=0.0):
                break
        starts[round(t, 9)] = c
        t += dt_acc
    assert starts[5.0]["restart"] is True
    assert starts[8.0]["restart"] is False
    assert starts[10.0]["restart"] is True


def test_the_restart_step_limits_the_free_solid_change() -> None:
    # a heat source that starts to ramp at the breakpoint t = 2: the step starting there is
    # limited to 4 tol max(range, 1 K) of change in the free solid temperatures
    load = HeatGeneration("gen", "all", Q=Table([0.0, 2.0, 10.0], [0.0, 0.0, 1e8], "t"))
    problem = _solid_problem(
        (FixedTemperature("wall", "left", T=300.0), load),
        end_time=6.0, initial_dt=1.0, auto_timestep=True, time_tol=0.02,
    )
    result = solve_transient(problem, T0=300.0)
    assert result.rejected >= 1
    # the step starting at 2.0 (restart) changed the solid by at most 4 tol * max(range, 1)
    times = np.array(result.times)
    k = int(np.flatnonzero(np.isclose(times, 2.0))[0])
    T0_, T1_ = result.temperatures[k], result.temperatures[k + 1]
    rng = result.temperatures[k + 1].max() - result.temperatures[k + 1].min()
    assert np.abs(T1_ - T0_).max() <= 4 * 0.02 * max(rng, 1.0) * (1 + 1e-9)
