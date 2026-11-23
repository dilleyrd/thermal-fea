"""M5.5 — export: nodal and history CSV, VTU series with a PVD index, and animations."""

from __future__ import annotations

import csv
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import meshio
import numpy as np
import pytest
from handmade import make_problem
from PIL import Image

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.model.bcs import Convection
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.post import export, plots
from thermalfea.post.results import Results
from thermalfea.solver.results_writer import ResultsWriter
from thermalfea.solver.run import run_transient

RHO, CP, SIDE = 7800.0, 500.0, 0.01
H, T_INF, T_INIT = 20.0, 300.0, 400.0
TAU = RHO * CP * SIDE * SIDE / (H * 4 * SIDE)
SIDES = ("bottom", "right", "top", "left")
NODAL_HEADER = "step,time,node,x,y,T,qx,qy"
MESHIO_TYPES = {"T3": "triangle", "Q4": "quad", "T6": "triangle6", "Q8": "quad8"}


def lumped():
    problem = make_problem("Q4", size=(SIDE, SIDE), cells=(2, 2), k=400.0, bcs=tuple(
        Convection(f"conv-{side}", side, h=H, T_inf=T_INF) for side in SIDES))
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(
        kind="transient", theta=1.0, initial_dt=TAU / 20, end_time=TAU, auto_timestep=False
    )
    return problem


@pytest.fixture
def results(tmp_path: Path) -> Results:
    path = tmp_path / "t.h5"
    run_transient(lumped(), path, T0=T_INIT)
    return Results(path)


def steady(etype: str, path: Path) -> Results:
    """A one-step results file with a non-uniform field, so the fluxes are not zero."""
    problem = make_problem(etype, size=(0.1, 0.02), cells=(4, 2))
    xy = problem.mesh.nodes
    T = 300.0 + 100.0 * xy[:, 0] / 0.1 + 50.0 * xy[:, 1] / 0.02
    with ResultsWriter(path, problem) as writer:
        writer.append_step(0.0, T)
    return Results(path)


def merged_flux(results: Results, step: int) -> np.ndarray:
    return Results.node_values(results.flux(step), results.mesh.n_nodes)


# ------------------------------------------------------------------------------ nodal table


def test_nodal_csv_header_rows_and_values(results: Results, tmp_path: Path) -> None:
    out = export.nodal_csv(results, tmp_path / "nodes.csv")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == NODAL_HEADER
    n = results.mesh.n_nodes
    assert len(lines) - 1 == results.n_steps * n
    data = np.genfromtxt(out, delimiter=",", names=True)
    assert data.dtype.names == tuple(NODAL_HEADER.split(","))
    xy = results.mesh.nodes
    for step in range(results.n_steps):
        rows = slice(step * n, (step + 1) * n)
        np.testing.assert_allclose(data["time"][rows], results.times[step], rtol=1e-12)
        np.testing.assert_array_equal(data["node"][rows], np.arange(n))
        np.testing.assert_allclose(data["x"][rows], xy[:, 0], rtol=1e-12)
        np.testing.assert_allclose(data["y"][rows], xy[:, 1], rtol=1e-12)
        np.testing.assert_allclose(data["T"][rows], results.temperature(step), rtol=1e-12)
        q = merged_flux(results, step)
        np.testing.assert_allclose(data["qx"][rows], q[:, 0], rtol=1e-12, atol=1e-12)
        np.testing.assert_allclose(data["qy"][rows], q[:, 1], rtol=1e-12, atol=1e-12)


def test_nodal_csv_selected_steps(results: Results, tmp_path: Path) -> None:
    out = export.nodal_csv(results, tmp_path / "two.csv", steps=[0, -1])
    assert len(out.read_text().splitlines()) - 1 == 2 * results.mesh.n_nodes
    data = np.genfromtxt(out, delimiter=",", names=True)
    assert data["time"][0] == results.times[0]
    assert data["time"][-1] == results.times[-1]


def test_nodal_csv_bad_step_is_rejected(results: Results, tmp_path: Path) -> None:
    with pytest.raises(ModelError):
        export.nodal_csv(results, tmp_path / "bad.csv", steps=[results.n_steps])
    with pytest.raises(ModelError):
        export.nodal_csv(results, tmp_path / "none.csv", steps=[])


# ----------------------------------------------------------------------------- history table


def read_table(path: Path) -> tuple[list[str], np.ndarray]:
    header = path.read_text(encoding="utf-8").splitlines()[0].split(",")
    return header, np.genfromtxt(path, delimiter=",", skip_header=1, ndmin=2)


