"""M2.10 — STEP/BREP import: only surfaces in the plane z = 0 are kept."""

from __future__ import annotations

import math
from collections.abc import Callable
from pathlib import Path

import pytest

from thermalfea.core.errors import GeometryError
from thermalfea.geometry.builder import build
from thermalfea.geometry.gmsh_session import fresh_model
from thermalfea.meshing.mesher import generate
from thermalfea.model import geometry_ops as g
from thermalfea.model.model import Model
from thermalfea.model.settings import MeshSettings

W, H, R = 0.6, 1.0, 0.1


def write_cad(path: Path, make: Callable) -> Path:
    """Create a CAD file with gmsh; ``make(occ)`` adds the shapes."""
    with fresh_model("export") as gmsh:
        make(gmsh.model.occ)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    return path


def plate_with_hole(occ) -> None:
    plate = occ.addRectangle(0.0, 0.0, 0.0, W, H)
    hole = occ.addDisk(0.3, 0.5, 0.0, R, R)
    occ.cut([(2, plate)], [(2, hole)])


def area(built) -> float:
    return sum(fp.measure for fp in built.surfaces.values())


@pytest.mark.parametrize("fmt", ["step", "brep"])
def test_import_plate_with_hole(tmp_path: Path, fmt: str) -> None:
    path = write_cad(tmp_path / f"part.{fmt}", plate_with_hole)
    model = Model(
        geometry=[g.ImportFile("part", str(path), fmt)],
        mesh_settings=MeshSettings(global_size=0.05),
    )
    built = build(model)
    assert len(built.surfaces) == 1
    assert area(built) == pytest.approx(W * H - math.pi * R**2, rel=1e-9)
    assert [d for d, _ in built.op_entities["part"]] == [2]
    assert len(built.curves) == 5
    mesh = generate(model, built)  # an imported shape meshes like any other
    mesh.validate()


def test_import_scale(tmp_path: Path) -> None:
    path = write_cad(tmp_path / "mm.step", lambda occ: occ.addRectangle(0, 0, 0, 600.0, 1000.0))
    built = build(Model(geometry=[g.ImportFile("part", str(path), "step", scale=0.001)]))
    assert area(built) == pytest.approx(0.6)
    assert built.bbox == pytest.approx((0, 0, 0, 0.6, 1.0, 0), abs=1e-5)


def test_imported_shape_combines_with_other_operations(tmp_path: Path) -> None:
    path = write_cad(tmp_path / "plate.brep", lambda occ: occ.addRectangle(0, 0, 0, 2.0, 1.0))
    built = build(
        Model(
            geometry=[
                g.ImportFile("plate", str(path), "brep"),
                g.Circle("hole", 1.0, 0.5, 0.25),
                g.Boolean("cut", "cut", ["plate"], ["hole"]),
                g.Rectangle("next", 2.0, 0.0, 1.0, 1.0),
            ]
        )
    )
    assert len(built.surfaces) == 2
    assert area(built) == pytest.approx(3.0 - math.pi * 0.25**2, rel=1e-9)
    assert sum(len(s) > 1 for s in built.curve_surfaces.values()) == 1  # shared edge


def test_two_surfaces_in_one_file(tmp_path: Path) -> None:
    def make(occ) -> None:
        occ.addRectangle(0, 0, 0, 1.0, 1.0)
        occ.addRectangle(1.0, 0, 0, 1.0, 1.0)

    path = write_cad(tmp_path / "two.brep", make)
    built = build(Model(geometry=[g.ImportFile("two", str(path), "brep")]))
    assert len(built.surfaces) == 2 and len(built.op_entities["two"]) == 2
    assert area(built) == pytest.approx(2.0)


def tilted(occ) -> None:
    r = occ.addRectangle(0, 0, 0, 1.0, 1.0)
    occ.rotate([(2, r)], 0, 0, 0, 1, 0, 0, math.pi / 2)  # now in the x-z plane


def lifted(occ) -> None:
    occ.addRectangle(0, 0, 0.5, 1.0, 1.0)


def slightly_tilted(occ) -> None:
    r = occ.addRectangle(0, 0, 0, 1.0, 1.0)
    occ.rotate([(2, r)], 0, 0, 0, 1, 0, 0, 0.001)


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (tilted, "does not lie in the plane z = 0"),
        (lifted, "does not lie in the plane z = 0.*0.5"),
        (slightly_tilted, "does not lie in the plane z = 0"),
        (lambda occ: occ.addBox(0, 0, 0, 1, 1, 1), "contains 3D solids"),
        (lambda occ: occ.addLine(occ.addPoint(0, 0, 0), occ.addPoint(1, 0, 0)), "no surfaces"),
    ],
)
@pytest.mark.parametrize("fmt", ["step", "brep"])
def test_anything_else_is_refused_with_an_explanation(
    tmp_path: Path, fmt: str, make: Callable, message: str
) -> None:
    path = write_cad(tmp_path / f"bad.{fmt}", make)
    with pytest.raises(GeometryError, match=f"operation 'part' .*{message}"):
        build(Model(geometry=[g.ImportFile("part", str(path), fmt)]))


def test_file_problems(tmp_path: Path) -> None:
    with pytest.raises(GeometryError, match="file not found"):
        build(Model(geometry=[g.ImportFile("part", str(tmp_path / "missing.step"), "step")]))
    garbage = tmp_path / "garbage.step"
    garbage.write_text("this is not a STEP file", encoding="utf-8")
    with pytest.raises(GeometryError, match="operation 'part'"):
        build(Model(geometry=[g.ImportFile("part", str(garbage), "step")]))
    good = write_cad(tmp_path / "ok.brep", lambda occ: occ.addRectangle(0, 0, 0, 1, 1))
    with pytest.raises(GeometryError, match="scale must be positive"):
        build(Model(geometry=[g.ImportFile("part", str(good), "brep", scale=0.0)]))
    with pytest.raises(GeometryError, match="not supported"):
        build(Model(geometry=[g.ImportFile("part", str(good), "dxf")]))
    # the session still works after the failures
    again = build(Model(geometry=[g.ImportFile("part", str(good), "brep")]))
    assert area(again) == pytest.approx(1.0)
