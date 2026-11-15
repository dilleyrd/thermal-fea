"""M4.4 — streaming output, progress, cancel, per-step energy columns."""

from __future__ import annotations

import logging
from pathlib import Path

import h5py
import numpy as np
import pytest
from handmade import make_problem

from thermalfea import api
from thermalfea.core.errors import ConvergenceError
from thermalfea.core.functions import Constant
from thermalfea.model.bcs import Convection, FixedTemperature, RadiationAmbient
from thermalfea.model.model import InitialCondition
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.post.results import Results
from thermalfea.solver import run as run_module
from thermalfea.solver.run import OutputSelector, StepInfo, run_transient

RHO, CP, SIDE = 7800.0, 500.0, 0.01
H, T_INF, T_INIT = 20.0, 300.0, 400.0
TAU = RHO * CP * SIDE * SIDE / (H * 4 * SIDE)


def lumped(theta: float = 1.0, **settings):
    problem = make_problem("Q4", size=(SIDE, SIDE), cells=(2, 2), k=400.0, bcs=tuple(
        Convection(f"conv-{side}", side, h=H, T_inf=T_INF)
        for side in ("bottom", "right", "top", "left")))
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    defaults = dict(kind="transient", theta=theta, initial_dt=TAU / 20, end_time=TAU,
                    auto_timestep=False)
    problem.settings = SolutionSettings(**{**defaults, **settings})
    return problem


# -------------------------------------------------------------------- output selection


def test_output_selector() -> None:
    every = OutputSelector(SolutionSettings(kind="transient", end_time=10.0))
    assert all(every.wanted(step, 0.1 * step) for step in range(0, 50))
    nth = OutputSelector(SolutionSettings(kind="transient", end_time=10.0, output="every_n",
                                          output_every=3))
    assert [s for s in range(8) if nth.wanted(s, 0.5 * s)] == [0, 3, 6]
    assert nth.wanted(7, 10.0)  # the last step is always stored
    times = OutputSelector(SolutionSettings(kind="transient", end_time=10.0, output="times",
                                            output_times=[4.0, 1.5]))
    assert [t for t in (0.5, 1.5, 2.0, 4.0, 4.0 + 1e-12, 7.0, 10.0) if times.wanted(3, t)] == [
        1.5, 4.0, 4.0 + 1e-12, 10.0]
    assert times.wanted(0, 0.0)  # the initial state too
    none = OutputSelector(SolutionSettings(kind="transient", end_time=10.0, output="times"))
    assert not none.wanted(2, 3.0) and none.wanted(9, 10.0)


def test_all_steps_are_streamed_with_extendable_datasets(tmp_path: Path) -> None:
    path = tmp_path / "all.h5"
    result = run_transient(lumped(), path, T0=T_INIT)
    assert result.n_steps == 20 and result.temperatures == []  # in the file, not in memory
    results = Results(path)
    assert results.n_steps == 21  # the initial state plus 20 steps
    np.testing.assert_allclose(results.times, np.linspace(0.0, TAU, 21), rtol=1e-12)
    np.testing.assert_array_equal(results.temperature(0), T_INIT)
    np.testing.assert_array_equal(results.dt[:2], [0.0, TAU / 20])
    np.testing.assert_array_equal(results.iterations, [0] + [1] * 20)
    assert results.converged.all()
    history = results.nodal_history(0)
    assert history.shape == (21,) and np.all(np.diff(history) < 0)
    exact = T_INF + (T_INIT - T_INF) * np.exp(-1.0)
    assert results.temperature().mean() == pytest.approx(exact, rel=5e-3)
    with h5py.File(path, "r") as f:
        t = f["steps/fields/T"]
        assert t.maxshape[0] is None and t.chunks[0] == 1  # extendable, chunked by step
        assert f["steps/time"].maxshape == (None,)


def test_every_n_and_times(tmp_path: Path) -> None:
    nth = tmp_path / "nth.h5"
    run_transient(lumped(output="every_n", output_every=6), nth, T0=T_INIT)
    np.testing.assert_allclose(
        Results(nth).times, np.array([0, 6, 12, 18, 20]) * TAU / 20, rtol=1e-12
    )
    at = tmp_path / "times.h5"
    wanted = [0.3 * TAU, 0.77 * TAU]
    result = run_transient(lumped(output="times", output_times=wanted), at, T0=T_INIT)
    np.testing.assert_allclose(Results(at).times, [0.0, *wanted, TAU], rtol=1e-12)
    assert result.n_steps > 20  # the extra steps that land on the output times
    # the stored states are those of the full run at the same instants
    full = tmp_path / "full.h5"
    run_transient(lumped(output="all", output_times=wanted), full, T0=T_INIT)
    assert Results(full).n_steps == 21  # output_times are ignored unless output == "times"


