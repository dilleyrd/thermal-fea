"""M1.4 — element geometry kernel and conduction matrix (Theory §1, §2)."""

from __future__ import annotations

import numpy as np
import pytest

from thermalfea.core.errors import MeshError
from thermalfea.core.mesh import ElementBlock
from thermalfea.core.meshgen import distort, rect_mesh
from thermalfea.core.registry import element
from thermalfea.physics.conduction import conduction
from thermalfea.physics.kernel import facet_geometry, geometry, gfactor

TYPES = ["T3", "Q4", "T6", "Q8"]
W, H = 2.0, 1.5


def mesh_of(etype: str, distorted: bool = True):
    mesh = rect_mesh(0.5, 0.25, W, H, 4, 3, etype)
    return distort(mesh, 0.2, seed=11) if distorted else mesh


def iso(geom, k: float) -> np.ndarray:
    dim = geom.xgp.shape[-1]
    return np.broadcast_to(k * np.eye(dim), (*geom.dV.shape, dim, dim))


@pytest.mark.parametrize("etype", TYPES)
def test_geometry_shapes_and_area(etype: str) -> None:
    mesh = mesh_of(etype)
    (block,) = mesh.blocks
    et = element(etype)
    geom = geometry(block, mesh.nodes)
    e, gp, n, dim = block.conn.shape[0], et.quadrature[1].size, et.n_nodes, mesh.dim
    assert geom.N.shape == (gp, n)
    assert geom.dNdx.shape == (e, gp, dim, n)
    assert geom.dV.shape == (e, gp)
    assert geom.xgp.shape == (e, gp, dim)
    assert np.all(geom.dV > 0)
    assert geom.dV.sum() == pytest.approx(W * H, rel=1e-13)


@pytest.mark.parametrize("etype", TYPES)
def test_dndx_gives_exact_gradient_of_linear_field(etype: str) -> None:
    mesh = mesh_of(etype)
    (block,) = mesh.blocks
    geom = geometry(block, mesh.nodes)
    grad = np.array([3.0, -2.0])
    t_nodes = 5.0 + mesh.nodes @ grad
    got = np.einsum("epin,en->epi", geom.dNdx, t_nodes[block.conn])
    np.testing.assert_allclose(got, np.broadcast_to(grad, got.shape), atol=1e-11)
    # integration points interpolate the coordinates
    x_from_n = np.einsum("pn,eni->epi", geom.N, mesh.nodes[block.conn])
    np.testing.assert_array_equal(geom.xgp, x_from_n)


def test_geometry_rejects_inverted_element() -> None:
    mesh = mesh_of("T3", distorted=False)
    (block,) = mesh.blocks
    block.conn[0] = block.conn[0][::-1]
    with pytest.raises(MeshError, match="Jacobian"):
        geometry(block, mesh.nodes)


@pytest.mark.parametrize("etype", TYPES)
def test_facet_geometry(etype: str) -> None:
    mesh = mesh_of(etype)
    (fb,) = mesh.facets
    ft = element(fb.etype)
    fg = facet_geometry(fb, mesh.nodes)
    f, gp = fb.conn.shape[0], ft.quadrature[1].size
    assert fg.N.shape == (gp, ft.n_nodes)
    assert fg.dS.shape == (f, gp)
    assert fg.xgp.shape == (f, gp, mesh.dim)
    assert fg.dS.sum() == pytest.approx(2 * (W + H), rel=1e-13)
    # per-facet length equals the distance between its end nodes (straight sides)
    ends = mesh.nodes[fb.conn[:, :2]]
    np.testing.assert_allclose(
        fg.dS.sum(axis=1), np.linalg.norm(ends[:, 1] - ends[:, 0], axis=1), rtol=1e-13
    )


def test_facet_measure_of_curved_l3_edge() -> None:
    """A three-node edge on a parabola: length by the general sqrt(det(J^T J)) formula."""
    from thermalfea.core.mesh import FacetBlock

    nodes = np.array([[0.0, 0.0], [2.0, 0.0], [1.0, 0.5]])
    fb = FacetBlock(
        "L3", np.array([[0, 1, 2]]), np.array([1], dtype=np.int32), np.array([0])
    )
    fg = facet_geometry(fb, nodes)
    # x = 1 + xi, y = 0.5 (1 - xi^2), so ds/dxi = sqrt(1 + xi^2) analytically.
    pts, w = element("L3").quadrature
    np.testing.assert_allclose(fg.dS[0], np.sqrt(1.0 + pts[:, 0] ** 2) * w, rtol=1e-14)
    # the 3-point rule integrates this non-polynomial length to about 0.05 %
    exact = np.sqrt(2.0) + np.arcsinh(1.0)
    assert fg.dS.sum() == pytest.approx(exact, rel=1e-3)


