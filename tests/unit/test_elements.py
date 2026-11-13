"""M1.2 — shape functions and the element registry (Theory §3, Data §13)."""

from __future__ import annotations

import numpy as np
import pytest

from thermalfea.core import registry
from thermalfea.core.elements import dshape, node_coords, shape
from thermalfea.core.errors import ModelError
from thermalfea.core.quadrature import rule
from thermalfea.core.registry import ElementType

ALL = ["T3", "T6", "Q4", "Q8", "L2", "L3"]
EXPECTED = {
    # name: (dim, n_nodes, order, gmsh_type, facet_type, n_facets, n_display)
    "T3": (2, 3, 1, 2, "L2", 3, 1),
    "T6": (2, 6, 2, 9, "L3", 3, 4),
    "Q4": (2, 4, 1, 3, "L2", 4, 2),
    "Q8": (2, 8, 2, 16, "L3", 4, 6),
    "L2": (1, 2, 1, 1, None, 0, 1),
    "L3": (1, 3, 2, 8, None, 0, 2),
}


def sample_points(etype: str, n: int = 25) -> np.ndarray:
    """Random points strictly inside the reference element."""
    et = registry.element(etype)
    rng = np.random.default_rng(1234)
    if etype.startswith("T"):
        p = rng.random((n, 2))
        flip = p.sum(axis=1) > 1.0
        p[flip] = 1.0 - p[flip]
        return 0.02 + 0.94 * p
    return rng.uniform(-0.98, 0.98, size=(n, et.dim))


@pytest.mark.parametrize("etype", ALL)
def test_shapes_of_arrays(etype: str) -> None:
    dim, n = EXPECTED[etype][:2]
    pts = sample_points(etype, 7)
    assert shape(etype, pts).shape == (7, n)
    assert dshape(etype, pts).shape == (7, dim, n)
    assert node_coords(etype).shape == (n, dim)


@pytest.mark.parametrize("etype", ALL)
def test_partition_of_unity(etype: str) -> None:
    pts = sample_points(etype)
    np.testing.assert_allclose(shape(etype, pts).sum(axis=1), 1.0, rtol=0, atol=1e-14)
    np.testing.assert_allclose(dshape(etype, pts).sum(axis=2), 0.0, rtol=0, atol=1e-13)


@pytest.mark.parametrize("etype", ALL)
def test_kronecker_delta_at_nodes(etype: str) -> None:
    n = EXPECTED[etype][1]
    np.testing.assert_allclose(shape(etype, node_coords(etype)), np.eye(n), rtol=0, atol=1e-14)


@pytest.mark.parametrize("etype", ALL)
def test_derivatives_match_central_differences(etype: str) -> None:
    dim = EXPECTED[etype][0]
    pts = sample_points(etype)
    dn = dshape(etype, pts)
    h = 1e-6
    for a in range(dim):
        step = np.zeros(dim)
        step[a] = h
        fd = (shape(etype, pts + step) - shape(etype, pts - step)) / (2.0 * h)
        np.testing.assert_allclose(dn[:, a, :], fd, rtol=0, atol=1e-7)


@pytest.mark.parametrize("etype", ALL)
def test_reproduces_linear_field(etype: str) -> None:
    """Isoparametric completeness: sum N_i x_i = x and sum dN_i x_i = identity."""
    dim = EXPECTED[etype][0]
    pts = sample_points(etype)
    xn = node_coords(etype)
    np.testing.assert_allclose(shape(etype, pts) @ xn, pts, rtol=0, atol=1e-13)
    jac = np.einsum("pan,nb->pab", dshape(etype, pts), xn)
    np.testing.assert_allclose(jac, np.broadcast_to(np.eye(dim), jac.shape), atol=1e-13)


@pytest.mark.parametrize("etype", ALL)
def test_registry_record(etype: str) -> None:
    dim, n, order, gmsh_type, facet_type, n_facets, n_display = EXPECTED[etype]
    et = registry.element(etype)
    assert (et.name, et.dim, et.n_nodes, et.order) == (etype, dim, n, order)
    assert et.gmsh_type == gmsh_type
    assert registry.element_by_gmsh_type(gmsh_type) is et
    assert et.facet_type == facet_type
    pts, w = et.quadrature
    ref_pts, ref_w = rule(etype)
    np.testing.assert_array_equal(pts, ref_pts)
    np.testing.assert_array_equal(w, ref_w)
    assert et.display_simplices.shape == (n_display, dim + 1)
    if facet_type is None:
        assert et.facets is None
    else:
        assert et.facets is not None
        assert et.facets.shape == (n_facets, registry.element(facet_type).n_nodes)


