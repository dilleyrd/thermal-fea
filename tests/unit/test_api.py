"""M2.11 — API facade (Data §11) and ``thermalfea info``."""

from __future__ import annotations

import logging
import math
import re
from pathlib import Path

import pytest

from thermalfea import api, cli
from thermalfea.core.errors import ModelError
from thermalfea.model import geometry_ops as g
from thermalfea.model.bcs import Contact, FixedTemperature, Stream
from thermalfea.model.model import Model


def test_script_from_the_data_model(tmp_path: Path) -> None:
    """The example of Data §11, up to meshing."""
    model = api.new_model(analysis="planar")
    geo = api.Geometry(model)
    r = geo.rectangle(0, 0, 0.6, 1.0)
    built = api.build(model)
    sel = api.select_curves(model, built, name="bottom", where=lambda c: abs(c.center[1]) < 1e-9)
    api.assign_region(model, "all", material="Carbon steel AISI 1010")
    model.bcs.append(FixedTemperature("base", "bottom", T=373.15))
    mesh = api.mesh(model, built)

    assert r == "rectangle1"
    assert isinstance(model, Model) and model.analysis == "planar"
    assert len(sel.tags) == 1
    assert model.regions[0].selection == "all" and model.regions[0].thickness == 1.0
    assert model.materials["Carbon steel AISI 1010"].k() == 63.9
    mesh.validate()
    assert mesh.node_sets["bottom"].size > 2
    assert set(mesh.node_sets["all"]) == set(range(mesh.n_nodes))

    path = tmp_path / "plate.tfea"
    api.save(model, path)
    assert api.load(path) == model


def test_new_model() -> None:
    assert api.new_model() == Model()
    m = api.new_model("axisymmetric", name="pipe")
    assert m.axisymmetric and m.name == "pipe"
    with pytest.raises(ModelError):
        api.new_model("spherical")  # type: ignore[arg-type]


def test_geometry_helpers_append_the_right_operations() -> None:
    model = api.new_model()
    geo = api.Geometry(model)
    p1, p2, p3 = geo.point(0, 0), geo.point(1, 0), geo.point(0, 1)
    ids = [
        geo.line(p1, p2), geo.arc(p2, p1, p3), geo.spline([p3, p1]),
        geo.rectangle(0, 0, 2, 1, corner_radius=0.1), geo.circle(1, 0.5, 0.2),
        geo.polygon([(0, 0), (1, 0), (0, 1)]),
    ]
    surf = geo.surface(["line1", "arc1", "spline1"], holes=[["x"]])
    u = geo.union(["rectangle1"], ["polygon1"])
    c = geo.cut([u], ["circle1"], id="plate")
    i = geo.intersect([c], ["polygon1"])
    t = geo.translate([c], 1, 2, copy=True)
    ro = geo.rotate([c], math.pi, cx=1, cy=2)
    mi = geo.mirror([c], 0, 0, 0, 1)
    sc = geo.scale([c], 2.0)
    im = geo.import_file("part.STP", scale=0.001)
    de = geo.delete([t])

    assert (p1, p2, p3) == ("point1", "point2", "point3")
    assert ids == ["line1", "arc1", "spline1", "rectangle1", "circle1", "polygon1"]
    assert (surf, u, c, i) == ("surfacefromcurves1", "boolean1", "plate", "boolean2")
    assert (t, ro, mi, sc, im, de) == (
        "transform1", "transform2", "transform3", "transform4", "importfile1", "delete1")
    by_id = {op.id: op for op in model.geometry}
    assert len(by_id) == len(model.geometry) == 19
    assert by_id["rectangle1"] == g.Rectangle("rectangle1", 0.0, 0.0, 2.0, 1.0, 0.1)
    assert by_id["arc1"] == g.Arc("arc1", "point2", "point1", "point3")
    assert by_id[surf] == g.SurfaceFromCurves(surf, ["line1", "arc1", "spline1"], [["x"]])
    assert by_id["plate"] == g.Boolean("plate", "cut", ["boolean1"], ["circle1"])
    assert by_id[t] == g.Transform(t, "translate", ["plate"], {"dx": 1.0, "dy": 2.0}, True)
    assert by_id[ro].params == {"angle": math.pi, "cx": 1.0, "cy": 2.0} and not by_id[ro].copy
    assert by_id[mi].params == {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 1.0}
    assert by_id[sc].params == {"factor": 2.0, "cx": 0.0, "cy": 0.0}
    assert by_id[im] == g.ImportFile(im, "part.STP", "step", 0.001)
    assert by_id[de] == g.Delete(de, ["transform1"])
    with pytest.raises(ModelError, match="already used"):
        geo.point(0, 0, id="plate")
    with pytest.raises(ModelError, match="format"):
        geo.import_file("part.xyz")
    assert geo.import_file("a.brep") == "importfile2"