def test_gfactor_planar_axisymmetric_and_3d() -> None:
    xgp = np.array([[[0.5, 1.0], [2.0, 3.0]], [[1.5, 0.0], [4.0, -1.0]]])
    np.testing.assert_array_equal(gfactor(xgp, False, 0.25, 2), np.full((2, 2), 0.25))
    per_elem = np.array([[0.1], [0.2]])
    np.testing.assert_array_equal(
        gfactor(xgp, False, per_elem, 2), np.array([[0.1, 0.1], [0.2, 0.2]])
    )
    np.testing.assert_allclose(gfactor(xgp, True, 0.25, 2), 2 * np.pi * xgp[..., 0])
    x3 = np.zeros((2, 4, 3))
    np.testing.assert_array_equal(gfactor(x3, False, 0.25, 3), np.ones((2, 4)))
    np.testing.assert_array_equal(gfactor(x3, True, 0.25, 3), np.ones((2, 4)))


def test_axisymmetric_t3_area_integral_of_g_is_ring_volume() -> None:
    # triangle (r, z): (1, 0), (3, 0), (1, 3) -> area 3, centroid radius 5/3
    nodes = np.array([[1.0, 0.0], [3.0, 0.0], [1.0, 3.0]])
    block = ElementBlock(
        "T3", np.array([[0, 1, 2]]), np.array([1], dtype=np.int32), np.array([0])
    )
    geom = geometry(block, nodes)
    g = gfactor(geom.xgp, True, 1.0, 2)
    volume = (g * geom.dV).sum()
    assert volume == pytest.approx(2 * np.pi * (5.0 / 3.0) * 3.0, rel=1e-14)  # Pappus


@pytest.mark.parametrize("etype", TYPES)
def test_axisymmetric_rectangle_volume_and_surface(etype: str) -> None:
    mesh = mesh_of(etype)  # r in [0.5, 2.5], z in [0.25, 1.75]
    (block,) = mesh.blocks
    geom = geometry(block, mesh.nodes)
    volume = (gfactor(geom.xgp, True, 1.0, mesh.dim) * geom.dV).sum()
    assert volume == pytest.approx(np.pi * (2.5**2 - 0.5**2) * H, rel=1e-12)
    (outer,) = mesh.facets_on([2])
    fg = facet_geometry(outer, mesh.nodes)
    area = (gfactor(fg.xgp, True, 1.0, mesh.dim) * fg.dS).sum()
    assert area == pytest.approx(2 * np.pi * 2.5 * H, rel=1e-13)


def test_unit_square_q4_equals_textbook_matrix() -> None:
    mesh = rect_mesh(0.0, 0.0, 1.0, 1.0, 1, 1, "Q4")
    (block,) = mesh.blocks
    geom = geometry(block, mesh.nodes)
    ke = conduction(geom, iso(geom, 1.0), gfactor(geom.xgp, False, 1.0, mesh.dim))
    # reorder to counter-clockwise corner order to compare with the textbook layout
    corners = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]])
    np.testing.assert_allclose(mesh.nodes[block.conn[0]], corners, atol=1e-15)
    a, o = -1.0 / 6.0, -1.0 / 3.0
    d = 2.0 / 3.0
    expected = np.array([[d, a, o, a], [a, d, a, o], [o, a, d, a], [a, o, a, d]])
    np.testing.assert_allclose(ke[0], expected, atol=1e-14)


@pytest.mark.parametrize("axisymmetric", [False, True])
@pytest.mark.parametrize("etype", TYPES)
def test_conduction_matrix_properties(etype: str, axisymmetric: bool) -> None:
    mesh = mesh_of(etype)
    (block,) = mesh.blocks
    geom = geometry(block, mesh.nodes)
    g = gfactor(geom.xgp, axisymmetric, 0.3, mesh.dim)
    # full (orthotropic, rotated) symmetric positive-definite conductivity
    c, s = np.cos(0.4), np.sin(0.4)
    rot = np.array([[c, -s], [s, c]])
    d_const = rot @ np.diag([5.0, 0.7]) @ rot.T
    d = np.broadcast_to(d_const, (*geom.dV.shape, mesh.dim, mesh.dim))
    ke = conduction(geom, d, g)
    n = element(etype).n_nodes
    assert ke.shape == (block.conn.shape[0], n, n)
    scale = np.abs(ke).max()
    np.testing.assert_allclose(ke.sum(axis=2), 0.0, atol=1e-12 * scale)
    np.testing.assert_allclose(ke, np.swapaxes(ke, 1, 2), atol=1e-13 * scale)
    eig = np.linalg.eigvalsh(ke)
    assert np.all(eig[:, 0] > -1e-11 * scale)  # positive semi-definite
    assert np.all(eig[:, 1] > 1e-9 * scale)  # exactly one zero-energy mode


@pytest.mark.parametrize("etype", TYPES)
def test_conduction_energy_of_linear_field(etype: str) -> None:
    """T^T K T = integral of grad(T) . D grad(T) g dA, exact for a linear field."""
    mesh = mesh_of(etype)
    (block,) = mesh.blocks
    geom = geometry(block, mesh.nodes)
    k, thickness = 4.0, 0.3
    ke = conduction(geom, iso(geom, k), gfactor(geom.xgp, False, thickness, mesh.dim))
    grad = np.array([3.0, -2.0])
    te = (5.0 + mesh.nodes @ grad)[block.conn]
    energy = np.einsum("en,enm,em->", te, ke, te)
    assert energy == pytest.approx(k * (grad @ grad) * W * H * thickness, rel=1e-12)
