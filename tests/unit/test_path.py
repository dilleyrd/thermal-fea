"""M5.4 — path sampling: point location, interpolation, derived fields, and the path plot."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from handmade import TYPES, make_problem
from matplotlib.figure import Figure

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.registry import element
from thermalfea.post import plots
from thermalfea.post.path import interpolate, locate, polyline_points, sample, value_at
from thermalfea.post.results import Results
from thermalfea.solver.results_writer import ResultsWriter

K = 50.0
SIZE = (2.0, 1.0)


def linear(xy: np.ndarray) -> np.ndarray:
    return 300.0 + 120.0 * xy[:, 0] - 75.0 * xy[:, 1]


def make_results(tmp_path: Path, etype: str, field=linear, distortion: float = 0.2,
                 cells=(4, 2), name: str = "p.h5") -> Results:
    problem = make_problem(etype, size=SIZE, cells=cells, distortion=distortion, k=K)
    T = field(problem.mesh.nodes[:, :2])
    path = tmp_path / name
    with ResultsWriter(path, problem) as writer:
        writer.append_step(0.0, T)
    return Results(path)


# a path with several segments, all inside the 2 x 1 domain
POLYLINE = [(0.1, 0.1), (1.0, 0.9), (1.9, 0.2), (0.0, 0.5), (0.7, 0.0)]


# --------------------------------------------------------------------------- acceptance


@pytest.mark.parametrize("etype", TYPES)
def test_linear_field_is_exact_on_distorted_meshes(tmp_path: Path, etype: str) -> None:
    results = make_results(tmp_path, etype)
    mesh = results.mesh
    s, values = sample(results, 0, POLYLINE, n=400)
    _, xy = polyline_points(POLYLINE, 400)
    assert np.all(np.isfinite(values))
    np.testing.assert_allclose(values, linear(xy), atol=1e-9)
    # points on the boundary, on element edges and exactly on mesh nodes
    on_nodes = mesh.nodes[:, :2]
    along_bottom = np.column_stack([np.linspace(0.0, 2.0, 37), np.zeros(37)])
    pts = np.vstack([on_nodes, along_bottom, [[1.0, 0.5], [0.5, 1.0], [2.0, 1.0]]])
    got = interpolate(mesh, locate(mesh, pts), linear(mesh.nodes[:, :2]))
    assert np.all(np.isfinite(got))
    np.testing.assert_allclose(got, linear(pts), atol=1e-9)


@pytest.mark.parametrize("etype", TYPES)
def test_points_outside_the_mesh_are_nan(tmp_path: Path, etype: str) -> None:
    results = make_results(tmp_path, etype)
    # starts inside, leaves through the right edge
    s, values = sample(results, 0, [(1.0, 0.5), (3.0, 0.5)], n=21)
    xs = 1.0 + s
    assert np.all(np.isfinite(values[xs <= 2.0 + 1e-12]))
    assert np.all(np.isnan(values[xs > 2.0 + 1e-6]))
    assert np.isnan(value_at(results, 0, (50.0, 50.0)))
    assert np.isnan(value_at(results, 0, (2.0 + 1e-6, 0.5)))
    assert np.isnan(value_at(results, 0, (1.0, -1e-6)))
    assert np.isnan(value_at(results, 0, (-1e-6, -1e-6)))
    # exactly on the boundary and at corner nodes
    for p in [(2.0, 0.5), (1.0, 1.0), (0.0, 0.0), (2.0, 1.0), (0.0, 1.0), (2.0, 0.0)]:
        assert value_at(results, 0, p) == pytest.approx(linear(np.array([p]))[0], abs=1e-9)


# ---------------------------------------------------------------------------- locate


@pytest.mark.parametrize("etype", TYPES)
def test_locate_returns_consistent_coordinates(tmp_path: Path, etype: str) -> None:
    results = make_results(tmp_path, etype)
    mesh = results.mesh
    rng = np.random.default_rng(3)
    pts = rng.uniform([0.0, 0.0], SIZE, size=(500, 2))
    loc = locate(mesh, pts)
    assert np.all(loc.elem_ids >= 0)
    all_ids = np.concatenate([b.elem_ids for b in mesh.blocks])
    assert np.all(np.isin(loc.elem_ids, all_ids))
    back = np.full_like(pts, np.nan)
    for ib, block in enumerate(mesh.blocks):
        sel = loc.block == ib
        et = element(block.etype)
        np.testing.assert_array_equal(block.elem_ids[loc.row[sel]], loc.elem_ids[sel])
        X = mesh.nodes[block.conn[loc.row[sel]]]
        back[sel] = np.einsum("mn,mni->mi", et.shape(loc.local[sel]), X)
        # inside the reference element
        corners = et.node_coords[et.facets[:, 0]]
        nxt = np.roll(corners, -1, axis=0)
        e = nxt - corners
        rel = loc.local[sel][:, None, :] - corners[None]
        cross = e[None, :, 0] * rel[:, :, 1] - e[None, :, 1] * rel[:, :, 0]
        assert np.all(cross >= -1e-8)
    np.testing.assert_allclose(back, pts, atol=1e-9)


def test_locate_outside_has_nan_local_and_minus_one() -> None:
    problem = make_problem("T6", size=SIZE, distortion=0.2)
    loc = locate(problem.mesh, np.array([[5.0, 5.0], [1.0, 0.5]]))
    np.testing.assert_array_equal(loc.elem_ids[0], -1)
    assert loc.block[0] == -1 and np.all(np.isnan(loc.local[0]))
    assert loc.elem_ids[1] >= 0 and np.all(np.isfinite(loc.local[1]))


# ------------------------------------------------------------------------ quadratic field


def quadratic(xy: np.ndarray) -> np.ndarray:
    return xy[:, 0] ** 2 + xy[:, 0] * xy[:, 1]


@pytest.mark.parametrize("etype", TYPES)
def test_quadratic_field_exact_only_for_quadratic_elements(tmp_path: Path, etype: str) -> None:
    results = make_results(tmp_path, etype, field=quadratic, distortion=0.0, cells=(3, 2))
    s, values = sample(results, 0, [(0.05, 0.1), (1.9, 0.9)], n=101)
    _, xy = polyline_points([(0.05, 0.1), (1.9, 0.9)], 101)
    err = np.max(np.abs(values - quadratic(xy)))
    if etype in ("T6", "Q8"):
        assert err < 1e-9
    else:
        assert err > 1e-3


# ------------------------------------------------------------------------- polyline_points


def test_polyline_points_equal_spacing_and_ends() -> None:
    line = [(0.0, 0.0), (3.0, 0.0), (3.0, 4.0)]
    s, xy = polyline_points(line, 15)
    assert s[0] == 0.0 and s[-1] == pytest.approx(7.0)
    np.testing.assert_allclose(np.diff(s), 0.5)
    np.testing.assert_allclose(xy[0], line[0])
    np.testing.assert_allclose(xy[-1], line[-1])
    np.testing.assert_allclose(xy[6], (3.0, 0.0))  # s = 3 is the corner
    np.testing.assert_allclose(np.linalg.norm(np.diff(xy, axis=0), axis=1)[:5], 0.5)
    np.testing.assert_allclose(xy[10], (3.0, 2.0))


def test_polyline_points_errors() -> None:
    with pytest.raises(ModelError):
        polyline_points([(0.0, 0.0)])
    with pytest.raises(ModelError):
        polyline_points([])
    with pytest.raises(ModelError):
        polyline_points([(1.0, 1.0), (1.0, 1.0)])
    with pytest.raises(ModelError):
        polyline_points([(0.0, 0.0), (1.0, 0.0)], n=1)
    with pytest.raises(ModelError):
        polyline_points("abc")


# --------------------------------------------------------------------- flux and gradient


@pytest.mark.parametrize("etype", TYPES)
def test_gradient_and_flux_along_a_path(tmp_path: Path, etype: str) -> None:
    results = make_results(tmp_path, etype)
    g = np.array([120.0, -75.0])
    line = [(0.2, 0.2), (1.8, 0.8)]
    _, gx = sample(results, 0, line, 30, "gradx")
    _, gy = sample(results, 0, line, 30, "grady")
    _, gm = sample(results, 0, line, 30, "gradmag")
    np.testing.assert_allclose(gx, g[0], atol=1e-7)
    np.testing.assert_allclose(gy, g[1], atol=1e-7)
    np.testing.assert_allclose(gm, np.linalg.norm(g), atol=1e-7)
    _, qx = sample(results, 0, line, 30, "qx")
    _, qy = sample(results, 0, line, 30, "qy")
    _, qm = sample(results, 0, line, 30, "qmag")
    np.testing.assert_allclose(qx, -K * g[0], atol=1e-6)
    np.testing.assert_allclose(qy, -K * g[1], atol=1e-6)
    np.testing.assert_allclose(qm, K * np.linalg.norm(g), atol=1e-6)
    _, out = sample(results, 0, [(1.0, 0.5), (3.0, 0.5)], 11, "qx")
    assert np.isnan(out[-1]) and np.isfinite(out[0])


def test_value_at_matches_sample_and_unknown_field(tmp_path: Path) -> None:
    results = make_results(tmp_path, "Q8")
    s, values = sample(results, 0, POLYLINE, 50)
    _, xy = polyline_points(POLYLINE, 50)
    for i in (0, 7, 25, 49):
        assert value_at(results, 0, xy[i]) == pytest.approx(values[i], abs=1e-12)
    assert value_at(results, 0, xy[3], "qx") == pytest.approx(-K * 120.0, abs=1e-6)
    with pytest.raises(ModelError):
        sample(results, 0, POLYLINE, 10, "bogus")
    with pytest.raises(ModelError):
        value_at(results, 0, (0.5, 0.5), "bogus")
    with pytest.raises(ModelError):
        sample(results, 5, POLYLINE, 10)


# ------------------------------------------------------------------------------ the plot


def test_path_plot(tmp_path: Path) -> None:
    results = make_results(tmp_path, "T6")
    line = [(0.5, 0.5), (3.0, 0.5)]  # leaves the mesh
    fig = plots.path(results, line, n=60)
    assert isinstance(fig, Figure)
    (ax,) = fig.axes
    (artist,) = ax.get_lines()
    s, kelvin = sample(results, 0, line, 60)
    np.testing.assert_allclose(artist.get_xdata(), s)
    np.testing.assert_allclose(artist.get_ydata(), kelvin)  # no model: displayed in K
    assert np.isnan(artist.get_ydata()[-1])
    assert "K" in ax.get_ylabel() and "Distance" in ax.get_xlabel()
    assert "steady state" in ax.get_title() and "t = " not in ax.get_title()  # M11.8
    png = tmp_path / "path.png"
    plots.path(results, POLYLINE, field="qmag", path=png)
    assert png.is_file() and png.stat().st_size > 0
    host = Figure()
    axes = host.add_subplot(1, 1, 1)
    out = plots.path(results, POLYLINE, field="gradx", ax=axes)
    assert out is host and len(axes.get_lines()) == 1
    assert "K/m" in axes.get_ylabel()
    with pytest.raises(ModelError):
        plots.path(results, POLYLINE, field="nope")
    with pytest.raises(ModelError):
        plots.path(results, POLYLINE, step=3)


def test_api_plot_path(tmp_path: Path) -> None:
    results = make_results(tmp_path, "Q4")
    png = tmp_path / "api.png"
    fig = api.plot_path(results, POLYLINE, field="T", path=png, n=40)
    assert isinstance(fig, Figure) and png.is_file()
    assert len(fig.axes[0].get_lines()[0].get_xdata()) == 40


# ------------------------------------------------------------------------------ performance


def test_locating_many_points_is_fast() -> None:
    problem = make_problem("Q8", size=SIZE, cells=(60, 60), distortion=0.2)
    rng = np.random.default_rng(1)
    pts = rng.uniform([0.0, 0.0], SIZE, size=(20000, 2))
    locate(problem.mesh, pts[:10])  # build the cached tree
    t0 = time.perf_counter()
    loc = locate(problem.mesh, pts)
    assert time.perf_counter() - t0 < 10.0
    assert np.all(loc.elem_ids >= 0)


# -------------------------------------------------------------------- fallback (M11.14)


def _large_beside_small():
    """One 10 x 1 quadrilateral with 20 small 0.5 x 0.5 cells on top of it (REVIEW.md 6)."""
    from thermalfea.core.mesh import ElementBlock, Mesh

    nodes = [(0.0, 0.0), (10.0, 0.0), (10.0, 1.0), (0.0, 1.0)]
    conn = [[0, 1, 2, 3]]
    for i in range(20):
        x0 = 0.5 * i
        base = len(nodes)
        nodes += [(x0, 1.0), (x0 + 0.5, 1.0), (x0 + 0.5, 1.5), (x0, 1.5)]
        conn.append([base, base + 1, base + 2, base + 3])
    block = ElementBlock(
        "Q4",
        np.array(conn, dtype=np.int64),
        np.ones(len(conn), dtype=np.int32),
        np.arange(len(conn), dtype=np.int64),
    )
    return Mesh(dim=2, nodes=np.array(nodes), blocks=[block])


def test_point_inside_large_element_beside_small_ones_is_found() -> None:
    mesh = _large_beside_small()
    pts = np.array([[5.0, 0.99], [9.9, 0.98], [0.1, 0.97]])
    loc = locate(mesh, pts)
    np.testing.assert_array_equal(loc.elem_ids, [0, 0, 0])
    got = interpolate(mesh, loc, linear(mesh.nodes))
    np.testing.assert_allclose(got, linear(pts), atol=1e-9)


def test_fallback_keeps_outside_points_at_minus_one() -> None:
    mesh = _large_beside_small()
    pts = np.array([[5.0, -0.01], [10.5, 0.5], [5.0, 2.0], [5.0, 0.99]])
    loc = locate(mesh, pts)
    np.testing.assert_array_equal(loc.elem_ids, [-1, -1, -1, 0])
    assert np.all(np.isnan(loc.local[:3]))
