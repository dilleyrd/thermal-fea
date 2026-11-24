"""M11.31 — rows without capacitance (stream fluid rows) are stepped with theta = 1 (Theory §6).

A fluid row is algebraic: with theta < 1 the scheme theta g(n+1) + (1 - theta) g(n) = 0
would carry an imbalance g(n) of the start forward as g(n+1) = -g(n) for ever (an
alternating outlet temperature). A restart with a changed mass flow starts from such an
imbalance (REVIEW-2 2.1-3).
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import numpy as np
import pytest

from thermalfea import api
from thermalfea.model.bcs import HeatFlux, Stream
from thermalfea.model.model import InitialCondition
from thermalfea.model.settings import SolutionSettings
from thermalfea.solver import transient as tr

LENGTH = 1.0


def plate(h_override: float | None):
    """A copper plate heated on top and cooled by an in-plane water stream underneath."""
    model = api.new_model(name="fluid rows")
    api.Geometry(model).rectangle(0.0, 0.0, LENGTH, 0.05)
    model.mesh_settings.global_size = 0.05
    built = api.build(model)
    api.select_curves(model, built, "channel", where=lambda cv: abs(cv.center[1]) < 1e-9)
    api.select_curves(model, built, "hot", where=lambda cv: abs(cv.center[1] - 0.05) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs.append(HeatFlux("load", "hot", q=20000.0))
    model.streams.append(
        Stream(
            name="coolant", fluid="Water", mode="in_plane", walls=["channel"], flow_area=1e-4,
            wetted_perimeter=0.04, cross_section="circular", T_inlet=300.0, mass_flow=0.05,
            path=[(0.0, 0.0), (LENGTH, 0.0)], h_override=h_override,
        )
    )
    model.initial_condition = InitialCondition("uniform", value=320.0)
    model.solution = SolutionSettings(
        kind="transient", end_time=5.0, initial_dt=1.0, auto_timestep=False, theta=0.5
    )
    return model, built, api.mesh(model, built)


@pytest.mark.parametrize("h_override", [2000.0, None], ids=["linear", "nonlinear"])
def test_a_restart_with_a_changed_mass_flow_does_not_alternate(
    tmp_path: Path, h_override: float | None
) -> None:
    path = tmp_path / "rows.h5"
    model, built, mesh = plate(h_override)
    api.solve(model, mesh, built=built, path=path)
    model.streams[0] = dataclasses.replace(model.streams[0], mass_flow=0.01)
    model.solution.end_time = 15.0
    more = api.solve(model, mesh, built=built, path=path, restart=True)
    out = more.stream("coolant")["T_out"][5:]  # from the restart time on
    # the outlet warms smoothly towards its new level: no step-to-step sign changes
    steps = np.diff(out)
    assert np.all(steps > 0.0), steps
    # each step's energy balance stays closed
    imbalance = more.energy_balance()["relative_imbalance"][6:]
    assert np.all(np.abs(imbalance) < 1e-6), imbalance


def test_fluid_rows_use_theta_one_and_solid_rows_theta(tmp_path: Path) -> None:
    model, built, mesh = plate(2000.0)
    seen: list = []
    real = tr.StepSystem.__init__

    def spy(self, base, C, u_prev, g_prev, dt, theta):
        has_c = np.asarray(abs(C).sum(axis=1)).ravel() != 0.0
        seen.append((has_c, np.broadcast_to(theta, u_prev.shape)))
        real(self, base, C, u_prev, g_prev, dt, theta)

    tr.StepSystem.__init__ = spy
    try:
        api.solve(model, mesh, built=built, path=tmp_path / "theta.h5")
    finally:
        tr.StepSystem.__init__ = real
    has_c, theta = seen[-1]  # a step after the start-up step
    assert not has_c.all()  # the fluid rows have no capacitance
    np.testing.assert_array_equal(theta[~has_c], 1.0)
    np.testing.assert_array_equal(theta[has_c], 0.5)


def test_a_restart_resolves_the_fluid_for_the_stored_walls(tmp_path: Path) -> None:
    path = tmp_path / "resolve.h5"
    model, built, mesh = plate(100.0)  # NTU about 0.5: the fluid does not just follow the wall
    first = api.solve(model, mesh, built=built, path=path)
    stored_out = float(first.stream("coolant")["T_out"][-1])
    calls: list = []
    real = tr._resolve_algebraic

    def spy(problem, T, t0, algebraic, solver):
        result = real(problem, T, t0, algebraic, solver)
        calls.append((T.copy(), result, algebraic.copy()))
        return result

    tr._resolve_algebraic = spy
    try:
        model.streams[0] = dataclasses.replace(model.streams[0], mass_flow=0.01)
        model.solution.end_time = 6.0
        api.solve(model, mesh, built=built, path=path, restart=True)
    finally:
        tr._resolve_algebraic = real
    assert len(calls) == 1
    before, after, fluid = calls[0]
    assert stored_out == pytest.approx(before[fluid][-1])
    # the solid temperatures are held at their stored values
    np.testing.assert_array_equal(after[~fluid], before[~fluid])
    # a fifth of the flow takes up the heat of the same walls: the outlet is re-solved
    # much warmer at once
    assert after[fluid][-1] - 300.0 > 2.0 * (before[fluid][-1] - 300.0)