def test_history_csv_columns_and_values(results: Results, tmp_path: Path) -> None:
    out = export.history_csv(results, tmp_path / "h.csv", nodes=[0, 3])
    header, data = read_table(out)
    assert header == ["time", "T:node 0", "T:node 3"] + [
        f"heat:{name}" for name in results.heat_flow_names
    ]
    np.testing.assert_allclose(data[:, 0], results.times, rtol=1e-12)
    np.testing.assert_allclose(data[:, 1], results.nodal_history(0), rtol=1e-12)
    np.testing.assert_allclose(data[:, 2], results.nodal_history(3), rtol=1e-12)
    for k, name in enumerate(results.heat_flow_names):
        np.testing.assert_allclose(
            data[:, 3 + k], results.heat_flow(name), rtol=1e-12, equal_nan=True
        )
    assert np.isnan(data[0, 3:]).all()  # the initial state has no heat flow


def test_history_csv_quotes_names_with_commas_and_quotes(tmp_path: Path) -> None:
    names = ["inlet, left", 'say "hi"']
    problem = make_problem("Q4", size=(SIDE, SIDE), cells=(2, 2), k=400.0, bcs=(
        Convection(names[0], "left", h=H, T_inf=T_INF),
        Convection(names[1], "right", h=H, T_inf=T_INF),
    ))
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(
        kind="transient", theta=1.0, initial_dt=TAU / 20, end_time=TAU, auto_timestep=False
    )
    run_transient(problem, tmp_path / "c.h5", T0=T_INIT)
    res = Results(tmp_path / "c.h5")
    out = export.history_csv(res, tmp_path / "c.csv", nodes=[0])
    with out.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.reader(fh))
    assert set(len(row) for row in rows) == {4}
    assert rows[0][0] == "time" and rows[0][1] == "T:node 0"
    assert sorted(rows[0][2:]) == sorted(f"heat:{n}" for n in names)
    assert len(rows) == 1 + res.n_steps


def test_history_csv_points_match_nodes(results: Results, tmp_path: Path) -> None:
    xy = results.mesh.nodes[:, :2]
    by_point = export.history_csv(
        results, tmp_path / "p.csv", points=[tuple(xy[3] + 1e-7), tuple(xy[0])]
    )
    by_node = export.history_csv(results, tmp_path / "n.csv", nodes=[3, 0])
    assert by_point.read_text() == by_node.read_text()


def test_history_csv_bc_selection(results: Results, tmp_path: Path) -> None:
    none = export.history_csv(results, tmp_path / "none.csv", nodes=[0], bc_names=[])
    header, _ = read_table(none)
    assert header == ["time", "T:node 0"]
    one = export.history_csv(results, tmp_path / "one.csv", bc_names=["conv-left"])
    header, data = read_table(one)
    assert header == ["time", "heat:conv-left"]
    np.testing.assert_allclose(data[:, 1], results.heat_flow("conv-left"), equal_nan=True)


def test_history_csv_rejects_bad_selectors(results: Results, tmp_path: Path) -> None:
    with pytest.raises(ModelError):
        export.history_csv(results, tmp_path / "x.csv", nodes=[0], points=[(0.0, 0.0)])
    with pytest.raises(ModelError):
        export.history_csv(results, tmp_path / "x.csv", nodes=[99])


# ----------------------------------------------------------------------------------- VTU


def test_vtu_series_and_pvd_index(results: Results, tmp_path: Path) -> None:
    pvd = export.vtu(results, tmp_path / "vtk", name="run")
    assert pvd == tmp_path / "vtk" / "run.pvd" and pvd.is_file()
    datasets = ET.parse(pvd).getroot().find("Collection").findall("DataSet")
    assert len(datasets) == results.n_steps
    for step, ds in enumerate(datasets):
        assert float(ds.get("timestep")) == pytest.approx(float(results.times[step]), rel=1e-15)
        assert (pvd.parent / ds.get("file")).is_file()
    assert datasets[0].get("file") == "run_0000.vtu"


@pytest.mark.parametrize("etype", list(MESHIO_TYPES))
def test_vtu_file_round_trip(tmp_path: Path, etype: str) -> None:
    res = steady(etype, tmp_path / f"{etype}.h5")
    pvd = export.vtu(res, tmp_path / "vtk", steps=[0])
    mesh = res.mesh
    (dataset,) = ET.parse(pvd).getroot().find("Collection").findall("DataSet")
    back = meshio.read(pvd.parent / dataset.get("file"))

    assert back.points.shape == (mesh.n_nodes, 3)
    np.testing.assert_allclose(back.points[:, :2], mesh.nodes, rtol=1e-12)
    np.testing.assert_array_equal(back.points[:, 2], 0.0)
    np.testing.assert_allclose(back.point_data["T"], res.temperature(0), rtol=1e-12)
    q = back.point_data["q"]
    np.testing.assert_allclose(q[:, :2], merged_flux(res, 0), rtol=1e-12, atol=1e-9)
    np.testing.assert_array_equal(q[:, 2], 0.0)

    assert [c.type for c in back.cells] == [MESHIO_TYPES[etype]] * len(mesh.blocks)
    for k, block in enumerate(mesh.blocks):
        np.testing.assert_array_equal(back.cells[k].data, block.conn)
        np.testing.assert_array_equal(back.cell_data["region"][k], block.region)
        assert back.cell_data["q_element"][k].shape == (block.conn.shape[0], 3)


