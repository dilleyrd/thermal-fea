"""M11.57: material provenance (``Material.source``) and the physics-only comparison."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import h5py
import pytest
from handmade import make_problem

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Constant
from thermalfea.materials import library
from thermalfea.materials.material import (
    Material,
    MaterialSource,
    PhaseChange,
    differing_properties,
    same_physics,
)
from thermalfea.model import serialize
from thermalfea.model.bcs import Convection, FixedTemperature
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.solver.results_writer import check_restart_compatible
from thermalfea.solver.run import run_transient

BCS = (
    FixedTemperature("hot", "left", T=400.0),
    Convection("air", "right", h=200.0, T_inf=280.0),
)


def mat(**kw) -> Material:
    return Material("m", Constant(10.0), Constant(7000.0), Constant(450.0), **kw)


def slab(end_time: float = 50.0):
    problem = make_problem("Q4", size=(0.1, 0.02), cells=(8, 2), k=50.0, bcs=BCS)
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(
        kind="transient", theta=0.5, initial_dt=10.0, end_time=end_time, auto_timestep=False
    )
    return problem


# ------------------------------------------------------------------------ round trips


def test_library_json_round_trip_and_none_writes_nothing() -> None:
    plain = mat()
    assert "source" not in plain.to_json()
    assert Material.from_json(plain.to_json()).source is None
    src = MaterialSource("user", "My alloy")
    back = Material.from_json(mat(source=src).to_json())
    assert back.source == src


def test_text_source_note_of_builtin_data_is_not_provenance() -> None:
    obj = {**mat().to_json(), "source": "Handbook, table 3"}
    assert Material.from_json(obj).source is None
    assert all(m.source is None for m in library.solids().values())


def test_model_json_round_trip(tmp_path: Path) -> None:
    model = api.new_model(name="plate")
    model.materials["a"] = mat(source=MaterialSource("builtin", "Copper (pure)"))
    model.materials["b"] = replace(mat(), name="b")
    data = serialize.to_json(model)
    assert data["materials"]["a"]["source"] == {"library": "builtin", "entry": "Copper (pure)"}
    again = serialize.from_json(json.loads(json.dumps(data)))
    assert again.materials["a"].source == MaterialSource("builtin", "Copper (pure)")
    assert again.materials["b"].source is None
    assert serialize.to_json(again) == data


def test_old_model_json_without_source_loads_as_none() -> None:
    model = api.new_model(name="plate")
    model.materials["a"] = mat()
    data = serialize.to_json(model)
    del data["materials"]["a"]["source"]
    assert serialize.from_json(data).materials["a"].source is None


def test_user_library_file_keeps_the_source(tmp_path: Path) -> None:
    path = tmp_path / "materials.json"
    src = MaterialSource("builtin", "Copper (pure)")
    library.save_user_library({"m": mat(source=src)}, {}, path)
    solids, _ = library.load_user_library(path)
    assert solids["m"].source == src


def test_bad_source_in_model_json_is_refused() -> None:
    model = api.new_model(name="plate")
    model.materials["a"] = mat()
    data = serialize.to_json(model)
    data["materials"]["a"]["source"] = {"library": "cloud", "entry": "x"}
    with pytest.raises(ModelError):
        serialize.from_json(data)


# ---------------------------------------------------------------------- same physics


def test_same_physics_ignores_name_and_source() -> None:
    a = mat(source=MaterialSource("builtin", "x"))
    b = replace(mat(), name="other")
    assert same_physics(a, b)
    assert differing_properties(a, b) == []


def test_same_physics_sees_each_property() -> None:
    base = mat()
    assert differing_properties(base, replace(base, k=Constant(11.0))) == ["k"]
    assert differing_properties(base, replace(base, k2=Constant(3.0))) == ["k2"]
    assert differing_properties(base, replace(base, rho=Constant(1.0))) == ["rho"]
    assert differing_properties(base, replace(base, cp=Constant(1.0))) == ["cp"]
    pc = PhaseChange(1500.0, 1600.0, 2e5)
    assert differing_properties(base, replace(base, phase_change=pc)) == ["phase_change"]
    both = replace(base, k=Constant(1.0), cp=Constant(2.0))
    assert differing_properties(base, both) == ["k", "cp"]


# --------------------------------------------------------------------------- restart


def _set_source(problem, source) -> None:
    r = next(iter(problem.regions.values()))
    r.material = replace(r.material, source=source)


def test_provenance_only_change_never_refuses_a_restart(tmp_path: Path) -> None:
    part = tmp_path / "part.h5"
    run_transient(slab(), part, T0=300.0)
    other = slab(200.0)
    _set_source(other, MaterialSource("user", "elsewhere"))
    check_restart_compatible(part, other)  # no exception
    result = run_transient(other, part, restart=True)
    assert result.times[-1] == pytest.approx(200.0)


def test_an_older_results_file_without_source_still_continues(tmp_path: Path) -> None:
    part = tmp_path / "part.h5"
    first = slab()
    _set_source(first, MaterialSource("builtin", "Copper (pure)"))
    run_transient(first, part, T0=300.0)
    with h5py.File(part, "r+") as f:
        regions = json.loads(str(f["meta"].attrs["regions"]))
        for entry in regions.values():
            assert "source" in entry["material"]
            del entry["material"]["source"]  # as written before M11.57
        f["meta"].attrs["regions"] = json.dumps(regions, sort_keys=True)
    later = slab(200.0)
    _set_source(later, MaterialSource("builtin", "Copper (pure)"))
    check_restart_compatible(part, later)


def test_a_physical_change_is_still_refused(tmp_path: Path) -> None:
    part = tmp_path / "part.h5"
    run_transient(slab(), part, T0=300.0)
    other = slab(200.0)
    r = next(iter(other.regions.values()))
    r.material = replace(r.material, k=Constant(100.0))
    with pytest.raises(ModelError, match="material, thickness or material angle"):
        check_restart_compatible(part, other)
