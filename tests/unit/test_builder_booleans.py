"""M2.5 — builder: booleans, transforms, final fragment, fingerprints."""

from __future__ import annotations

import math

import numpy as np
import pytest

from thermalfea.core.errors import GeometryError
from thermalfea.geometry.builder import POLYLINE_POINTS, BuiltGeometry, build
from thermalfea.model import geometry_ops as g
from thermalfea.model.model import Model

W, H, R = 0.6, 1.0, 0.1


def area(built: BuiltGeometry, op_id: str | None = None) -> float:
    if op_id is None:
        return sum(fp.measure for fp in built.surfaces.values())
    return sum(built.surfaces[t].measure for d, t in built.op_entities[op_id] if d == 2)


def plate_with_hole() -> Model:
    return Model(
        geometry=[
            g.Rectangle("plate", 0.0, 0.0, W, H),
            g.Circle("hole", 0.3, 0.5, R),
            g.Boolean("cut", "cut", ["plate"], ["hole"]),
        ]
    )


def two_touching() -> Model:
    return Model(
        geometry=[g.Rectangle("left", 0.0, 0.0, 1.0, 1.0), g.Rectangle("right", 1.0, 0.0, 2.0, 1.0)]
    )


# ------------------------------------------------------------------------- acceptance


def test_plate_with_hole_area() -> None:
    built = build(plate_with_hole())
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(W * H - math.pi * R**2, rel=1e-10)
    # op-id map follows the boolean: the plate became the cut result, the hole is gone
    assert built.op_entities["cut"] == built.op_entities["plate"] != []
    assert built.op_entities["hole"] == []
    assert len(built.curves) == 5  # four sides and the circle
    circle = [fp for fp in built.curves.values() if fp.measure == pytest.approx(2 * math.pi * R)]
    assert len(circle) == 1
    assert circle[0].center == pytest.approx((0.3, 0.5, 0.0), abs=1e-9)


def test_two_touching_rectangles_share_exactly_one_curve() -> None:
    built = build(two_touching())
    assert len(built.surfaces) == 2
    shared = [tag for tag, surfs in built.curve_surfaces.items() if len(surfs) > 1]
    assert len(shared) == 1
    fp = built.curves[shared[0]]
    assert fp.measure == pytest.approx(1.0)
    assert fp.center == pytest.approx((1.0, 0.5, 0.0), abs=1e-12)
    assert sorted(built.curve_surfaces[shared[0]]) == sorted(built.surfaces)
    assert len(built.curves) == 7 and len(built.points) == 6
    assert area(built, "left") == pytest.approx(1.0)
    assert area(built, "right") == pytest.approx(2.0)
    # every other curve bounds exactly one surface
    assert sorted(len(s) for s in built.curve_surfaces.values()) == [1] * 6 + [2]


@pytest.mark.parametrize("make", [plate_with_hole, two_touching])
def test_rebuild_gives_identical_fingerprints(make) -> None:
    first, second = build(make()), build(make())
    assert second.serial == first.serial + 1
    assert first.surfaces == second.surfaces
    assert first.curves == second.curves
    assert first.points == second.points
    assert first.curve_surfaces == second.curve_surfaces
    assert first.op_entities == second.op_entities
    assert first.bbox == second.bbox
    for tag, line in first.curve_polylines.items():
        np.testing.assert_array_equal(line, second.curve_polylines[tag])


# ------------------------------------------------------------------ BuiltGeometry data


def test_fingerprints_adjacency_and_polylines() -> None:
    built = build(plate_with_hole())
    (surface,) = built.surfaces.values()
    assert surface.dim == 2
    assert surface.center == pytest.approx((0.3, 0.5, 0.0), abs=1e-9)
    assert surface.bbox == pytest.approx((0.0, 0.0, 0.0, W, H, 0.0), abs=1e-6)
    assert built.bbox == pytest.approx((0.0, 0.0, 0.0, W, H, 0.0), abs=1e-6)
    assert built.diagonal == pytest.approx(math.hypot(W, H), rel=1e-6)
    assert built.entities(1) is built.curves
    assert all(fp.dim == 1 and fp.measure > 0 for fp in built.curves.values())
    assert sum(fp.measure for fp in built.curves.values()) == pytest.approx(
        2 * (W + H) + 2 * math.pi * R
    )
    for fp in built.points.values():
        assert fp.dim == 0 and fp.measure == 0.0
        assert fp.bbox == fp.center + fp.center
    corners = {(round(fp.center[0], 9), round(fp.center[1], 9)) for fp in built.points.values()}
    assert {(0.0, 0.0), (W, 0.0), (W, H), (0.0, H)} <= corners
    assert set(built.curve_polylines) == set(built.curves) == set(built.curve_surfaces)
    for tag, line in built.curve_polylines.items():
        assert line.shape == (POLYLINE_POINTS, 3)
        assert np.all(line[:, 2] == 0.0)
        chord = np.linalg.norm(np.diff(line, axis=0), axis=1).sum()
        assert chord == pytest.approx(built.curves[tag].measure, rel=2e-3)


