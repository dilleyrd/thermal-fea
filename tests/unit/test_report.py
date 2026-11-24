"""M10.5 — self-contained HTML report: sections, escaping, embedded plots and error paths."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Constant, Expression
from thermalfea.materials.material import Material
from thermalfea.model.bcs import Convection, FixedTemperature
from thermalfea.model.settings import SolutionSettings
from thermalfea.post.plots import heat_flow_history_data
from thermalfea.post.report import write_report
from thermalfea.post.results import Results

MATERIAL = "<b>Copper</b> alloy"
SECTIONS = ("summary", "materials", "mesh", "loads", "solver", "energy", "plots")
IMAGE = "data:image/png;base64,"


def _solved(path: Path, kind: str, name: str) -> Results:
    model = api.new_model(name=name)
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5)
    model.mesh_settings.global_size = 0.1
    built = api.build(model)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    model.materials[MATERIAL] = Material(
        MATERIAL, Expression("200 + 0.05*T"), Constant(8000.0), Constant(500.0)
    )
    api.assign_region(model, "all", material=MATERIAL)
    model.bcs += [
        FixedTemperature("hot", "west", T=400.0),
        Convection("cool", "east", h=100.0, T_inf=300.0),
    ]
    if kind == "transient":
        model.solution = SolutionSettings(
            kind="transient", end_time=60.0, auto_timestep=False, initial_dt=10.0,
            output="every_n", output_every=1,
        )  # fmt: skip
    else:
        model.solution = SolutionSettings(kind="steady")
    mesh = api.mesh(model, built)
    return api.solve(model, mesh, built=built, path=path)


@pytest.fixture(scope="module")
def steady(tmp_path_factory: pytest.TempPathFactory) -> Results:
    folder = tmp_path_factory.mktemp("report-steady")
    return _solved(folder / "steady.h5", "steady", "Plate steady")


@pytest.fixture(scope="module")
def transient(tmp_path_factory: pytest.TempPathFactory) -> Results:
    folder = tmp_path_factory.mktemp("report-transient")
    return _solved(folder / "transient.h5", "transient", "Plate transient")


def test_steady_report_has_every_section_and_the_model(steady: Results, tmp_path: Path) -> None:
    path = write_report(steady, tmp_path / "steady.html")
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>")
    for section in SECTIONS:
        assert f'<h2 id="{section}">' in text, section
    assert "<title>ThermalFEA report – Plate steady</title>" in text
    assert "<td>hot</td>" in text and "<td>cool</td>" in text
    assert f"<td>{steady.mesh.n_nodes}</td>" in text
    assert "<td>200 + 0.05*T</td>" in text  # a function of T is shown as its text
    assert "<td>8000</td>" in text
    assert "<h3>FixedTemperature</h3>" in text and "<h3>Convection</h3>" in text


def test_material_name_is_escaped(steady: Results, tmp_path: Path) -> None:
    text = write_report(steady, tmp_path / "escaped.html").read_text(encoding="utf-8")
    assert "&lt;b&gt;Copper&lt;/b&gt; alloy" in text
    assert "<b>Copper" not in text and "</b>" not in text


def test_report_has_no_external_links_or_scripts(steady: Results, tmp_path: Path) -> None:
    text = write_report(steady, tmp_path / "plain.html").read_text(encoding="utf-8")
    assert "http://" not in text and "https://" not in text and "<script" not in text


def test_steady_report_embeds_one_plot(steady: Results, tmp_path: Path) -> None:
    text = write_report(steady, tmp_path / "one.html").read_text(encoding="utf-8")
    assert text.count(IMAGE) == 1
    assert "Smallest time step" not in text  # no time steps in a steady solution


def test_each_requested_field_is_embedded(steady: Results, tmp_path: Path) -> None:
    text = write_report(steady, tmp_path / "fields.html", plots=("T", "qmag")).read_text(
        encoding="utf-8"
    )
    assert text.count(IMAGE) == 2


def test_transient_report_shows_dt_range_and_heat_flow_history(
    transient: Results, tmp_path: Path
) -> None:
    text = write_report(transient, tmp_path / "transient.html").read_text(encoding="utf-8")
    dt = np.asarray(transient.dt, dtype=float)
    dt = dt[np.isfinite(dt) & (dt > 0.0)]
    assert "Smallest time step [s]" in text and "Largest time step [s]" in text
    assert f"<td>{dt.min():.6g}</td>" in text and f"<td>{dt.max():.6g}</td>" in text
    assert text.count(IMAGE) == 2  # temperature contour and heat-flow history
    title = heat_flow_history_data(transient).title
    assert title and f"<h3>{title}</h3>" in text


def test_unknown_plot_field_is_a_model_error(steady: Results, tmp_path: Path) -> None:
    path = tmp_path / "bad.html"
    with pytest.raises(ModelError, match="unknown contour field 'nope'"):
        write_report(steady, path, plots=("nope",))
    assert not path.exists()


def test_step_out_of_range_is_a_model_error(steady: Results, tmp_path: Path) -> None:
    with pytest.raises(ModelError):
        write_report(steady, tmp_path / "step.html", step=steady.n_steps + 4)


