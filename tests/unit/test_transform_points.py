"""M11.34: Transforms of points and curves; Transform(copy=False) keeps the points of a shape."""

from __future__ import annotations

import math

import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.geometry.builder import BuiltGeometry, build
from thermalfea.model import geometry_ops as g
from thermalfea.model import selections
from thermalfea.model.geometry_edit import candidate_ids, op_kind, validate_op
from thermalfea.model.model import Model

CORNERS = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]


def square_ops() -> list[g.GeometryOp]:
    pts = [g.Point(f"p{i}", x, y) for i, (x, y) in enumerate(CORNERS)]
    lines = [g.Line(f"l{i}", f"p{i}", f"p{(i + 1) % 4}") for i in range(4)]
    return [*pts, *lines, g.SurfaceFromCurves("s", [f"l{i}" for i in range(4)])]


def centers(built: BuiltGeometry, op_id: str, dim: int) -> list[tuple[float, float]]:
    return [
        (built.entities(dim)[t].center[0], built.entities(dim)[t].center[1])
        for d, t in built.op_entities[op_id]
        if d == dim
    ]


def area(built: BuiltGeometry) -> float:
    return sum(fp.measure for fp in built.surfaces.values())


def expected_corners(
    kind: str, params: dict[str, float], points: list[tuple[float, float]] = CORNERS
) -> list[tuple[float, float]]:
    out = []
    for x, y in points:
        if kind == "translate":
            out.append((x + params["dx"], y + params["dy"]))
        elif kind == "rotate":
            c, s = math.cos(params["angle"]), math.sin(params["angle"])
            out.append((c * x - s * y, s * x + c * y))
        elif kind == "mirror":  # about the y axis
            out.append((-x, y))
        else:
            out.append((params["factor"] * x, params["factor"] * y))
    return out


CASES = [
    ("translate", {"dx": 3.0, "dy": -2.0}, 1.0),
    ("rotate", {"angle": 0.7, "cx": 0.0, "cy": 0.0}, 1.0),
    ("mirror", {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 1.0}, 1.0),
    ("scale", {"factor": 1.5, "cx": 0.0, "cy": 0.0}, 2.25),
]


@pytest.mark.parametrize(("kind", "params", "area_factor"), CASES)
def test_moving_a_surface_moves_its_points_and_curves(
    kind: str, params: dict[str, float], area_factor: float
) -> None:
    geometry = [*square_ops(), g.Transform("t", kind, ["s"], params)]  # type: ignore[arg-type]
    built = build(Model(geometry=geometry))
    assert area(built) == pytest.approx(2.0 * area_factor, rel=1e-9)
    want = expected_corners(kind, params)
    for i in range(4):
        (got,) = centers(built, f"p{i}", 0)
        assert got == pytest.approx(want[i], abs=1e-6)
        assert len(built.op_entities[f"l{i}"]) == 1
        assert built.op_entities[f"l{i}"][0][0] == 1
    xs, ys = [c[0] for c in want], [c[1] for c in want]
    bbox = built.surfaces[built.op_entities["s"][0][1]].bbox
    assert bbox[0] == pytest.approx(min(xs), abs=1e-6)
    assert bbox[3] == pytest.approx(max(xs), abs=1e-6)
    assert bbox[1] == pytest.approx(min(ys), abs=1e-6)
    assert bbox[4] == pytest.approx(max(ys), abs=1e-6)
    # the transform owns the moved surface, the surface operation keeps owning it
    assert built.op_entities["t"] == built.op_entities["s"]
    # nothing was lost: four points, four curves
    assert (len(built.points), len(built.curves), len(built.surfaces)) == (4, 4, 1)


def moved_xy(kind: str, params: dict[str, float], x: float, y: float) -> tuple[float, float]:
    return expected_corners(kind, params, [(x, y)])[0]


TRI = [(1.0, 0.0), (2.0, 0.0), (2.0, 1.0)]


@pytest.mark.parametrize(("kind", "params", "area_factor"), CASES)
@pytest.mark.parametrize("copy", [True, False])
def test_transforming_points(
    kind: str, params: dict[str, float], area_factor: float, copy: bool
) -> None:
    """Targets are Point operations; lines use the transformed points."""
    del area_factor
    geometry: list[g.GeometryOp] = [g.Point(f"p{i}", x, y) for i, (x, y) in enumerate(TRI)]
    geometry += [
        g.Transform(f"t{i}", kind, [f"p{i}"], params, copy=copy)  # type: ignore[arg-type]
        for i in range(3)
    ]
    geometry += [g.Line(f"l{i}", f"t{i}", f"t{(i + 1) % 3}") for i in range(3)]
    geometry.append(g.SurfaceFromCurves("s", ["l0", "l1", "l2"]))
    built = build(Model(geometry=geometry))
    for i, (x, y) in enumerate(TRI):
        assert [d for d, _ in built.op_entities[f"t{i}"]] == [0]
        assert centers(built, f"t{i}", 0) == [pytest.approx(moved_xy(kind, params, x, y), abs=1e-6)]
        if not copy:  # the Point operation owns the moved point as well
            assert built.op_entities[f"p{i}"] == built.op_entities[f"t{i}"]
        else:
            assert centers(built, f"p{i}", 0) == []  # the original bounds nothing: removed
    assert len(built.points) == 3
    f = params.get("factor", 1.0)
    assert area(built) == pytest.approx(0.5 * f * f, rel=1e-9)


