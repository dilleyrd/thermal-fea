"""M11.20 — the flow providers are updated once per nonlinear iteration (Theory §9.2).

Line-search trials and the ``_jumps`` probes must not update them.
"""

from __future__ import annotations

import numpy as np
import pytest
from test_coupling import coupled, network, stream

from thermalfea.model.bcs import FixedTemperature
from thermalfea.model.settings import SolutionSettings
from thermalfea.solver.nonlinear import newton
from thermalfea.solver.steady import assemble, steady_solution, update_providers
from thermalfea.solver.terms import State
from thermalfea.solver.transient import _jumps, solve_transient


def fed_problem():
    problem, provider = coupled(
        [stream(mass_flow=None)], network(), bcs=(FixedTemperature("w", "top", T=340.0),)
    )
    calls: list[np.ndarray] = []
    original = provider.update

    def spy(s) -> None:
        calls.append(s.u.copy())
        original(s)

    provider.update = spy  # type: ignore[method-assign]
    return problem, provider, calls


def test_steady_updates_the_provider_once_per_iteration() -> None:
    problem, _, calls = fed_problem()
    result = steady_solution(problem)
    assert result.converged
    assert len(calls) == result.iterations + 1
    # the last update was made at the accepted solution
    assert np.array_equal(calls[-1], result.T)


def test_line_search_trials_do_not_update_the_provider() -> None:
    problem, _, calls = fed_problem()
    n_assemblies = 0

    def counting(u):
        nonlocal n_assemblies
        n_assemblies += 1
        return assemble(problem, u, 0.0, update=False)

    refreshed: list[np.ndarray] = []

    def refresh(u) -> None:
        refreshed.append(u.copy())
        update_providers(problem, State(u=u, u_prev=u, t=0.0, dt=None, dofs=problem.dofs))

    fixed = problem.prescribed(0.0)
    start = np.full(problem.dofs.n_dofs, 320.0)
    result = newton(counting, start, fixed, problem.settings, refresh=refresh)
    # one refresh per iterate: the start and every accepted update, none per trial
    assert len(refreshed) == result.iterations + 1
    assert len(calls) == len(refreshed)  # assemble(update=False) never touches the provider
    assert n_assemblies > len(refreshed)  # the trials were assembled, not refreshed
    assert np.array_equal(refreshed[-1], result.T)


def test_newton_without_refresh_assembles_as_before() -> None:
    problem, _, _ = fed_problem()
    assemble(problem, np.full(problem.dofs.n_dofs, 320.0))  # hydraulics once, up front
    n = 0

    def counting(u):
        nonlocal n
        n += 1
        return assemble(problem, u, 0.0, update=False)

    result = newton(counting, np.full(problem.dofs.n_dofs, 320.0), problem.prescribed(0.0),
                    problem.settings)
    assert n == 1 + result.iterations  # the start and one trial per iteration (no line search)


def test_transient_step_updates_the_provider_once_per_iteration() -> None:
    problem, provider, _ = fed_problem()
    step_updates = 0
    counted = provider.update

    def spy(s) -> None:
        nonlocal step_updates
        step_updates += s.dt is not None  # the start-up assemblies have no step size
        counted(s)

    provider.update = spy  # type: ignore[method-assign]
    problem.settings = SolutionSettings(
        kind="transient", end_time=1.0, initial_dt=1.0, auto_timestep=False, theta=0.5
    )
    result = solve_transient(problem, 320.0)
    assert result.n_steps == 1
    # one update per iterate of the step: the start and every accepted update
    assert step_updates == result.iterations[0] + 1


def test_jumps_do_not_update_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    problem, _, calls = fed_problem()
    monkeypatch.setattr(type(problem), "is_time_dependent", property(lambda self: True))
    u = np.full(problem.dofs.n_dofs, 320.0)
    system = assemble(problem, u, 0.0)
    assert len(calls) == 1
    _jumps(problem, u, 0.0, 1.0, system)
    assert len(calls) == 1
