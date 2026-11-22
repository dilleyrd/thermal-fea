"""M11.18 — restart, second part: network-fed streams, the /meta rewrite, from_results checks."""

from __future__ import annotations

from pathlib import Path

import h5py
import numpy as np
import pytest

from thermalfea import api
from thermalfea.core.errors import ConvergenceError, ModelError
from thermalfea.core.functions import Constant
from thermalfea.model.bcs import (
    Convection,
    FlowNetwork,
    HeatFlux,
    NetBranch,
    NetNode,
    Stream,
)
from thermalfea.model.model import InitialCondition
from thermalfea.model.settings import SolutionSettings
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.initial import initial_temperature

LENGTH = 1.0


def plate(end_time: float, network: bool = False, q: float = 2000.0):
    """A copper plate with a cooled channel; the stream's flow comes from a network."""
    model = api.new_model(name="restart plate")
    api.Geometry(model).rectangle(0.0, 0.0, LENGTH, 0.05)
    model.mesh_settings.global_size = 0.05
    built = api.build(model)
    api.select_curves(model, built, "channel", where=lambda cv: abs(cv.center[1]) < 1e-9)
    api.select_curves(model, built, "hot", where=lambda cv: abs(cv.center[1] - 0.05) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs.append(HeatFlux("load", "hot", q=q))
    model.streams.append(
        Stream(
            name="coolant", fluid="Water", mode="in_plane", walls=["channel"], flow_area=1e-4,
            wetted_perimeter=0.04, cross_section="circular", T_inlet=300.0,
            mass_flow=None if network else 0.05, path=[(0.0, 0.0), (LENGTH, 0.0)],
        )
    )
    if network:
        model.network = FlowNetwork(
            nodes=[NetNode("in", pressure=300.0), NetNode("out", pressure=0.0)],
            branches=[NetBranch("duct", "in", "out", length=LENGTH, stream="coolant")],
        )
    model.initial_condition = InitialCondition("uniform", value=320.0)
    model.solution = SolutionSettings(
        kind="transient", end_time=end_time, initial_dt=1.0, auto_timestep=False, theta=1.0
    )
    return model, built, api.mesh(model, built)


def test_restart_with_a_network_fed_stream(tmp_path: Path) -> None:
    path = tmp_path / "net.h5"
    model, built, mesh = plate(5.0, network=True)
    first = api.solve(model, mesh, built=built, path=path)
    assert first.n_steps == 6
    model.solution.end_time = 10.0
    api.solve(model, mesh, built=built, path=path, restart=True)
    from thermalfea.post.results import Results

    more = Results(path)
    assert more.n_steps == 11 and more.times[-1] == pytest.approx(10.0)
    assert bool(np.all(more.converged))


def _meta(path: Path) -> dict:
    with h5py.File(path, "r") as f:
        return {k: f["meta"].attrs[k] for k in ("model", "model_hash", "analysis")}


def test_meta_is_kept_when_the_first_new_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "meta.h5"
    model, built, mesh = plate(5.0)
    api.solve(model, mesh, built=built, path=path)
    before = _meta(path)
    model.solution.end_time = 10.0
    model.bcs[0].q = Constant(5000.0)  # a different model

    def fail(*args, **kwargs):
        raise ConvergenceError("forced failure")

    monkeypatch.setattr("thermalfea.solver.transient.newton", fail)
    with pytest.raises(ConvergenceError):
        api.solve(model, mesh, built=built, path=path, restart=True)
    assert _meta(path) == before
    monkeypatch.undo()
    # a restart that succeeds describes the new model
    api.solve(model, mesh, built=built, path=path, restart=True)
    assert _meta(path)["model_hash"] != before["model_hash"]


def _first_results(tmp_path: Path, name: str = "first.h5"):
    model, built, mesh = plate(5.0)
    model.bcs.append(Convection("cool", "channel", h=10.0, T_inf=300.0))
    results = api.solve(model, mesh, built=built, path=tmp_path / name)
    return model, built, mesh, results


def test_from_results_refuses_other_connectivity(tmp_path: Path) -> None:
    model, built, mesh, first = _first_results(tmp_path)
    model.initial_condition = InitialCondition("from_results", results_path=str(first.path))
    problem = compile_problem(model, built, mesh)
    conn = problem.mesh.blocks[0].conn
    conn[0] = np.roll(conn[0], 1)  # same nodes, other connectivity
    with pytest.raises(ModelError, match="different mesh.*connectivity"):
        initial_temperature(problem)


def test_from_results_refuses_a_file_without_steps(tmp_path: Path) -> None:
    model, built, mesh, first = _first_results(tmp_path)
    empty = tmp_path / "empty.h5"
    empty.write_bytes(first.path.read_bytes())
    with h5py.File(empty, "r+") as f:
        for name in ("time", "dt", "iterations", "converged"):
            f["steps"][name].resize((0,))
        f["steps"]["energy"].resize((0, f["steps"]["energy"].shape[1]))
        t = f["steps"]["fields"]["T"]
        t.resize((0, t.shape[1]))
    model.initial_condition = InitialCondition("from_results", results_path=str(empty))
    with pytest.raises(ModelError, match="no steps"):
        initial_temperature(compile_problem(model, built, mesh))


def test_from_results_accepts_a_steady_file(tmp_path: Path) -> None:
    model, built, mesh = plate(5.0)
    model.bcs.append(Convection("cool", "channel", h=10.0, T_inf=300.0))
    model.solution = SolutionSettings(kind="steady")
    steady = api.solve(model, mesh, built=built, path=tmp_path / "steady.h5")
    model.solution = SolutionSettings(
        kind="transient", end_time=5.0, initial_dt=1.0, auto_timestep=False
    )
    model.initial_condition = InitialCondition("from_results", results_path=str(steady.path))
    problem = compile_problem(model, built, mesh)
    np.testing.assert_array_equal(
        initial_temperature(problem)[problem.dofs.field_dofs("T")], steady.temperature()
    )