@pytest.mark.parametrize(("kind", "params", "area_factor"), CASES)
@pytest.mark.parametrize("copy", [True, False])
def test_transforming_curves(
    kind: str, params: dict[str, float], area_factor: float, copy: bool
) -> None:
    """Targets are Line operations; a surface is made from the transform."""
    del area_factor
    geometry: list[g.GeometryOp] = [g.Point(f"p{i}", x, y) for i, (x, y) in enumerate(TRI)]
    geometry += [g.Line(f"l{i}", f"p{i}", f"p{(i + 1) % 3}") for i in range(3)]
    geometry += [
        g.Transform("t", kind, ["l2", "l0", "l1"], params, copy=copy),  # type: ignore[arg-type]
        g.SurfaceFromCurves("s", ["t"]),
    ]
    built = build(Model(geometry=geometry))
    assert [d for d, _ in built.op_entities["t"]] == [1, 1, 1]
    f = params.get("factor", 1.0)
    assert area(built) == pytest.approx(0.5 * f * f, rel=1e-9)
    assert (len(built.points), len(built.curves)) == (3, 3)
    if not copy:  # the Line operations own the moved curves, their points moved too
        for i, (x, y) in enumerate(TRI):
            assert len(built.op_entities[f"l{i}"]) == 1
            assert centers(built, f"p{i}", 0) == [
                pytest.approx(moved_xy(kind, params, x, y), abs=1e-6)
            ]


def test_a_copied_point_then_a_line_to_it_then_a_surface() -> None:
    geometry = [
        g.Point("a", 0.0, 0.0),
        g.Point("b", 1.0, 0.0),
        g.Point("c", 1.0, 1.0),
        g.Transform("a2", "translate", ["a"], {"dx": 0.0, "dy": 1.0}, copy=True),
        g.Line("l1", "a", "b"),
        g.Line("l2", "b", "c"),
        g.Line("l3", "c", "a2"),
        g.Line("side", "a", "a2"),  # from the original to the transformed point
        g.SurfaceFromCurves("s", ["l1", "l2", "l3", "side"]),
    ]
    model = Model(geometry=geometry)
    built = build(model)
    side = built.curves[built.op_entities["side"][0][1]]
    assert side.measure == pytest.approx(1.0, rel=1e-12)
    assert area(built) == pytest.approx(1.0, rel=1e-12)
    mesh = api.mesh(model, built)
    assert mesh.n_nodes > 4


def test_a_copied_line_in_a_loop() -> None:
    geometry = [
        *square_ops()[:8],
        g.Transform("t", "translate", ["l0", "l2", "l1", "l3"], {"dx": 4.0, "dy": 0.0}, copy=True),
        g.SurfaceFromCurves("s2", ["t"]),
    ]
    built = build(Model(geometry=geometry))
    assert area(built) == pytest.approx(2.0, rel=1e-12)
    (surface,) = built.surfaces.values()
    assert surface.bbox[0] == pytest.approx(4.0)
    # a loop of copied curves bounds a surface, so they and their points survive
    assert (len(built.points), len(built.curves)) == (4, 4)


def test_moving_a_point_used_later_by_a_line() -> None:
    geometry = [
        g.Point("a", 0.0, 0.0),
        g.Point("b", 1.0, 0.0),
        g.Point("c", 0.0, 1.0),
        g.Transform("t", "translate", ["b"], {"dx": 2.0, "dy": 0.0}),  # copy=False
        g.Line("l1", "a", "b"),  # the Point operation, which now is at (3, 0)
        g.Line("l2", "t", "c"),
        g.Line("l3", "c", "a"),
        g.SurfaceFromCurves("s", ["l1", "l2", "l3"]),
    ]
    built = build(Model(geometry=geometry))
    assert centers(built, "b", 0) == [pytest.approx((3.0, 0.0), abs=1e-6)]
    assert built.op_entities["b"] == built.op_entities["t"]
    assert area(built) == pytest.approx(1.5, rel=1e-12)
    assert sorted(fp.measure for fp in built.curves.values()) == pytest.approx(
        [1.0, 3.0, math.sqrt(10.0)]
    )



