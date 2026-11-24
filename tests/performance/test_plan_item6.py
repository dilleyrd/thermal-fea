"""M11.3 — Plan §6 item 6: a 100 000-node linear transient model runs 100 steps in under 60 s.

The whole pipeline is timed through the API, as a user would run it: geometry, mesh,
compile, 100 fixed steps and the results file (every step stored). On the development
laptop it takes about 13 s (mesh 7 s, solve 5 s).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from thermalfea import api
from thermalfea.model.bcs import Convection, FixedTemperature
from thermalfea.model.model import InitialCondition
from thermalfea.model.settings import SolutionSettings

#: Plan §6 item 6.
NODES, STEPS, BUDGET_S = 100_000, 100, 60.0


def test_a_100k_node_linear_transient_runs_100_steps_in_under_60_s(tmp_path: Path) -> None:
    start = time.perf_counter()
    model = api.new_model(name="plan item 6")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 1.0)
    model.mesh_settings.global_size = 0.0033
    built = api.build(model)
    api.select_curves(model, built, "left", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "right", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs += [FixedTemperature("hot", "left", T=400.0),
                  Convection("cool", "right", h=50.0, T_inf=300.0)]
    model.initial_condition = InitialCondition("uniform", value=300.0)
    model.solution = SolutionSettings(kind="transient", end_time=float(STEPS), initial_dt=1.0,
                                      auto_timestep=False, theta=1.0)
    mesh = api.mesh(model, built)
    assert mesh.n_nodes >= NODES
    results = api.solve(model, mesh, built=built, path=tmp_path / "item6.h5")
    elapsed = time.perf_counter() - start
    assert results.n_steps == STEPS + 1  # the initial state and every step
    assert bool(results.converged.all())
    T = results.temperature()
    assert T.min() >= 300.0 - 1e-6 and T.max() == pytest.approx(400.0)
    assert elapsed < BUDGET_S, f"{mesh.n_nodes} nodes, {STEPS} steps took {elapsed:.1f} s"
