"""M1.3 — mesh classes (Data §2) and the test-mesh generator."""

from __future__ import annotations

import numpy as np
import pytest

from thermalfea.core.errors import MeshError
from thermalfea.core.mesh import ElementBlock, FacetBlock, Mesh, jacobians, natural_normals
from thermalfea.core.meshgen import BOTTOM, LEFT, RIGHT, TOP, distort, rect_mesh
from thermalfea.core.registry import element

TYPES = ["T3", "Q4", "T6", "Q8"]
X0, Y0, W, H, NX, NY = 0.5, -0.25, 2.0, 1.5, 4, 3


def make(etype: str, distorted: bool = False) -> Mesh:
    mesh = rect_mesh(X0, Y0, W, H, NX, NY, etype, region=7)
    return distort(mesh, 0.2, seed=3) if distorted else mesh


def total_area(mesh: Mesh) -> float:
    area = 0.0
    for b in mesh.blocks:
        w = element(b.etype).quadrature[1]
        area += float((np.linalg.det(jacobians(b.etype, mesh.nodes[b.conn])) * w).sum())
    return area


@pytest.mark.parametrize("distorted", [False, True])
@pytest.mark.parametrize("etype", TYPES)
def test_validate_passes(etype: str, distorted: bool) -> None:
    mesh = make(etype, distorted)
    mesh.validate()
    assert mesh.dim == mesh.nodes.shape[1] == element(etype).dim
    assert total_area(mesh) == pytest.approx(W * H, rel=1e-12)


@pytest.mark.parametrize("etype", TYPES)
def test_counts(etype: str) -> None:
    mesh = make(etype)
    et = element(etype)
    per_cell = 2 if len(et.facets) == 3 else 1
    assert mesh.n_elements == NX * NY * per_cell
    (block,) = mesh.blocks
    assert block.conn.shape == (NX * NY * per_cell, et.n_nodes)
    assert block.conn.dtype == np.int64
    assert np.all(block.region == 7)
    np.testing.assert_array_equal(block.elem_ids, np.arange(mesh.n_elements))
    corner_nodes = (NX + 1) * (NY + 1)
    edges = NX * (NY + 1) + NY * (NX + 1) + (NX * NY if per_cell == 2 else 0)
    expected = corner_nodes + (edges if et.order == 2 else 0)
    assert mesh.n_nodes == expected
    assert np.unique(block.conn).size == mesh.n_nodes


@pytest.mark.parametrize("etype", TYPES)
def test_facet_blocks(etype: str) -> None:
    mesh = make(etype)
    et = element(etype)
    (fb,) = mesh.facets
    assert fb.etype == et.facet_type
    expected = {BOTTOM: NX, RIGHT: NY, TOP: NX, LEFT: NY}
    coord = {BOTTOM: (1, Y0), RIGHT: (0, X0 + W), TOP: (1, Y0 + H), LEFT: (0, X0)}
    normal = {BOTTOM: (0, -1), RIGHT: (1, 0), TOP: (0, 1), LEFT: (-1, 0)}
    for tag, n in expected.items():
        (side,) = mesh.facets_on([tag])
        assert side.conn.shape == (n, element(et.facet_type).n_nodes)
        assert np.all(side.entity == tag)
        axis, value = coord[tag]
        np.testing.assert_allclose(mesh.nodes[side.conn][..., axis], value, atol=1e-14)
        np.testing.assert_allclose(
            mesh.outward_normals(side), np.tile(normal[tag], (n, 1)), atol=1e-14
        )
    assert mesh.facets_on([99]) == []
    both = mesh.facets_on([BOTTOM, TOP])
    assert sum(b.conn.shape[0] for b in both) == 2 * NX
    # total boundary length equals the perimeter
    ft = element(fb.etype)
    jac = jacobians(fb.etype, mesh.nodes[fb.conn])
    length = (np.linalg.norm(natural_normals(jac), axis=-1) * ft.quadrature[1]).sum()
    assert length == pytest.approx(2 * (W + H), rel=1e-13)


@pytest.mark.parametrize("etype", TYPES)
def test_outward_normal_equals_dy_minus_dx_rule(etype: str) -> None:
    mesh = make(etype, distorted=True)
    (fb,) = mesh.facets
    ends = mesh.nodes[fb.conn[:, :2]]
    d = ends[:, 1] - ends[:, 0]
    expected = np.column_stack([d[:, 1], -d[:, 0]]) / np.linalg.norm(d, axis=1)[:, None]
    np.testing.assert_allclose(mesh.outward_normals(fb), expected, atol=1e-13)


@pytest.mark.parametrize("etype", TYPES)
def test_outward_normals_ignore_facet_node_order(etype: str) -> None:
    mesh = make(etype)
    (fb,) = mesh.facets
    flipped_conn = fb.conn.copy()
    flipped_conn[:, [0, 1]] = flipped_conn[:, [1, 0]]
    flipped = FacetBlock(fb.etype, flipped_conn, fb.entity, fb.parent_elem)
    np.testing.assert_allclose(
        mesh.outward_normals(flipped), mesh.outward_normals(fb), atol=1e-14
    )


@pytest.mark.parametrize("etype", TYPES)
def test_point_nodes_are_the_corners(etype: str) -> None:
    mesh = make(etype)
    corners = [(X0, Y0), (X0 + W, Y0), (X0 + W, Y0 + H), (X0, Y0 + H)]
    for tag, xy in enumerate(corners, start=1):
        np.testing.assert_allclose(mesh.nodes[mesh.point_nodes[tag]], xy, atol=1e-14)


