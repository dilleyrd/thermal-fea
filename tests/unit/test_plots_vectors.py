"""M5.2 — vector plot: thinning of the heat-flux arrows, their values, and drawing."""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest
from handmade import TYPES, make_problem
from matplotlib.figure import Figure
from matplotlib.quiver import Quiver

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.model.bcs import FixedTemperature
from thermalfea.model.settings import SolutionSettings
from thermalfea.post.plots import vector_data, vectors
from thermalfea.post.results import Results
from thermalfea.solver.results_writer import ResultsWriter
from thermalfea.solver.steady import solve_steady

K = 50.0  # conductivity of the slab (handmade.make_problem default)


def write(problem, path: Path, T: np.ndarray, times=(0.0,)) -> Results:
    with ResultsWriter(path, problem) as writer:
        for t in times:
            writer.append_step(t, T)
    return Results(path)


def slab(etype: str, path: Path, cells=(4, 2), size=(4.0, 2.0), times=(0.0,)) -> Results:
    """A slab 400 K at the left and 300 K at the right: a uniform flux in +x.

    Several ``times`` are stored as a transient run (a steady file has no time, M11.8).
    """
    problem = make_problem(etype, size=size, cells=cells, bcs=(
        FixedTemperature("hot", "left", T=400.0), FixedTemperature("cold", "right", T=300.0)))
    T = solve_steady(problem)
    if len(times) > 1:
        problem.settings = SolutionSettings(kind="transient", end_time=max(times), initial_dt=1.0)
    return write(problem, path, T, times=times)


def grid_cells(xy_all: np.ndarray, xy: np.ndarray, density: int) -> tuple[np.ndarray, ...]:
    """Grid cell (i, j) of points ``xy`` on the grid built from all centroids ``xy_all``."""
    lo = xy_all.min(axis=0)
    extent = float(np.max(xy_all.max(axis=0) - lo))
    h = extent / density
    ij = np.floor((xy - lo) / h).astype(int)
    centre = lo + (ij + 0.5) * h
    return ij, np.sum((xy - centre) ** 2, axis=1)


# ------------------------------------------------------------------------------ arrow data


@pytest.mark.parametrize("etype", TYPES)
def test_coarse_mesh_keeps_every_element(etype: str, tmp_path: Path) -> None:
    results = slab(etype, tmp_path / "r.h5")
    mesh = results.mesh
    centroids = mesh.element_centroids()
    flux = results.element_flux(-1)
    data = vector_data(results, -1, density=30)
    n_el = centroids.shape[0]
    np.testing.assert_array_equal(data.elements, np.arange(n_el))
    np.testing.assert_allclose(data.xy, centroids[:, :2])
    np.testing.assert_allclose(data.q, flux[data.elements, :2])
    np.testing.assert_allclose(data.magnitude, np.linalg.norm(data.q, axis=1))
    assert data.time == 0.0 and data.title.startswith("Heat flux")


@pytest.mark.parametrize("etype", TYPES)
def test_thinning_keeps_one_element_per_cell(etype: str, tmp_path: Path) -> None:
    results = slab(etype, tmp_path / "r.h5", cells=(40, 20), size=(4.0, 2.0))
    density = 10
    centroids = results.mesh.element_centroids()
    data = vector_data(results, -1, density=density)
    n = data.elements.size
    assert 10 <= n <= (density + 1) * (math.ceil(density * 0.5) + 1)
    assert n < centroids.shape[0]  # the mesh is finer than the grid
    xy_all = centroids[:, :2]
    ij, dist = grid_cells(xy_all, data.xy, density)
    assert len(np.unique(ij, axis=0)) == n  # no two kept elements share a cell
    # each kept element is the one nearest its cell centre among all elements of that cell
    all_ij, all_dist = grid_cells(xy_all, xy_all, density)
    for k in range(n):
        same = np.all(all_ij == ij[k], axis=1)
        assert dist[k] <= all_dist[same].min() + 1e-15


def test_density_below_one_is_rejected(tmp_path: Path) -> None:
    results = slab("Q4", tmp_path / "r.h5")
    with pytest.raises(ModelError):
        vector_data(results, -1, density=0)


def test_out_of_range_step_is_rejected(tmp_path: Path) -> None:
    results = slab("Q4", tmp_path / "r.h5")
    with pytest.raises(ModelError):
        vector_data(results, 3, density=10)


# ------------------------------------------------------------------------- uniform flux


@pytest.mark.parametrize("etype", TYPES)
def test_uniform_slab_flux_points_in_x(etype: str, tmp_path: Path) -> None:
    length = 4.0
    results = slab(etype, tmp_path / "r.h5", cells=(40, 20), size=(length, 2.0))
    data = vector_data(results, -1, density=10)
    expected = K * 100.0 / length
    np.testing.assert_allclose(data.q[:, 0], expected, rtol=1e-6)
    np.testing.assert_allclose(data.q[:, 1], 0.0, atol=1e-6 * expected)
    np.testing.assert_allclose(data.magnitude, expected, rtol=1e-6)


# ------------------------------------------------------------------------------ drawing


@pytest.fixture
def results(tmp_path: Path) -> Results:
    return slab("Q8", tmp_path / "r.h5", cells=(40, 20), size=(4.0, 2.0), times=(0.0, 12.5))


def quivers(ax) -> list[Quiver]:
    return [c for c in ax.collections if isinstance(c, Quiver)]


def test_vectors_returns_a_figure_with_one_quiver(results: Results) -> None:
    fig = vectors(results, density=10)
    assert isinstance(fig, Figure)
    ax = fig.axes[0]
    found = quivers(ax)
    assert len(found) == 1
    assert len(found[0].get_offsets()) == len(vector_data(results, -1, density=10).xy)
    assert len(fig.axes) == 2  # plot and colour bar
    assert fig.axes[1].get_ylabel() == "Heat flux [W/m²]"
    assert ax.get_aspect() == 1.0


def test_title_contains_the_time(results: Results) -> None:
    assert "12.5 s" in vectors(results, step=-1).axes[0].get_title()
    assert "0 s" in vectors(results, step=0).axes[0].get_title()


def test_vectors_draws_into_the_given_axes(results: Results) -> None:
    host = Figure()
    ax = host.add_subplot(1, 1, 1)
    fig = vectors(results, ax=ax)
    assert fig is host
    assert len(quivers(ax)) == 1
    assert ax.get_title()


def test_vectors_saves_a_png(results: Results, tmp_path: Path) -> None:
    out = tmp_path / "vectors.png"
    vectors(results, path=out)
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 1000


def test_plot_vectors_through_the_api(results: Results, tmp_path: Path) -> None:
    out = tmp_path / "api.png"
    fig = api.plot_vectors(results, step=-1, path=out, density=10)
    assert isinstance(fig, Figure) and out.stat().st_size > 0
    assert len(quivers(fig.axes[0])) == 1


def test_vectors_rejects_zero_density(results: Results) -> None:
    with pytest.raises(ModelError):
        vectors(results, density=0)
