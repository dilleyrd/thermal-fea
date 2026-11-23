"""M4.2 — theta-method at a fixed step (Theory §6). Includes V-16 and V-21."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, make_problem
from scipy.integrate import solve_ivp

from thermalfea.core.constants import STEFAN_BOLTZMANN as SIGMA
from thermalfea.core.errors import ConvergenceError, ModelError
from thermalfea.core.functions import Expression, Table
from thermalfea.model.bcs import (
    Convection,
    FixedTemperature,
    HeatGeneration,
    RadiationAmbient,
)
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.solver.transient import StepRecord, TransientResult, solve_transient

RHO, CP = 7800.0, 500.0
SIDE = 0.01  # V-16: square 0.01 x 0.01
H16, T_INF, T_INIT = 20.0, 300.0, 400.0
AREA, VOLUME = 4 * SIDE * 1.0, SIDE * SIDE * 1.0
TAU = RHO * CP * VOLUME / (H16 * AREA)


def transient(problem, lumped: bool = False, **settings):
    """Add the thermal mass to a hand-built problem and set its solution settings."""
    term = CapacitanceTerm(lumped=lumped)
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(kind="transient", **settings)
    return problem


def lumped_body(etype: str, theta: float, dt: float, end: float, **kw):
    problem = make_problem(etype, size=(SIDE, SIDE), cells=(2, 2), k=400.0, bcs=tuple(
        Convection(f"conv-{side}", side, h=H16, T_inf=T_INF)
        for side in ("bottom", "right", "top", "left")))
    return transient(problem, theta=theta, initial_dt=dt, end_time=end, auto_timestep=False, **kw)


def exact_lumped(t: float) -> float:
    return T_INF + (T_INIT - T_INF) * np.exp(-t / TAU)


# ------------------------------------------------------------------------------- V-16


@pytest.mark.parametrize(("theta", "tol"), [(1.0, 5e-3), (0.5, 1e-4)])
@pytest.mark.parametrize("etype", TYPES)
def test_v16_lumped_body(etype: str, theta: float, tol: float) -> None:
    """Square 0.01 x 0.01, k = 400, initial 400 K, h = 20 on all four edges, T_inf = 300.

    T(t) = T_inf + (T_i - T_inf) exp(-h A t / (rho c V)); checked at tau and 3 tau with
    dt = tau / 200; tolerance 5e-3 (theta = 1) and 1e-4 (theta = 1/2).
    """
    assert pytest.approx(487.5) == TAU
    problem = lumped_body(etype, theta, TAU / 200.0, 3.0 * TAU)
    result = solve_transient(problem, T0=T_INIT)
    assert isinstance(result, TransientResult) and result.n_steps == 600
    assert result.times[0] == 0.0 and result.times[-1] == pytest.approx(3.0 * TAU, rel=1e-12)
    assert result.times[200] == pytest.approx(TAU, rel=1e-12)
    for index, time in ((200, TAU), (600, 3.0 * TAU)):
        computed = result.temperatures[index]
        exact = exact_lumped(time)
        assert np.max(np.abs(computed - exact)) / exact < tol
    # the convection is switched on at t = 0 on a body at 400 K: a load discontinuity,
    # so the first step uses theta = 1; every later step uses the requested theta
    assert result.thetas[0] == 1.0 and set(result.thetas[1:]) == {theta}
    # linear, constant dt: factorised once per distinct theta and reused
    assert result.factorizations == (1 if theta == 1.0 else 2)
    assert set(result.iterations) == {1}


# ------------------------------------------------------------------------------- V-21


@pytest.mark.parametrize(("theta", "expected"), [(1.0, 1.0), (0.5, 2.0)])
@pytest.mark.parametrize("etype", TYPES)
def test_v21_time_stepping_order(etype: str, theta: float, expected: float) -> None:
    """V-16 with dt, dt/2, dt/4: observed order ~1 (theta = 1), ~2 (theta = 1/2), +-0.15.

    The order is taken from the differences between successive solutions, which removes
    the (time-step independent) departure of the 2D body from the lumped formula.
    """
    dt = TAU / 200.0  # the step of V-16
    finals = [
        solve_transient(lumped_body(etype, theta, dt / 2**i, TAU), T0=T_INIT).T.mean()
        for i in range(3)
    ]
    order = np.log2(abs(finals[0] - finals[1]) / abs(finals[1] - finals[2]))
    assert abs(order - expected) < 0.15


# --------------------------------------------------------------------- driver behaviour


def test_steps_land_exactly_on_the_end_time() -> None:
    result = solve_transient(lumped_body("Q4", 1.0, 30.0, 100.0), T0=T_INIT)
    np.testing.assert_allclose(result.times, [0.0, 30.0, 60.0, 90.0, 100.0])
    assert result.factorizations == 2  # the shorter last step needs its own factorisation
    whole = solve_transient(lumped_body("Q4", 1.0, 0.1, 1.0), T0=T_INIT)
    assert whole.n_steps == 10 and whole.times[-1] == pytest.approx(1.0, rel=1e-13)


def test_on_step_records_and_cancel() -> None:
    records: list[StepRecord] = []

    def on_step(record: StepRecord) -> bool:
        records.append(record)
        return record.step < 3

    problem = lumped_body("Q4", 0.5, 10.0, 100.0)
    result = solve_transient(problem, T0=T_INIT, on_step=on_step, store=False)
    assert result.cancelled and result.n_steps == 3 and result.temperatures == []
    assert [r.step for r in records] == [1, 2, 3]
    assert [r.t for r in records] == [10.0, 20.0, 30.0]
    first, second = records[0], records[1]
    assert first.dt == 10.0 and first.converged and first.iterations == 1
    assert (first.theta, second.theta) == (1.0, 0.5)  # start-up step, then the requested theta
    np.testing.assert_array_equal(first.T_prev, T_INIT)
    np.testing.assert_array_equal(second.T_prev, first.T)
    np.testing.assert_array_equal(result.T, records[-1].T)
    # each record is consistent with the scheme: C dT/dt = theta g_new + (1 - theta) g_old
    for record in (first, second):
        g_new = record.system.residual(record.T)
        expected = record.theta * g_new + (1.0 - record.theta) * record.g_prev
        np.testing.assert_allclose(
            record.capacitance_rate, expected, atol=1e-9 * abs(g_new).max()
        )
        assert record.residual < 1e-9 * abs(g_new).max()
        assert record.capacitance_rate.sum() < 0.0  # the body is losing heat
    np.testing.assert_array_equal(second.g_prev, first.system.residual(first.T))  # stored


def test_initial_condition_from_scalar_array_and_default() -> None:
    problem = lumped_body("Q4", 1.0, 10.0, 10.0)
    by_scalar = solve_transient(problem, T0=350.0)
    by_array = solve_transient(problem, T0=np.full(problem.dofs.n_dofs, 350.0))
    np.testing.assert_array_equal(by_scalar.T, by_array.T)
    default = solve_transient(problem)  # no model: the 293.15 K placeholder
    np.testing.assert_array_equal(default.temperatures[0], 293.15)
    assert default.T.mean() > 293.15  # warming towards the 300 K fluid


def test_backward_euler_is_monotone_and_unconditionally_stable() -> None:
    result = solve_transient(lumped_body("T6", 1.0, 50.0 * TAU, 500.0 * TAU), T0=T_INIT)
    means = [t.mean() for t in result.temperatures]
    assert all(a > b for a, b in zip(means, means[1:], strict=False))
    assert means[-1] == pytest.approx(T_INF, abs=1e-3) and min(means) >= T_INF - 1e-9


@pytest.mark.parametrize("etype", TYPES)
def test_slab_reaches_the_steady_solution(etype: str) -> None:
    length = 0.1
    problem = make_problem(etype, size=(length, length / 10), cells=(10, 1), bcs=(
        FixedTemperature("hot", "left", T=400.0), FixedTemperature("cold", "right", T=300.0)))
    alpha = 50.0 / (RHO * CP)
    transient(problem, theta=1.0, initial_dt=length**2 / alpha / 20, end_time=5 * length**2 / alpha,
              auto_timestep=False)
    result = solve_transient(problem, T0=300.0)
    x = problem.mesh.nodes[:, 0]
    np.testing.assert_allclose(result.T, 400.0 - 100.0 * x / length, atol=1e-6)
    # the hot face jumps from the 300 K initial state to 400 K at t = 0: a discontinuity
    np.testing.assert_array_equal(result.temperatures[0][np.isclose(x, 0.0)], 400.0)


# --------------------------------------------------------------------- discontinuities


def slab(theta: float, bcs, n_steps: int = 10, T0: float = 300.0, **kw):
    problem = make_problem("Q4", size=(0.1, 0.01), cells=(20, 1), bcs=bcs)
    transient(problem, theta=theta, initial_dt=1.0, end_time=float(n_steps),
              auto_timestep=False, **kw)
    return solve_transient(problem, T0=T0), problem


def test_theta_is_one_on_the_first_step_after_a_jump_in_a_prescribed_temperature() -> None:
    result, _ = slab(0.5, (FixedTemperature("hot", "left", T=400.0),))
    assert result.thetas[0] == 1.0 and set(result.thetas[1:]) == {0.5}
    # no jump when the initial state matches the prescribed value and is in equilibrium
    smooth, _ = slab(0.5, (FixedTemperature("same", "left", T=300.0),))
    assert set(smooth.thetas) == {0.5}
    # a load on a body that starts out of equilibrium with it is a jump at the start
    loaded, _ = slab(0.5, (Convection("conv", "right", h=100.0, T_inf=350.0),))
    assert loaded.thetas[0] == 1.0 and set(loaded.thetas[1:]) == {0.5}
    # with theta = 1 throughout nothing needs overriding
    euler, _ = slab(1.0, (FixedTemperature("hot", "left", T=400.0),))
    assert set(euler.thetas) == {1.0}


def test_theta_is_one_on_the_step_after_a_load_jumps() -> None:
    step_load = HeatGeneration("gen", "all", Q=Expression("where(t > 4, 1e7, 0)"))
    result, _ = slab(0.5, (FixedTemperature("wall", "left", T=300.0), step_load))
    # the load switches on just after t = 4: the step from 4 to 5 is the discontinuity step
    assert result.thetas == [0.5, 0.5, 0.5, 0.5, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5]
    assert np.allclose(result.temperatures[4], 300.0) and result.temperatures[5].max() > 300.1
    # a continuous ramp is not a jump
    ramp = HeatGeneration("gen", "all", Q=Table([0.0, 10.0], [0.0, 1e7], "t"))
    ramped, _ = slab(0.5, (FixedTemperature("wall", "left", T=300.0), ramp))
    assert set(ramped.thetas) == {0.5}


def test_theta_is_one_when_a_prescribed_temperature_jumps_mid_run() -> None:
    wall = FixedTemperature("wall", "left", T=Expression("where(t > 2, 400, 300)"))
    result, problem = slab(0.5, (wall,), n_steps=5)
    assert result.thetas == [0.5, 0.5, 1.0, 0.5, 0.5]
    x = problem.mesh.nodes[:, 0]
    assert result.temperatures[2][np.isclose(x, 0.0)].max() == 300.0
    assert result.temperatures[3][np.isclose(x, 0.0)].min() == 400.0


def test_prescribed_temperature_follows_its_function_of_time() -> None:
    """NAFEMS T3 setting: T(L, t) = 100 sin(pi t / 40) (here in kelvin above 300)."""
    wall = FixedTemperature("wall", "right", T=Expression("300 + 100*sin(pi*t/40)"))
    result, problem = slab(0.5, (wall, FixedTemperature("zero", "left", T=300.0)), n_steps=40)
    x = problem.mesh.nodes[:, 0]
    end = np.isclose(x, 0.1)
    for step in (0, 10, 20, 33):
        expected = 300.0 + 100.0 * np.sin(np.pi * result.times[step] / 40.0)
        np.testing.assert_allclose(result.temperatures[step][end], expected, rtol=1e-13)
    assert set(result.thetas) == {0.5}
    assert result.factorizations == 1  # K is unchanged, so the factorisation is reused


def test_time_dependent_coefficient_changes_the_matrix_and_refactorises() -> None:
    conv = Convection("conv", "right", h=Table([0.0, 10.0], [10.0, 1000.0], "t"), T_inf=350.0)
    result, _ = slab(1.0, (conv,), n_steps=6)
    assert result.factorizations == 6
    assert result.T.max() > 300.0


# ----------------------------------------------------------------------- nonlinear path


@pytest.mark.parametrize("theta", [1.0, 0.5])
def test_radiative_cooling_of_a_lumped_body(theta: float) -> None:
    """V-20 setting at a fixed step: rho c V dT/dt = -eps sigma A (T^4 - T_inf^4)."""
    eps, t_init = 0.8, 800.0
    problem = make_problem("Q4", size=(SIDE, SIDE), cells=(2, 2), k=400.0, bcs=tuple(
        RadiationAmbient(f"rad-{side}", side, emissivity=eps, T_inf=300.0)
        for side in ("bottom", "right", "top", "left")))
    end = 2000.0
    transient(problem, theta=theta, initial_dt=end / 400, end_time=end, auto_timestep=False)
    assert not problem.is_linear
    result = solve_transient(problem, T0=t_init)
    reference = solve_ivp(
        lambda t, y: -eps * SIGMA * AREA * (y**4 - 300.0**4) / (RHO * CP * VOLUME),
        (0.0, end), [t_init], rtol=1e-10, atol=1e-10,
    ).y[0, -1]
    tol = 2e-3 if theta == 1.0 else 2e-4
    assert abs(result.T.mean() - reference) / reference < tol
    assert max(result.iterations) <= 6 and min(result.iterations) >= 2
    assert result.factorizations == 0  # the nonlinear path factorises inside Newton


def test_temperature_dependent_capacity_uses_t_theta() -> None:
    """c = c0 (1 + b (T - 300)): cooling follows from d/dt of the enthalpy."""
    c0, b = 500.0, 0.004
    problem = make_problem("Q4", size=(SIDE, SIDE), cells=(1, 1), k=400.0,
                           cp=Expression(f"{c0}*(1 + {b}*(T - 300))"), bcs=tuple(
        Convection(f"c-{side}", side, h=H16, T_inf=T_INF)
        for side in ("bottom", "right", "top", "left")))
    end = TAU
    transient(problem, theta=0.5, initial_dt=end / 200, end_time=end, auto_timestep=False)
    assert not problem.is_linear
    result = solve_transient(problem, T0=T_INIT)
    reference = solve_ivp(
        lambda t, y: -H16 * AREA * (y - T_INF) / (RHO * c0 * (1 + b * (y - 300.0)) * VOLUME),
        (0.0, end), [T_INIT], rtol=1e-10, atol=1e-10,
    ).y[0, -1]
    assert abs(result.T.mean() - reference) / reference < 1e-4


def test_unconverged_step_raises_with_the_step_named() -> None:
    problem = make_problem("Q4", size=(SIDE, SIDE), cells=(1, 1), bcs=(
        RadiationAmbient("rad", "right", emissivity=1.0, T_inf=300.0),))
    transient(problem, theta=1.0, initial_dt=1e6, end_time=1e6, auto_timestep=False,
              max_iterations=1)
    with pytest.raises(ConvergenceError, match=r"step 1 \(t = 1e\+06 s"):
        solve_transient(problem, T0=3000.0)


def test_bad_settings() -> None:
    problem = lumped_body("Q4", 1.0, 1.0, 10.0)
    problem.settings.initial_dt = None
    with pytest.raises(ModelError, match="initial time step"):
        solve_transient(problem, T0=T_INIT)
    problem.settings.initial_dt = 1.0
    problem.settings.end_time = 0.0
    with pytest.raises(ModelError, match="end time"):
        solve_transient(problem, T0=T_INIT)


def test_lumped_and_consistent_capacitance_agree_for_a_lumped_body() -> None:
    a = solve_transient(lumped_body("Q8", 0.5, TAU / 50, TAU), T0=T_INIT).T.mean()
    problem = make_problem("Q8", size=(SIDE, SIDE), cells=(2, 2), k=400.0, bcs=tuple(
        Convection(f"conv-{side}", side, h=H16, T_inf=T_INF)
        for side in ("bottom", "right", "top", "left")))
    transient(problem, lumped=True, theta=0.5, initial_dt=TAU / 50, end_time=TAU,
              auto_timestep=False)
    b = solve_transient(problem, T0=T_INIT).T.mean()
    assert a == pytest.approx(b, rel=1e-5)
    assert a == pytest.approx(exact_lumped(TAU), rel=1e-4)


@pytest.mark.parametrize("etype", TYPES)
def test_radiative_equilibrium_steps_converge_in_one_iteration(etype: str) -> None:
    """M11.17 (D1): at equilibrium the round-off test accepts each step at once."""
    problem = make_problem(etype, size=(0.1, 0.01), cells=(4, 1), bcs=(
        RadiationAmbient("rad", "right", emissivity=0.8, T_inf=300.0),))
    transient(problem, theta=0.5, initial_dt=1.0, end_time=5.0, auto_timestep=False)
    result = solve_transient(problem, T0=300.0)
    assert result.iterations == [1] * 5
    assert result.newton_failures == 0
    np.testing.assert_allclose(result.T, 300.0, atol=1e-6)  # round-off drift only