@pytest.mark.parametrize("etype", TYPES)
def test_region_elements(etype: str) -> None:
    mesh = make(etype)
    mesh.blocks[0].region[:3] = 9
    (r9,) = mesh.region_elements(9)
    (r7,) = mesh.region_elements(7)
    assert r9.conn.shape[0] == 3
    assert r7.conn.shape[0] == mesh.n_elements - 3
    np.testing.assert_array_equal(r9.elem_ids, [0, 1, 2])
    assert mesh.region_elements(1234) == []


@pytest.mark.parametrize("etype", TYPES)
def test_distort_moves_only_interior_nodes(etype: str) -> None:
    mesh = make(etype)
    moved = distort(mesh, 0.2, seed=3)
    assert moved is not mesh
    boundary = np.unique(mesh.facets[0].conn)
    interior = np.setdiff1d(np.arange(mesh.n_nodes), boundary)
    np.testing.assert_array_equal(moved.nodes[boundary], mesh.nodes[boundary])
    assert np.all(np.any(moved.nodes[interior] != mesh.nodes[interior], axis=1))
    np.testing.assert_array_equal(distort(mesh, 0.2, seed=3).nodes, moved.nodes)
    assert np.any(distort(mesh, 0.2, seed=4).nodes != moved.nodes)
    # the input is untouched
    np.testing.assert_array_equal(mesh.nodes, make(etype).nodes)


@pytest.mark.parametrize("distorted", [False, True])
@pytest.mark.parametrize("etype", TYPES)
def test_one_reversed_element_fails_validation(etype: str, distorted: bool) -> None:
    mesh = make(etype, distorted)
    et = element(etype)
    n_corner = len(et.facets)
    # reverse the corner order (and the matching mid-side nodes) of one element
    perm = np.arange(et.n_nodes)
    perm[:n_corner] = perm[:n_corner][::-1]
    if et.n_nodes > n_corner:
        mids = perm[n_corner:].copy()
        perm[n_corner:] = np.roll(mids[::-1], -1)
    conn = mesh.blocks[0].conn
    conn[5] = conn[5][perm]
    with pytest.raises(MeshError, match="Jacobian"):
        mesh.validate()


def test_reversed_facet_fails_validation() -> None:
    mesh = make("Q4")
    conn = mesh.facets[0].conn
    conn[2] = conn[2][::-1]
    with pytest.raises(MeshError, match="oriented"):
        mesh.validate()


def test_facet_with_wrong_parent_fails_validation() -> None:
    mesh = make("T6")
    fb = mesh.facets[0]
    fb.parent_elem[0] = fb.parent_elem[-1]
    with pytest.raises(MeshError, match="parent"):
        mesh.validate()


def test_orphan_node_fails_validation() -> None:
    mesh = make("T3")
    mesh.nodes = np.vstack([mesh.nodes, [[10.0, 10.0]]])
    with pytest.raises(MeshError, match="orphan"):
        mesh.validate()


def test_other_validation_failures() -> None:
    mesh = make("Q4")
    mesh.blocks[0].elem_ids[1] = 0
    with pytest.raises(MeshError, match="unique"):
        mesh.validate()

    mesh = make("Q4")
    mesh.blocks[0].conn[0, 0] = mesh.n_nodes
    with pytest.raises(MeshError, match="out of range"):
        mesh.validate()

    mesh = make("Q4")
    mesh.blocks[0].etype = "L2"
    with pytest.raises(MeshError, match="dimension"):
        mesh.validate()

    mesh = make("Q4")
    mesh.facets[0].etype = "L3"
    with pytest.raises(MeshError, match="connectivity"):
        mesh.validate()

    mesh = make("Q4")
    mesh.point_nodes[1] = -1
    with pytest.raises(MeshError, match="point"):
        mesh.validate()

    mesh = make("Q4")
    mesh.node_sets["s"] = np.array([0, 10_000])
    with pytest.raises(MeshError, match="node set"):
        mesh.validate()

    with pytest.raises(MeshError, match="no elements"):
        Mesh(dim=2, nodes=np.zeros((1, 2)), blocks=[]).validate()


def test_mixed_blocks_validate() -> None:
    """Two blocks of different types sharing an interface, with interface facets."""
    left = rect_mesh(0.0, 0.0, 1.0, 1.0, 1, 1, "Q4", region=1)
    nodes = np.vstack([left.nodes, [[2.0, 0.0], [2.0, 1.0]]])
    # left quad nodes: 0 (0,0) 1 (1,0) 2 (0,1) 3 (1,1); new: 4 (2,0) 5 (2,1)
    tri = ElementBlock(
        "T3",
        conn=np.array([[1, 4, 5], [1, 5, 3]], dtype=np.int64),
        region=np.array([2, 2], dtype=np.int32),
        elem_ids=np.array([1, 2], dtype=np.int64),
    )
    interface = FacetBlock(
        "L2",
        conn=np.array([[1, 3]], dtype=np.int64),
        entity=np.array([10], dtype=np.int32),
        parent_elem=np.array([0], dtype=np.int64),
    )
    mesh = Mesh(dim=2, nodes=nodes, blocks=[left.blocks[0], tri], facets=[interface])
    mesh.validate()
    np.testing.assert_allclose(mesh.outward_normals(interface), [[1.0, 0.0]], atol=1e-15)
    assert total_area(mesh) == pytest.approx(2.0)
    assert mesh.element_centroids().shape == (3, 2)


def test_rect_mesh_rejects_bad_input() -> None:
    with pytest.raises(MeshError):
        rect_mesh(0, 0, 1, 1, 0, 1, "Q4")
    with pytest.raises(MeshError):
        rect_mesh(0, 0, -1, 1, 1, 1, "Q4")
    with pytest.raises(MeshError):
        rect_mesh(0, 0, 1, 1, 1, 1, "L2")
