"""M4.6 — ``thermalfea solve model.tfea [-o results.h5]``."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from thermalfea import api, cli
from thermalfea.core.functions import Constant
from thermalfea.model.bcs import Convection, FixedTemperature, RadiationAmbient
from thermalfea.model.model import InitialCondition, Model
from thermalfea.model.settings import SolutionSettings
from thermalfea.post.results import Results

SIDE = 0.01


def base_model(name: str) -> tuple[Model, object]:
    model = api.new_model(name=name)
    api.Geometry(model).rectangle(0.0, 0.0, SIDE, SIDE)
    model.mesh_settings.global_size = SIDE / 2
    built = api.build(model)
    api.select_curves(model, built, "left", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "right", where=lambda c: abs(c.center[0] - SIDE) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    return model, built


def steady_file(tmp_path: Path) -> Path:
    model, _ = base_model("steady case")
    model.bcs += [
        FixedTemperature("hot", "left", T=400.0),
        Convection("cool", "right", h=100.0, T_inf=300.0),
    ]
    path = tmp_path / "steady.tfea"
    api.save(model, path)
    return path


def transient_file(tmp_path: Path, **settings) -> Path:
    model, _ = base_model("transient case")
    model.bcs.append(Convection("cool", "right", h=2000.0, T_inf=300.0))
    model.initial_condition = InitialCondition("uniform", value=Constant(400.0))
    defaults = dict(kind="transient", end_time=40.0, initial_dt=10.0, auto_timestep=False)
    model.solution = SolutionSettings(**{**defaults, **settings})
    path = tmp_path / "transient.tfea"
    api.save(model, path)
    return path


def test_steady_solve_writes_results_beside_the_model(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = steady_file(tmp_path)
    assert cli.main(["solve", str(path)]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    expected = tmp_path / "steady.tfea.h5"
    assert expected.is_file()
    assert "steady case (planar, steady)" in out
    assert re.search(r"Mesh:\s+\d+ nodes, \d+ elements", out)
    assert "steady solution: 1 iteration(s)" in out
    assert re.search(r"Steps stored:\s+1 \(", out)
    assert re.search(r"^\s+hot\s+\d", out, re.M) and re.search(r"^\s+cool\s+-\d", out, re.M)
    assert "Energy balance [W]:" in out and str(expected) in out
    results = Results(expected)
    assert results.n_steps == 1 and results.temperature().max() == pytest.approx(400.0)


def test_transient_solve_prints_one_progress_line_per_step(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = transient_file(tmp_path)
    target = tmp_path / "out" / "custom.h5"
    target.parent.mkdir()
    assert cli.main(["solve", str(path), "-o", str(target)]) == 0
    out, _ = capsys.readouterr()
    lines = [ln for ln in out.splitlines() if ln.startswith("step ")]
    assert len(lines) == 4
    for n, line in enumerate(lines, start=1):
        assert re.match(rf"step\s+{n}\s+t = {10 * n} s\s+dt = 10 s\s+iterations 1\s+residual", line)
    assert lines[-1].rstrip().endswith("(100 %)") and lines[0].rstrip().endswith("(25 %)")
    assert target.is_file() and not (tmp_path / "transient.tfea.h5").exists()
    assert re.search(r"Steps stored:\s+5 \(", out) and str(target) in out
    results = Results(target)
    np.testing.assert_allclose(results.times, [0.0, 10.0, 20.0, 30.0, 40.0])
    assert results.temperature().mean() < 400.0
    # the long option works too
    assert cli.main(["solve", str(path), "--output", str(target)]) == 0


def test_exit_code_2_when_the_solution_does_not_converge(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model, _ = base_model("stubborn")
    model.bcs += [
        FixedTemperature("hot", "left", T=3000.0),
        RadiationAmbient("rad", "right", emissivity=1.0, T_inf=300.0),
    ]
    model.solution.max_iterations = 1
    path = tmp_path / "stubborn.tfea"
    api.save(model, path)
    assert cli.main(["solve", str(path)]) == 2
    out, err = capsys.readouterr()
    assert err.startswith("error: the solution did not converge")
    assert "no convergence in 1 iterations" in err


def test_exit_code_1_for_model_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["solve", str(tmp_path / "missing.tfea")]) == 1
    assert capsys.readouterr().err.startswith("error: cannot read model file")
    model, _ = base_model("no reference")  # steady, with no temperature reference
    path = tmp_path / "invalid.tfea"
    api.save(model, path)
    assert cli.main(["solve", str(path)]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error:") and "temperature reference" in err
    assert not (tmp_path / "invalid.tfea.h5").exists()


def test_console_script_in_a_subprocess(tmp_path: Path) -> None:
    """The installed entry point: real process, real exit codes."""
    path = transient_file(tmp_path)
    done = subprocess.run(
        [sys.executable, "-m", "thermalfea.cli", "solve", str(path)],
        capture_output=True, text=True, timeout=120, check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.count("\nstep ") == 4 and "Results:" in done.stdout
    assert (tmp_path / "transient.tfea.h5").is_file()
    usage = subprocess.run(
        [sys.executable, "-m", "thermalfea.cli", "--help"],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert usage.returncode == 0 and "solve" in usage.stdout and "info" in usage.stdout
