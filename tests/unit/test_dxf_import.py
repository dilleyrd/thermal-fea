"""M10.3 — DXF import: closed outlines become surfaces, inner outlines become holes."""

from __future__ import annotations

import logging
import math
import sys
from pathlib import Path

import numpy as np
import pytest

ezdxf = pytest.importorskip("ezdxf")

from thermalfea.core.errors import GeometryError  # noqa: E402
from thermalfea.geometry import dxf as dxf_mod  # noqa: E402
from thermalfea.geometry.builder import build  # noqa: E402
from thermalfea.meshing.mesher import generate  # noqa: E402
from thermalfea.model import geometry_ops as g  # noqa: E402
from thermalfea.model.model import Model  # noqa: E402
from thermalfea.model.settings import MeshSettings  # noqa: E402

W, H, R = 0.6, 1.0, 0.1


def new_drawing():
    doc = ezdxf.new()
    return doc, doc.modelspace()


def save(doc, tmp_path: Path, name: str = "part.dxf") -> Path:
    path = tmp_path / name
    doc.saveas(path)
    return path


def rectangle(msp, x0: float, y0: float, x1: float, y1: float) -> None:
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    for i in range(4):
        msp.add_line(corners[i], corners[(i + 1) % 4])


def import_model(path: Path, scale: float = 1.0, **kw):
    return Model(geometry=[g.ImportFile("part", str(path), "dxf", scale=scale)], **kw)


def area(built) -> float:
    return sum(fp.measure for fp in built.surfaces.values())


