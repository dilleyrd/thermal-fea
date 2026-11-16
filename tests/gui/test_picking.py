"""Pure picking geometry (no Qt events)."""

from __future__ import annotations

import numpy as np

from thermalfea.gui import picking


def circle(r: float, n: int = 64, cx: float = 0.0, cy: float = 0.0, closed: bool = True):
    t = np.linspace(0.0, 2.0 * np.pi, n + 1)
    pts = np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)])
    return pts if closed else pts[:-1]


def square(x0: float, y0: float, x1: float, y1: float) -> np.ndarray:
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], dtype=float)


def test_nearest_point() -> None:
    pts = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]])
    assert picking.nearest_point(pts, (0.98, 0.02), 0.1) == 1
    assert picking.nearest_point(pts, (0.5, 0.5), 0.1) is None
    assert picking.nearest_point(np.zeros((0, 2)), (0.0, 0.0), 1.0) is None


def test_distance_to_segments_including_endpoints_and_degenerate() -> None:
    a = np.array([[0.0, 0.0], [5.0, 5.0]])
    b = np.array([[2.0, 0.0], [5.0, 5.0]])  # second segment has zero length
    d = picking.distance_to_segments(a, b, (1.0, 1.0))
    assert np.allclose(d, [1.0, np.hypot(4.0, 4.0)])
    d = picking.distance_to_segments(a[:1], b[:1], (4.0, 0.0))  # beyond the end point
    assert np.allclose(d, [2.0])


def test_nearest_curve_straight_and_curved() -> None:
    line = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
    arc = circle(1.0, 60) + np.array([3.0, 0.0])
    a, b, owner = picking.polyline_segments([line, arc])
    assert picking.nearest_segment_owner(a, b, owner, (0.5, 0.02), 0.05) == 0
    # a point on the curved polyline, far from its chord ends
    on_arc = (3.0 + np.cos(1.0), np.sin(1.0))
    assert picking.nearest_segment_owner(a, b, owner, on_arc, 0.02) == 1
    # the centre of the circle is far from the polyline
    assert picking.nearest_segment_owner(a, b, owner, (3.0, 0.0), 0.1) is None
    assert picking.nearest_segment_owner(a[:0], b[:0], owner[:0], (0, 0), 1.0) is None


def test_point_in_polygon_square_and_concave() -> None:
    assert picking.point_in_polygon(square(0, 0, 2, 2), (1.0, 1.0))
    assert not picking.point_in_polygon(square(0, 0, 2, 2), (3.0, 1.0))
    l_shape = np.array([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]], dtype=float)
    assert picking.point_in_polygon(l_shape, (0.5, 1.5))
    assert not picking.point_in_polygon(l_shape, (1.5, 1.5))
    # a repeated closing vertex is harmless
    closed = np.vstack([square(0, 0, 2, 2), [[0.0, 0.0]]])
    assert picking.point_in_polygon(closed, (1.0, 1.0))


def test_surface_with_hole() -> None:
    loops = [square(0, 0, 4, 4), circle(1.0, 48, 2.0, 2.0, closed=False)]
    assert picking.point_in_loops(loops, (0.5, 0.5))
    assert not picking.point_in_loops(loops, (2.0, 2.0))  # inside the hole
    assert not picking.point_in_loops(loops, (5.0, 5.0))


def test_nested_surfaces_prefer_smallest() -> None:
    outer = (1, [square(0, 0, 10, 10)], 100.0)
    inner = (2, [square(4, 4, 6, 6)], 4.0)
    assert picking.smallest_containing([outer, inner], (5.0, 5.0)) == 2
    assert picking.smallest_containing([inner, outer], (5.0, 5.0)) == 2
    assert picking.smallest_containing([outer, inner], (1.0, 1.0)) == 1
    assert picking.smallest_containing([outer, inner], (20.0, 1.0)) is None


def test_chain_loops_joins_and_orients_pieces() -> None:
    # a square from four edges, some stored reversed and out of order
    edges = [
        np.array([[0.0, 0.0], [1.0, 0.0]]),
        np.array([[1.0, 1.0], [1.0, 0.0]]),  # reversed
        np.array([[1.0, 1.0], [0.0, 1.0]]),
        np.array([[0.0, 1.0], [0.0, 0.0]]),
    ]
    loops = picking.chain_loops(edges, 1e-9)
    assert len(loops) == 1
    assert loops[0].shape == (4, 2)
    assert abs(abs(picking.loop_area(loops[0])) - 1.0) < 1e-12
    # a closed curve plus a separate square give two loops
    both = picking.chain_loops([circle(0.2, 20) + 5.0, *edges], 1e-9)
    assert len(both) == 2


def test_box_selection_helpers() -> None:
    box = picking.normalized_box((2.0, 3.0), (0.0, 1.0))
    assert box == (0.0, 1.0, 2.0, 3.0)
    pts = np.array([[1.0, 2.0], [2.0, 3.0], [2.1, 2.0], [-0.1, 2.0]])
    assert picking.points_in_box(pts, box).tolist() == [True, True, False, False]
    assert picking.all_in_box(pts[:2], box)
    assert not picking.all_in_box(pts, box)
    assert not picking.all_in_box(np.zeros((0, 2)), box)


def test_field_display_from_contour_merges_parts() -> None:
    from thermalfea.gui.field_display import field_display_from_contour
    from thermalfea.post.plots import ContourData, ContourPart

    tri = np.array([[0, 1, 2]])
    xy = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0]])
    parts = [
        ContourPart(1, np.arange(3), xy, tri, np.array([1.0, 2.0, 3.0])),
        ContourPart(2, np.arange(3), xy + 1.0, tri, np.array([4.0, 5.0, 6.0])),
    ]
    data = ContourData(parts, 1.0, 6.0, xy[0], xy[2] + 1.0, "K", "T [K]", "T, t = 0 s", 0.0)
    spec = field_display_from_contour(data, levels=None, show_mesh=True)
    assert spec.xy.shape == (6, 2) and spec.triangles.tolist() == [[0, 1, 2], [3, 4, 5]]
    assert spec.values.tolist() == [1, 2, 3, 4, 5, 6]
    assert (spec.vmin, spec.vmax, spec.levels, spec.show_mesh) == (1.0, 6.0, None, True)
    assert [m[2] for m in spec.markers] == ["min 1", "max 6"]