def test_empty_model() -> None:
    built = build(Model())
    assert built.surfaces == {} and built.curves == {} and built.points == {}
    assert built.diagonal == 0.0


# ---------------------------------------------------------------------------- booleans


def test_union_of_overlapping_rectangles() -> None:
    built = build(
        Model(
            geometry=[
                g.Rectangle("a", 0.0, 0.0, 2.0, 1.0),
                g.Rectangle("b", 1.0, 0.0, 2.0, 1.0),
                g.Boolean("u", "union", ["a"], ["b"]),
            ]
        )
    )
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(3.0)
    assert built.op_entities["u"] == built.op_entities["a"] == built.op_entities["b"]


def test_intersection() -> None:
    built = build(
        Model(
            geometry=[
                g.Rectangle("a", 0.0, 0.0, 2.0, 1.0),
                g.Rectangle("b", 1.5, 0.5, 2.0, 1.0),
                g.Boolean("i", "intersect", ["a"], ["b"]),
            ]
        )
    )
    assert area(built) == pytest.approx(0.5 * 0.5)
    assert len(built.surfaces) == 1


def test_overlapping_surfaces_are_fragmented_without_a_boolean() -> None:
    """Inset second material: a disc drawn on top of a plate becomes its own region."""
    built = build(
        Model(geometry=[g.Rectangle("plate", 0.0, 0.0, W, H), g.Circle("inset", 0.3, 0.5, R)])
    )
    assert len(built.surfaces) == 2
    assert area(built) == pytest.approx(W * H, rel=1e-10)
    assert area(built, "inset") == pytest.approx(math.pi * R**2, rel=1e-10)
    assert area(built, "plate") == pytest.approx(W * H, rel=1e-10)  # owns both pieces
    interface = [t for t, s in built.curve_surfaces.items() if len(s) > 1]
    assert len(interface) == 1
    assert built.curves[interface[0]].measure == pytest.approx(2 * math.pi * R)


def test_cut_then_later_op_uses_the_result() -> None:
    model = plate_with_hole()
    model.geometry += [
        g.Circle("hole2", 0.3, 0.8, 0.05),
        g.Boolean("cut2", "cut", ["plate"], ["hole2"]),  # "plate" now means the cut plate
    ]
    built = build(model)
    assert area(built) == pytest.approx(W * H - math.pi * (R**2 + 0.05**2), rel=1e-10)
    assert built.op_entities["plate"] == built.op_entities["cut"] == built.op_entities["cut2"]


# -------------------------------------------------------------------------- transforms


def centre_of(built: BuiltGeometry, op_id: str) -> tuple[float, float]:
    ((_, tag),) = [e for e in built.op_entities[op_id] if e[0] == 2]
    return built.surfaces[tag].center[:2]