def test_a_transformed_point_survives_cleaning_when_its_line_bounds_a_surface() -> None:
    geometry = [
        g.Point("a", 0.0, 0.0),
        g.Point("b", 1.0, 0.0),
        g.Point("c", 0.0, 1.0),
        g.Point("loose", 5.0, 5.0),
        g.Transform("b2", "translate", ["b"], {"dx": 1.0, "dy": 0.0}, copy=True),
        g.Transform("loose2", "translate", ["loose"], {"dx": 1.0, "dy": 0.0}, copy=True),
        g.Line("l1", "a", "b2"),
        g.Line("l2", "b2", "c"),
        g.Line("l3", "c", "a"),
        g.SurfaceFromCurves("s", ["l1", "l2", "l3"]),
    ]
    built = build(Model(geometry=geometry))
    assert len(built.points) == 3
    assert built.op_entities["b2"] and built.op_entities["loose2"] == []
    assert area(built) == pytest.approx(1.0, rel=1e-12)


def test_validate_op_accepts_transformed_points_and_curves() -> None:
    earlier = [
        g.Point("p1", 0.0, 0.0),
        g.Point("p2", 1.0, 0.0),
        g.Rectangle("r", 0, 0, 1, 1),
        g.Line("l", "p1", "p2"),
        g.Transform("tp", "translate", ["p1"], {"dx": 1.0, "dy": 0.0}, copy=True),
        g.Transform("tt", "rotate", ["tp"], {"angle": 1.0, "cx": 0.0, "cy": 0.0}),
        g.Transform("tl", "translate", ["l"], {"dx": 1.0, "dy": 0.0}, copy=True),
        g.Transform("tr", "translate", ["r"], {"dx": 1.0, "dy": 0.0}, copy=True),
        g.Transform("mixed", "translate", ["p1", "l"], {"dx": 1.0, "dy": 0.0}),
    ]
    assert [op_kind(earlier[i], earlier[:i]) for i in (4, 5, 6, 7, 8)] == [
        "point", "point", "curve", "surface", "surface",
    ]  # fmt: skip
    validate_op(g.Line("n", "p1", "tp"), earlier)
    validate_op(g.Line("n", "tt", "tp"), earlier)  # a transform of a transform
    validate_op(g.Arc("n", "p1", "tp", "p2"), earlier)
    validate_op(g.Spline("n", ["p1", "tp", "p2"]), earlier)
    validate_op(g.SurfaceFromCurves("n", ["l", "tl"]), earlier)
    validate_op(g.Transform("n", "translate", ["tp"], {"dx": 0.0, "dy": 0.0}), earlier)
    with pytest.raises(ModelError, match="'tr' is a Transform, not a point"):
        validate_op(g.Line("n", "tr", "p2"), earlier)
    with pytest.raises(ModelError, match="not a line/arc/spline"):
        validate_op(g.SurfaceFromCurves("n", ["tp"]), earlier)
    with pytest.raises(ModelError, match="not a point"):
        validate_op(g.Line("n", "mixed", "p2"), earlier)
    with pytest.raises(ModelError, match="not a rectangle"):
        validate_op(g.Boolean("n", "union", ["tp"], ["r"]), earlier)
    validate_op(g.Boolean("n", "union", ["tr"], ["r"]), earlier)
    assert candidate_ids(earlier, (g.Point,)) == ["p1", "p2", "tp", "tt"]
    assert candidate_ids(earlier, (g.Line,)) == ["l", "tl"]


def test_a_rebuild_keeps_the_selections_of_moved_entities() -> None:
    model = Model(geometry=[*square_ops(), g.Transform("t", "rotate", ["s"], {
        "angle": 0.4, "cx": 0.5, "cy": 0.2}), g.Rectangle("other", 10.0, 0.0, 3.0, 3.0)])
    built = api.build(model)
    one = api.select_curves(model, built, "edge", where=lambda c: abs(c.measure - 1.0) < 1e-9)
    corners = api.select_points(model, built, "corners", where=lambda p: p.center[0] < 5.0)
    body = api.select_surfaces(model, built, "body", where=lambda s: abs(s.measure - 2.0) < 1e-9)
    assert (len(one.tags), len(corners.tags), len(body.tags)) == (2, 4, 1)
    before = {name: sorted(model.selections[name].tags) for name in ("edge", "corners", "body")}
    before_fp = {n: list(model.selections[n].fingerprints) for n in before}

    # an unrelated change of the model, then a second build
    model.geometry[-1].width = 4.0  # type: ignore[attr-defined]
    rebuilt = api.build(model)
    assert selections.refresh(model.selections, rebuilt) == {}
    for name, tags in before.items():
        assert sorted(model.selections[name].tags) == tags
        entities = rebuilt.entities(model.selections[name].dim)
        for tag, fp in zip(model.selections[name].tags, before_fp[name], strict=True):
            assert selections.fingerprint_matches(fp, entities[tag], rebuilt.diagonal)
    # the operations still own the moved entities
    assert len(rebuilt.op_entities["l0"]) == 1 and len(rebuilt.op_entities["p3"]) == 1