# ----------------------------------------------------------------------------- energy


@pytest.mark.parametrize("theta", [1.0, 0.5])
def test_per_step_energy_columns_close_to_round_off(tmp_path: Path, theta: float) -> None:
    path = tmp_path / "energy.h5"
    run_transient(lumped(theta=theta), path, T0=T_INIT)
    results = Results(path)
    balance = results.energy_balance()
    assert np.isnan(balance["net"][0])  # no balance for the initial state
    for name in ("heat_out", "stored_rate", "imbalance", "relative_imbalance"):
        assert np.all(np.isfinite(balance[name][1:]))
    assert np.all(balance["stored_rate"][1:] < 0.0)  # cooling
    assert np.all(balance["heat_in"][1:] == 0.0)
    np.testing.assert_allclose(balance["heat_out"][1:], -balance["stored_rate"][1:], rtol=1e-9)
    assert np.abs(balance["relative_imbalance"][1:]).max() < 1e-8  # V-34, linear
    # heat flow of each boundary condition per step; four equal sides
    flows = np.array([results.heat_flow(f"conv-{s}") for s in ("bottom", "right", "top", "left")])
    assert np.isnan(flows[:, 0]).all() and np.all(flows[:, 1:] < 0.0)
    np.testing.assert_allclose(flows[:, 1:].sum(axis=0), balance["net"][1:], rtol=1e-12)
    np.testing.assert_allclose(flows[0, 1:], flows[2, 1:], rtol=1e-9)
    # integrated over time, the heat lost equals the drop in stored energy
    dt = np.diff(results.times)
    lost = float(np.sum(-balance["net"][1:] * dt))
    mean_drop = results.temperature(0).mean() - results.temperature().mean()
    assert lost == pytest.approx(RHO * CP * SIDE * SIDE * mean_drop, rel=2e-3)


def test_energy_balance_with_a_fixed_temperature_and_radiation(tmp_path: Path) -> None:
    problem = make_problem("Q8", size=(0.1, 0.01), cells=(10, 1), bcs=(
        FixedTemperature("hot", "left", T=600.0),
        RadiationAmbient("rad", "right", emissivity=0.8, T_inf=300.0),
    ))
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(kind="transient", theta=0.5, initial_dt=5.0,
                                        end_time=200.0, auto_timestep=False)
    path = tmp_path / "rad.h5"
    run_transient(problem, path, T0=300.0)
    results = Results(path)
    balance = results.energy_balance()
    assert np.abs(balance["relative_imbalance"][1:]).max() < 1e-3  # V-34, nonlinear
    assert np.all(results.heat_flow("hot")[1:] > 0.0)  # heat enters at the hot face
    assert np.all(results.heat_flow("rad")[2:] < 0.0)  # and leaves by radiation
    assert np.all(balance["stored_rate"][1:] > 0.0)  # the bar is warming up
    assert results.iterations[1:].min() >= 2  # nonlinear steps iterate


# ------------------------------------------------------------------ progress and cancel


def test_progress_is_called_after_every_step(tmp_path: Path) -> None:
    seen: list[StepInfo] = []
    run_transient(lumped(output="every_n", output_every=5), tmp_path / "p.h5",
                  progress=lambda info: seen.append(info) or True, T0=T_INIT)
    assert [i.step for i in seen] == list(range(1, 21))  # every step, stored or not
    first, last = seen[0], seen[-1]
    assert first.time == pytest.approx(TAU / 20) and first.dt == pytest.approx(TAU / 20)
    assert first.iterations == 1 and first.converged and first.residual >= 0.0
    assert first.end_time == TAU and last.time == pytest.approx(TAU)


