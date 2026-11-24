"""M11.53: one traversal of the selection references; rename and delete of a selection."""

from __future__ import annotations

import numpy as np
import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import default_instance
from thermalfea.materials.material import Material
from thermalfea.meshing.node_sets import node_sets_of
from thermalfea.model.bcs import Contact, Convection, Enclosure, EnclosureSurface, Stream
from thermalfea.model.model import InitialCondition, RegionAssignment
from thermalfea.model.selections import (
    ALL_SELECTION,
    Selection,
    check_new_selection_name,
    delete_selection,
    rename_selection,
    selection_refs,
    selection_users,
)
from thermalfea.model.serialize import to_json
from thermalfea.model.settings import Refinement


def _sel(name: str, dim: int) -> Selection:
    return Selection(name, dim, [], [])


@pytest.fixture
def model():
    """A model that uses the curve selection ``edge`` and the surface selection ``body``
    in every place a selection name can be stored."""
    m = api.new_model(name="refs")
    for name, dim in (("edge", 1), ("body", 2), ("corner", 0), ("other", 1)):
        m.selections[name] = _sel(name, dim)
    m.materials["steel"] = Material("steel", 50.0, 7800.0, 500.0)
    m.regions.append(RegionAssignment("body", "steel"))
    m.bcs.append(Convection("cooling", "edge", h=10.0, T_inf=300.0))
    off = Convection("spare", "edge", h=5.0, T_inf=300.0)
    off.active = False
    m.bcs.append(off)
    m.contacts.append(default_instance(Contact, name="joint", selection="edge"))
    m.enclosures.append(
        default_instance(Enclosure, name="cavity",
                         surfaces=[EnclosureSurface("other", 0.5), EnclosureSurface("edge", 0.8)])
    )  # fmt: skip
    m.streams.append(default_instance(Stream, name="coolant", walls=["edge", "other", "edge"]))
    ms = m.mesh_settings
    ms.curve_sizes["edge"] = 0.01
    ms.point_sizes["corner"] = 0.002
    ms.curve_divisions["edge"] = 12
    ms.structured_surfaces.append("body")
    ms.refinements.append(default_instance(Refinement, selection="edge"))
    m.initial_condition = InitialCondition("per_region", per_region={"body": 320.0})
    return m


def test_every_reference_is_found(model) -> None:
    edge = {(r.address, r.label) for r in selection_refs(model, "edge")}
    assert edge == {
        (("bcs", 0), "convection cooling"),
        (("bcs", 1), "convection spare"),  # suppressed loads count
        (("contacts", 0), "contact joint"),
        (("enclosures", 0), "enclosure cavity surface 2"),
        (("streams", 0), "stream coolant walls"),
        (("mesh_settings",), "mesh: boundary size"),
        (("mesh_settings",), "mesh: divisions"),
        (("mesh_settings",), "mesh: refinement 1"),
    }
    # the repeated wall entry is two references, one user
    assert len([r for r in selection_refs(model, "edge") if r.address == ("streams", 0)]) == 2
    assert [u.label for u in selection_users(model, "edge")].count("stream coolant walls") == 1
    body = {r.label for r in selection_refs(model, "body")}
    assert body == {"part body", "mesh: structured parts", "initial condition (per part)"}
    assert {r.label for r in selection_refs(model, "corner")} == {"mesh: point size"}
    assert selection_refs(model, "unused") == []


def test_rename_reaches_every_reference(model) -> None:
    before = to_json(model)
    assert rename_selection(model, "edge", "rim")
    assert "edge" not in model.selections and model.selections["rim"].name == "rim"
    assert list(model.selections) == ["rim", "body", "corner", "other"]  # order kept
    assert selection_refs(model, "edge") == []
    assert len(selection_refs(model, "rim")) == 9
    assert [bc.selection for bc in model.bcs] == ["rim", "rim"]
    assert model.contacts[0].selection == "rim"
    assert [s.selection for s in model.enclosures[0].surfaces] == ["other", "rim"]
    assert model.streams[0].walls == ["rim", "other", "rim"]
    ms = model.mesh_settings
    assert ms.curve_sizes == {"rim": 0.01} and ms.curve_divisions == {"rim": 12}
    assert ms.refinements[0].selection == "rim"
    # nothing else changed: renaming back restores the JSON exactly
    rename_selection(model, "rim", "edge")
    assert to_json(model) == before


