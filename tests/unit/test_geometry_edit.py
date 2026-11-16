"""M8.5: pure helpers of the geometry tools (no Qt)."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import (
    format_str_lists,
    format_xy_list,
    parse_str_list,
    parse_str_lists,
    parse_xy_list,
)
from thermalfea.model import geometry_ops as g
from thermalfea.model.geometry_edit import (
    ANY_OPS,
    SURFACE_OPS,
    GridSnap,
    Placement,
    candidate_ids,
    dependents,
    import_format,
    ops_for_entities,
    refs_of,
    validate_op,
)


def test_grid_snap() -> None:
    snap = GridSnap(0.1, True)
    assert snap.snap(0.123, -0.26) == pytest.approx((0.1, -0.3))
    assert snap.snap(0.04, 0.06) == pytest.approx((0.0, 0.1))
    assert snap.snap(-0.001, 0.0) == (0.0, 0.0)  # no negative zero
    assert str(snap.snap(-0.001, 0.0)[0]) == "0.0"
    off = GridSnap(0.1, False)
    assert off.snap(0.123, 0.456) == (0.123, 0.456)
    with pytest.raises(ModelError):
        GridSnap(0.0)
    with pytest.raises(ModelError):
        GridSnap(-1.0)


def two_rectangles():
    model = api.new_model()
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 1.0, 1.0, id="a")
    geo.rectangle(0.5, 0.5, 1.0, 1.0, id="b")
    return model, geo, api.build(model)


def test_entities_map_back_to_operations() -> None:
    model, geo, built = two_rectangles()
    order = [op.id for op in model.geometry]
    all_tags = sorted(built.surfaces)
    assert len(all_tags) == 3  # a-only, shared, b-only
    assert ops_for_entities(order, built.op_entities, 2, all_tags) == ["a", "b"]
    only_a = [t for t in all_tags if (2, t) in built.op_entities["a"]
              and (2, t) not in built.op_entities["b"]]
    only_b = [t for t in all_tags if (2, t) in built.op_entities["b"]
              and (2, t) not in built.op_entities["a"]]
    assert ops_for_entities(order, built.op_entities, 2, only_a) == ["a"]
    assert ops_for_entities(order, built.op_entities, 2, only_b) == ["b"]
    assert ops_for_entities(order, built.op_entities, 2, []) == []
    # a restriction to allowed ids and a wrong dimension
    assert ops_for_entities(order, built.op_entities, 2, all_tags, allowed=["a"]) == ["a"]
    assert ops_for_entities(order, built.op_entities, 1, all_tags) == []


def test_latest_owner_reported_after_a_transform() -> None:
    model, geo, _ = two_rectangles()
    geo.translate(["a"], 5.0, 0.0, id="move")
    built = api.build(model)
    order = [op.id for op in model.geometry]
    moved = [t for d, t in built.op_entities["move"]]
    assert ops_for_entities(order, built.op_entities, 2, moved) == ["move"]


def test_refs_dependents_candidates() -> None:
    ops = [
        g.Point("p1", 0.0, 0.0),
        g.Point("p2", 1.0, 0.0),
        g.Line("l1", "p1", "p2"),
        g.Rectangle("r", 0.0, 0.0, 1.0, 1.0),
        g.Boolean("u", "union", ["r"], ["r2"]),
        g.SurfaceFromCurves("s", ["l1"], [["l1"]]),
    ]
    assert refs_of(ops[2]) == ["p1", "p2"]
    assert refs_of(ops[5]) == ["l1"]
    assert refs_of(ops[3]) == []
    assert dependents(ops, "p1") == ["l1"]
    assert dependents(ops, "l1") == ["s"]
    assert dependents(ops, "s") == []
    assert candidate_ids(ops, (g.Point,)) == ["p1", "p2"]
    assert candidate_ids(ops, SURFACE_OPS) == ["r", "u", "s"]
    assert set(candidate_ids(ops, ANY_OPS)) == {op.id for op in ops}


def test_validate_op() -> None:
    earlier = [g.Point("p1", 0.0, 0.0), g.Point("p2", 1.0, 0.0), g.Rectangle("r", 0, 0, 1, 1)]
    validate_op(g.Line("l", "p1", "p2"), earlier)
    with pytest.raises(ModelError, match="already used"):
        validate_op(g.Point("p1", 0.0, 0.0), earlier)
    with pytest.raises(ModelError, match="no earlier operation 'zz'"):
        validate_op(g.Line("l", "p1", "zz"), earlier)
    with pytest.raises(ModelError, match="not a point"):
        validate_op(g.Line("l", "p1", "r"), earlier)
    with pytest.raises(ModelError, match="width"):
        validate_op(g.Rectangle("x", 0, 0, 0.0, 1.0), earlier)
    with pytest.raises(ModelError, match="radius"):
        validate_op(g.Circle("x", 0, 0, -1.0), earlier)
    with pytest.raises(ModelError, match="at least three"):
        validate_op(g.Polygon("x", [(0, 0), (1, 0)]), earlier)
    with pytest.raises(ModelError, match="at least one tool"):
        validate_op(g.Boolean("x", "cut", ["r"], []), earlier)
    with pytest.raises(ModelError, match="both object and tool"):
        validate_op(g.Boolean("x", "cut", ["r"], ["r"]), earlier)
    with pytest.raises(ModelError, match="missing parameter"):
        validate_op(g.Transform("x", "translate", ["r"], {"dx": 1.0}), earlier)
    with pytest.raises(ModelError, match="scale factor"):
        validate_op(g.Transform("x", "scale", ["r"], {"factor": 0.0, "cx": 0, "cy": 0}), earlier)
    with pytest.raises(ModelError, match="file not found"):
        validate_op(g.ImportFile("x", "/no/such/file.step", "step"), earlier)
    validate_op(g.ImportFile("x", "/no/such/file.step", "step"), earlier, check_files=False)


def test_import_format() -> None:
    assert import_format("a/b.STEP") == "step"
    assert import_format("c.stp") == "step"
    assert import_format("c.brep") == "brep"
    assert import_format("c.txt") is None


def test_placement() -> None:
    point = Placement("point")
    assert point.pick(1.0, 2.0) == {"x": 1.0, "y": 2.0}
    assert point.pick(3.0, 4.0) == {"x": 3.0, "y": 4.0}  # the latest click wins
    rect = Placement("rectangle")
    assert rect.pick(2.0, 3.0) == {"x": 2.0, "y": 3.0}
    assert rect.pick(0.0, 1.0) == {"x": 0.0, "y": 1.0, "width": 2.0, "height": 2.0}
    assert rect.pick(5.0, 5.0) == {"x": 5.0, "y": 5.0}  # a third click starts again
    circle = Placement("circle")
    assert circle.pick(1.0, 1.0) == {"xc": 1.0, "yc": 1.0}
    assert circle.pick(4.0, 5.0)["radius"] == pytest.approx(5.0)
    polygon = Placement("polygon")
    polygon.pick(0.0, 0.0)
    assert polygon.pick(1.0, 0.0) == {"vertices": [(0.0, 0.0), (1.0, 0.0)]}
    translate = Placement("translate")
    assert translate.pick(1.0, 1.0) == {}
    assert translate.pick(3.0, 0.0) == {"dx": 2.0, "dy": -1.0}
    rotate = Placement("rotate")
    rotate.pick(0.0, 0.0)
    assert rotate.pick(1.0, 2.0) == {"cx": 1.0, "cy": 2.0}
    mirror = Placement("mirror")
    assert mirror.pick(0.0, 0.0) == {"x0": 0.0, "y0": 0.0}
    assert mirror.pick(1.0, 1.0) == {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}
    with pytest.raises(ModelError):
        Placement("spline")


def test_text_list_parsing() -> None:
    assert parse_str_list(" a, b ;c,, ") == ["a", "b", "c"]
    assert parse_str_lists("a, b; c") == [["a", "b"], ["c"]]
    assert format_str_lists([["a", "b"], ["c"]]) == "a, b; c"
    assert parse_xy_list("0,0; 1, 0.5") == [(0.0, 0.0), (1.0, 0.5)]
    assert parse_xy_list(format_xy_list([(0.1, 0.2), (3.0, -4.0)])) == [(0.1, 0.2), (3.0, -4.0)]
    with pytest.raises(ValueError, match="x, y"):
        parse_xy_list("1,2,3")
    with pytest.raises(ValueError):
        parse_xy_list("a,b")