def test_pvd_escapes_the_base_name(results: Results, tmp_path: Path) -> None:
    pvd = export.vtu(results, tmp_path / "vtk", name="a&b", steps=[0])
    (dataset,) = ET.parse(pvd).getroot().find("Collection").findall("DataSet")
    assert dataset.get("file") == "a&b_0000.vtu"
    assert (pvd.parent / dataset.get("file")).is_file()


def test_file_without_steps_is_a_model_error(tmp_path: Path) -> None:
    path = tmp_path / "empty.h5"
    with ResultsWriter(path, lumped()):
        pass  # a run cancelled before its first step leaves a file like this
    res = Results(path)
    assert res.n_steps == 0
    with pytest.raises(ModelError, match="no steps"):
        export.nodal_csv(res, tmp_path / "n.csv")
    with pytest.raises(ModelError, match="no steps"):
        export.history_csv(res, tmp_path / "h.csv", nodes=[0])
    with pytest.raises(ModelError, match="no steps"):
        export.vtu(res, tmp_path / "vtk")
    with pytest.raises(ModelError, match="no steps"):
        export.animation(res, tmp_path / "a.gif")


def test_vtu_writes_into_a_new_folder_with_all_steps(results: Results, tmp_path: Path) -> None:
    folder = tmp_path / "deep" / "vtk"
    pvd = export.vtu(results, folder)
    files = sorted(p.name for p in folder.glob("results_*.vtu"))
    assert files == [f"results_{i:04d}.vtu" for i in range(results.n_steps)]
    assert pvd.name == "results.pvd"


# ----------------------------------------------------------------------------------- animation


def test_gif_has_one_frame_per_step(results: Results, tmp_path: Path) -> None:
    out = export.animation(results, tmp_path / "anim.gif", steps=[0, 1, 2], fps=5, dpi=40)
    assert out.stat().st_size > 0
    with Image.open(out) as img:
        assert img.n_frames == 3


def test_all_frames_share_the_colour_range(
    results: Results, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = plots.contour
    seen: list[dict] = []

    def recorder(res, step, field="T", **kwargs):
        seen.append(kwargs)
        return original(res, step, field, **kwargs)

    monkeypatch.setattr(plots, "contour", recorder)
    export.animation(results, tmp_path / "range.gif", steps=[0, 1, 2], dpi=40)
    assert len(seen) == 3
    assert seen[0]["vmin"] is not None and seen[0]["vmax"] is not None
    assert all(k["vmin"] == seen[0]["vmin"] and k["vmax"] == seen[0]["vmax"] for k in seen)
    expected_lo = min(plots.contour_data(results, s).vmin for s in range(3))
    expected_hi = max(plots.contour_data(results, s).vmax for s in range(3))
    assert seen[0]["vmin"] == pytest.approx(expected_lo)
    assert seen[0]["vmax"] == pytest.approx(expected_hi)


def test_given_colour_limits_are_kept(results: Results, tmp_path: Path) -> None:
    out = export.animation(results, tmp_path / "fixed.gif", steps=[0, 1], dpi=40, vmin=300.0,
                           vmax=420.0)
    with Image.open(out) as img:
        assert img.n_frames == 2


def test_mp4_needs_ffmpeg(results: Results, tmp_path: Path) -> None:
    if shutil.which("ffmpeg") is not None:
        pytest.skip("ffmpeg is installed here")
    with pytest.raises(ModelError, match="ffmpeg"):
        export.animation(results, tmp_path / "anim.mp4", steps=[0])


@pytest.mark.parametrize(
    ("name", "kwargs"),
    [
        ("anim.avi", {}),
        ("anim.gif", {"fps": 0}),
        ("anim.gif", {"fps": -2.0}),
        ("anim.gif", {"fps": float("nan")}),
        ("anim.gif", {"fps": float("inf")}),
        ("anim.gif", {"steps": []}),
    ],
)
def test_bad_animation_arguments_are_rejected(
    results: Results, tmp_path: Path, name: str, kwargs: dict
) -> None:
    with pytest.raises(ModelError):
        export.animation(results, tmp_path / name, **kwargs)


# ----------------------------------------------------------------------------------- api


def test_export_wrappers_through_the_api(results: Results, tmp_path: Path) -> None:
    csv_path = api.export_csv(results, tmp_path / "api.csv", steps=[-1])
    assert csv_path.read_text().splitlines()[0] == NODAL_HEADER
    pvd = api.export_vtu(results, tmp_path / "apivtk", name="api", steps=[0])
    assert pvd.name == "api.pvd" and pvd.is_file()
    gif = api.export_animation(results, tmp_path / "api.gif", steps=[0, 1], fps=5, dpi=40)
    with Image.open(gif) as img:
        assert img.n_frames == 2