def test_rename_of_a_part_selection_and_a_dict_key(model) -> None:
    rename_selection(model, "body", "plate")
    assert model.regions[0].selection == "plate"
    assert model.mesh_settings.structured_surfaces == ["plate"]
    assert model.initial_condition.per_region == {"plate": 320.0}


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("edge", "", "empty"),
        ("edge", "  ", "empty"),
        ("edge", "other", "already used"),
        ("edge", ALL_SELECTION, "reserved"),
        (ALL_SELECTION, "x", "cannot be renamed"),
        ("missing", "x", "no selection"),
    ],
)
def test_rename_refusals_change_nothing(model, old, new, message) -> None:
    model.selections[ALL_SELECTION] = _sel(ALL_SELECTION, 2)
    before = to_json(model)
    with pytest.raises(ModelError, match=message):
        rename_selection(model, old, new)
    assert to_json(model) == before


def test_rename_refuses_a_dangling_key(model) -> None:
    """A size left behind for a deleted selection must not attach itself to the renamed one."""
    model.mesh_settings.curve_sizes["ghost"] = 0.5
    before = to_json(model)
    with pytest.raises(ModelError, match="mesh settings"):
        rename_selection(model, "other", "ghost")
    assert to_json(model) == before
    with pytest.raises(ModelError, match="mesh settings"):
        check_new_selection_name(model, "ghost")


def test_rename_to_the_same_name_is_nothing(model) -> None:
    before = to_json(model)
    assert rename_selection(model, "edge", " edge ") is False
    assert to_json(model) == before


def test_delete(model) -> None:
    with pytest.raises(ModelError, match="used by .*convection cooling"):
        delete_selection(model, "edge")
    model.selections["loose"] = _sel("loose", 1)
    delete_selection(model, "loose")
    assert "loose" not in model.selections
    model.selections[ALL_SELECTION] = _sel(ALL_SELECTION, 2)
    with pytest.raises(ModelError, match="cannot be deleted"):
        delete_selection(model, ALL_SELECTION)
    with pytest.raises(ModelError, match="no selection"):
        delete_selection(model, "loose")


def test_new_selection_names(model) -> None:
    assert check_new_selection_name(model, "  fresh ") == "fresh"
    for bad in ("", ALL_SELECTION, "edge"):
        with pytest.raises(ModelError):
            check_new_selection_name(model, bad)


def test_node_sets_found_again_match_the_mesher() -> None:
    """The node sets recomputed on an existing mesh equal the mesher's for every kind."""
    model = api.new_model(name="sets")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 0.6, 0.2)
    geo.rectangle(0.0, 0.2, 0.6, 0.8)
    built = api.build(model)

    def on_x(value):
        return lambda c: abs(c.bbox[0] - value) < 1e-6 and abs(c.bbox[3] - value) < 1e-6

    api.select_curves(model, built, "right", where=on_x(0.6))
    api.select_surfaces(model, built, "lower", where=lambda s: s.bbox[4] < 0.25)
    api.select_points(model, built, "corner", where=lambda p: p.bbox[0] > 0.59 and p.bbox[1] < 1e-6)
    model.mesh_settings.global_size = 0.1
    mesh = api.mesh(model, built)
    again = node_sets_of(mesh, model, built)
    assert set(again) == set(mesh.node_sets) >= {"right", "lower", "corner", ALL_SELECTION}
    for name, nodes in mesh.node_sets.items():
        np.testing.assert_array_equal(again[name], np.sort(nodes))
    # a selection made after meshing gets a set, and a renamed one moves with its name
    api.select_curves(model, built, "left", where=on_x(0.0))
    rename_selection(model, "right", "cooled")
    later = node_sets_of(mesh, model, built)
    assert "left" in later and "right" not in later
    np.testing.assert_array_equal(later["cooled"], again["right"])
