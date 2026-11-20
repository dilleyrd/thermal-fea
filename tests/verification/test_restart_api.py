"""M10.6 — restart through the API and the command line, with a stream in the model.

A run that is stopped and continued is compared with the same run made in one go.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from cases import load

from thermalfea import api, cli
from thermalfea.core.errors import ModelError
from thermalfea.model.bcs import Convection, FixedTemperature, HeatGeneration

END, DT = 40.0, 2.0


def cold_plate(end_time: float):
    """A heated strip cooled by a water stream along its lower side (as V-29), transient."""
    common, v29 = load("common"), load("v29_stream_energy")
    model, built = common.rectangle(
        "restart with a stream", "Q4", 0.0, 0.0, v29.LENGTH, v29.HEIGHT, 20, 2
    )
    model.bcs.append(HeatGeneration("heating", "all", Q=4.0e5))
    model.bcs.append(FixedTemperature("hot end", "left", T=340.0))
    model.bcs.append(Convection("air", "right", h=50.0, T_inf=300.0))
    model.streams.append(v29._stream("lower", "bottom", 0.0, 0.02))
    common.transient(
        model, 300.0, end_time=end_time, initial_dt=DT, auto_timestep=False, theta=1.0,
        rtol=1e-11, ttol=1e-11, max_iterations=60,
    )
    return model, built


def test_restart_with_a_stream_equals_one_run(tmp_path: Path) -> None:
    whole, part = tmp_path / "whole.h5", tmp_path / "part.h5"
    model, built = cold_plate(END)
    mesh = api.mesh(model, built)
    reference = api.solve(model, mesh, built=built, path=whole)

    model.solution.end_time = END / 2
    first = api.solve(model, mesh, built=built, path=part)
    assert first.times[-1] == pytest.approx(END / 2)
    model.solution.end_time = END
    seen: list[float] = []
    results = api.solve(
        model, mesh, lambda info: seen.append(info.time) or True, built=built, path=part,
        restart=True,
    )
    assert seen[0] == pytest.approx(END / 2 + DT) and seen[-1] == pytest.approx(END)
    np.testing.assert_allclose(results.times, reference.times, rtol=1e-12)
    # the fluid unknowns are restored from the file with the node temperatures
    for step in (len(seen) + 1, -1):
        np.testing.assert_allclose(
            results.temperature(step), reference.temperature(step), rtol=1e-9
        )
        np.testing.assert_allclose(
            results.fluid_temperature("lower", step), reference.fluid_temperature("lower", step),
            rtol=1e-9,
        )
    a, b = reference.stream("lower"), results.stream("lower")
    np.testing.assert_allclose(b["T_out"], a["T_out"], rtol=1e-9)
    np.testing.assert_allclose(b["heat"], a["heat"], rtol=1e-7, atol=1e-7 * np.abs(a["heat"]).max())
    assert results.model.solution.end_time == END  # the embedded model is the current one


def test_api_refusals(tmp_path: Path) -> None:
    model, built = cold_plate(END)
    mesh = api.mesh(model, built)
    with pytest.raises(ModelError, match="needs the path"):
        api.solve(model, mesh, built=built, restart=True)
    with pytest.raises(ModelError, match="results file not found"):
        api.solve(model, mesh, built=built, path=tmp_path / "none.h5", restart=True)
    model.solution.kind = "steady"
    with pytest.raises(ModelError, match="only a transient analysis"):
        api.solve(model, mesh, built=built, path=tmp_path / "none.h5", restart=True)


def test_renamed_stream_refuses_the_restart(tmp_path: Path) -> None:
    part = tmp_path / "part.h5"
    model, built = cold_plate(END / 2)
    mesh = api.mesh(model, built)
    api.solve(model, mesh, built=built, path=part)
    untouched = part.read_bytes()
    model.solution.end_time = END
    model.streams[0].name = "upper"
    with pytest.raises(ModelError, match="streams of the model are not those of the results"):
        api.solve(model, mesh, built=built, path=part, restart=True)
    assert part.read_bytes() == untouched


def test_command_line_restart(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    model, _ = cold_plate(END / 2)
    file = tmp_path / "plate.tfea"
    api.save(model, file)
    assert cli.main(["solve", str(file)]) == cli.EXIT_OK
    results = api.Results(api.results_path(file))
    assert results.times[-1] == pytest.approx(END / 2)
    n_first = results.n_steps

    assert cli.main(["solve", str(file), "--restart"]) == cli.EXIT_ERROR  # nothing to add
    assert "Set a later end time" in capsys.readouterr().err

    model.solution.end_time = END
    api.save(model, file)
    assert cli.main(["solve", str(file), "--restart"]) == cli.EXIT_OK
    assert results.times[-1] == pytest.approx(END)
    assert results.n_steps == n_first + int(round(END / 2 / DT))