@pytest.mark.parametrize(
    ("kind", "params", "centre", "scale"),
    [
        ("translate", {"dx": 3.0, "dy": -1.0}, (4.0, -0.5), 1.0),
        ("rotate", {"angle": math.pi / 2, "cx": 0.0, "cy": 0.0}, (-0.5, 1.0), 1.0),
        ("mirror", {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 1.0}, (-1.0, 0.5), 1.0),
        ("mirror", {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 1.0}, (0.5, 1.0), 1.0),
        ("scale", {"factor": 2.0, "cx": 0.0, "cy": 0.0}, (2.0, 1.0), 4.0),
    ],
)
def test_transform(kind: str, params: dict, centre: tuple, scale: float) -> None:
    base = g.Rectangle("r", 0.0, 0.0, 2.0, 1.0)  # centre (1, 0.5), area 2
    moved = build(Model(geometry=[base, g.Transform("t", kind, ["r"], params)]))
    assert len(moved.surfaces) == 1
    assert centre_of(moved, "t") == pytest.approx(centre, abs=1e-9)
    assert moved.op_entities["t"] == moved.op_entities["r"]
    assert area(moved) == pytest.approx(2.0 * scale)

    far = {**params, "dx": 30.0} if kind == "translate" else params
    copied = build(Model(geometry=[base, g.Transform("t", kind, ["r"], far, copy=True)]))
    # the original stays; each operation owns all of its (possibly fragmented) pieces
    assert area(copied, "r") == pytest.approx(2.0)
    assert area(copied, "t") == pytest.approx(2.0 * scale)
    shared = set(copied.op_entities["t"]) & set(copied.op_entities["r"])
    if kind in ("translate", "rotate") or params.get("x1") == 0.0:
        assert not shared  # the copy does not overlap the original
        assert len(copied.surfaces) == 2
        assert centre_of(copied, "r") == pytest.approx((1.0, 0.5), abs=1e-9)
        expected = (centre[0] + 27.0, centre[1]) if kind == "translate" else centre
        assert centre_of(copied, "t") == pytest.approx(expected, abs=1e-9)
    else:  # overlapping copy: the final fragment splits both along each other
        assert shared
        assert sum(fp.measure for fp in copied.surfaces.values()) < 2.0 + 2.0 * scale


def test_transform_errors() -> None:
    r = g.Rectangle("r", 0.0, 0.0, 1.0, 1.0)
    for op, message in (
        (g.Transform("t", "translate", ["r"], {"dx": 1.0}), "lacks parameter 'dy'"),
        (g.Transform("t", "mirror", ["r"], {"x0": 0, "y0": 0, "x1": 0, "y1": 0}), "coincide"),
        (g.Transform("t", "scale", ["r"], {"factor": 0.0, "cx": 0, "cy": 0}), "positive"),
        (g.Transform("t", "translate", [], {"dx": 1.0, "dy": 0.0}), "at least one target"),
        (g.Transform("t", "translate", ["nope"], {"dx": 1.0, "dy": 0.0}), "unknown"),
        (g.Boolean("t", "cut", ["r"], []), "at least one object and one tool"),
    ):
        with pytest.raises(GeometryError, match=f"operation 't' .*{message}"):
            build(Model(geometry=[r, op]))


def test_delete() -> None:
    built = build(
        Model(
            geometry=[
                g.Rectangle("keep", 0.0, 0.0, 1.0, 1.0),
                g.Rectangle("drop", 5.0, 0.0, 1.0, 1.0),
                g.Delete("d", ["drop"]),
            ]
        )
    )
    assert len(built.surfaces) == 1
    assert built.op_entities["drop"] == [] and built.op_entities["d"] == []
    assert len(built.curves) == 4 and len(built.points) == 4
    with pytest.raises(GeometryError, match="operation 'u' .*at least one object"):
        build(
            Model(
                geometry=[
                    g.Rectangle("a", 0, 0, 1, 1),
                    g.Rectangle("b", 5, 0, 1, 1),
                    g.Delete("d", ["b"]),
                    g.Boolean("u", "union", ["a"], ["b"]),
                ]
            )
        )


def test_pattern_of_copies_fragments_into_shared_edges() -> None:
    """Three unit squares in a row made by copy-translate share two interface curves."""
    built = build(
        Model(
            geometry=[
                g.Rectangle("a", 0.0, 0.0, 1.0, 1.0),
                g.Transform("b", "translate", ["a"], {"dx": 1.0, "dy": 0.0}, copy=True),
                g.Transform("c", "translate", ["b"], {"dx": 1.0, "dy": 0.0}, copy=True),
            ]
        )
    )
    assert len(built.surfaces) == 3
    assert sum(len(s) > 1 for s in built.curve_surfaces.values()) == 2
    assert len(built.curves) == 10 and len(built.points) == 8
    assert [centre_of(built, k)[0] for k in "abc"] == pytest.approx([0.5, 1.5, 2.5])
