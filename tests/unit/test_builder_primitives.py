"""M2.4 — builder: primitives. Areas and lengths from ``occ.getMass`` equal analytic values."""

from __future__ import annotations

import math

import pytest

from thermalfea.core.errors import GeometryError
from thermalfea.geometry.builder import BuiltGeometry, build
from thermalfea.geometry.gmsh_session import GmshSession
from thermalfea.model import geometry_ops as g
from thermalfea.model.model import Model


def measure(built: BuiltGeometry, op_id: str) -> float:
    """Sum of occ.getMass over the entities owned by an operation."""
    with GmshSession.get().use(built.serial) as gmsh:
        return sum(gmsh.model.occ.getMass(dim, tag) for dim, tag in built.op_entities[op_id])


def dims(built: BuiltGeometry, op_id: str) -> list[int]:
    return [dim for dim, _ in built.op_entities[op_id]]


def test_rectangle() -> None:
    built = build(Model(geometry=[g.Rectangle("r", 0.1, 0.2, 0.6, 1.0)]))
    assert dims(built, "r") == [2]
    assert measure(built, "r") == pytest.approx(0.6, rel=1e-12)


def test_rounded_rectangle() -> None:
    r = 0.05
    built = build(Model(geometry=[g.Rectangle("r", 0.0, 0.0, 0.6, 1.0, corner_radius=r)]))
    assert measure(built, "r") == pytest.approx(0.6 - (4.0 - math.pi) * r**2, rel=1e-10)


def test_circle() -> None:
    built = build(Model(geometry=[g.Circle("c", 0.3, -0.2, 0.25)]))
    assert dims(built, "c") == [2]
    assert measure(built, "c") == pytest.approx(math.pi * 0.25**2, rel=1e-10)


def test_polygon() -> None:
    vertices = [(0.0, 0.0), (2.0, 0.0), (2.0, 1.0), (1.0, 1.0), (1.0, 2.0), (0.0, 2.0)]  # L-shape
    built = build(Model(geometry=[g.Polygon("p", vertices)]))
    shoelace = 0.5 * abs(
        sum(
            x0 * y1 - x1 * y0
            for (x0, y0), (x1, y1) in zip(vertices, vertices[1:] + vertices[:1], strict=True)
        )
    )
    assert shoelace == 3.0
    assert dims(built, "p") == [2]
    assert measure(built, "p") == pytest.approx(shoelace, rel=1e-12)


def test_point_line_arc_spline() -> None:
    """Curves are checked as the boundary of surfaces: construction geometry that bounds
    nothing is dropped at the end of a build (M2.5)."""
    built = build(
        Model(
            geometry=[
                # quarter disc of radius 1
                g.Point("o", 0.0, 0.0),
                g.Point("c", 1.0, 0.0),
                g.Point("d", 0.0, 1.0),
                g.Line("oc", "o", "c"),
                g.Arc("arc", "c", "o", "d"),
                g.Line("do", "d", "o"),
                g.SurfaceFromCurves("quarter", ["oc", "arc", "do"]),
                # 3-4-5 triangle whose hypotenuse is a spline through collinear points
                g.Point("a", 10.0, 0.0),
                g.Point("b", 13.0, 4.0),
                g.Point("e", 11.5, 2.0),
                g.Point("f", 13.0, 0.0),
                g.Spline("spline", ["a", "e", "b"]),
                g.Line("bf", "b", "f"),
                g.Line("fa", "f", "a"),
                g.SurfaceFromCurves("triangle", ["spline", "bf", "fa"]),
                # construction geometry that bounds nothing
                g.Point("lonely", 50.0, 50.0),
                g.Point("lonely2", 51.0, 50.0),
                g.Line("unused", "lonely", "lonely2"),
            ]
        )
    )
    assert dims(built, "o") == [0]
    assert dims(built, "oc") == dims(built, "arc") == dims(built, "spline") == [1]
    assert measure(built, "oc") == pytest.approx(1.0, rel=1e-12)
    assert measure(built, "arc") == pytest.approx(math.pi / 2.0, rel=1e-10)
    assert measure(built, "quarter") == pytest.approx(math.pi / 4.0, rel=1e-10)
    assert measure(built, "spline") == pytest.approx(5.0, rel=1e-8)
    assert measure(built, "bf") == pytest.approx(4.0, rel=1e-12)
    assert measure(built, "triangle") == pytest.approx(6.0, rel=1e-8)
    for op_id in ("lonely", "lonely2", "unused", "e"):
        assert built.op_entities[op_id] == []
    assert len(built.surfaces) == 2 and len(built.curves) == 6 and len(built.points) == 6


