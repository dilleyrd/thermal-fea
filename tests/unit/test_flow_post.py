"""M7.5 — flow post-processing: wall temperature, stream plot and summary table."""

from __future__ import annotations

import math

import numpy as np
import pytest

from thermalfea import api
from thermalfea.convection.correlations import RE_LAMINAR, RE_TURBULENT
from thermalfea.core.errors import ModelError
from thermalfea.model.bcs import HeatFlux, Stream
from thermalfea.post.flow import (
    StreamSummary,
    flow_regime,
    format_stream_summary,
    plot_stream,
    stream_summary,
    wall_temperature,
)

LENGTH, T_IN = 1.0, 300.0


def stream(**changes) -> Stream:
    base = dict(
        name="coolant", fluid="Water", mode="in_plane", walls=["bottom"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=T_IN, mass_flow=0.25,
        path=[(0.0, 0.0), (LENGTH, 0.0)],
    )
    return Stream(**{**base, **changes})


def cold_plate(**stream_changes):
    model = api.new_model(name="cold plate")
    api.Geometry(model).rectangle(0.0, 0.0, LENGTH, 0.05)
    model.mesh_settings.global_size = 0.05
    built = api.build(model)
    api.select_curves(model, built, "channel", where=lambda cv: abs(cv.center[1]) < 1e-9)
    api.select_curves(model, built, "hot", where=lambda cv: abs(cv.center[1] - 0.05) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs.append(HeatFlux("load", "hot", q=2000.0))
    model.streams.append(stream(walls=["channel"], **stream_changes))
    return model, built, api.mesh(model, built)


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    model, built, mesh = cold_plate(h_override=800.0, mass_flow=0.05)
    path = tmp_path_factory.mktemp("flow") / "cold_plate.h5"
    res = api.solve(model, mesh, built=built, path=path)
    return res


@pytest.fixture(scope="module")
def through_results(tmp_path_factory):
    model, built, mesh = cold_plate(mode="through_plane", path=None, mass_flow=0.05)
    path = tmp_path_factory.mktemp("flow_tp") / "cold_plate.h5"
    return api.solve(model, mesh, built=built, path=path)


# ------------------------------------------------------------------ wall temperature


def test_wall_temperature_follows_the_channel_wall(results) -> None:
    s, t_wall = wall_temperature(results, "coolant")
    assert np.all(np.diff(s) > 0)
    assert s[0] == pytest.approx(0.0) and s[-1] == pytest.approx(LENGTH)
    # the channel is the bottom edge y = 0: its nodes are the wall nodes
    nodes = np.flatnonzero(np.isclose(results.mesh.nodes[:, 1], 0.0))
    nodes = nodes[np.argsort(results.mesh.nodes[nodes, 0])]
    np.testing.assert_allclose(s, results.mesh.nodes[nodes, 0], atol=1e-12)
    np.testing.assert_allclose(t_wall, results.temperature()[nodes], rtol=1e-12)
    # heated from above: every wall node is hotter than the fluid at the same s
    s_fluid = results.stream("coolant")["s"]
    t_fluid = np.interp(s, s_fluid, results.fluid_temperature("coolant"))
    assert np.all(t_wall > t_fluid)


def test_wall_temperature_errors(results, through_results) -> None:
    with pytest.raises(ModelError, match="unknown stream"):
        wall_temperature(results, "other")
    with pytest.raises(ModelError, match="through-plane"):
        wall_temperature(through_results, "coolant")


def test_wall_temperature_without_any_facets_is_a_model_error(results, monkeypatch) -> None:
    monkeypatch.setattr(results.mesh, "facets", [])
    with pytest.raises(ModelError, match="contain no mesh facets"):
        wall_temperature(results, "coolant")


# ------------------------------------------------------------------------ plot


def test_plot_stream_has_fluid_and_wall_lines(results, tmp_path) -> None:
    fig = plot_stream(results, "coolant")
    assert len(fig.axes) == 1
    ax = fig.axes[0]
    labels = [line.get_label() for line in ax.lines]
    assert labels == ["fluid", "mean wall"]
    assert ax.get_xlabel() == "s [m]" and ax.get_ylabel() == "T [K]"
    assert ax.get_legend() is not None
    assert "coolant" in ax.get_title()
    fluid, wall = ax.lines
    np.testing.assert_allclose(fluid.get_xdata(), results.stream("coolant")["s"])
    np.testing.assert_allclose(fluid.get_ydata(), results.fluid_temperature("coolant"))
    s_wall, t_wall = wall_temperature(results, "coolant")
    np.testing.assert_allclose(wall.get_xdata(), s_wall)
    np.testing.assert_allclose(wall.get_ydata(), t_wall)

    target = tmp_path / "stream.png"
    fig.savefig(target)
    assert target.stat().st_size > 0


def test_plot_stream_rejects_through_plane(through_results) -> None:
    with pytest.raises(ModelError, match="through-plane"):
        plot_stream(through_results, "coolant")


# --------------------------------------------------------------------- summary


def test_stream_summary_matches_the_stored_numbers(results) -> None:
    (row,) = stream_summary(results)
    data = results.stream("coolant")
    assert isinstance(row, StreamSummary)
    assert row.name == "coolant" and row.mode == "in_plane"
    assert row.mass_flow == data["mass_flow"][-1] == pytest.approx(0.05)
    assert row.Re == data["Re"][-1]
    assert row.h_mean == data["h_mean"][-1] == pytest.approx(800.0)
    assert row.dp == data["dp"][-1]
    assert row.T_in == data["T_in"][-1] == pytest.approx(T_IN)
    assert row.T_out == data["T_out"][-1]
    assert row.heat == data["heat"][-1] == pytest.approx(2000.0 * LENGTH, rel=1e-9)
    assert row.regime == flow_regime(row.Re)


def test_stream_summary_of_through_plane(through_results) -> None:
    (row,) = stream_summary(through_results)
    assert row.mode == "through_plane" and row.name == "coolant"


def test_flow_regime_limits() -> None:
    assert flow_regime(500.0) == "laminar"
    assert flow_regime(RE_LAMINAR) == "laminar"
    assert flow_regime(3000.0) == "transitional"
    assert flow_regime(RE_TURBULENT) == "turbulent"
    assert flow_regime(1.0e5) == "turbulent"
    assert flow_regime(math.nan) == ""


def _row(**changes) -> StreamSummary:
    base = dict(
        name="coolant", mode="in_plane", mass_flow=0.05, Re=500.0, regime="laminar",
        h_mean=800.0, dp=120.0, T_in=300.0, T_out=305.0, heat=2000.0,
    )
    return StreamSummary(**{**base, **changes})


def test_format_stream_summary_table() -> None:
    text = format_stream_summary([_row(dp=math.nan)])
    lines = text.splitlines()
    assert len(lines) == 2
    header = lines[0]
    for unit in ("m_dot [kg/s]", "Re", "regime", "h [W/(m^2 K)]", "dp [Pa]",
                 "T_in [K]", "T_out [K]", "heat [W]"):
        assert unit in header
    assert lines[1].startswith("coolant")
    cells = lines[1].split()
    assert "-" in cells and "2000" in cells


def test_format_stream_summary_empty() -> None:
    assert format_stream_summary([]) == "no streams"