def test_build_refreshes_selections_and_warns_about_stale_ones(
    caplog: pytest.LogCaptureFixture,
) -> None:
    model = api.new_model()
    geo = api.Geometry(model)
    geo.rectangle(0, 0, 0.6, 1.0, id="plate")
    built = api.build(model)
    assert model.selections["all"].tags == sorted(built.surfaces)
    api.select_curves(model, built, "bottom", where=lambda c: abs(c.center[1]) < 1e-9)
    api.select_curves(model, built, "left", where=lambda c: abs(c.center[0]) < 1e-9)

    geo.rectangle(0.3, 0.0, 0.3, 1.0, id="inset")  # splits the bottom curve
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        rebuilt = api.build(model)
    assert len(model.selections["all"].tags) == len(rebuilt.surfaces) == 2
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1 and "'bottom' is stale" in messages[0]
    (left,) = model.selections["left"].tags
    assert rebuilt.curves[left].center == pytest.approx((0.0, 0.5, 0.0), abs=1e-12)

    empty = api.new_model()
    api.build(empty)
    assert "all" not in empty.selections


def test_assign_region() -> None:
    model = api.new_model()
    api.Geometry(model).rectangle(0, 0, 1, 1)
    with pytest.raises(ModelError, match="unknown selection 'all'"):
        api.assign_region(model, "all", material="Copper (pure)")
    built = api.build(model)
    first = api.assign_region(model, "all", material="copper (pure)", thickness=0.01)
    assert first.material == "Copper (pure)" and first.thickness == 0.01
    second = api.assign_region(model, "all", material="Silicon", material_angle=0.5)
    assert model.regions == [second]  # replaced, not duplicated
    assert set(model.materials) == {"Copper (pure)", "Silicon"}
    model.materials["Copper (pure)"].k = model.materials["Silicon"].k
    api.assign_region(model, "all", material="Copper (pure)")
    assert model.materials["Copper (pure)"].k() == 148.0  # the model's own copy is kept
    api.select_curves(model, built, "edges", where=lambda c: True)
    for args, message in (
        (("edges", "Silicon"), "does not contain surfaces"),
        (("all", "Unobtainium"), "no solid named"),
    ):
        with pytest.raises(ModelError, match=message):
            api.assign_region(model, *args)
    with pytest.raises(ModelError, match="thickness"):
        api.assign_region(model, "all", "Silicon", thickness=0.0)


# --------------------------------------------------------------------------------- CLI


def write_model(tmp_path: Path) -> Path:
    model = api.new_model(name="CLI plate")
    geo = api.Geometry(model)
    geo.rectangle(0, 0, 0.6, 1.0, id="plate")
    geo.circle(0.3, 0.5, 0.1, id="inset")
    model.mesh_settings.global_size = 0.1
    api.build(model)
    api.assign_region(model, "all", material="Silicon")
    path = tmp_path / "plate.tfea"
    api.save(model, path)
    return path