@pytest.mark.parametrize("etype", ["T3", "T6", "Q4", "Q8"])
def test_facets_are_on_the_boundary_with_element_on_the_left(etype: str) -> None:
    et = registry.element(etype)
    ft = registry.element(et.facet_type)
    xn = et.node_coords
    centroid = xn.mean(axis=0)
    s = np.linspace(-1.0, 1.0, 5).reshape(-1, 1)
    nf = ft.shape(s)
    corners: list[int] = []
    for local in et.facets:
        a, b = xn[local[0]], xn[local[1]]
        # facet shape functions interpolate the straight side exactly
        np.testing.assert_allclose(nf @ xn[local], a + 0.5 * (s + 1.0) * (b - a), atol=1e-14)
        # the element centroid is to the left of the direction a -> b
        t, c = b - a, centroid - a
        assert t[0] * c[1] - t[1] * c[0] > 0
        corners.append(int(local[0]))
    # every corner starts exactly one facet (closed loop)
    assert sorted(corners) == list(range(len(et.facets)))


@pytest.mark.parametrize("etype", ["T3", "T6", "Q4", "Q8"])
def test_display_simplices_cover_reference_area(etype: str) -> None:
    et = registry.element(etype)
    tri = et.node_coords[et.display_simplices]
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    areas = 0.5 * (e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0])
    assert np.all(areas > 0)
    assert areas.sum() == pytest.approx(et.quadrature[1].sum())
    assert set(et.display_simplices.ravel()) == set(range(et.n_nodes))


@pytest.mark.parametrize("etype", ["L2", "L3"])
def test_line_display_segments_cover_reference_length(etype: str) -> None:
    et = registry.element(etype)
    seg = et.node_coords[et.display_simplices][:, :, 0]
    lengths = seg[:, 1] - seg[:, 0]
    assert np.all(lengths > 0)
    assert lengths.sum() == pytest.approx(2.0)


def test_quadrature_integrates_shape_functions_to_reference_measure() -> None:
    for etype in ALL:
        et = registry.element(etype)
        pts, w = et.quadrature
        assert (w @ et.shape(pts)).sum() == pytest.approx(w.sum())


def test_dummy_element_registered_in_test_is_returned() -> None:
    dummy = ElementType(
        name="_DUMMY_P1",
        dim=1,
        n_nodes=1,
        order=0,
        gmsh_type=-999,
        shape=lambda pts: np.ones((pts.shape[0], 1)),
        dshape=lambda pts: np.zeros((pts.shape[0], 1, 1)),
        node_coords=np.zeros((1, 1)),
        quadrature=(np.zeros((1, 1)), np.array([2.0])),
        facet_type=None,
        facets=None,
        display_simplices=np.array([[0, 0]]),
    )
    registry.register_element(dummy)
    try:
        assert registry.element("_DUMMY_P1") is dummy
        assert "_DUMMY_P1" in registry.element_names()
        assert registry.element_by_gmsh_type(-999) is dummy
        np.testing.assert_array_equal(shape("_DUMMY_P1", np.zeros((3, 1))), np.ones((3, 1)))
        assert dshape("_DUMMY_P1", np.zeros((3, 1))).shape == (3, 1, 1)
    finally:
        registry._ELEMENTS.pop("_DUMMY_P1")


def test_unknown_and_inconsistent_types_raise() -> None:
    with pytest.raises(ModelError):
        registry.element("NOPE")
    with pytest.raises(ModelError):
        registry.element_by_gmsh_type(123456)
    bad = ElementType(
        name="_BAD",
        dim=2,
        n_nodes=3,
        order=1,
        gmsh_type=-1,
        shape=lambda pts: pts,
        dshape=lambda pts: pts,
        node_coords=np.zeros((4, 2)),
        quadrature=(np.zeros((1, 2)), np.array([0.5])),
        facet_type=None,
        facets=None,
        display_simplices=np.array([[0, 1, 2]]),
    )
    with pytest.raises(ModelError):
        registry.register_element(bad)