def test_surface_from_curves_half_disc() -> None:
    built = build(
        Model(
            geometry=[
                g.Point("o", 0.0, 0.0),
                g.Point("p1", 2.0, 0.0),
                g.Point("p2", -2.0, 0.0),
                g.Point("top", 0.0, 2.0),
                g.Arc("a1", "p1", "o", "top"),
                g.Arc("a2", "top", "o", "p2"),
                g.Line("base", "p2", "p1"),
                g.SurfaceFromCurves("s", ["a1", "a2", "base"]),
            ]
        )
    )
    assert dims(built, "s") == [2]
    assert measure(built, "s") == pytest.approx(0.5 * math.pi * 2.0**2, rel=1e-10)


def test_surface_from_curves_with_hole() -> None:
    def square(prefix: str, x0: float, y0: float, side: float) -> tuple[list, list[str]]:
        corners = [(x0, y0), (x0 + side, y0), (x0 + side, y0 + side), (x0, y0 + side)]
        pts = [g.Point(f"{prefix}p{i}", x, y) for i, (x, y) in enumerate(corners)]
        lines = [
            g.Line(f"{prefix}l{i}", f"{prefix}p{i}", f"{prefix}p{(i + 1) % 4}") for i in range(4)
        ]
        return pts + lines, [ln.id for ln in lines]

    outer_ops, outer = square("o", 0.0, 0.0, 3.0)
    hole_ops, hole = square("h", 1.0, 1.0, 1.0)
    built = build(
        Model(geometry=[*outer_ops, *hole_ops, g.SurfaceFromCurves("s", outer, holes=[hole])])
    )
    assert measure(built, "s") == pytest.approx(9.0 - 1.0, rel=1e-12)
    # curve order in the loop does not matter
    built = build(Model(geometry=[*outer_ops, g.SurfaceFromCurves("s", outer[::2] + outer[1::2])]))
    assert measure(built, "s") == pytest.approx(9.0, rel=1e-12)
    # an open chain is reported clearly
    with pytest.raises(GeometryError, match="operation 's' .*closed loop"):
        build(Model(geometry=[*outer_ops, g.SurfaceFromCurves("s", outer[:3])]))


def test_built_geometry_records_the_session_serial() -> None:
    first = build(Model(name="one", geometry=[g.Rectangle("r", 0, 0, 1, 1)]))
    second = build(Model(name="two", geometry=[g.Rectangle("r", 0, 0, 2, 1)]))
    assert second.serial == first.serial + 1 == GmshSession.get().serial
    assert measure(second, "r") == pytest.approx(2.0)
    with pytest.raises(GeometryError, match="rebuilt"):
        measure(first, "r")
    assert build(Model()).op_entities == {}


@pytest.mark.parametrize(
    ("geometry", "message"),
    [
        ([g.Line("l", "a", "b")], "operation 'l' .*unknown or later operation 'a'"),
        ([g.Point("a", 0, 0), g.Point("a", 1, 0)], "duplicate geometry operation id 'a'"),
        ([g.Rectangle("r", 0, 0, 1, 1), g.Line("l", "r", "r")], "no entity of dimension 0"),
        ([g.Rectangle("r", 0, 0, -1, 1)], "operation 'r' .*positive"),
        ([g.Circle("c", 0, 0, 0)], "operation 'c' .*positive"),
        ([g.Polygon("p", [(0, 0), (1, 0)])], "at least three"),
        ([g.Point("a", 0, 0), g.Spline("s", ["a"])], "at least two"),
        ([g.Point("a", 0, 0), g.Point("b", 0, 0), g.Line("l", "a", "b")], "operation 'l'"),
        ([g.ImportFile("i", "no-such-file.step", "step")], "operation 'i' .*file not found"),
        ([g.ImportFile("i", "x.dxf", "dxf")], "not supported"),
    ],
)
def test_errors_name_the_operation(geometry: list, message: str) -> None:
    with pytest.raises(GeometryError, match=message):
        build(Model(geometry=geometry))
    # the session is usable again after a failed build
    assert measure(build(Model(geometry=[g.Rectangle("r", 0, 0, 1, 1)])), "r") == pytest.approx(1.0)