def test_cli_info(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = write_model(tmp_path)
    assert cli.main(["info", str(path)]) == 0
    out, err = capsys.readouterr()
    assert err == ""
    assert "CLI plate" in out and "planar, steady" in out
    assert "2 surfaces, 5 curves, 5 points" in out
    assert "Materials: 1" in out and "Regions: 1" in out
    nodes, elements, t3 = map(
        int, re.search(r"(\d+) nodes, (\d+) elements \((\d+) T3\)", out).groups()
    )
    model = api.load(path)
    mesh = api.mesh(model, api.build(model))
    assert (nodes, elements, t3) == (mesh.n_nodes, mesh.n_elements, mesh.n_elements)
    assert "minimum angle" in out


def test_cli_info_counts_streams_contacts_and_enclosures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    model = api.new_model(name="wired plate")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.05)
    model.mesh_settings.global_size = 0.05
    built = api.build(model)
    api.select_curves(model, built, "channel", where=lambda c: abs(c.center[1]) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.streams.append(Stream(
        name="coolant", fluid="Water", mode="in_plane", walls=["channel"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=300.0, mass_flow=0.05,
        path=[(0.0, 0.0), (1.0, 0.0)],
    ))
    model.contacts.append(Contact("gap", "channel", conductance=100.0))
    path = tmp_path / "wired.tfea"
    api.save(model, path)
    assert cli.main(["info", str(path)]) == 0
    out = capsys.readouterr().out
    assert "Streams:   1    Contacts: 1    Enclosures: 0" in out


def test_repeated_tags_are_stored_once() -> None:
    model, built = _plate_model()
    tag = next(iter(built.entities(1)))
    selection = api.select_curves(model, built, "once", tags=[tag, tag])
    assert selection.tags == [tag] and len(selection.fingerprints) == 1
    assert model.selections["once"].tags == [tag]


@pytest.mark.parametrize(
    ("name", "stem"),
    [
        ("CON", "CON_"), ("con", "con_"), ("nul", "nul_"), ("AUX ", "AUX_"),
        ("COM1", "COM1_"), ("lpt9", "lpt9_"), ("PRN.draft", "PRN_draft"),
        ("CON2", "CON2"), ("plate.v2", "plate_v2"), ("", "model"),
    ],
)
def test_default_file_stem_avoids_windows_device_names(name: str, stem: str) -> None:
    assert api._safe_file_stem(name) == stem


def test_model_named_con_gets_a_results_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tempfile

    monkeypatch.setattr(tempfile, "mkdtemp", lambda prefix: str(tmp_path))
    model, built = _plate_model()
    model.name = "CON"
    results = api.solve(model, api.mesh(model, built), built=built)
    assert results.path == tmp_path / "CON_.tfea.h5" and results.path.is_file()


def test_solve_logs_validation_warnings(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    from thermalfea.core.functions import Table
    from thermalfea.materials.material import Material

    model, built = _plate_model()
    mesh = api.mesh(model, built)
    # the conductivity is tabulated only at 320 to 380 K, but the model reaches 300 to 400 K
    table = Table([320.0, 380.0], [40.0, 35.0], "T")
    model.materials["Carbon steel AISI 1010"] = Material(
        "Carbon steel AISI 1010", table, 7800.0, 500.0
    )
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        api.solve(model, mesh, built=built, path=tmp_path / "warned.h5")
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert any("material Carbon steel AISI 1010" in m and "held" in m for m in messages)


def test_cli_errors_and_usage(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["info", str(tmp_path / "missing.tfea")]) == 1
    out, err = capsys.readouterr()
    assert out == "" and err.startswith("error: cannot read model file")
    assert cli.main([]) == 0
    assert "usage: thermalfea" in capsys.readouterr().out
    empty = tmp_path / "empty.tfea"
    api.save(api.new_model(), empty)
    assert cli.main(["info", str(empty)]) == 0
    assert "no surfaces to mesh" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["frobnicate"])


def _plate_model() -> tuple[Model, object]:
    model = api.new_model(analysis="planar")
    api.Geometry(model).rectangle(0, 0, 0.1, 0.1)
    model.mesh_settings.global_size = 0.05
    built = api.build(model)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 0.1) < 1e-9)
    api.assign_region(model, "all", material="Carbon steel AISI 1010")
    model.bcs += [
        FixedTemperature("hot", "west", T=400.0),
        FixedTemperature("cold", "east", T=300.0),
    ]
    return model, built


def test_solve_without_built_runs_the_checks_that_need_only_the_model(tmp_path: Path) -> None:
    from thermalfea.core.functions import Expression
    from thermalfea.model.bcs import HeatFlux

    model, built = _plate_model()
    mesh = api.mesh(model, built)
    assert api.solve(model, mesh, path=tmp_path / "ok.h5").n_steps >= 1  # a good model solves
    model.bcs.append(HeatFlux("flux", "all", q=1.0))  # a surface selection
    with pytest.raises(ModelError, match=r"needs a selection of boundaries \(curves\)"):
        api.solve(model, mesh, path=tmp_path / "a.h5")
    model.bcs.pop()
    material = model.materials["Carbon steel AISI 1010"]
    material.k = Expression("sqrt(T - 4000)")
    with pytest.raises(ModelError, match="not finite"):
        api.solve(model, mesh, path=tmp_path / "b.h5")
    material.k = Expression("50 + T/100")
    model.solution.kind, model.solution.end_time, model.solution.dt_min = "transient", 10.0, 0.0
    with pytest.raises(ModelError, match="dt_min"):
        api.solve(model, mesh, path=tmp_path / "c.h5")