def shoelace(xy: np.ndarray) -> float:
    x, y = xy[:, 0], xy[:, 1]
    return 0.5 * abs(float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


# ------------------------------------------------------------------ the main behaviours


def test_rectangle_with_circular_hole(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, W, H)
    msp.add_circle((0.3, 0.5), R)
    model = import_model(save(doc, tmp_path), mesh_settings=MeshSettings(global_size=0.05))
    built = build(model)
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(W * H - math.pi * R**2, rel=1e-9)
    assert [d for d, _ in built.op_entities["part"]] == [2]
    assert len(built.curves) == 5
    generate(model, built).validate()


@pytest.mark.parametrize("clockwise", [False, True])
def test_stadium_from_lwpolyline_with_bulges(tmp_path: Path, clockwise: bool) -> None:
    length, r = 0.8, 0.15
    if clockwise:
        points = [(0, r, 0), (length, r, -1), (length, -r, 0), (0, -r, -1)]
    else:
        points = [(0, -r, 0), (length, -r, 1), (length, r, 0), (0, r, 1)]
    doc, msp = new_drawing()
    msp.add_lwpolyline(points, format="xyb", close=True)
    built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(length * 2 * r + math.pi * r**2, rel=1e-9)
    assert built.bbox == pytest.approx((-r, -r, 0, length + r, r, 0), abs=1e-6)


def test_open_lwpolyline_closed_by_a_line(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    msp.add_lwpolyline([(0, 0), (1, 0), (1, 1)], format="xy")  # open: two segments
    msp.add_line((1, 1), (0, 0))
    built = build(import_model(save(doc, tmp_path)))
    assert area(built) == pytest.approx(0.5, rel=1e-12)


def rounded_rectangle(msp, w: float, h: float, rc: float, gap: float = 0.0) -> None:
    """Lines and arcs; every line end is moved by ``gap`` along x to mismatch the arcs."""
    msp.add_line((rc + gap, 0), (w - rc, 0))
    msp.add_arc((w - rc, rc), rc, -90, 0)
    msp.add_line((w, rc), (w, h - rc))
    msp.add_arc((w - rc, h - rc), rc, 0, 90)
    msp.add_line((w - rc, h), (rc, h))
    msp.add_arc((rc, h - rc), rc, 90, 180)
    msp.add_line((0, h - rc), (0, rc))
    msp.add_arc((rc, rc), rc, 180, 270)


def test_end_points_within_tolerance_are_joined(tmp_path: Path) -> None:
    w, h, rc = 2.0, 1.0, 0.25
    doc, msp = new_drawing()
    rounded_rectangle(msp, w, h, rc, gap=1e-9 * w)  # 5e-10 relative: well inside JOIN_TOL
    built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(w * h - (4 - math.pi) * rc**2, rel=1e-8)
    assert len(built.curves) == 8


def test_end_points_beyond_tolerance_leave_the_outline_open(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    doc, msp = new_drawing()
    rounded_rectangle(msp, 2.0, 1.0, 0.25, gap=1e-3)
    with caplog.at_level(logging.WARNING), pytest.raises(GeometryError, match="no closed loop"):
        build(import_model(save(doc, tmp_path)))
    assert "open chain" in caplog.text


def test_arc_in_a_mirrored_coordinate_system(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    # OCS x axis points along -X for extrusion (0, 0, -1): this arc is the upper half of the
    # circle about (2, 0) in the world, from (1, 0) over (2, 1) to (3, 0)
    msp.add_arc((-2.0, 0.0), 1.0, 0, 180, dxfattribs={"extrusion": (0, 0, -1)})
    msp.add_line((1, 0), (3, 0))
    built = build(import_model(save(doc, tmp_path)))
    assert area(built) == pytest.approx(math.pi / 2, rel=1e-9)
    assert built.bbox == pytest.approx((1, 0, 0, 3, 1, 0), abs=1e-6)


def test_lwpolyline_in_a_mirrored_coordinate_system(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    msp.add_lwpolyline(
        [(-1, 0, 1), (-3, 0, 1)], format="xyb", close=True, dxfattribs={"extrusion": (0, 0, -1)}
    )
    built = build(import_model(save(doc, tmp_path)))
    assert area(built) == pytest.approx(math.pi, rel=1e-9)  # a disc of radius 1 about (2, 0)
    assert built.bbox == pytest.approx((1, -1, 0, 3, 1, 0), abs=1e-6)


# OCC integrates the area of a spline-bounded face with ~3e-5 relative accuracy, hence the
# loose tolerances of the spline tests (sampling the OCC curves reproduces the expected area
# to 1e-8).


def expected_area(control_points, closed_periodic: bool) -> float:
    """Area enclosed by a B-spline, from a dense sampling of its valid parameter range."""
    from ezdxf.math import BSpline, closed_uniform_bspline

    spline = (
        closed_uniform_bspline(control_points, order=4)
        if closed_periodic
        else BSpline(control_points, order=4)
    )
    knots = list(spline.knots())
    ts = np.linspace(knots[spline.degree], knots[spline.count], 20001)[:-1]
    return shoelace(np.array([tuple(p)[:2] for p in spline.points(ts)]))


SQUARE_ISH = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (0.0, 1.0)]


def test_closed_periodic_spline(tmp_path: Path) -> None:
    from ezdxf.math import closed_uniform_bspline

    doc, msp = new_drawing()
    spline = msp.add_spline()
    spline.apply_construction_tool(closed_uniform_bspline(SQUARE_ISH, order=4))
    spline.closed = True
    built = build(import_model(save(doc, tmp_path)))
    # a spline closing on itself is cut in two: gmsh would take one curve for periodic
    assert len(built.surfaces) == 1 and len(built.curves) == 2
    assert area(built) == pytest.approx(expected_area(SQUARE_ISH, True), rel=1e-4)


def test_clamped_spline_closed_by_repeating_its_first_point(tmp_path: Path) -> None:
    cps = [(0.0, 0.0), (1.0, -0.5), (2.0, 0.0), (2.5, 1.0), (1.0, 1.5), (-0.5, 0.8), (0.0, 0.0)]
    doc, msp = new_drawing()
    msp.add_open_spline(cps, degree=3)
    built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(expected_area(cps, False), rel=1e-4)


def test_spline_through_fit_points(tmp_path: Path) -> None:
    r = 1.0
    pts = [(r * math.cos(a), r * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 9)[:-1]]
    doc, msp = new_drawing()
    msp.add_spline(fit_points=[*pts, pts[0]])
    built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(math.pi * r**2, rel=2e-2)


def test_spline_and_line_share_end_points(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    msp.add_open_spline([(0.0, 0.0), (0.5, 0.4), (1.0, 0.4), (1.5, 0.0)], degree=3)
    msp.add_line((1.5, 0.0), (0.0, 0.0))
    built = build(import_model(save(doc, tmp_path)))
    from ezdxf.math import BSpline

    curve = BSpline([(0.0, 0.0), (0.5, 0.4), (1.0, 0.4), (1.5, 0.0)], order=4)
    ts = np.linspace(0.0, curve.max_t, 20001)
    expect = shoelace(np.array([tuple(p)[:2] for p in curve.points(ts)]))
    assert len(built.surfaces) == 1 and len(built.curves) == 2
    assert area(built) == pytest.approx(expect, rel=1e-6)


def test_island_inside_a_hole(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 10, 10)
    rectangle(msp, 2, 2, 8, 8)  # a hole
    rectangle(msp, 4, 4, 6, 6)  # an island in the hole
    built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 2
    assert area(built) == pytest.approx(100 - 36 + 4, rel=1e-12)
    assert sorted(fp.measure for fp in built.surfaces.values()) == pytest.approx([4, 64])


def test_two_separate_loops(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 1, 1)
    msp.add_circle((3, 0.5), 0.5)
    built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 2
    assert area(built) == pytest.approx(1 + math.pi * 0.25, rel=1e-9)


def test_scale_of_a_drawing_in_millimetres(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 600, 1000)
    msp.add_circle((300, 500), 100)
    msp.add_arc((600, 500), 50, 90, 270)  # open, ignored
    built = build(import_model(save(doc, tmp_path), scale=0.001))
    assert area(built) == pytest.approx(0.6 - math.pi * 0.01, rel=1e-9)
    assert built.bbox == pytest.approx((0, 0, 0, 0.6, 1.0, 0), abs=1e-6)


def test_dxf_combines_with_other_operations(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 2, 1)
    path = save(doc, tmp_path)
    built = build(
        Model(
            geometry=[
                g.ImportFile("plate", str(path), "dxf"),
                g.Circle("hole", 1.0, 0.5, 0.25),
                g.Boolean("cut", "cut", ["plate"], ["hole"]),
                g.Rectangle("next", 2.0, 0.0, 1.0, 1.0),
            ]
        )
    )
    assert len(built.surfaces) == 2
    assert area(built) == pytest.approx(3.0 - math.pi * 0.25**2, rel=1e-9)
    assert sum(len(s) > 1 for s in built.curve_surfaces.values()) == 1  # shared edge


# ------------------------------------------------------------------------ refusals


def test_unsupported_entities_are_ignored_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 1, 1)
    msp.add_text("label")
    msp.add_text("another")
    msp.add_point((5, 5))
    with caplog.at_level(logging.WARNING):
        built = build(import_model(save(doc, tmp_path)))
    assert area(built) == pytest.approx(1.0)
    assert "TEXT x2" in caplog.text and "POINT x1" in caplog.text


def test_open_extra_line_is_ignored_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 1, 1)
    msp.add_line((3, 3), (4, 4))
    with caplog.at_level(logging.WARNING):
        built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 1 and area(built) == pytest.approx(1.0)
    assert "1 open chain" in caplog.text and "(3, 3)" in caplog.text


def test_branching_point_is_an_error(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 1, 1)
    msp.add_line((0, 0), (-1, -1))  # a third segment end at the corner (0, 0)
    with pytest.raises(GeometryError, match=r"branches at \(0, 0\): 3 segment ends"):
        build(import_model(save(doc, tmp_path)))


def test_entity_out_of_the_plane_is_refused(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 1, 1)
    msp.add_line((0, 0, 1), (1, 0, 1))
    with pytest.raises(GeometryError, match="does not lie in the plane z = 0"):
        build(import_model(save(doc, tmp_path)))


def test_circle_in_a_tilted_plane_is_refused(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    msp.add_circle((0, 0), 1.0, dxfattribs={"extrusion": (1, 0, 0)})
    with pytest.raises(GeometryError, match="not parallel to z = 0"):
        build(import_model(save(doc, tmp_path)))


def test_drawing_without_supported_entities(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    msp.add_text("only text")
    with pytest.raises(GeometryError, match="no supported geometry"):
        build(import_model(save(doc, tmp_path)))


def test_file_problems(tmp_path: Path) -> None:
    with pytest.raises(GeometryError, match="operation 'part' .*file not found"):
        build(import_model(tmp_path / "missing.dxf"))
    garbage = tmp_path / "garbage.dxf"
    garbage.write_text("this is not a DXF file", encoding="utf-8")
    with pytest.raises(GeometryError, match="operation 'part' .*could not read garbage.dxf"):
        build(import_model(garbage))
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 1, 1)
    good = save(doc, tmp_path, "ok.dxf")
    with pytest.raises(GeometryError, match="scale must be positive"):
        build(import_model(good, scale=0.0))
    assert area(build(import_model(good))) == pytest.approx(1.0)  # session still works


def test_missing_ezdxf_is_explained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 1, 1)
    path = save(doc, tmp_path)
    monkeypatch.setitem(sys.modules, "ezdxf", None)  # makes ``import ezdxf`` fail
    with pytest.raises(GeometryError, match="pip install ezdxf"):
        dxf_mod.read_dxf(str(path))


# ------------------------------------------------------------- pure part (no gmsh)


def square(x0: float, y0: float, x1: float, y1: float, gap: float = 0.0) -> list[dxf_mod.Line]:
    c = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    lines = [dxf_mod.Line(c[i], c[(i + 1) % 4]) for i in range(4)]
    a, b = lines[0].p1, lines[1].p0
    lines[1] = dxf_mod.Line((b[0] + gap, b[1]), lines[1].p1)
    assert a == b
    return lines


def test_join_merges_close_end_points_and_orients_the_chain() -> None:
    segments = square(0, 0, 1, 1, gap=1e-8)
    # reverse one segment: the chain must flip it
    segments[2] = segments[2].reversed()
    drawing = dxf_mod.join_segments(segments)
    assert len(drawing.points) == 4 and len(drawing.loops) == 1
    loop = drawing.loops[0]
    assert len(loop.items) == 4
    for i, item in enumerate(loop.items):
        nxt = loop.items[(i + 1) % 4]
        assert item.end == pytest.approx(nxt.start, abs=1e-7)


def test_join_tolerance_is_relative_to_the_drawing_size() -> None:
    small = square(0, 0, 1, 1, gap=1e-5)  # 1e-5 of the size: beyond JOIN_TOL
    with pytest.raises(GeometryError, match="no closed loop"):
        dxf_mod.join_segments(small)
    large = square(0, 0, 1000, 1000, gap=1e-5)  # 1e-8 of the size: joined
    assert len(dxf_mod.join_segments(large).loops) == 1


def test_join_keeps_closed_loops_and_reports_open_chains(caplog) -> None:
    segments = [*square(0, 0, 1, 1), dxf_mod.Circle((5, 5), 1.0), dxf_mod.Line((8, 8), (9, 9))]
    with caplog.at_level(logging.WARNING):
        drawing = dxf_mod.join_segments(segments)
    assert len(drawing.loops) == 2
    assert "1 open chain" in caplog.text


def test_nesting_depths() -> None:
    segments = [
        *square(0, 0, 10, 10),  # surface A
        *square(1, 1, 9, 9),  # hole of A
        *square(2, 2, 8, 8),  # island in that hole: surface B
        dxf_mod.Circle((5, 5), 1.0),  # hole of B
        *square(20, 0, 30, 10),  # surface C, no holes
    ]
    drawing = dxf_mod.join_segments(segments)
    regions = dxf_mod.nest_loops(drawing)

    def bbox(i: int) -> tuple[float, ...]:
        xs, ys = zip(*drawing.loops[i].polygon(), strict=True)
        return min(xs), min(ys), max(xs), max(ys)

    summary = sorted((bbox(r.outer), sorted(bbox(h) for h in r.holes)) for r in regions)
    assert summary == [
        ((0, 0, 10, 10), [(1, 1, 9, 9)]),
        ((2, 2, 8, 8), [(4, 4, 6, 6)]),
        ((20, 0, 30, 10), []),
    ]


def test_arc_orientation_and_reversal() -> None:
    arc = dxf_mod.Arc((0.0, 0.0), 1.0, (1.0, 0.0), (0.0, 1.0), True, math.pi / 2)
    mid = arc.point_at(0.5)
    assert mid == pytest.approx((math.sqrt(0.5), math.sqrt(0.5)))
    back = arc.reversed()
    assert back.start == (0.0, 1.0) and not back.ccw
    assert back.point_at(0.5) == pytest.approx(mid)


# ------------------------------------------------------------- review fixes (M11.22)


@pytest.mark.parametrize("bulge", [0.5, 2.0, -2.0])
def test_bulge_arc_centre_radius_and_area(tmp_path: Path, bulge: float) -> None:
    """Closed polyline: arc (0, 0) -> (2, 0) with the given bulge, then straight to (1, s).

    DXF bulge b = tan(theta / 4), theta the included angle; b > 0 is counter-clockwise from
    the start vertex. Chord c = 2, so the centre lies at signed distance
    d = (c / 2) (1 - b^2) / (2 b) from the chord midpoint along its left normal, and the
    radius is r = c (1 + b^2) / (4 |b|). For b = 2: d = -0.75, r = 1.25, centre (1, -0.75).
    The apex of the arc is at distance r from the centre on the side away from the centre.
    The enclosed area is the triangle (0, 0), (2, 0), (1, s), with s = sign(b), plus the
    circular segment on the other side of the chord, r^2 / 2 (theta - sin theta) with
    theta = 4 atan(|b|). The two parts do not overlap, so the areas add.
    """
    apex_side = math.copysign(1.0, bulge)
    theta = 4.0 * math.atan(abs(bulge))
    radius = (1.0 + bulge * bulge) / (2.0 * abs(bulge))
    centre_y = (1.0 - bulge * bulge) / (2.0 * bulge)
    expected_area = 1.0 + radius**2 / 2.0 * (theta - math.sin(theta))

    doc, msp = new_drawing()
    msp.add_lwpolyline([(0, 0, bulge), (2, 0, 0), (1, apex_side, 0)], format="xyb", close=True)
    path = save(doc, tmp_path)

    arcs = [s for s in dxf_mod.read_dxf(str(path)) if isinstance(s, dxf_mod.Arc)]
    assert len(arcs) == 1
    arc = arcs[0]
    assert arc.center == pytest.approx((1.0, centre_y), rel=1e-9)
    assert arc.radius == pytest.approx(radius, rel=1e-9)
    assert arc.sweep == pytest.approx(theta, rel=1e-9)
    assert arc.ccw == (bulge > 0.0)
    apex = (1.0, centre_y - apex_side * radius)
    assert arc.point_at(0.5) == pytest.approx(apex, rel=1e-9, abs=1e-12)

    built = build(import_model(path))
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(expected_area, rel=1e-9)


def test_duplicate_line_segments_are_merged(tmp_path: Path) -> None:
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 1, 1)
    msp.add_line((1, 0), (0, 0))  # the bottom edge again, reversed
    built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(1.0, rel=1e-12)
    assert len(built.curves) == 4


def test_duplicate_arc_segments_are_merged(tmp_path: Path) -> None:
    w, h, rc = 2.0, 1.0, 0.25
    doc, msp = new_drawing()
    rounded_rectangle(msp, w, h, rc)
    msp.add_arc((w - rc, rc), rc, -90, 0)  # the corner arc drawn a second time
    built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(w * h - (4 - math.pi) * rc**2, rel=1e-9)
    assert len(built.curves) == 8


def test_hole_inside_a_fit_point_spline_outline_is_nested(tmp_path: Path) -> None:
    """Eight fit points on a circle of radius 5. The polygon through them is at radius
    5 cos(22.5 deg) = 4.62 on the bisector of two neighbouring points, while the curve stays
    near radius 5 there. A hole of radius 0.1 centred at radius 4.8 on that bisector lies
    inside the curve but outside the polygon, so it must be a hole of the outline."""
    r, hole_r, hole_at = 5.0, 0.1, 4.8
    angles = np.linspace(0, 2 * math.pi, 8, endpoint=False)
    pts = [(r * math.cos(a), r * math.sin(a)) for a in angles]
    bisector = math.pi / 8
    c = (hole_at * math.cos(bisector), hole_at * math.sin(bisector))
    doc, msp = new_drawing()
    spline = msp.add_spline(fit_points=pts)
    spline.closed = True
    msp.add_circle(c, hole_r)
    path = save(doc, tmp_path)

    regions = dxf_mod.nest_loops(dxf_mod.join_segments(dxf_mod.read_dxf(str(path))))
    assert sorted(len(reg.holes) for reg in regions) == [1]

    doc2, msp2 = new_drawing()
    spline2 = msp2.add_spline(fit_points=pts)
    spline2.closed = True
    outer_only = build(import_model(save(doc2, tmp_path, "outer.dxf")))
    built = build(import_model(path))
    assert len(built.surfaces) == 1
    # the surface is the outline less the hole: the same OCC curve, so the difference is exact
    assert area(outer_only) - area(built) == pytest.approx(math.pi * hole_r**2, rel=1e-9)


def test_closed_fit_point_spline_inside_a_rectangle_is_a_hole(tmp_path: Path) -> None:
    r, cx, cy = 2.0, 5.0, 5.0
    pts = [
        (cx + r * math.cos(a), cy + r * math.sin(a))
        for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)
    ]
    doc, msp = new_drawing()
    rectangle(msp, 0, 0, 10, 10)
    spline = msp.add_spline(fit_points=pts)
    spline.closed = True
    built = build(import_model(save(doc, tmp_path)))
    assert len(built.surfaces) == 1
    # the hole is the area enclosed by the interpolating spline, close to the disc of radius r;
    # the same 2e-2 tolerance as test_spline_through_fit_points
    assert 100.0 - area(built) == pytest.approx(math.pi * r**2, rel=2e-2)
