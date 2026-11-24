"""M11.28 - term results (contact heat, mean coefficient) in the results file (Data §9)."""

from __future__ import annotations

import logging
from pathlib import Path

import h5py
import numpy as np
import pytest
from test_contact import contact_problem

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.units import UnitSettings
from thermalfea.model.bcs import Contact, CorrelationConvection, FixedTemperature
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.post import plots
from thermalfea.post.results import Results
from thermalfea.solver.compile import attach
from thermalfea.solver.results_writer import RESULTS_SCHEMA_VERSION, ResultsWriter
from thermalfea.solver.run import run_steady, run_transient, term_results
from thermalfea.solver.terms import State

CONTACT_KEY = "contact_heat:gap"
H_KEY = "h_mean:film"


def problem_with_terms(transient: bool = False, end: float = 40.0):
    """A two-layer slab with a contact, a fixed hot side and a correlation film on the cold one."""
    problem, contact = contact_problem("Q4", 500.0)
    attach(problem, FixedTemperature("hot", "left", T=400.0))
    attach(problem, CorrelationConvection(
        "film", "right", "vplate_natural", "Air", 300.0, char_length=0.5))
    if transient:
        cap = CapacitanceTerm()
        cap.setup(problem)
        problem.terms.append(cap)
        problem.settings = SolutionSettings(
            kind="transient", theta=1.0, initial_dt=10.0, end_time=end, auto_timestep=False
        )
    return problem, contact


def state(problem, u: np.ndarray, t: float = 0.0) -> State:
    return State(u=u, u_prev=u, t=t, dt=None, dofs=problem.dofs)


def correlation_term(problem):
    return next(t for t in problem.terms if getattr(t, "name", "") == "film")


# ------------------------------------------------------------------------ write and read


def test_steady_run_stores_the_term_results(tmp_path: Path) -> None:
    problem, contact = problem_with_terms()
    path = tmp_path / "steady.h5"
    run_steady(problem, path)
    results = Results(path)
    assert set(results.term_result_names) == {CONTACT_KEY, H_KEY}
    T = results.temperature(0)
    u = np.zeros(problem.dofs.n_dofs)
    u[problem.dofs.field_dofs("T")] = T
    heat = results.term_result(CONTACT_KEY)
    assert heat.shape == (results.n_steps,) == (1,)
    assert heat[0] == pytest.approx(contact.heat_across(state(problem, u)), rel=1e-12)
    assert heat[0] > 0.0
    h = results.term_result(H_KEY)
    assert h[0] == pytest.approx(correlation_term(problem).mean_coefficient(state(problem, u)),
                                 rel=1e-12)
    assert results.term_result_units(CONTACT_KEY) == ("power", "W")
    assert results.term_result_units(H_KEY) == ("htc", "W/(m^2 K)")
    with h5py.File(path, "r") as f:
        assert f["meta"].attrs["schema_version"] == RESULTS_SCHEMA_VERSION == 2
        ds = f["terms"]["0"]
        assert ds.attrs["name"] == results.term_result_names[0]
        assert ds.attrs["units"] in ("W", "W/(m^2 K)")


