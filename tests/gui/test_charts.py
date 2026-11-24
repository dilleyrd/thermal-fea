"""M8.11: chart windows (history, path, heat flow, energy balance) and export actions.

A short transient plate with two boundary conditions is solved once per module. A fake
``SceneView`` emits ``selection_changed`` / ``point_picked`` and records ``save_image`` and
``set_selection_mode``. File choosers are injected, nothing is modal, nothing waits.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from thermalfea import api
from thermalfea.gui.chart_tools import (
    ENERGY_ID,
    EXPORT_CSV_ID,
    EXPORT_GIF_ID,
    EXPORT_IMAGE_ID,
    EXPORT_REPORT_ID,
    EXPORT_VTU_ID,
    HEAT_FLOWS_ID,
    HISTORY_ID,
    PATH_CANCEL_ID,
    PATH_FINISH_ID,
    PATH_ID,
    attach_charts,
)
from thermalfea.gui.charts import ENERGY_POWER_COLUMNS, ChartWindow
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.results_tools import PROBE_ID, attach_results
from thermalfea.gui.scene import NODE_DIM
from thermalfea.model import bcs
from thermalfea.model.model import Model
from thermalfea.model.settings import SolutionSettings
from thermalfea.post.plots import heat_flow_history_data, history_data, path_data
from thermalfea.post.results import Results


class FakeView(QObject):
    """A SceneView stand-in that records mode changes and image saves."""

    selection_changed = Signal(int, list)
    point_picked = Signal(float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.modes: list[str] = []
        self.images: list[tuple[str, int]] = []

    def widget(self) -> Any:  # pragma: no cover - never shown
        raise NotImplementedError

    def set_field(self, spec: Any) -> None: ...
    def set_geometry(self, built: Any) -> None: ...
    def set_mesh(self, mesh: Any, color_by: Any = None) -> None: ...
    def set_symbols(self, symbols: Any) -> None: ...
    def set_entity_colors(self, dim, colors, legend) -> None: ...

    def set_overlay(self, layer: str, items: Any) -> None: ...
    def highlight(self, dim: int, tags: Any) -> None: ...
    def fit(self) -> None: ...

    def set_selection_mode(self, mode: Any) -> None:
        self.modes.append(mode)

    def save_image(self, path: str, dpi: int = 200) -> None:
        self.images.append((path, dpi))
        Path(path).write_bytes(b"image")


@pytest.fixture(scope="module")
def case(tmp_path_factory: pytest.TempPathFactory) -> tuple[Model, Path]:
    model = api.new_model(name="plate-charts")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5)
    model.mesh_settings.global_size = 0.1
    built = api.build(model)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs += [
        bcs.FixedTemperature("hot", "west", T=400.0),
        bcs.Convection("cool", "east", h=100.0, T_inf=300.0),
    ]
    model.solution = SolutionSettings(
        kind="transient", end_time=60.0, auto_timestep=False, initial_dt=10.0,
        output="every_n", output_every=1,
    )  # fmt: skip
    mesh = api.mesh(model, built)
    path = tmp_path_factory.mktemp("charts") / "results.h5"
    api.solve(model, mesh, built=built, path=path)
    return model, path


@pytest.fixture
def shell(window, case, tmp_path):
    model, path = case
    document = Document(model)
    view = FakeView()
    attach_tree(window, document, None)
    results_ctrl = attach_results(window, document, view)
    charts = attach_charts(window, document, view, results_ctrl)
    local = tmp_path / "work.h5"
    shutil.copy(path, local)
    out = SimpleNamespace(
        window=window, doc=document, view=view, ctrl=results_ctrl, charts=charts,
        path=local, tmp=tmp_path, choices=[],
    )

    def chooser(_parent: Any, _caption: str, _filter: str) -> str | None:
        return out.choices.pop(0) if out.choices else None

    charts.choose_save = chooser
    charts.choose_folder = lambda _p, _c: out.choices.pop(0) if out.choices else None
    document.set_results(local)
    yield out
    charts.close_windows()


def lines(chart: ChartWindow) -> list[np.ndarray]:
    return [np.asarray(line.get_ydata(), dtype=float) for line in chart.axes.get_lines()]


# ------------------------------------------------------------------------ nodal history
def test_history_of_selected_nodes(shell) -> None:
    results: Results = shell.ctrl.results
    nodes = [0, 3, 7]
    shell.view.selection_changed.emit(NODE_DIM, nodes)
    chart = shell.charts.request_history()
    assert isinstance(chart, ChartWindow) and chart.isVisible()
    expected = history_data(results, nodes=nodes)
    got = lines(chart)
    assert len(got) == len(nodes) == len(expected.series)
    for y, ref in zip(got, expected.series.values(), strict=True):
        np.testing.assert_allclose(y, ref)
    for node, y in zip(nodes, got, strict=True):
        np.testing.assert_allclose(y, results.nodal_history(node))  # model is in K
    assert chart.nodes == nodes and shell.charts.windows == [chart]
    assert shell.window.actions[HISTORY_ID].isEnabled()


def test_history_without_selection_asks_for_nodes(shell) -> None:
    action = shell.window.actions[HISTORY_ID]
    action.trigger()
    assert shell.charts.windows == [] and shell.charts.history_pending
    assert shell.view.modes[-1] == "node" and shell.window.actions["select.node"].isChecked()
    assert "Pick the nodes" in shell.window.statusBar().currentMessage()
    shell.view.selection_changed.emit(NODE_DIM, [2, 4])
    assert shell.charts.windows == [] and "2 selected nodes" in action.text()
    action.trigger()
    (chart,) = shell.charts.windows
    assert chart.nodes == [2, 4] and len(lines(chart)) == 2
    assert not shell.charts.history_pending and action.text() == "Nodal &history..."
    assert shell.view.modes[-1] == "none"  # the earlier selection mode is restored


def test_selection_of_other_dimension_is_not_nodes(shell) -> None:
    shell.view.selection_changed.emit(NODE_DIM, [1])
    shell.view.selection_changed.emit(1, [3])
    assert shell.charts.selected_nodes == []


# --------------------------------------------------------------------------- path plot
POLYLINE = [(0.1, 0.25), (0.5, 0.25), (0.9, 0.25)]


def click_all(shell, points=POLYLINE) -> None:
    for x, y in points:
        shell.view.point_picked.emit(x, y, 0.0)


def test_path_plot_three_clicks_and_finish(shell) -> None:
    results = shell.ctrl.results
    shell.window.actions[PATH_ID].trigger()
    assert shell.charts.path_active and shell.view.modes[-1] == "none"
    assert shell.window.actions[PATH_FINISH_ID].isEnabled()
    click_all(shell)
    assert shell.charts.path_points == POLYLINE
    assert "3 vertex" in shell.window.statusBar().currentMessage()
    assert shell.ctrl.probes == []  # the probe did not react
    shell.window.actions[PATH_FINISH_ID].trigger()
    (chart,) = shell.charts.windows
    assert not shell.charts.path_active
    obj = shell.ctrl.get(shell.ctrl.shown)
    expected = path_data(results, obj.step, POLYLINE, field=obj.field)
    np.testing.assert_allclose(chart.data.s, expected.s)
    np.testing.assert_allclose(chart.data.values, expected.values)
    (line,) = chart.axes.get_lines()
    np.testing.assert_allclose(np.asarray(line.get_ydata(), float), expected.values)
    assert chart.kind == "path"


def test_path_needs_two_points_and_can_be_cancelled(shell) -> None:
    shell.window.actions[PATH_ID].trigger()
    shell.view.point_picked.emit(0.1, 0.1, 0.0)
    shell.window.actions[PATH_FINISH_ID].trigger()
    assert shell.charts.path_active and shell.charts.windows == []
    shell.window.actions[PATH_CANCEL_ID].trigger()
    assert not shell.charts.path_active and shell.charts.windows == []
    assert not shell.window.actions[PATH_FINISH_ID].isEnabled()
    shell.view.point_picked.emit(0.3, 0.1, 0.0)  # ignored: no pick running
    assert shell.charts.path_points == []


def test_path_pick_and_probe_are_exclusive(shell) -> None:
    probe = shell.window.actions[PROBE_ID]
    probe.setChecked(True)
    shell.window.actions[PATH_ID].trigger()
    assert not probe.isChecked()  # starting the path pick switched the probe off
    click_all(shell, POLYLINE[:2])
    assert shell.ctrl.probes == [] and len(shell.charts.path_points) == 2
    probe.setChecked(True)  # switching it on cancels the pick
    assert not shell.charts.path_active
    shell.view.point_picked.emit(0.5, 0.25, 0.0)
    assert len(shell.ctrl.probes) == 1 and shell.charts.path_points == []


# ----------------------------------------------------------- heat flow and energy balance
def test_heat_flow_window(shell) -> None:
    results = shell.ctrl.results
    assert shell.window.actions[HEAT_FLOWS_ID].isEnabled()
    shell.window.actions[HEAT_FLOWS_ID].trigger()
    (chart,) = shell.charts.windows
    expected = heat_flow_history_data(results)
    assert len(expected.series) == 2
    got = lines(chart)
    assert len(got) == 2
    for y, ref in zip(got, expected.series.values(), strict=True):
        np.testing.assert_allclose(y, ref)
    np.testing.assert_allclose(chart.data.times, results.times)


def test_energy_balance_window(shell) -> None:
    results = shell.ctrl.results
    shell.window.actions[ENERGY_ID].trigger()
    (chart,) = shell.charts.windows
    columns = results.energy_balance()
    got = lines(chart)
    assert len(got) == len(ENERGY_POWER_COLUMNS)
    for y, name in zip(got, ENERGY_POWER_COLUMNS, strict=True):
        np.testing.assert_allclose(y, columns[name])
    assert chart.kind == "energy"


# ----------------------------------------------------------------- chart file export
def test_chart_csv_and_image_via_chooser(shell) -> None:
    chart = shell.charts.plot_heat_flows()
    csv = shell.tmp / "flows.csv"
    shell.choices.append(str(csv))
    assert chart.export_csv() == csv
    rows = csv.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("Time [s],") and len(rows) == 1 + chart.data.times.size
    assert rows[0].count(",") == len(chart.data.series)
    png = shell.tmp / "flows.png"
    shell.choices.append(str(png))
    assert chart.save_image() == png and png.stat().st_size > 0


def test_cancelled_chooser_writes_nothing(shell) -> None:
    chart = shell.charts.plot_energy_balance()
    before = set(shell.tmp.iterdir())
    assert chart.export_csv() is None and chart.save_image() is None
    assert set(shell.tmp.iterdir()) == before


def test_chart_export_error_goes_to_error_hook(shell, dialogs) -> None:
    chart = shell.charts.plot_energy_balance()
    shell.choices.append(str(shell.tmp / "missing" / "dir" / "x.csv"))
    assert chart.export_csv() is None
    assert dialogs.calls and dialogs.calls[-1][0] == "Export CSV failed"


# ----------------------------------------------------------------------- export actions
def test_export_actions(shell) -> None:
    acts = shell.window.actions
    for key in (EXPORT_IMAGE_ID, EXPORT_CSV_ID, EXPORT_VTU_ID, EXPORT_GIF_ID):
        assert acts[key].isEnabled()
    image = shell.tmp / "view.png"
    shell.choices.append(str(image))
    acts[EXPORT_IMAGE_ID].trigger()
    assert shell.view.images == [(str(image), 200)] and image.stat().st_size > 0

    csv = shell.tmp / "nodal.csv"
    shell.choices.append(str(csv))
    acts[EXPORT_CSV_ID].trigger()
    assert csv.read_text(encoding="utf-8").startswith("step,time,node")

    folder = shell.tmp / "vtu"
    shell.choices.append(str(folder))
    acts[EXPORT_VTU_ID].trigger()
    files = sorted(folder.iterdir())
    assert any(f.suffix == ".pvd" for f in files) and any(f.suffix == ".vtu" for f in files)
    assert all(f.stat().st_size > 0 for f in files)

    gif = shell.tmp / "anim.gif"
    shell.choices.append(str(gif))
    acts[EXPORT_GIF_ID].trigger()
    assert gif.read_bytes()[:4] == b"GIF8"
    assert "Animation written" in shell.window.statusBar().currentMessage()


def test_report_export_action(shell, monkeypatch) -> None:
    action = shell.window.actions[EXPORT_REPORT_ID]
    assert action.isEnabled()
    target = shell.tmp / "report.html"
    monkeypatch.setattr(shell.charts, "_target", lambda caption, flt, suffix: target)
    action.trigger()
    text = target.read_text(encoding="utf-8")
    assert text.startswith("<!DOCTYPE html>") and 'id="plots"' in text
    assert "HTML report written" in shell.window.statusBar().currentMessage()


def test_export_cancel_writes_nothing(shell) -> None:
    before = set(shell.tmp.iterdir())
    for key in (EXPORT_IMAGE_ID, EXPORT_CSV_ID, EXPORT_VTU_ID, EXPORT_GIF_ID):
        shell.window.actions[key].trigger()  # chooser returns None
    assert set(shell.tmp.iterdir()) == before and shell.view.images == []


def test_export_errors_are_reported_not_raised(shell, dialogs) -> None:
    blocker = shell.tmp / "blocker"
    blocker.write_text("a file, not a folder")
    acts = shell.window.actions
    for key, target in (
        (EXPORT_IMAGE_ID, blocker / "a.png"),
        (EXPORT_CSV_ID, blocker / "a.csv"),
        (EXPORT_VTU_ID, blocker / "sub"),
        (EXPORT_GIF_ID, blocker / "a.gif"),
    ):
        n = len(dialogs.calls)
        shell.choices.append(str(target))
        acts[key].trigger()
        assert len(dialogs.calls) == n + 1, key


def test_actions_disabled_without_results(window) -> None:
    document = Document()
    view = FakeView()
    attach_tree(window, document, None)
    ctrl = attach_results(window, document, view)
    attach_charts(window, document, view, ctrl)
    for key in (
        HISTORY_ID, PATH_ID, HEAT_FLOWS_ID, ENERGY_ID, EXPORT_CSV_ID, EXPORT_VTU_ID,
        EXPORT_GIF_ID, EXPORT_IMAGE_ID, EXPORT_REPORT_ID, PATH_FINISH_ID, PATH_CANCEL_ID,
    ):
        assert not window.actions[key].isEnabled(), key


# --------------------------------------------------------------- results change / close
def test_results_changed_marks_charts_out_of_date(shell) -> None:
    chart = shell.charts.plot_energy_balance()
    shell.window.actions[PATH_ID].trigger()
    assert shell.charts.path_active and "out of date" not in chart.windowTitle()
    shell.doc.set_results(shell.path)
    assert chart.out_of_date and chart.windowTitle().endswith("(out of date)")
    assert not shell.charts.path_active
    assert shell.charts.windows == [chart] and lines(chart)  # data is kept


def test_charts_close_with_the_main_window(shell) -> None:
    first = shell.charts.plot_energy_balance()
    second = shell.charts.plot_heat_flows()
    assert first.isVisible() and second.isVisible()
    closed: list[object] = []
    first.closed.connect(closed.append)
    second.closed.connect(closed.append)
    shell.window.close()
    assert len(closed) == 2 and shell.charts.windows == []


def test_closing_one_chart_forgets_it(shell) -> None:
    first = shell.charts.plot_energy_balance()
    second = shell.charts.plot_heat_flows()
    first.close()
    assert shell.charts.windows == [second]
