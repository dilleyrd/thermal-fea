"""M3.11 — results file (Data §9) for a single step, and ``api.solve`` for steady models."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import h5py
import numpy as np
import pytest
from handmade import make_problem

from thermalfea import api
from thermalfea.core.errors import ModelError, SolverError
from thermalfea.model.bcs import Convection, FixedTemperature, HeatFlux
from thermalfea.model.model import Model
from thermalfea.post.energy import energy_balance
from thermalfea.post.results import Results
from thermalfea.solver.results_writer import ENERGY_COLUMNS, ResultsWriter, model_hash
from thermalfea.solver.run import StepInfo, run_steady
from thermalfea.solver.steady import steady_solution

W, H = 0.6, 1.0


def nafems_t4(size: float = 0.1, order: int = 1) -> tuple[Model, object, object]:
    """NAFEMS T4 (V-10): 0.6 x 1.0, k = 52, bottom 100 degC, right and top h = 750 to 0 degC."""
    model = api.new_model(name="NAFEMS T4")
    api.Geometry(model).rectangle(0.0, 0.0, W, H)
    model.mesh_settings.global_size = size
    model.mesh_settings.order = order
    built = api.build(model)
    api.select_curves(model, built, "bottom", where=lambda c: abs(c.center[1]) < 1e-9)
    api.select_curves(
        model, built, "cooled",
        where=lambda c: abs(c.center[0] - W) < 1e-9 or abs(c.center[1] - H) < 1e-9,
    )
    api.assign_region(model, "all", material="Carbon steel AISI 1010")
    model.materials["Carbon steel AISI 1010"].k = api_constant(52.0)
    model.bcs += [
        FixedTemperature("base", "bottom", T=373.15),
        Convection("cooling", "cooled", h=750.0, T_inf=273.15),
    ]
    return model, built, api.mesh(model, built)


def api_constant(value: float):
    from thermalfea.core.functions import Constant

    return Constant(value)


@pytest.fixture(scope="module")
def solved(tmp_path_factory: pytest.TempPathFactory):
    model, built, mesh = nafems_t4()
    path = tmp_path_factory.mktemp("results") / "t4.tfea.h5"
    seen: list[StepInfo] = []
    results = api.solve(model, mesh, progress=lambda info: seen.append(info) or True,
                        built=built, path=path)
    return model, mesh, results, seen, path


# ------------------------------------------------------------------------- file layout


def test_file_layout(solved) -> None:
    model, mesh, _, _, path = solved
    with h5py.File(path, "r") as f:
        meta = f["meta"].attrs
        assert meta["schema_version"] == 2  # M11.28: schema 2 adds /terms
        assert meta["analysis"] == "planar, steady"
        assert len(meta["model_hash"]) == 64 and meta["created"]
        assert json.loads(meta["settings"])["kind"] == "steady"
        assert json.loads(meta["model"])["name"] == "NAFEMS T4"
        assert f["mesh"].attrs["dim"] == 2
        assert f["mesh/nodes"].shape == (mesh.n_nodes, 2)
        block = f["mesh/blocks/0"]
        assert block.attrs["etype"] == "T3" and set(block) == {"conn", "region", "elem_ids"}
        facet = f["mesh/facets/0"]
        assert facet.attrs["etype"] == "L2" and set(facet) == {"conn", "entity", "parent_elem"}
        steps = f["steps"]
        assert steps["time"].shape == (1,) and steps["time"].maxshape == (None,)
        temperature = steps["fields/T"]
        assert temperature.shape == (1, mesh.n_nodes)
        assert temperature.maxshape == (None, mesh.n_nodes)
        assert temperature.chunks[0] == 1 and temperature.compression == "gzip"
        assert temperature.attrs["location"] == "node" and temperature.attrs["units"] == "K"
        assert set(steps) == {"time", "dt", "iterations", "converged", "energy", "fields"}
        assert list(steps["energy"].attrs["columns"]) == list(ENERGY_COLUMNS)
        names = sorted(ds.attrs["name"] for ds in f["reactions"].values())
        assert names == ["base", "cooling"]
        assert all(ds.shape == (1,) for ds in f["reactions"].values())


# ----------------------------------------------------------------------------- Results


def test_results_access(solved) -> None:
    model, mesh, results, seen, path = solved
    assert isinstance(results, Results) and results.path == path
    assert results.n_steps == 1 and "steps=1" in repr(results)
    np.testing.assert_array_equal(results.times, [0.0])
    np.testing.assert_array_equal(results.dt, [0.0])
    np.testing.assert_array_equal(results.iterations, [1])
    np.testing.assert_array_equal(results.converged, [True])
    assert results.fields == ["T"]
    t = results.temperature(0)
    assert t.shape == (mesh.n_nodes,)
    np.testing.assert_array_equal(results.temperature(-1), t)
    np.testing.assert_array_equal(results.temperature(), t)
    np.testing.assert_array_equal(results.field("T"), t)
    np.testing.assert_array_equal(results.nodal_history(5), [t[5]])
    assert 273.15 < t.min() and t.max() == pytest.approx(373.15)
    # NAFEMS T4 target at (0.6, 0.2): 18.3 degC; this coarse linear mesh is within 1.5 K
    probe = np.argmin(np.linalg.norm(mesh.nodes - [0.6, 0.2], axis=1))
    np.testing.assert_allclose(mesh.nodes[probe], [0.6, 0.2], atol=1e-12)
    assert t[probe] - 273.15 == pytest.approx(18.3, abs=1.5)
    # the progress callback was told about the one step
    assert len(seen) == 1 and seen[0].step == 0 and seen[0].converged
    assert seen[0].iterations == 1 and seen[0].time == 0.0
    for bad in (1, -2):
        with pytest.raises(ModelError, match="out of range"):
            results.temperature(bad)
    with pytest.raises(ModelError, match="no field"):
        results.field("pressure")
    with pytest.raises(ModelError, match="out of range"):
        results.nodal_history(mesh.n_nodes)


def test_mesh_and_model_round_trip(solved) -> None:
    model, mesh, results, _, _ = solved
    again = results.mesh
    again.validate()
    assert again.dim == mesh.dim and again.axisymmetric == mesh.axisymmetric
    np.testing.assert_array_equal(again.nodes, mesh.nodes)
    for a, b in zip(again.blocks, mesh.blocks, strict=True):
        assert a.etype == b.etype
        np.testing.assert_array_equal(a.conn, b.conn)
        np.testing.assert_array_equal(a.region, b.region)
        np.testing.assert_array_equal(a.elem_ids, b.elem_ids)
        assert a.conn.dtype == b.conn.dtype and a.region.dtype == b.region.dtype
    for a, b in zip(again.facets, mesh.facets, strict=True):
        assert a.etype == b.etype
        np.testing.assert_array_equal(a.conn, b.conn)
        np.testing.assert_array_equal(a.entity, b.entity)
        np.testing.assert_array_equal(a.parent_elem, b.parent_elem)
    assert again.point_nodes == mesh.point_nodes
    assert set(again.node_sets) == set(mesh.node_sets)
    for name, nodes in mesh.node_sets.items():
        np.testing.assert_array_equal(again.node_sets[name], nodes)
    assert results.model == model
    assert results.meta["model_hash"] == model_hash(api_to_json(model))
    assert results.meta["analysis"] == "planar, steady"


def api_to_json(model: Model) -> dict:
    from thermalfea.model.serialize import to_json

    return to_json(model)


def test_heat_flows_and_energy_balance(solved) -> None:
    _, _, results, _, _ = solved
    assert results.heat_flow_names == ["cooling", "base"]
    base, cooling = results.heat_flow("base")[0], results.heat_flow("cooling")[0]
    assert base > 0 > cooling  # heat enters at the hot base and leaves by convection
    assert base == pytest.approx(-cooling, rel=1e-9)
    balance = results.energy_balance()
    assert list(balance) == list(ENERGY_COLUMNS)
    assert all(v.shape == (1,) for v in balance.values())
    assert balance["heat_in"][0] == pytest.approx(base)
    assert balance["heat_out"][0] == pytest.approx(-cooling)
    assert balance["stored_rate"][0] == 0.0
    assert abs(balance["relative_imbalance"][0]) < 1e-8  # V-34, linear steady
    with pytest.raises(ModelError, match="no heat flow stored for 'nope'.*cooling, base"):
        results.heat_flow("nope")


def test_flux_is_computed_on_demand_from_the_embedded_materials(solved) -> None:
    _, mesh, results, _, _ = solved
    flux = results.flux()
    (region,) = flux
    nodes, q = flux[region]
    assert q.shape == (mesh.n_nodes, 2) and nodes.size == mesh.n_nodes
    # at the insulated left edge the x component of the flux is small
    left = np.isclose(mesh.nodes[:, 0], 0.0) & (mesh.nodes[:, 1] > 0.3)
    assert np.abs(q[left, 0]).max() < 0.1 * np.abs(q[:, 1]).max()
    assert q[:, 1].mean() > 0  # heat flows upwards, away from the hot base
    _, g = results.gradient()[region]
    np.testing.assert_allclose(q, -52.0 * g, rtol=1e-12)  # k = 52 came from the file
    qe = results.element_flux()
    assert qe.shape == (mesh.n_elements, 2)
    merged = Results.node_values(flux, mesh.n_nodes)
    np.testing.assert_array_equal(merged, q)


# ------------------------------------------------------------------------------ writer


def test_writer_on_a_hand_built_problem_and_appending(tmp_path: Path) -> None:
    problem = make_problem("Q8", bcs=(FixedTemperature("hot", "left", T=400.0),
                                      Convection("conv", "right", h=50.0, T_inf=300.0)))
    result = steady_solution(problem)
    balance = energy_balance(problem, result.T, system=result.system)
    path = tmp_path / "hand.h5"
    with ResultsWriter(path, problem) as writer:
        writer.append_step(0.0, result.T, balance=balance)
        writer.flush()
        writer.append_step(1.5, result.T + 1.0, dt=1.5, iterations=3, converged=False)
        assert writer.n_steps == 2
    results = Results(path)
    assert results.model is None and results.meta["model_hash"] == ""
    np.testing.assert_array_equal(results.times, [0.0, 1.5])
    np.testing.assert_array_equal(results.iterations, [1, 3])
    np.testing.assert_array_equal(results.converged, [True, False])
    np.testing.assert_allclose(results.temperature(1), results.temperature(0) + 1.0)
    np.testing.assert_allclose(results.nodal_history(0), [result.T[0], result.T[0] + 1.0])
    flows = results.heat_flow("conv")
    assert flows[0] == pytest.approx(balance.flows["conv"]) and np.isnan(flows[1])
    assert np.isnan(results.energy_balance()["net"][1])
    # the region properties travel with the file, so flux works without a model
    _, q = results.flux(0)[1]
    assert np.all(q[:, 0] > 0)
    with pytest.raises(RuntimeError, match="not open"):
        writer.append_step(2.0, result.T)


def test_run_steady_writes_nothing_when_the_solve_fails(tmp_path: Path) -> None:
    no_reference = (HeatFlux("in", "left", q=1.0), HeatFlux("out", "right", q=-1.0))
    problem = make_problem("Q4", bcs=no_reference)
    path = tmp_path / "fail.h5"
    with pytest.raises(SolverError):
        run_steady(problem, path)
    assert not path.exists()


def test_bad_results_files(tmp_path: Path) -> None:
    with pytest.raises(ModelError, match="not found"):
        Results(tmp_path / "missing.h5")
    junk = tmp_path / "junk.h5"
    junk.write_text("not hdf5", encoding="utf-8")
    with pytest.raises(ModelError, match="not a ThermalFEA results file"):
        Results(junk)
    other = tmp_path / "other.h5"
    with h5py.File(other, "w") as f:
        f.create_group("data")
    with pytest.raises(ModelError, match="not a ThermalFEA results file"):
        Results(other)
    future = tmp_path / "future.h5"
    with h5py.File(future, "w") as f:
        f.create_group("meta").attrs["schema_version"] = 99
    with pytest.raises(ModelError, match="schema version 99"):
        Results(future)


# --------------------------------------------------------------------------- api.solve


def test_solve_validates_when_given_the_built_geometry() -> None:
    model, built, mesh = nafems_t4()
    model.regions.clear()
    with pytest.raises(ModelError, match="no part assignment"):
        api.solve(model, mesh, built=built)


def test_solve_without_built_uses_the_stored_tags(caplog: pytest.LogCaptureFixture) -> None:
    """The call of Data §11: api.solve(model, mesh)."""
    model, built, mesh = nafems_t4()
    with caplog.at_level(logging.INFO, logger="thermalfea"):
        results = api.solve(model, mesh)
    reference = api.solve(model, mesh, built=built)
    np.testing.assert_array_equal(results.temperature(), reference.temperature())
    assert results.path.name == "NAFEMS T4.tfea.h5" and results.path.is_file()
    assert results.path != reference.path
    # every solve prints an energy balance (Plan §6)
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "energy balance" in text and "relative imbalance" in text and "cooling" in text


def test_results_path() -> None:
    assert api.results_path("C:/work/plate.tfea") == Path("C:/work/plate.tfea.h5")
