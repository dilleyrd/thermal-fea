"""M5.1 — contour plot: display triangulation, plotted arrays, units, drawing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from handmade import TYPES, make_problem
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.units import UnitSettings
from thermalfea.materials.material import Material
from thermalfea.model.bcs import FixedTemperature
from thermalfea.model.model import Model
from thermalfea.model.settings import SolutionSettings
from thermalfea.post.plots import FIELDS, contour, contour_data, display_triangulation
from thermalfea.post.recovery import gradient, nodal_flux
from thermalfea.post.results import Results
from thermalfea.solver.problem import RegionData
from thermalfea.solver.results_writer import ResultsWriter
from thermalfea.solver.steady import solve_steady

TRIANGLES = {"T3": 1, "Q4": 2, "T6": 4, "Q8": 6}
FLUX_FIELDS = [f for f in FIELDS if f != "T"]


def write(problem, path: Path, T: np.ndarray, times=(0.0,)) -> Results:
    with ResultsWriter(path, problem) as writer:
        for i, t in enumerate(times):
            writer.append_step(t, T + 10.0 * i)
    return Results(path)


def two_region(etype: str, path: Path):
    """Two layers in series (k = 50 and 5), left 400 K and right 300 K."""
    length = 0.1
    problem = make_problem(etype, size=(length, length / 10), cells=(20, 1), bcs=(
        FixedTemperature("hot", "left", T=400.0), FixedTemperature("cold", "right", T=300.0)))
    mesh = problem.mesh
    block = mesh.blocks[0]
    block.region[mesh.nodes[block.conn].mean(axis=1)[:, 0] > length / 2] = 2
    problem.regions[2] = RegionData(Material("poor", 5.0, 1.0, 1.0))
    problem.cache.clear()
    for term in problem.terms:
        term.setup(problem)
    T = solve_steady(problem)
    return problem, T, write(problem, path, T)


def tri_areas(mesh, tri: np.ndarray) -> np.ndarray:
    p = mesh.nodes[tri]
    return 0.5 * (
        (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1])
        - (p[:, 2, 0] - p[:, 0, 0]) * (p[:, 1, 1] - p[:, 0, 1])
    )


# ------------------------------------------------------------------ display triangulation


@pytest.mark.parametrize("etype", TYPES)
def test_triangulation_covers_the_mesh_exactly(etype: str) -> None:
    problem = make_problem(etype, size=(2.0, 1.0), cells=(4, 2))
    mesh = problem.mesh
    display = display_triangulation(mesh)
    n_el = sum(b.conn.shape[0] for b in mesh.blocks)
    assert display.triangles.shape == (n_el * TRIANGLES[etype], 3)
    assert display.region.shape == (display.triangles.shape[0],)
    areas = tri_areas(mesh, display.triangles)
    assert np.all(areas > 0.0)
    assert areas.sum() == pytest.approx(2.0, rel=1e-12)
    assert display_triangulation(mesh) is display  # cached


@pytest.mark.parametrize("etype", TYPES)
def test_triangulation_of_a_distorted_mesh_is_positive(etype: str) -> None:
    mesh = make_problem(etype, distortion=0.2).mesh
    display = display_triangulation(mesh)
    assert np.all(tri_areas(mesh, display.triangles) > 0.0)
    assert display.triangles.shape[0] == mesh.n_elements * TRIANGLES[etype]


@pytest.mark.parametrize("etype", ["T3", "Q4"])
def test_distorted_straight_sided_area_matches_the_elements(etype: str) -> None:
    mesh = make_problem(etype, distortion=0.2).mesh
    block = mesh.blocks[0]
    corners = mesh.nodes[block.conn]
    x, y = corners[..., 0], corners[..., 1]
    shoelace = 0.5 * np.sum(x * np.roll(y, -1, axis=1) - np.roll(x, -1, axis=1) * y, axis=1)
    areas = tri_areas(mesh, display_triangulation(mesh).triangles)
    assert areas.sum() == pytest.approx(np.abs(shoelace).sum(), rel=1e-12)


def test_triangulation_records_the_parent_region() -> None:
    problem = make_problem("Q4", cells=(4, 2))
    block = problem.mesh.blocks[0]
    block.region[:3] = 5
    display = display_triangulation(problem.mesh)
    np.testing.assert_array_equal(display.region, np.repeat(block.region, 2))


# ------------------------------------------------------------------------ plotted arrays


@pytest.mark.parametrize("etype", TYPES)
def test_plotted_extrema_equal_the_fields(etype: str, tmp_path: Path) -> None:
    problem, T, results = two_region(etype, tmp_path / "r.h5")
    mesh = results.mesh
    data = contour_data(results, -1, "T")
    assert len(data.parts) == 1
    assert data.parts[0].values.min() == data.vmin == T.min()
    assert data.parts[0].values.max() == data.vmax == T.max()
    flux = nodal_flux(mesh, problem, T)
    grad = gradient(mesh, problem, T)
    for name in FLUX_FIELDS:
        source, component, _, _ = FIELDS[name]
        raw = flux if source == "flux" else grad
        vals = np.concatenate([
            np.linalg.norm(q, axis=1) if component is None else q[:, component]
            for _, q in raw.values()
        ])
        data = contour_data(results, -1, name)
        plotted = np.concatenate([p.values for p in data.parts])
        assert plotted.min() == data.vmin == pytest.approx(vals.min(), rel=1e-12, abs=1e-9)
        assert plotted.max() == data.vmax == pytest.approx(vals.max(), rel=1e-12, abs=1e-9)
        for xy, v in ((data.xy_min, data.vmin), (data.xy_max, data.vmax)):
            hit = [p for p in data.parts if np.any(np.all(p.xy == xy, axis=1) & (p.values == v))]
            assert hit


def test_extrema_with_a_step_and_a_distorted_mesh(tmp_path: Path) -> None:
    problem = make_problem("Q8", distortion=0.2, bcs=(FixedTemperature("h", "left", T=400.0),
                                                       FixedTemperature("c", "right", T=300.0)))
    T = solve_steady(problem)
    results = write(problem, tmp_path / "r.h5", T, times=(0.0, 2.5))
    first = contour_data(results, 0, "T")
    last = contour_data(results, -1, "T")
    assert first.time == 0.0 and last.time == 2.5
    assert first.vmin == T.min() and last.vmax == pytest.approx(T.max() + 10.0)
    with pytest.raises(ModelError):
        contour_data(results, 5, "T")


# ------------------------------------------------------------------- region by region


@pytest.mark.parametrize("etype", TYPES)
def test_flux_is_drawn_region_by_region(etype: str, tmp_path: Path) -> None:
    problem, T, results = two_region(etype, tmp_path / "r.h5")
    flux = nodal_flux(results.mesh, problem, T)
    grad = gradient(results.mesh, problem, T)
    data = contour_data(results, -1, "qx")
    assert sorted(p.region for p in data.parts) == [1, 2]
    for part in data.parts:
        nodes, q = flux[part.region]
        lookup = dict(zip(nodes, q[:, 0], strict=True))
        np.testing.assert_allclose(part.values, [lookup[n] for n in part.nodes])
    interface = np.flatnonzero(np.isclose(results.mesh.nodes[:, 0], 0.05))
    for node in interface:
        assert all(node in p.nodes for p in data.parts)
    # the gradient jumps across the interface by the conductivity ratio
    gx = {p.region: dict(zip(p.nodes, p.values, strict=True))
          for p in contour_data(results, -1, "gradx").parts}
    for node in interface:
        assert gx[2][node] == pytest.approx(10.0 * gx[1][node], rel=1e-9)
        assert gx[1][node] == pytest.approx(dict(zip(*grad[1], strict=True))[node][0])
    # triangles of each part use only that region's elements
    display = display_triangulation(results.mesh)
    for part in data.parts:
        used = np.unique(part.nodes[part.triangles])
        np.testing.assert_array_equal(
            used, np.unique(display.triangles[display.region == part.region])
        )


# --------------------------------------------------------------------------------- units


def test_temperature_defaults_to_kelvin(tmp_path: Path) -> None:
    _, T, results = two_region("Q4", tmp_path / "r.h5")
    assert results.model is None
    data = contour_data(results, -1, "T")
    assert data.unit == "K" and data.vmin == T.min()
    assert "[K]" in data.label


@pytest.mark.parametrize(
    ("unit", "label", "offset", "scale"),
    [("K", "K", 0.0, 1.0), ("degC", "°C", -273.15, 1.0),
     ("degF", "°F", None, 1.8)],
)
def test_temperature_is_shown_in_the_display_unit(
    unit: str, label: str, offset: float | None, scale: float, tmp_path: Path
) -> None:
    problem, T, results = two_region("T3", tmp_path / "r.h5")
    results.model = Model(display_units=UnitSettings(temperature=unit))
    data = contour_data(results, -1, "T")
    expected = T + offset if offset is not None else (T - 273.15) * 1.8 + 32.0
    assert data.vmin == pytest.approx(expected.min()) and data.vmax == pytest.approx(expected.max())
    assert data.unit == label and f"[{label}]" in data.label
    grad = contour_data(results, -1, "gradmag")
    assert grad.unit == f"{label}/m" if unit != "K" else grad.unit == "K/m"
    raw = gradient(results.mesh, problem, T)
    top = max(np.linalg.norm(g, axis=1).max() for _, g in raw.values())
    assert grad.vmax == pytest.approx(top * scale)
    assert contour_data(results, -1, "qmag").unit == "W/m^2"


def test_unit_conversion_through_the_api(tmp_path: Path) -> None:
    model = api.new_model(name="slab")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5)
    model.mesh_settings.global_size = 0.25
    model.display_units = UnitSettings(temperature="degC")
    built = api.build(model)
    api.select_curves(model, built, "l", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "r", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "all", material="Carbon steel AISI 1010")
    model.bcs += [FixedTemperature("a", "l", T=373.15), FixedTemperature("b", "r", T=273.15)]
    results = api.solve(model, api.mesh(model, built), built=built, path=tmp_path / "s.h5")
    data = contour_data(results, -1, "T")
    assert data.unit == "°C"
    assert data.vmin == pytest.approx(0.0, abs=1e-9) and data.vmax == pytest.approx(100.0)
    fig = api.plot_contour(results, field="T", path=tmp_path / "s.png")
    assert isinstance(fig, Figure) and (tmp_path / "s.png").stat().st_size > 0


# ------------------------------------------------------------------------------ drawing


@pytest.fixture
def results(tmp_path: Path) -> Results:
    return two_region("Q8", tmp_path / "r.h5")[2]


def test_contour_returns_a_figure_with_title_colorbar_and_markers(results: Results) -> None:
    fig = contour(results, field="T", levels=8)
    assert isinstance(fig, Figure)
    assert len(fig.axes) == 2  # plot and color bar
    ax = fig.axes[0]
    assert "steady state" in ax.get_title()  # a steady file has no time (M11.8)
    # the color bar is vertical for tall models and horizontal for flat ones
    bar = fig.axes[1]
    assert "Temperature [K]" in (bar.get_ylabel(), bar.get_xlabel())
    assert len(ax.collections) >= 1 and len(ax.texts) == 2
    assert ax.get_aspect() == 1.0


def test_title_contains_the_time(tmp_path: Path) -> None:
    problem = make_problem("T3", bcs=(FixedTemperature("h", "left", T=400.0),
                                      FixedTemperature("c", "right", T=300.0)))
    T = solve_steady(problem)
    # stored as a transient run
    problem.settings = SolutionSettings(kind="transient", end_time=12.5, initial_dt=12.5)
    results = write(problem, tmp_path / "r.h5", T, times=(0.0, 12.5))
    assert "12.5 s" in contour(results, step=-1).axes[0].get_title()
    assert "0 s" in contour(results, step=0).axes[0].get_title()


def test_contour_draws_into_the_given_axes(results: Results) -> None:
    host = Figure()
    ax = host.add_subplot(1, 1, 1)
    fig = contour(results, field="qx", ax=ax)
    assert fig is host and len(ax.collections) >= 2  # one per region
    assert ax.get_title()


def test_contour_saves_a_png(results: Results, tmp_path: Path) -> None:
    out = tmp_path / "plot.png"
    contour(results, field="qmag", path=out)
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 1000


@pytest.mark.parametrize("smooth", [False, True])
@pytest.mark.parametrize("field", list(FIELDS))
def test_banded_and_smooth_both_draw(results: Results, smooth: bool, field: str) -> None:
    fig = contour(results, field=field, smooth=smooth, vmin=None, vmax=None)
    assert isinstance(fig, Figure)
    assert len(fig.axes[0].collections) >= 1


def test_explicit_limits_are_accepted(results: Results) -> None:
    fig = contour(results, field="T", vmin=310.0, vmax=390.0, levels=4)
    assert isinstance(fig, Figure)


def test_show_mesh_adds_a_line_collection(results: Results) -> None:
    plain = contour(results, show_mesh=False).axes[0]
    meshed = contour(results, show_mesh=True).axes[0]
    assert not any(isinstance(c, LineCollection) for c in plain.collections)
    assert any(isinstance(c, LineCollection) for c in meshed.collections)


@pytest.mark.parametrize("smooth", [False, True])
def test_uniform_field_does_not_raise(tmp_path: Path, smooth: bool) -> None:
    problem = make_problem("Q4")
    results = write(problem, tmp_path / "u.h5", np.full(problem.mesh.n_nodes, 350.0))
    fig = contour(results, field="T", smooth=smooth)
    assert isinstance(fig, Figure)
    assert contour_data(results, -1, "T").vmin == 350.0
    assert isinstance(contour(results, field="qmag", smooth=smooth), Figure)


def test_unknown_field_raises(results: Results) -> None:
    with pytest.raises(ModelError, match="unknown contour field"):
        contour(results, field="vonmises")
    with pytest.raises(ModelError):
        contour_data(results, -1, "nope")
