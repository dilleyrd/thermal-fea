"""M2.7 — mesher: plate with a hole and a two-region plate, all four element types."""

from __future__ import annotations

import math

import numpy as np
import pytest

from thermalfea import api
from thermalfea.core.errors import GeometryError, MeshError
from thermalfea.core.mesh import Mesh
from thermalfea.core.registry import element
from thermalfea.geometry.builder import build
from thermalfea.meshing.mesher import _reversal_permutation, generate
from thermalfea.model import geometry_ops as g
from thermalfea.model.model import Model
from thermalfea.model.settings import MeshSettings
from thermalfea.physics.kernel import facet_geometry, geometry

W, H, R = 0.6, 1.0, 0.1
CASES = [
    ("tri", 1, {"T3"}),
    ("quad", 1, {"Q4", "T3"}),
    ("tri", 2, {"T6"}),
    ("quad", 2, {"Q8", "T6"}),
]
IDS = ["T3", "Q4", "T6", "Q8"]


def settings(shape: str, order: int, size: float) -> MeshSettings:
    return MeshSettings(global_size=size, order=order, element_shape=shape)


def plate_with_hole(shape: str, order: int, size: float = 0.02) -> Model:
    return Model(
        geometry=[
            g.Rectangle("plate", 0.0, 0.0, W, H),
            g.Circle("hole", 0.3, 0.5, R),
            g.Boolean("cut", "cut", ["plate"], ["hole"]),
        ],
        mesh_settings=settings(shape, order, size),
    )


def two_regions(shape: str, order: int, size: float = 0.05) -> Model:
    return Model(
        geometry=[
            g.Rectangle("left", 0.0, 0.0, 0.4, 0.5),
            g.Rectangle("right", 0.4, 0.0, 0.6, 0.5),
        ],
        mesh_settings=settings(shape, order, size),
    )


def area(mesh: Mesh, region: int | None = None) -> float:
    blocks = mesh.blocks if region is None else mesh.region_elements(region)
    return float(sum(geometry(b, mesh.nodes).dV.sum() for b in blocks))


def length(mesh: Mesh, curves: list[int]) -> float:
    return float(sum(facet_geometry(f, mesh.nodes).dS.sum() for f in mesh.facets_on(curves)))


def tol(order: int) -> float:
    return 1e-3 if order == 1 else 1e-6


@pytest.mark.parametrize(("shape", "order", "allowed"), CASES, ids=IDS)
def test_plate_with_hole(shape: str, order: int, allowed: set[str]) -> None:
    model = plate_with_hole(shape, order)
    built = build(model)
    mesh = generate(model, built)
    mesh.validate()
    assert mesh.dim == 2 and mesh.nodes.shape[1] == 2 and not mesh.axisymmetric
    types = {b.etype for b in mesh.blocks}
    assert types <= allowed
    assert IDS[CASES.index((shape, order, allowed))] in types  # the main type is present
    assert all(element(b.etype).order == order for b in mesh.blocks)

    exact = W * H - math.pi * R**2
    assert area(mesh) == pytest.approx(exact, rel=tol(order))

    (circle,) = [
        t for t, fp in built.curves.items() if fp.measure == pytest.approx(2 * math.pi * R)
    ]
    outer = [t for t in built.curves if t != circle]  # the four sides
    assert len(outer) == 4
    assert length(mesh, outer) == pytest.approx(2 * (W + H), rel=1e-12)
    assert length(mesh, [circle]) == pytest.approx(2 * math.pi * R, rel=tol(order) * 10)
    # outward normals on the hole point towards its centre
    (hole,) = mesh.facets_on([circle])
    mid = mesh.nodes[hole.conn[:, :2]].mean(axis=1)
    inward = np.array([0.3, 0.5]) - mid
    assert np.all(np.einsum("fi,fi->f", mesh.outward_normals(hole), inward) > 0)

    # dense 0-based numbering with no unused nodes; ids unique and dense
    used = np.unique(np.concatenate([b.conn.ravel() for b in mesh.blocks]))
    np.testing.assert_array_equal(used, np.arange(mesh.n_nodes))
    ids = np.sort(np.concatenate([b.elem_ids for b in mesh.blocks]))
    np.testing.assert_array_equal(ids, np.arange(mesh.n_elements))
    (surface,) = built.surfaces
    assert all(np.all(b.region == surface) for b in mesh.blocks)
    assert all(f.conn.dtype == np.int64 and f.entity.dtype == np.int32 for f in mesh.facets)
    # element size is about the requested one
    assert 0.3 * 0.02**2 < exact / mesh.n_elements < 1.5 * 0.02**2
    # geometry points map to nodes at their positions
    assert set(mesh.point_nodes) == set(built.points)
    for tag, node in mesh.point_nodes.items():
        np.testing.assert_allclose(mesh.nodes[node], built.points[tag].center[:2], atol=1e-12)


