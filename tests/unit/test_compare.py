"""M11.58: the differences between the solved model and the current one."""

from __future__ import annotations

import copy

import pytest

from thermalfea import api
from thermalfea.core.functions import Constant, Table
from thermalfea.core.units import UnitSettings
from thermalfea.model import bcs
from thermalfea.model.compare import model_changes
from thermalfea.model.serialize import from_json, to_json
from thermalfea.model.settings import Refinement


@pytest.fixture
def solved():
    """A plate with two loads, a refinement and two geometry steps, as model JSON."""
    model = api.new_model(name="plate")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 1.0, 0.2)
    geo.rectangle(0.0, 0.2, 1.0, 0.3)
    built = api.build(model)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs += [
        bcs.FixedTemperature("hot", "west", T=400.0),
        bcs.Convection("cool", "east", h=100.0, T_inf=300.0),
    ]
    model.mesh_settings.refinements.append(Refinement("east", 0.01, 0.1, 0.0, 0.2))
    return to_json(model)


def edited(data, change) -> dict:
    model = from_json(copy.deepcopy(data))
    change(model)
    return to_json(model)


def test_the_same_model_has_no_changes(solved) -> None:
    assert model_changes(solved, copy.deepcopy(solved)) == []
    assert model_changes(from_json(solved), from_json(solved)) == []


def test_a_value_change_is_described_in_display_units(solved) -> None:
    def change(m):
        m.bcs[1].h = Constant(50.0)
        m.display_units = UnitSettings(temperature="degC")

    (line,) = model_changes(solved, edited(solved, change))
    assert line.startswith("Load cool: ") and "100" in line and "50" in line and "→" in line


def test_suppress_and_unsuppress(solved) -> None:
    off = edited(solved, lambda m: setattr(m.bcs[0], "active", False))
    assert model_changes(solved, off) == ["Load hot suppressed"]
    assert model_changes(off, solved) == ["Load hot unsuppressed"]


def test_a_refinement_change_falls_back_to_its_section(solved) -> None:
    def change(m):
        m.mesh_settings.refinements[0].size_min = 0.005

    (line,) = model_changes(solved, edited(solved, change))
    assert line.startswith("Mesh: ") and "changed" in line


def test_geometry_reorder_and_step_values(solved) -> None:
    flipped = copy.deepcopy(solved)
    flipped["geometry"].reverse()
    assert model_changes(solved, flipped) == ["Geometry steps reordered"]
    wider = edited(solved, lambda m: setattr(m.geometry[0], "width", 2.0))
    (line,) = model_changes(solved, wider)
    assert line.startswith(f"Geometry step {from_json(solved).geometry[0].id}: ")
    assert "1 m" in line and "2 m" in line


def test_a_value_inside_a_table_is_a_change(solved) -> None:
    def with_table(last: float):
        return lambda m: setattr(m.bcs[1], "h", Table([300.0, 400.0], [10.0, last], "T"))

    table = edited(solved, with_table(20.0))
    table2 = edited(table, with_table(25.0))
    # both are shown as "table(T)": the line says the field changed instead of a no-op arrow
    assert model_changes(table, table2) == ["Load cool: Heat-transfer coefficient h changed"]


def test_renames(solved) -> None:
    renamed = edited(solved, lambda m: setattr(m.bcs[0], "name", "base"))
    assert model_changes(solved, renamed) == ["Renamed load hot → base"]

    def rename_and_edit(m):
        m.bcs[1].name = "cooling"
        m.bcs[1].h = Constant(75.0)

    lines = model_changes(solved, edited(solved, rename_and_edit))
    assert lines[0] == "Renamed load cool → cooling" and lines[1].startswith("Load cooling: ")


def test_added_and_removed_objects(solved) -> None:
    more = edited(solved, lambda m: m.bcs.append(bcs.Adiabatic("insulated", "west")))
    assert model_changes(solved, more) == ["Added load insulated"]
    assert model_changes(more, solved) == ["Removed load insulated"]


def test_display_only_differences_are_ignored(solved) -> None:
    other = copy.deepcopy(solved)
    other["display_units"] = to_json(api.new_model())["display_units"] | {"temperature": "degC"}
    other["name"] = "renamed model"
    for sel in other["selections"].values():
        sel["tags"] = [t + 100 for t in sel["tags"]]  # cached tags, not user input
    other["selections"]["all"]["fingerprints"] = []  # the derived selection
    for mat in other["materials"].values():
        mat["source"] = {"library": "builtin", "entry": "Copper (pure)"}  # provenance only
    assert model_changes(solved, other) == []


def test_selection_changes(solved) -> None:
    other = copy.deepcopy(solved)
    other["selections"]["cooled"] = other["selections"].pop("east")
    lines = model_changes(solved, other)
    assert "Renamed selection east → cooled" in lines
    redefined = copy.deepcopy(solved)
    redefined["selections"]["west"]["fingerprints"] = []
    assert model_changes(solved, redefined) == ["Selection west redefined"]


def test_an_unknown_section_is_reported_by_name(solved) -> None:
    other = copy.deepcopy(solved)
    other["future_section"] = {"x": 1}
    assert model_changes(solved, other) == ["future_section changed"]
