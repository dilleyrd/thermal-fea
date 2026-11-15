"""M5.3 — history plots: nearest nodes, the series of each plot, units, and drawing."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from handmade import make_problem
from matplotlib.figure import Figure

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.units import UnitSettings
from thermalfea.model.bcs import Convection
from thermalfea.model.model import Model
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.post.plots import (
    heat_flow_history,
    heat_flow_history_data,
    history,
    history_data,
    history_stat,
    history_stat_data,
    nearest_nodes,
)
from thermalfea.post.results import Results
from thermalfea.solver.run import run_transient

RHO, CP, SIDE = 7800.0, 500.0, 0.01
H, T_INF, T_INIT = 20.0, 300.0, 400.0
TAU = RHO * CP * SIDE * SIDE / (H * 4 * SIDE)
SIDES = ("bottom", "right", "top", "left")


def lumped(theta: float = 1.0, **settings):
    problem = make_problem("Q4", size=(SIDE, SIDE), cells=(2, 2), k=400.0, bcs=tuple(
        Convection(f"conv-{side}", side, h=H, T_inf=T_INF) for side in SIDES))
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    defaults = dict(kind="transient", theta=theta, initial_dt=TAU / 20, end_time=TAU,
                    auto_timestep=False)
    problem.settings = SolutionSettings(**{**defaults, **settings})
    return problem


@pytest.fixture
def results(tmp_path: Path) -> Results:
    path = tmp_path / "h.h5"
    run_transient(lumped(), path, T0=T_INIT)
    opened = Results(path)
    opened.mesh.node_sets["corner"] = np.array([0, 1])  # cached: the same dict every time
    return opened


def only(data) -> np.ndarray:
    (values,) = data.series.values()
    return values


# ----------------------------------------------------------------------------- nearest node


def test_nearest_node_of_points_on_and_near_the_nodes(results: Results) -> None:
    xy = results.mesh.nodes[:, :2]
    on = [0, 4, 8]
    np.testing.assert_array_equal(nearest_nodes(results.mesh, xy[on]), on)
    near = [3, 5]
    off = xy[near] + np.array([[1e-6, -1e-6], [-1e-6, 1e-6]])
    np.testing.assert_array_equal(nearest_nodes(results.mesh, off), near)


# ---------------------------------------------------------------------------- node histories


def test_history_data_of_nodes(results: Results) -> None:
    data = history_data(results, nodes=[0, 3])
    assert len(data.series) == 2
    for node, values in zip([0, 3], data.series.values(), strict=True):
        np.testing.assert_allclose(values, results.nodal_history(node))
    np.testing.assert_array_equal(data.times, results.times)
    labels = list(data.series)
    assert "node 0" in labels[0] and "node 3" in labels[1]
    assert data.ylabel == "Temperature [K]"


def test_points_give_the_same_series_as_their_nodes(results: Results) -> None:
    xy = results.mesh.nodes[:, :2]
    by_point = history_data(results, points=[tuple(xy[3] + 1e-7), tuple(xy[0])])
    by_node = history_data(results, nodes=[3, 0])
    assert list(by_point.series) == list(by_node.series)
    for a, b in zip(by_point.series.values(), by_node.series.values(), strict=True):
        np.testing.assert_array_equal(a, b)


def test_label_gives_the_node_coordinates(results: Results) -> None:
    node = 8
    x, y = results.mesh.nodes[node, :2]
    (label,) = history_data(results, nodes=[node]).series
    assert label == f"node {node} ({x:g}, {y:g})"


def test_neither_or_both_selectors_are_rejected(results: Results) -> None:
    with pytest.raises(ModelError):
        history_data(results)
    with pytest.raises(ModelError):
        history_data(results, points=[(0.0, 0.0)], nodes=[0])


@pytest.mark.parametrize("bad", [[99], [-1], []])
def test_bad_node_index_is_rejected(results: Results, bad: list[int]) -> None:
    with pytest.raises(ModelError):
        history_data(results, nodes=bad)


# ------------------------------------------------------------------------------ node sets


@pytest.mark.parametrize(
    ("stat", "func"), [("min", np.min), ("max", np.max), ("mean", np.mean)]
)
def test_statistics_over_a_node_set(results: Results, stat: str, func) -> None:
    stacked = np.stack([results.nodal_history(0), results.nodal_history(1)], axis=1)
    data = history_stat_data(results, "corner", stat)
    np.testing.assert_allclose(only(data), func(stacked, axis=1), rtol=1e-12)
    np.testing.assert_array_equal(data.times, results.times)
    assert list(data.series) == [f"{stat} of corner"]
    assert data.ylabel == "Temperature [K]"


def test_default_statistic_is_the_mean(results: Results) -> None:
    np.testing.assert_array_equal(
        only(history_stat_data(results, "corner")),
        only(history_stat_data(results, "corner", "mean")),
    )


def test_unknown_selection_and_statistic_are_rejected(results: Results) -> None:
    with pytest.raises(ModelError, match="corner"):
        history_stat_data(results, "nowhere")
    with pytest.raises(ModelError):
        history_stat_data(results, "corner", "median")


# ------------------------------------------------------------------------------ heat flows


def test_heat_flow_series_of_every_boundary_condition(results: Results) -> None:
    data = heat_flow_history_data(results)
    assert list(data.series) == results.heat_flow_names and len(data.series) == 4
    for name, values in data.series.items():
        np.testing.assert_array_equal(values, results.heat_flow(name))
    np.testing.assert_array_equal(data.times, results.times)
    assert data.ylabel == "Heat flow into the body [W]"


def test_heat_flow_subset_and_unknown_name(results: Results) -> None:
    data = heat_flow_history_data(results, ["conv-left"])
    assert list(data.series) == ["conv-left"]
    with pytest.raises(ModelError):
        heat_flow_history_data(results, ["conv-nowhere"])


# --------------------------------------------------------------------------------- drawing


def test_history_returns_a_figure_with_one_line_per_series(results: Results) -> None:
    fig = history(results, nodes=[0, 3, 8])
    assert isinstance(fig, Figure)
    ax = fig.axes[0]
    assert len(ax.lines) == 3
    assert ax.get_legend() is not None
    assert ax.get_xlabel() == "Time [s]" and ax.get_ylabel() == "Temperature [K]"
    assert ax.get_title()
    assert ax.lines[0].get_marker() == "o"  # few steps: markers


def test_statistic_and_heat_flow_plots_draw_their_series(results: Results) -> None:
    stat_ax = history_stat(results, "corner", "max").axes[0]
    assert len(stat_ax.lines) == 1 and stat_ax.get_legend() is not None
    flow_ax = heat_flow_history(results).axes[0]
    assert len(flow_ax.lines) == 4 and flow_ax.get_legend() is not None
    assert flow_ax.get_ylabel() == "Heat flow into the body [W]"


def test_plots_draw_into_a_given_axes(results: Results) -> None:
    host = Figure()
    ax = host.add_subplot(1, 1, 1)
    assert history(results, nodes=[0], ax=ax) is host
    assert len(ax.lines) == 1
    assert history_stat(results, "corner", ax=ax) is host
    assert len(ax.lines) == 2
    assert heat_flow_history(results, ax=ax) is host
    assert len(ax.lines) == 6


@pytest.mark.parametrize("name", ["history", "stat", "flow"])
def test_plots_save_a_png(results: Results, tmp_path: Path, name: str) -> None:
    out = tmp_path / f"{name}.png"
    if name == "history":
        history(results, nodes=[0], path=out)
    elif name == "stat":
        history_stat(results, "corner", path=out)
    else:
        heat_flow_history(results, path=out)
    data = out.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) > 1000


# ------------------------------------------------------------------------------------ units


def test_history_is_shown_in_the_display_unit(results: Results) -> None:
    kelvin = only(history_data(results, nodes=[0]))
    kelvin_stat = only(history_stat_data(results, "corner", "max"))
    results.model = Model(display_units=UnitSettings(temperature="degC"))
    data = history_data(results, nodes=[0])
    np.testing.assert_allclose(only(data), kelvin - 273.15, rtol=1e-12)
    assert data.ylabel == "Temperature [°C]"
    stat = history_stat_data(results, "corner", "max")
    np.testing.assert_allclose(only(stat), kelvin_stat - 273.15, rtol=1e-12)
    assert stat.ylabel == "Temperature [°C]"


# -------------------------------------------------------------------------------------- api


def test_plot_history_through_the_api(results: Results, tmp_path: Path) -> None:
    out = tmp_path / "api.png"
    xy = results.mesh.nodes[:, :2]
    fig = api.plot_history(results, points=[tuple(xy[0]), tuple(xy[8])], path=out)
    assert isinstance(fig, Figure) and out.stat().st_size > 0
    assert len(fig.axes[0].lines) == 2
