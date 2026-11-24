"""M11.56: part names (``RegionAssignment.name``) in the model layer."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.model.model import RegionAssignment, check_part_name, part_name
from thermalfea.model.selections import Selection, rename_selection
from thermalfea.model.serialize import from_json, to_json


def test_an_unnamed_part_shows_its_selection() -> None:
    assert part_name(RegionAssignment("plate", "steel")) == "plate"
    assert part_name(RegionAssignment("plate", "steel", name="Fin")) == "Fin"


def test_old_files_load_without_a_name() -> None:
    model = api.new_model(name="old")
    model.regions.append(RegionAssignment("all", "steel", name="Body"))
    data = to_json(model)
    assert data["regions"][0]["name"] == "Body"
    del data["regions"][0]["name"]  # as written before M11.56
    loaded = from_json(data)
    assert loaded.regions[0].name == "" and part_name(loaded.regions[0]) == "all"


def test_part_names_are_unique() -> None:
    model = api.new_model(name="parts")
    model.regions += [RegionAssignment("a", "m", name="Fin"), RegionAssignment("b", "m")]
    assert check_part_name(model, " Base ") == "Base"
    assert check_part_name(model, "Fin", index=0) == "Fin"  # its own name
    for bad, index in (("Fin", 1), ("b", 0), ("Fin", None), ("", None)):
        with pytest.raises(ModelError):
            check_part_name(model, bad, index)


def test_a_selection_rename_keeps_the_part_name() -> None:
    model = api.new_model(name="parts")
    model.selections["plate"] = Selection("plate", 2, [], [])
    model.regions += [RegionAssignment("plate", "m"), RegionAssignment("plate", "m", name="Kept")]
    rename_selection(model, "plate", "body")
    assert [r.selection for r in model.regions] == ["body", "body"]
    assert [part_name(r) for r in model.regions] == ["plate", "Kept"]
