"""M5.6 — text summary of a results file: numbers, units, text layout and warnings."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from handmade import make_problem

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.units import UnitSettings
from thermalfea.model.bcs import Convection, FixedTemperature
from thermalfea.model.model import Model
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.post.energy import EnergyBalance, energy_balance
from thermalfea.post.results import Results
from thermalfea.post.summary import format_summary, summarize, text_summary
from thermalfea.solver.results_writer import ResultsWriter
from thermalfea.solver.run import run_transient
from thermalfea.solver.steady import steady_solution

RHO, CP, SIDE = 7800.0, 500.0, 0.01
H, T_INF, T_INIT = 20.0, 300.0, 400.0
TAU = RHO * CP * SIDE * SIDE / (H * 4 * SIDE)
SIDES = ("bottom", "right", "top", "left")
SECTIONS = (
    "Analysis:", "Mesh:", "Steps stored:", "Temperature:", "Iterations:",
    "Heat entering the body [W]:", "Energy balance [W]:",
)


def lumped(**settings):
    problem = make_problem("Q4", size=(SIDE, SIDE), cells=(2, 2), k=400.0, bcs=tuple(
        Convection(f"conv-{side}", side, h=H, T_inf=T_INF) for side in SIDES))
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    defaults = dict(kind="transient", theta=1.0, initial_dt=TAU / 20, end_time=TAU,
                    auto_timestep=False)
    problem.settings = SolutionSettings(**{**defaults, **settings})
    return problem


@pytest.fixture
def transient(tmp_path: Path) -> Results:
    path = tmp_path / "t.h5"
    run_transient(lumped(), path, T0=T_INIT)
    return Results(path)


def write_file(path: Path, problem, steps) -> Results:
    """A results file written by hand: ``steps`` is a list of (time, u, options)."""
    with ResultsWriter(path, problem) as writer:
        for time, u, options in steps:
            writer.append_step(time, u, **options)
    return Results(path)


@pytest.fixture
def steady(tmp_path: Path) -> Results:
    problem = make_problem("Q4", bcs=(FixedTemperature("hot", "left", T=400.0),
                                      Convection("cool", "right", h=50.0, T_inf=300.0)))
    result = steady_solution(problem)
    balance = energy_balance(problem, result.T, system=result.system)
    return write_file(tmp_path / "s.h5", problem,
                      [(0.0, result.T, dict(balance=balance))])


# ------------------------------------------------------------------------------- summarize


def test_summary_of_the_last_step(transient: Results) -> None:
    s = summarize(transient)
    assert s.n_steps == 21 and s.n_steps == transient.n_steps
    assert s.time == pytest.approx(TAU) and s.end_time == pytest.approx(TAU)
    assert s.n_nodes == transient.mesh.n_nodes and s.n_elements == transient.mesh.n_elements
    # no model is embedded in these files, so the writer records only the geometry kind
    assert s.analysis == "planar, transient" and s.unit == "K"

    field = transient.temperature(-1)
    node = int(np.argmin(field))
    assert s.t_min == pytest.approx(field.min()) and s.t_min_node == node
    assert s.t_min_at == pytest.approx(tuple(transient.mesh.nodes[node, :2]))
    node = int(np.argmax(field))
    assert s.t_max == pytest.approx(field.max()) and s.t_max_node == node
    assert s.t_max_at == pytest.approx(tuple(transient.mesh.nodes[node, :2]))

    assert set(s.heat_flows) == set(transient.heat_flow_names) and len(s.heat_flows) == 4
    for name, value in s.heat_flows.items():
        assert value == pytest.approx(transient.heat_flow(name)[-1])
    for key, column in transient.energy_balance().items():
        assert s.energy[key] == pytest.approx(column[-1])

    iterations = transient.iterations
    assert s.total_iterations == int(iterations.sum())
    assert s.max_iterations == int(iterations.max())
    assert s.unconverged_steps == 0
    assert s.warnings == []


def test_initial_state_has_no_heat_flows_or_energy(transient: Results) -> None:
    s = summarize(transient, step=0)
    assert s.time == 0.0 and s.heat_flows == {}
    assert all(np.isnan(v) for v in s.energy.values())
    text = format_summary(s)
    assert text.count("(none stored for this step)") == 2
    assert "summary at t = 0 s" in text


def test_steady_single_step(steady: Results) -> None:
    s = summarize(steady)
    assert s.n_steps == 1 and s.analysis == "planar, steady"
    assert s.heat_flows["hot"] > 0.0 and s.heat_flows["cool"] < 0.0
    assert s.t_max == pytest.approx(400.0) and s.t_max_node == int(
        np.argmax(steady.temperature()))
    assert s.warnings == []
    assert "(none stored" not in format_summary(s)


# -------------------------------------------------------------------------------- warnings


def test_unconverged_step_warns(tmp_path: Path) -> None:
    problem = lumped()
    u = np.full(problem.mesh.n_nodes, 350.0)
    results = write_file(tmp_path / "c.h5", problem, [
        (0.0, u, {}), (1.0, u, dict(iterations=3, converged=False)),
    ])
    s = summarize(results)
    assert s.unconverged_steps == 1
    assert s.warnings == ["1 step(s) did not converge"]


def test_temperature_at_or_below_zero_kelvin_warns(tmp_path: Path) -> None:
    problem = make_problem("Q4")
    u = np.full(problem.mesh.n_nodes, 300.0)
    u[2] = -5.0
    results = write_file(tmp_path / "z.h5", problem, [(0.0, u, {})])
    assert summarize(results).warnings == [
        "temperatures at or below 0 K: check that temperatures are absolute"
    ]


def test_non_finite_temperature_warns(tmp_path: Path) -> None:
    problem = make_problem("Q4")
    u = np.full(problem.mesh.n_nodes, 300.0)
    u[1] = np.nan
    results = write_file(tmp_path / "n.h5", problem, [(0.0, u, {})])
    s = summarize(results)
    assert s.warnings == ["the solution contains non-finite temperatures"]
    assert np.isfinite(s.t_min) and np.isfinite(s.t_max)


def test_large_energy_imbalance_warns(tmp_path: Path) -> None:
    problem = make_problem("Q4")
    u = np.full(problem.mesh.n_nodes, 300.0)
    balance = EnergyBalance({"in": 100.0, "out": -90.0})  # imbalance 10 W of 100 W
    results = write_file(tmp_path / "e.h5", problem, [(0.0, u, dict(balance=balance))])
    s = summarize(results)
    assert s.energy["relative_imbalance"] == pytest.approx(0.1)
    assert s.warnings == ["energy imbalance is 1.0e-01 of the throughput (limit 1e-3)"]


def test_small_energy_imbalance_does_not_warn(tmp_path: Path) -> None:
    problem = make_problem("Q4")
    u = np.full(problem.mesh.n_nodes, 300.0)
    balance = EnergyBalance({"in": 100.0, "out": -99.99})  # 1e-4 of the throughput
    results = write_file(tmp_path / "e2.h5", problem, [(0.0, u, dict(balance=balance))])
    assert summarize(results).warnings == []


# ---------------------------------------------------------------------------------- format


def test_format_has_every_section_and_heat_flow(transient: Results) -> None:
    text = format_summary(summarize(transient))
    for label in SECTIONS:
        assert label in text
    lines = text.splitlines()
    for name in transient.heat_flow_names:
        assert any(line.strip().startswith(name) for line in lines)
    assert "Warnings:" not in text
    assert not text.endswith("\n")
    assert text_summary(transient) == text


def test_format_lists_each_warning(tmp_path: Path) -> None:
    problem = lumped()
    u = np.full(problem.mesh.n_nodes, 350.0)
    u[0] = np.nan
    results = write_file(tmp_path / "w.h5", problem, [
        (0.0, u, {}), (1.0, u, dict(converged=False)),
    ])
    text = format_summary(summarize(results))
    assert "Warnings:" in text
    assert "  - 1 step(s) did not converge" in text
    assert "  - the solution contains non-finite temperatures" in text
    assert not text.endswith("\n")


# -------------------------------------------------------------------------------- display unit


def test_minimum_and_maximum_in_degrees_celsius(transient: Results) -> None:
    field = transient.temperature(-1)
    kelvin = summarize(transient)
    transient.model = Model(display_units=UnitSettings(temperature="degC"))
    s = summarize(transient)
    assert s.unit == "°C"
    assert s.t_min == pytest.approx(field.min() - 273.15)
    assert s.t_max == pytest.approx(field.max() - 273.15)
    assert kelvin.t_min == pytest.approx(field.min())
    assert "°C" in text_summary(transient)


# ------------------------------------------------------------------------------------- api


def test_api_summary_matches_text_summary(transient: Results) -> None:
    assert api.summary(transient) == text_summary(transient)
    assert api.summary(transient, 0) == text_summary(transient, 0)


@pytest.mark.parametrize("step", [21, -22])
def test_bad_step_is_a_model_error(transient: Results, step: int) -> None:
    with pytest.raises(ModelError):
        api.summary(transient, step)
    with pytest.raises(ModelError):
        summarize(transient, step)