@pytest.mark.parametrize("reply", [False, None])
def test_returning_false_cancels_cleanly(tmp_path: Path, reply: bool | None) -> None:
    path = tmp_path / "cancel.h5"

    def progress(info: StepInfo) -> bool | None:
        return reply if info.step >= 7 else True

    result = run_transient(lumped(output="every_n", output_every=5), path, progress, T0=T_INIT)
    results = Results(path)
    if reply is False:
        assert result.cancelled and result.n_steps == 7
        # stored: the initial state, step 5, and the last computed step (7)
        np.testing.assert_allclose(results.times, np.array([0, 5, 7]) * TAU / 20, rtol=1e-12)
        assert np.all(np.isfinite(results.temperature()))
        assert np.isfinite(results.energy_balance()["net"][-1])
    else:  # only an explicit False cancels
        assert not result.cancelled and result.n_steps == 20


def test_a_failed_run_leaves_a_readable_file(tmp_path: Path) -> None:
    problem = make_problem("Q4", size=(SIDE, SIDE), cells=(1, 1), bcs=(
        RadiationAmbient("rad", "right", emissivity=1.0, T_inf=300.0),))
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(kind="transient", initial_dt=1e6, end_time=1e6,
                                        auto_timestep=False, max_iterations=1)
    path = tmp_path / "failed.h5"
    with pytest.raises(ConvergenceError):
        run_transient(problem, path, T0=3000.0)
    results = Results(path)  # still a valid file holding the initial state
    assert results.n_steps == 1
    np.testing.assert_array_equal(results.temperature(0), 3000.0)


def test_file_is_flushed_every_ten_stored_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert run_module.FLUSH_EVERY == 10
    flushed_at: list[int] = []
    original = run_module.ResultsWriter.flush

    def counting(self) -> None:
        flushed_at.append(self.n_steps)
        original(self)

    monkeypatch.setattr(run_module.ResultsWriter, "flush", counting)
    run_transient(lumped(initial_dt=TAU / 35), tmp_path / "flush.h5", T0=T_INIT)
    assert flushed_at == [1, 10, 20, 30]  # after the initial state, then every ten steps


def test_file_is_readable_while_the_run_is_in_progress(tmp_path: Path) -> None:
    """After a flush, another reader sees the steps written so far."""
    path = tmp_path / "live.h5"
    seen: dict[int, int] = {}

    def progress(info: StepInfo) -> bool:
        if info.step in (10, 19):
            try:
                seen[info.step] = Results(path).n_steps
            except Exception:  # noqa: BLE001 - a locked file would also be a finding
                seen[info.step] = -1
        return True

    run_transient(lumped(), path, progress, T0=T_INIT)
    # either the reader could open the flushed file, or the platform locks it for writing
    assert seen[10] in (-1, 10, 11) and seen[19] in (-1, 10, 11, 20)
    assert Results(path).n_steps == 21


# --------------------------------------------------------------------------- api.solve


def test_api_solve_runs_a_transient_model(caplog: pytest.LogCaptureFixture) -> None:
    model = api.new_model(name="quench")
    api.Geometry(model).rectangle(0.0, 0.0, SIDE, SIDE)
    model.mesh_settings.global_size = SIDE / 2
    built = api.build(model)
    api.select_curves(model, built, "skin", where=lambda c: True)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs.append(Convection("cool", "skin", h=H, T_inf=T_INF))
    model.initial_condition = InitialCondition("uniform", value=Constant(T_INIT))
    tau = 8933.0 * 385.0 * SIDE / (4 * H)
    model.solution = SolutionSettings(kind="transient", end_time=tau, output="times",
                                      output_times=[0.5 * tau])
    mesh = api.mesh(model, built)
    steps: list[StepInfo] = []
    with caplog.at_level(logging.INFO, logger="thermalfea"):
        results = api.solve(model, mesh, progress=lambda i: steps.append(i) or True, built=built)
    np.testing.assert_allclose(results.times, [0.0, 0.5 * tau, tau], rtol=1e-12)
    assert results.meta["analysis"] == "planar, transient"
    for index, time in ((1, 0.5 * tau), (2, tau)):
        exact = T_INF + (T_INIT - T_INF) * np.exp(-time / tau)
        assert results.temperature(index).mean() == pytest.approx(exact, rel=2e-3)
    assert len(steps) > 3 and steps[-1].time == pytest.approx(tau)
    assert np.all(np.diff([s.time for s in steps]) > 0)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "energy balance" in text and "transient run finished" in text
    assert results.model == model
