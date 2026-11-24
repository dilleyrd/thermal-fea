"""M11.28: the Results menu shows the stored term results (contact heat, mean h)."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from test_charts import FakeView

from thermalfea import api
from thermalfea.gui.chart_tools import CONTACT_HEAT_ID, H_MEAN_ID, attach_charts
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.results_tools import attach_results
from thermalfea.model import bcs
from thermalfea.model.bcs import Contact, CorrelationConvection
from thermalfea.model.model import Model


def build_model(with_correlation: bool) -> Model:
    model = api.new_model(name="two-blocks")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 0.5, 0.5, id="a")
    geo.rectangle(0.5, 0.0, 0.5, 0.5, id="b")
    model.mesh_settings.global_size = 0.1
    built = api.build(model)
    api.select_surfaces(model, built, "A", where=lambda fp: fp.center[0] < 0.5)
    api.select_surfaces(model, built, "B", where=lambda fp: fp.center[0] > 0.5)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.select_curves(model, built, "joint", where=lambda c: abs(c.center[0] - 0.5) < 1e-9)
    api.assign_region(model, "A", material="Copper (pure)")
    api.assign_region(model, "B", material="Copper (pure)")
    model.bcs.append(bcs.FixedTemperature("hot", "west", T=400.0))
    if with_correlation:
        model.bcs.append(
            CorrelationConvection("film", "east", "vplate_natural", "Air", 300.0, char_length=0.5)
        )
        model.contacts.append(Contact("joint", "joint", conductance=2000.0))
    else:
        model.bcs.append(bcs.Convection("cool", "east", h=100.0, T_inf=300.0))
    return model


@pytest.fixture(scope="module")
def files(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    folder = tmp_path_factory.mktemp("terms")
    out = {}
    for key, flag in (("with", True), ("without", False)):
        model = build_model(flag)
        built = api.build(model)
        mesh = api.mesh(model, built)
        api.solve(model, mesh, built=built, path=folder / f"{key}.h5")
        out[key] = folder / f"{key}.h5"
        out[f"model_{key}"] = model  # type: ignore[assignment]
    return out


def make_shell(window, model: Model, path: Path, tmp_path: Path) -> SimpleNamespace:
    document = Document(model)
    view = FakeView()
    attach_tree(window, document, None)
    results_ctrl = attach_results(window, document, view)
    charts = attach_charts(window, document, view, results_ctrl)
    local = tmp_path / "work.h5"
    shutil.copy(path, local)
    document.set_results(local)
    return SimpleNamespace(window=window, ctrl=results_ctrl, charts=charts)


def test_actions_are_disabled_without_such_results(window, files, tmp_path) -> None:
    shell = make_shell(window, files["model_without"], files["without"], tmp_path)  # type: ignore[arg-type]
    assert shell.ctrl.results.term_result_names == []
    assert not window.actions[CONTACT_HEAT_ID].isEnabled()
    assert not window.actions[H_MEAN_ID].isEnabled()
    shell.charts.close_windows()


def test_actions_are_disabled_without_results(window) -> None:
    document = Document()
    view = FakeView()
    attach_tree(window, document, None)
    ctrl = attach_results(window, document, view)
    attach_charts(window, document, view, ctrl)
    assert not window.actions[CONTACT_HEAT_ID].isEnabled()
    assert not window.actions[H_MEAN_ID].isEnabled()


def test_contact_heat_and_mean_h_charts(window, files, tmp_path) -> None:
    shell = make_shell(window, files["model_with"], files["with"], tmp_path)  # type: ignore[arg-type]
    results = shell.ctrl.results
    try:
        assert window.actions[CONTACT_HEAT_ID].isEnabled()
        assert window.actions[H_MEAN_ID].isEnabled()
        window.actions[CONTACT_HEAT_ID].trigger()
        (chart,) = shell.charts.windows
        assert chart.kind == "contact_heat"
        (y,) = [np.asarray(line.get_ydata(), dtype=float) for line in chart.axes.get_lines()]
        np.testing.assert_allclose(y, results.term_result("contact_heat:joint"))
        window.actions[H_MEAN_ID].trigger()
        assert shell.charts.windows[-1].kind == "h_mean"
        assert len(shell.charts.windows) == 2
        assert shell.charts.plot_h_mean() is not None
    finally:
        shell.charts.close_windows()