@pytest.mark.parametrize(("shape", "order", "allowed"), CASES, ids=IDS)
def test_two_region_plate(shape: str, order: int, allowed: set[str]) -> None:
    model = two_regions(shape, order)
    built = build(model)
    api.select_curves(model, built, "bottom", where=lambda c: abs(c.center[1]) < 1e-9)
    api.select_surfaces(model, built, "left", where=lambda s: s.center[0] < 0.4)
    api.select_points(model, built, "corner", where=lambda p: p.center[0] + p.center[1] < 1e-9)
    mesh = generate(model, built)
    mesh.validate()
    assert {b.etype for b in mesh.blocks} <= allowed

    left = next(t for t, fp in built.surfaces.items() if fp.center[0] < 0.4)
    right = next(t for t in built.surfaces if t != left)
    assert area(mesh) == pytest.approx(0.5, rel=tol(order))
    assert area(mesh, left) == pytest.approx(0.2, rel=tol(order))
    assert area(mesh, right) == pytest.approx(0.3, rel=tol(order))

    (interface,) = [t for t, s in built.curve_surfaces.items() if len(s) > 1]
    outer = [t for t in built.curves if t != interface]
    assert length(mesh, outer) == pytest.approx(2 * (1.0 + 0.5), rel=1e-12)
    assert length(mesh, [interface]) == pytest.approx(0.5, rel=1e-12)  # counted once

    # every interface edge appears exactly once, with the lower region id as parent
    (iface,) = mesh.facets_on([interface])
    keys = {tuple(sorted(e)) for e in iface.conn[:, :2].tolist()}
    assert len(keys) == iface.conn.shape[0]
    region_of = np.empty(mesh.n_elements, dtype=np.int64)
    for b in mesh.blocks:
        region_of[b.elem_ids] = b.region
    assert np.all(region_of[iface.parent_elem] == min(left, right))
    sign = 1.0 if left < right else -1.0
    np.testing.assert_allclose(
        mesh.outward_normals(iface), np.tile([sign, 0.0], (iface.conn.shape[0], 1)), atol=1e-12
    )
    # the nodes on the interface are shared by both regions (conformal mesh)
    def nodes_of(region: int) -> set:
        return set(np.concatenate([b.conn.ravel() for b in mesh.region_elements(region)]))

    shared = nodes_of(left) & nodes_of(right)
    assert shared == set(iface.conn.ravel())
    assert np.allclose(mesh.nodes[sorted(shared), 0], 0.4)

    # every boundary edge of the mesh is a facet exactly once
    all_edges = np.concatenate([f.conn[:, :2] for f in mesh.facets])
    assert len({tuple(sorted(e)) for e in all_edges.tolist()}) == all_edges.shape[0]

    # named node sets from the selections
    bottom = mesh.node_sets["bottom"]
    assert np.allclose(mesh.nodes[bottom, 1], 0.0)
    assert bottom.size == np.count_nonzero(np.abs(mesh.nodes[:, 1]) < 1e-12)
    np.testing.assert_array_equal(mesh.node_sets["left"], np.array(sorted(nodes_of(left))))
    (corner,) = mesh.node_sets["corner"]
    np.testing.assert_allclose(mesh.nodes[corner], [0.0, 0.0], atol=1e-12)


def test_axisymmetric_flag_and_mirrored_surface() -> None:
    """A mirrored surface has its normal along -z in gmsh; elements must still be valid."""
    model = Model(
        analysis="axisymmetric",
        geometry=[
            g.Polygon("p", [(0.1, 0.0), (0.5, 0.0), (0.5, 0.3), (0.1, 0.6)]),
            g.Transform("m", "mirror", ["p"], {"x0": 0.0, "y0": 0.0, "x1": 1.0, "y1": 0.0}),
        ],
        mesh_settings=MeshSettings(global_size=0.05, order=2),
    )
    built = build(model)
    mesh = generate(model, built)
    mesh.validate()
    assert mesh.axisymmetric
    assert mesh.nodes[:, 1].max() <= 1e-12  # it really was mirrored below the axis
    assert area(mesh) == pytest.approx(0.4 * 0.3 + 0.5 * 0.4 * 0.3, rel=1e-9)


@pytest.mark.parametrize("etype", ["T3", "T6", "Q4", "Q8"])
def test_reversal_permutation_flips_orientation(etype: str) -> None:
    et = element(etype)
    perm = _reversal_permutation(et)
    assert sorted(perm) == list(range(et.n_nodes))
    x = et.node_coords[perm]
    pts = et.quadrature[0]
    det = np.linalg.det(np.einsum("pan,ni->pia", et.dshape(pts), x))
    assert np.all(det < 0)
    # the reordered nodes are still a valid element of the same shape, mirrored:
    # interpolating the reference coordinates reproduces a reflection of the element
    np.testing.assert_allclose(np.abs(det), np.abs(np.linalg.det(
        np.einsum("pan,ni->pia", et.dshape(pts), et.node_coords))), atol=1e-13)
    np.testing.assert_array_equal(perm[perm], np.arange(et.n_nodes))  # an involution


def test_generate_needs_the_current_build() -> None:
    model = two_regions("tri", 1)
    stale = build(model)
    build(model)
    with pytest.raises(GeometryError, match="rebuilt"):
        generate(model, stale)
    with pytest.raises(MeshError, match="empty"):
        generate(Model(), build(Model()))


def test_mesh_can_be_regenerated_with_new_settings() -> None:
    model = two_regions("tri", 1, size=0.1)
    built = build(model)
    coarse = generate(model, built)
    model.mesh_settings.global_size = 0.025
    fine = generate(model, built)
    assert fine.n_elements > 8 * coarse.n_elements
    model.mesh_settings.order = 2
    assert {b.etype for b in generate(model, built).blocks} == {"T6"}
