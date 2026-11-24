"""M2 gate — L-bracket with a hole and an inset second material.

Runs ``examples/l_bracket.py``: build from a script, save, load, rebuild, mesh; selections
must resolve identically. Also holds the regression tests from the review of the
builder's tag tracking.
"""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import numpy as np
import pytest

from thermalfea import api
from thermalfea.core.errors import GeometryError
from thermalfea.model.selections import fingerprint_matches

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "l_bracket.py"


@pytest.fixture(scope="module")
def example():
    spec = importlib.util.spec_from_file_location("l_bracket_example", EXAMPLE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def result(example, tmp_path_factory: pytest.TempPathFactory) -> dict:
    return example.main(tmp_path_factory.mktemp("l_bracket"))


def test_save_load_gives_an_equal_model(result: dict) -> None:
    assert result["path"].is_file()
    assert result["model_round_trip"] is True
    assert api.load(result["path"]) == result["model"]


def test_selections_resolve_identically_after_rebuild(result: dict) -> None:
    assert result["selections_identical"] is True
    assert set(result["tags"]) == {
        "all", "body", "inset", "base", "top", "hole", "inset-boundary", "corner"
    }
    assert result["resolved"] == result["tags"]
    built, model = result["built"], result["model"]
    for name, selection in model.selections.items():
        entities = built.entities(selection.dim)
        assert len(selection.tags) == len(set(selection.tags)) > 0, name
        for tag, fp in zip(selection.tags, selection.fingerprints, strict=True):
            assert fingerprint_matches(fp, entities[tag], built.diagonal), name
    sizes = {name: len(tags) for name, tags in result["tags"].items()}
    assert sizes == {
        "all": 2, "body": 1, "inset": 1, "base": 1, "top": 1, "hole": 1,
        "inset-boundary": 4, "corner": 1,
    }


def test_geometry_and_regions(result: dict, example) -> None:
    built, model = result["built"], result["model"]
    assert result["n_surfaces"] == 2
    assert len(built.curves) == 6 + 1 + 4  # outline, hole, inset
    exact = example.exact_areas()
    total = sum(fp.measure for fp in built.surfaces.values())
    assert total == pytest.approx(exact["body"] + exact["inset"], rel=1e-10)
    assert [(r.selection, r.material) for r in model.regions] == [
        ("body", "Aluminum, Alloy 2024-T6"), ("inset", "Copper (pure)"),
    ]
    assert set(model.materials) == {"Aluminum, Alloy 2024-T6", "Copper (pure)"}
    # every surface has exactly one region
    covered = [t for r in model.regions for t in model.selections[r.selection].tags]
    assert sorted(covered) == sorted(built.surfaces)
    # each inset boundary curve separates the two regions
    for tag in model.selections["inset-boundary"].tags:
        assert sorted(built.curve_surfaces[tag]) == sorted(built.surfaces)


def test_mesh(result: dict) -> None:
    mesh = result["mesh"]
    mesh.validate()
    assert result["element_types"] == ["T6"]
    assert result["n_nodes"][0] == result["n_nodes"][1]  # same mesh before and after
    assert result["n_elements"][0] == result["n_elements"][1]
    assert result["min_angle"] > 20.0
    for name, exact in result["exact_areas"].items():
        assert result["areas"][name] == pytest.approx(exact, rel=1e-6), name
    # node sets of the selections lie where they should
    nodes, sets = mesh.nodes, mesh.node_sets
    assert np.allclose(nodes[sets["base"], 1], 0.0)
    assert np.allclose(nodes[sets["top"], 1], 0.2)
    centre = np.array([0.15, 0.025])
    assert np.allclose(np.linalg.norm(nodes[sets["hole"]] - centre, axis=1), 0.010, rtol=1e-9)
    assert sets["corner"].size == 1 and np.allclose(nodes[sets["corner"][0]], 0.0)
    # the local size on the hole took effect
    model, built = result["model"], result["built"]
    (hole,) = mesh.facets_on(model.selections["hole"].tags)
    assert hole.conn.shape[0] >= 0.8 * 2 * math.pi * 0.010 / (0.005 / 3)
    # interface facets appear once, parented by the lower region id
    (iface,) = mesh.facets_on(model.selections["inset-boundary"].tags)
    region_of = np.empty(mesh.n_elements, dtype=np.int64)
    for b in mesh.blocks:
        region_of[b.elem_ids] = b.region
    assert np.all(region_of[iface.parent_elem] == min(built.surfaces))


# ------------------------------------------------- review of the builder's tag tracking


def square_from_lines() -> tuple[api.Geometry, list[str], list[str]]:
    model = api.new_model()
    geo = api.Geometry(model)
    points = [geo.point(x, y) for x, y in [(0, 0), (2, 0), (2, 1), (0, 1)]]
    lines = [geo.line(points[i], points[(i + 1) % 4]) for i in range(4)]  # bottom right top left
    geo.surface(lines, id="s")
    return geo, points, lines


def owned_curves(built, op_id: str) -> list[tuple[tuple[float, float], float]]:
    return [
        (tuple(round(c, 9) for c in built.curves[t].center[:2]), round(built.curves[t].measure, 9))
        for d, t in built.op_entities[op_id] if d == 1
    ]


def test_curve_ops_never_point_at_a_different_curve_after_a_boolean() -> None:
    """Regression: a cut renumbers the boundary curves; Line ops used to keep stale tags
    that then referred to *other* curves."""
    geo, points, lines = square_from_lines()
    geo.rectangle(1.5, -0.5, 1.0, 1.0, id="tool")  # bites off the lower-right corner
    geo.cut(["s"], ["tool"], id="cut")
    built = api.build(geo.model)
    bottom, right, top, left = lines
    assert owned_curves(built, top) == [((1.0, 1.0), 2.0)]  # untouched: still the top edge
    assert owned_curves(built, left) == [((0.0, 0.5), 1.0)]
    assert owned_curves(built, bottom) == []  # trimmed by the cut: released, not re-pointed
    assert owned_curves(built, right) == []
    owned_points = {
        p: [tuple(round(c, 9) for c in built.points[t].center[:2])
            for d, t in built.op_entities[p]]
        for p in points
    }
    assert owned_points == {
        points[0]: [(0.0, 0.0)], points[1]: [], points[2]: [(2.0, 1.0)], points[3]: [(0.0, 1.0)]
    }
    assert sum(fp.measure for fp in built.surfaces.values()) == pytest.approx(2.0 - 0.25)


def test_curve_ops_follow_the_final_fragment() -> None:
    geo, _, lines = square_from_lines()
    geo.rectangle(2.0, 0.0, 1.0, 1.0, id="neighbour")  # shares the right edge
    built = api.build(geo.model)
    expected = [((1.0, 0.0), 2.0), ((2.0, 0.5), 1.0), ((1.0, 1.0), 2.0), ((0.0, 0.5), 1.0)]
    assert [owned_curves(built, line) for line in lines] == [[e] for e in expected]
    (shared,) = [t for t, s in built.curve_surfaces.items() if len(s) > 1]
    assert built.op_entities[lines[1]] == [(1, shared)]


def test_released_curve_gives_a_clear_error_when_used_again() -> None:
    geo, _, lines = square_from_lines()
    geo.rectangle(1.5, -0.5, 1.0, 1.0, id="tool")
    geo.cut(["s"], ["tool"], id="cut")
    geo.surface(lines, id="again")  # the bottom and right lines no longer exist as drawn
    with pytest.raises(GeometryError, match="operation 'again' .*has no entity of dimension 1"):
        api.build(geo.model)


def test_moved_shape_keeps_its_boundary_ops() -> None:
    # Owner's decision D12.4 (Q29.12, M11.34): Transform(copy=False) moves the points and
    # curves that belong to the shape, so the Point and Line ops follow it. (Before M11.34
    # they were released: they owned nothing after the move.)
    geo, points, lines = square_from_lines()
    geo.translate(["s"], 5.0, 0.0, id="move")
    built = api.build(geo.model)
    expected = [((6.0, 0.0), 2.0), ((7.0, 0.5), 1.0), ((6.0, 1.0), 2.0), ((5.0, 0.5), 1.0)]
    for line, (center, length) in zip(lines, expected, strict=True):
        ((got_center, got_length),) = owned_curves(built, line)
        assert got_center == pytest.approx(center, abs=1e-6)
        assert got_length == pytest.approx(length, abs=1e-9)
    for p, (x, y) in zip(points, [(5, 0), (7, 0), (7, 1), (5, 1)], strict=True):
        ((d, t),) = built.op_entities[p]
        assert d == 0 and built.points[t].center[:2] == pytest.approx((x, y), abs=1e-6)
    (tag,) = [t for d, t in built.op_entities["s"] if d == 2]
    assert built.surfaces[tag].center[:2] == pytest.approx((6.0, 0.5))
    assert built.op_entities["move"] == built.op_entities["s"]


def test_loop_ordering_survives_a_boolean_elsewhere() -> None:
    """Curves drawn before an unrelated boolean can still be chained into a surface."""
    model = api.new_model()
    geo = api.Geometry(model)
    points = [geo.point(x, y) for x, y in [(10, 0), (12, 0), (12, 1), (10, 1)]]
    lines = [geo.line(points[i], points[(i + 1) % 4]) for i in range(4)]
    geo.rectangle(0.0, 0.0, 2.0, 1.0, id="plate")
    geo.circle(1.0, 0.5, 0.2, id="hole")
    geo.cut(["plate"], ["hole"], id="cut")
    geo.surface([lines[0], lines[2], lines[1], lines[3]], id="late")  # out of order
    built = api.build(model)
    assert len(built.surfaces) == 2
    (tag,) = [t for d, t in built.op_entities["late"] if d == 2]
    assert built.surfaces[tag].measure == pytest.approx(2.0)
    assert built.surfaces[tag].center[:2] == pytest.approx((11.0, 0.5))
