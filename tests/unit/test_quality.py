"""M2.9 — mesh quality report."""

from __future__ import annotations

import math

import numpy as np
import pytest

from thermalfea.core.mesh import ElementBlock, Mesh
from thermalfea.core.meshgen import distort, rect_mesh
from thermalfea.geometry.builder import build
from thermalfea.meshing.mesher import generate
from thermalfea.meshing.quality import QualityReport, report
from thermalfea.model import geometry_ops as g
from thermalfea.model.model import Model
from thermalfea.model.settings import MeshSettings


def single(etype: str, coords: list) -> Mesh:
    nodes = np.array(coords, dtype=float)
    block = ElementBlock(
        etype, np.arange(len(coords))[None, :], np.array([1], dtype=np.int32), np.array([0])
    )
    return Mesh(dim=2, nodes=nodes, blocks=[block])


def test_equilateral_triangle_is_perfect() -> None:
    q = report(single("T3", [(0, 0), (1, 0), (0.5, math.sqrt(3) / 2)]))
    assert q.min_angle[0] == pytest.approx(60.0)
    assert q.aspect_ratio[0] == pytest.approx(1.0)
    assert q.jacobian_ratio[0] == pytest.approx(1.0)
    assert q.counts == {"T3": 1} and q.n_nodes == 3 and q.n_elements == 1


def test_right_triangle_and_needle() -> None:
    q = report(single("T3", [(0, 0), (3, 0), (0, 4)]))
    assert q.min_angle[0] == pytest.approx(math.degrees(math.atan2(3, 4)))
    assert q.aspect_ratio[0] == pytest.approx(5.0 / 3.0)
    needle = report(single("T3", [(0, 0), (10, 0), (5, 0.1)]))
    assert needle.min_angle[0] == pytest.approx(math.degrees(math.atan2(0.1, 5)))
    assert needle.min_angle[0] < 2.0


@pytest.mark.parametrize("etype", ["Q4", "Q8"])
def test_rectangles(etype: str) -> None:
    mesh = rect_mesh(0.0, 0.0, 4.0, 1.0, 2, 2, etype)  # cells 2 x 0.5
    q = report(mesh)
    np.testing.assert_allclose(q.min_angle, 90.0)
    np.testing.assert_allclose(q.aspect_ratio, 4.0)
    np.testing.assert_allclose(q.jacobian_ratio, 1.0)
    assert q.counts == {etype: 4}
    assert q.n_nodes == mesh.n_nodes
    assert list(q.etype) == [etype] * 4
    assert q.summary()["aspect_ratio_max"] == pytest.approx(4.0)


def test_trapezoid_has_reduced_jacobian_ratio() -> None:
    q = report(single("Q4", [(0, 0), (2, 0), (1.5, 1), (0.5, 1)]))
    assert q.min_angle[0] == pytest.approx(math.degrees(math.atan2(1, 0.5)))
    assert q.aspect_ratio[0] == pytest.approx(2.0)
    assert q.jacobian_ratio[0] == pytest.approx(0.5)  # det J is linear: 0.5 (top) .. 1 (bottom)


def test_curved_quadratic_triangle() -> None:
    straight = [(0, 0), (1, 0), (0, 1), (0.5, 0), (0.5, 0.5), (0, 0.5)]
    assert report(single("T6", straight)).jacobian_ratio[0] == pytest.approx(1.0)
    bulged = [*straight[:4], (0.65, 0.65), straight[5]]
    q = report(single("T6", bulged))
    assert 0.0 < q.jacobian_ratio[0] < 0.9
    assert q.min_angle[0] == pytest.approx(45.0)  # corner angles ignore the curvature


def test_inverted_element_has_negative_jacobian_ratio() -> None:
    q = report(single("Q4", [(0, 0), (1, 0), (0.2, 0.2), (0, 1)]))  # concave ("arrowhead") quad
    assert q.jacobian_ratio[0] < 0.0
    flipped = report(single("T3", [(0, 0), (0, 1), (1, 0)]))
    assert flipped.jacobian_ratio[0] == -np.inf


def test_worst_elements_and_ordering_by_id() -> None:
    mesh = distort(rect_mesh(0.0, 0.0, 1.0, 1.0, 5, 5, "Q4"), 0.25, seed=5)
    block = mesh.blocks[0]
    # shuffle the block so that element ids are not in storage order
    perm = np.random.default_rng(0).permutation(block.conn.shape[0])
    mesh.blocks[0] = ElementBlock("Q4", block.conn[perm], block.region[perm], block.elem_ids[perm])
    q = report(mesh)
    assert isinstance(q, QualityReport)
    np.testing.assert_array_equal(q.elem_ids, np.arange(25))
    worst = q.worst(3)
    assert len(worst) == 3
    assert q.min_angle[worst[0]] == q.min_angle.min()
    assert list(q.min_angle[worst]) == sorted(q.min_angle)[:3]
    assert q.aspect_ratio[q.worst(1, by="aspect_ratio")[0]] == q.aspect_ratio.max()
    assert q.jacobian_ratio[q.worst(1, by="jacobian_ratio")[0]] == q.jacobian_ratio.min()
    assert len(q.worst(100)) == 25
    s = q.summary()
    assert s["min_angle_min"] == q.min_angle.min() < s["min_angle_mean"] < 90.0
    assert 0.0 < s["jacobian_ratio_min"] < 1.0


def test_gmsh_mesh_with_mixed_blocks() -> None:
    model = Model(
        geometry=[
            g.Rectangle("plate", 0.0, 0.0, 0.6, 1.0),
            g.Circle("hole", 0.3, 0.5, 0.1),
            g.Boolean("cut", "cut", ["plate"], ["hole"]),
        ],
        mesh_settings=MeshSettings(global_size=0.05, order=2, element_shape="quad"),
    )
    mesh = generate(model, build(model))
    q = report(mesh)
    assert sum(q.counts.values()) == mesh.n_elements == q.n_elements
    assert set(q.counts) == {b.etype for b in mesh.blocks}
    np.testing.assert_array_equal(q.elem_ids, np.arange(mesh.n_elements))
    for b in mesh.blocks:
        assert set(q.etype[b.elem_ids]) == {b.etype}
    assert np.all(q.min_angle > 15.0) and np.all(q.min_angle <= 120.0)
    assert np.all(q.aspect_ratio >= 1.0) and np.all(q.aspect_ratio < 6.0)
    assert np.all(q.jacobian_ratio > 0.1) and np.all(q.jacobian_ratio <= 1.0 + 1e-12)


def test_empty_block() -> None:
    mesh = Mesh(
        dim=2,
        nodes=np.zeros((0, 2)),
        blocks=[ElementBlock("T3", np.empty((0, 3), dtype=int), np.empty(0, np.int32),
                             np.empty(0, np.int64))],
    )
    q = report(mesh)
    assert q.n_elements == 0 and q.counts == {"T3": 0} and q.summary() == {}
    assert q.worst() == []