def test_transient_run_stores_one_value_per_step(tmp_path: Path) -> None:
    problem, contact = problem_with_terms(transient=True)
    path = tmp_path / "transient.h5"
    run_transient(problem, path, T0=300.0)
    results = Results(path)
    n = results.n_steps
    assert n > 2
    for name in (CONTACT_KEY, H_KEY):
        assert results.term_result(name).shape == (n,)
    term = correlation_term(problem)
    for step in (0, n // 2, n - 1):
        u = np.zeros(problem.dofs.n_dofs)
        u[problem.dofs.field_dofs("T")] = results.temperature(step)
        t = float(results.times[step])
        np.testing.assert_allclose(
            results.term_result(CONTACT_KEY)[step], contact.heat_across(state(problem, u, t)),
            rtol=1e-12,
        )
        np.testing.assert_allclose(
            results.term_result(H_KEY)[step], term.mean_coefficient(state(problem, u, t)),
            rtol=1e-12,
        )
    assert abs(results.term_result(CONTACT_KEY)[0]) < 1e-9  # uniform start: no heat yet
    assert np.isfinite(results.term_result(CONTACT_KEY)).all()
    assert abs(results.term_result(CONTACT_KEY)[-1]) > 1e-3  # heat flows once the run is under way


def test_term_results_collects_every_term() -> None:
    problem, _ = problem_with_terms()
    u = np.full(problem.dofs.n_dofs, 350.0)
    out = term_results(problem, u, 0.0)
    assert set(out) == {CONTACT_KEY, H_KEY}


def test_unknown_term_result_lists_the_available_names(tmp_path: Path) -> None:
    problem, _ = problem_with_terms()
    path = tmp_path / "steady.h5"
    run_steady(problem, path)
    results = Results(path)
    with pytest.raises(ModelError, match="contact_heat:gap"):
        results.term_result("contact_heat:nothing")
    with pytest.raises(ModelError, match="no term result"):
        results.term_result_units("h_mean:nothing")


def test_a_term_result_that_is_not_a_number_is_skipped(tmp_path: Path, caplog) -> None:
    problem, _ = problem_with_terms()
    path = tmp_path / "w.h5"
    u = np.full(problem.dofs.n_dofs, 300.0)
    with caplog.at_level(logging.WARNING, logger="thermalfea.solver.results_writer"):
        with ResultsWriter(path, problem) as writer:
            writer.append_step(0.0, u, terms={"contact_heat:vec": np.ones(3),
                                              "weird:x": np.array([2.0])})
    assert "contact_heat:vec" in caplog.text
    results = Results(path)
    assert results.term_result_names == ["weird:x"]
    assert results.term_result_units("weird:x") == ("", "")


def test_a_term_missing_in_a_step_reads_nan(tmp_path: Path) -> None:
    problem, _ = problem_with_terms()
    path = tmp_path / "w.h5"
    u = np.full(problem.dofs.n_dofs, 300.0)
    with ResultsWriter(path, problem) as writer:
        writer.append_step(0.0, u)
        writer.append_step(1.0, u, terms={CONTACT_KEY: np.array([5.0])})
        writer.append_step(2.0, u)
    values = Results(path).term_result(CONTACT_KEY)
    assert np.isnan(values[0]) and values[1] == 5.0 and np.isnan(values[2])


# ----------------------------------------------------------------------- an older file


def make_schema_1(path: Path) -> None:
    with h5py.File(path, "r+") as f:
        del f["terms"]
        f["meta"].attrs["schema_version"] = 1


def test_a_schema_1_file_still_opens(tmp_path: Path) -> None:
    problem, _ = problem_with_terms(transient=True)
    path = tmp_path / "old.h5"
    run_transient(problem, path, T0=300.0)
    expected_T = Results(path).temperature(-1)
    make_schema_1(path)
    results = Results(path)
    assert results.meta["schema_version"] == 1
    assert results.term_result_names == []
    np.testing.assert_array_equal(results.temperature(-1), expected_T)
    assert results.heat_flow_names
    with pytest.raises(ModelError, match="none"):
        results.term_result(CONTACT_KEY)
    with pytest.raises(ModelError, match="no contact_heat"):
        plots.term_history_data(results, "contact_heat")


def test_continuing_a_schema_1_file_adds_the_terms(tmp_path: Path) -> None:
    first, _ = problem_with_terms(transient=True, end=40.0)
    path = tmp_path / "old.h5"
    run_transient(first, path, T0=300.0)
    n_old = Results(path).n_steps
    make_schema_1(path)
    second, _ = problem_with_terms(transient=True, end=80.0)
    run_transient(second, path, restart=True)
    results = Results(path)
    assert results.meta["schema_version"] == 2
    assert results.n_steps > n_old
    values = results.term_result(CONTACT_KEY)
    assert values.shape == (results.n_steps,)
    assert np.isnan(values[:n_old]).all()
    assert np.isfinite(values[n_old:]).all()
    assert np.isfinite(results.term_result(H_KEY)[n_old:]).all()


def test_a_file_from_a_newer_schema_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "future.h5"
    with h5py.File(path, "w") as f:
        f.create_group("meta").attrs["schema_version"] = RESULTS_SCHEMA_VERSION + 1
    with pytest.raises(ModelError, match="schema version 3"):
        Results(path)


# ------------------------------------------------------------------------------ plots


def test_term_history_data_in_display_units(tmp_path: Path) -> None:
    problem, _ = problem_with_terms(transient=True)
    path = tmp_path / "t.h5"
    run_transient(problem, path, T0=300.0)
    results = Results(path)
    data = plots.term_history_data(results, "contact_heat")
    assert list(data.series) == ["gap"]
    np.testing.assert_allclose(data.series["gap"], results.term_result(CONTACT_KEY))
    assert data.ylabel.startswith("Heat across contacts [W]")
    assert data.title == "Heat across contacts"
    results.display_units = UnitSettings(power="kW")
    kw = plots.term_history_data(results, "contact_heat")
    np.testing.assert_allclose(kw.series["gap"], results.term_result(CONTACT_KEY) / 1000.0)
    assert "kW" in kw.ylabel
    h = plots.term_history_data(results, "h_mean")
    assert list(h.series) == ["film"] and h.title == "Mean heat-transfer coefficient"
    assert "W/(m" in h.ylabel
    with pytest.raises(ModelError, match="no radiation"):
        plots.term_history_data(results, "radiation")


# --------------------------------------------------------------------------- api level


def test_api_model_with_a_contact_stores_the_heat(tmp_path: Path) -> None:
    model = api.new_model(name="two blocks")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 0.5, 0.5, id="a")
    geo.rectangle(0.5, 0.0, 0.5, 0.5, id="b")
    model.mesh_settings.global_size = 0.1
    built = api.build(model)
    api.select_surfaces(model, built, "A", where=lambda fp: fp.center[0] < 0.5)
    api.select_surfaces(model, built, "B", where=lambda fp: fp.center[0] > 0.5)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.select_curves(model, built, "joint", where=lambda c: abs(c.center[0] - 0.5) < 1e-9)
    api.assign_region(model, "A", material="Copper (pure)")
    api.assign_region(model, "B", material="Copper (pure)")
    model.bcs += [
        FixedTemperature("hot", "west", T=400.0),
        FixedTemperature("cold", "east", T=300.0),
    ]
    model.contacts.append(Contact("joint", "joint", conductance=2000.0))
    mesh = api.mesh(model, built)
    results = api.solve(model, mesh, built=built, path=tmp_path / "r.h5")
    assert results.term_result_names == ["contact_heat:joint"]
    assert results.term_result("contact_heat:joint")[0] != 0.0
