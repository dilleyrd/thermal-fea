"""M11.63: renaming a geometry operation rewrites every reference to it."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.model import geometry_ops as g
from thermalfea.model.geometry_edit import rename_operation
from thermalfea.model.serialize import to_json


def test_every_reference_kind_follows() -> None:
    """Point, line, arc, spline, hole loop, boolean, transform and delete references."""
    model = api.new_model(name="refs")
    model.geometry = [
        g.Point("a", 0.0, 0.0), g.Point("b", 1.0, 0.0), g.Point("c", 0.0, 1.0),
        g.Line("l1", "a", "b"), g.Arc("arc", "b", "a", "c"), g.Line("l2", "c", "a"),
        g.Spline("sp", ["a", "b", "a"]),  # a repeated reference keeps both places
        g.Rectangle("hole_box", 0.1, 0.1, 0.2, 0.2, 0.0),
        g.SurfaceFromCurves("s", ["l1", "arc", "l2"], [["l1", "l2"], ["arc"]]),
        g.Rectangle("r", 2.0, 0.0, 1.0, 1.0, 0.0), g.Circle("c2", 2.5, 0.5, 0.1),
        g.Boolean("cut", "cut", ["r"], ["c2"]),
        g.Transform("move", "translate", ["cut", "s"], {"dx": 1.0, "dy": 0.0}, False),
        g.Delete("gone", ["hole_box"]),
    ]  # fmt: skip
    assert rename_operation(model, "a", "origin")
    ops = {op.id: op for op in model.geometry}
    assert "a" not in ops and isinstance(ops["origin"], g.Point)
    assert (ops["l1"].p1, ops["l2"].p2) == ("origin", "origin")
    assert ops["arc"].p_center == "origin"
    assert ops["sp"].points == ["origin", "b", "origin"]
    rename_operation(model, "l1", "base")
    assert ops["s"].curves == ["base", "arc", "l2"]
    assert ops["s"].holes == [["base", "l2"], ["arc"]]
    rename_operation(model, "r", "plate")
    rename_operation(model, "c2", "bore")
    assert (ops["cut"].objects, ops["cut"].tools) == (["plate"], ["bore"])
    rename_operation(model, "cut", "plate_with_bore")
    assert ops["move"].targets == ["plate_with_bore", "s"]
    rename_operation(model, "hole_box", "spare")
    assert ops["gone"].targets == ["spare"]


def test_a_renamed_model_builds_the_same_geometry() -> None:
    model = api.new_model(name="plate")
    geo = api.Geometry(model)
    r = geo.rectangle(0.0, 0.0, 1.0, 0.5)
    c = geo.circle(0.5, 0.25, 0.1)
    geo.cut([r], [c], id="plate")
    before = api.build(model)
    rename_operation(model, r, "outline")
    after = api.build(model)
    assert sorted(fp.measure for fp in before.surfaces.values()) == pytest.approx(
        sorted(fp.measure for fp in after.surfaces.values())
    )
    assert "outline" in after.op_entities and r not in after.op_entities


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [("missing", "x", "no geometry operation"), ("a", " ", "empty"), ("a", "b", "already used")],
)
def test_refusals_change_nothing(old, new, message) -> None:
    model = api.new_model(name="refs")
    model.geometry = [g.Point("a", 0.0, 0.0), g.Point("b", 1.0, 0.0), g.Line("l", "a", "b")]
    before = to_json(model)
    with pytest.raises(ModelError, match=message):
        rename_operation(model, old, new)
    assert to_json(model) == before


def test_the_same_id_is_nothing() -> None:
    model = api.new_model(name="refs")
    model.geometry = [g.Point("a", 0.0, 0.0)]
    assert rename_operation(model, "a", " a ") is False
