"""M11.48: the picked path is drawn in the viewport overlay layer ``"path"``."""

from __future__ import annotations

import shutil
from types import SimpleNamespace
from typing import Any

import pytest
from test_charts import FakeView, case  # noqa: F401  (case is a fixture)

from thermalfea.gui.chart_tools import (
    PATH_CANCEL_ID,
    PATH_FINISH_ID,
    PATH_ID,
    PATH_OVERLAY_LAYER,
    attach_charts,
)
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.results_tools import PROBE_ID, attach_results
from thermalfea.gui.scene import OverlayMarker, OverlayPolyline

POLYLINE = [(0.1, 0.25), (0.5, 0.25), (0.9, 0.25)]


class RecordingView(FakeView):
    """FakeView that keeps the current items of every overlay layer."""

    def __init__(self) -> None:
        super().__init__()
        self.layers: dict[str, list[Any]] = {}

    def set_overlay(self, layer: str, items: Any) -> None:
        self.layers[layer] = list(items)


@pytest.fixture
def shell(window, case, tmp_path):  # noqa: F811
    model, path = case
    document = Document(model)
    view = RecordingView()
    attach_tree(window, document, None)
    results_ctrl = attach_results(window, document, view)
    charts = attach_charts(window, document, view, results_ctrl)
    local = tmp_path / "work.h5"
    shutil.copy(path, local)
    document.set_results(local)
    yield SimpleNamespace(window=window, view=view, charts=charts)
    charts.close_windows()


def drawn(shell) -> list[Any]:
    return shell.view.layers.get(PATH_OVERLAY_LAYER, [])


def click(shell, points) -> None:
    for x, y in points:
        shell.view.point_picked.emit(x, y, 0.0)


def markers(items) -> list[OverlayMarker]:
    return [i for i in items if isinstance(i, OverlayMarker)]


def polylines(items) -> list[OverlayPolyline]:
    return [i for i in items if isinstance(i, OverlayPolyline)]


def test_markers_and_polyline_after_each_click(shell) -> None:
    shell.window.actions[PATH_ID].trigger()
    assert drawn(shell) == []
    click(shell, POLYLINE[:1])
    (m,) = markers(drawn(shell))
    assert (m.x, m.y, m.text) == (0.1, 0.25, "1")
    assert polylines(drawn(shell)) == []
    click(shell, POLYLINE[1:2])
    assert [m.text for m in markers(drawn(shell))] == ["1", "2"]
    assert len(polylines(drawn(shell))) == 1
    click(shell, POLYLINE[2:])
    assert [m.text for m in markers(drawn(shell))] == ["1", "2", "3"]
    assert [(m.x, m.y) for m in markers(drawn(shell))] == POLYLINE
    (line,) = polylines(drawn(shell))
    assert list(line.points) == POLYLINE


def test_cancel_clears_the_drawing(shell) -> None:
    shell.window.actions[PATH_ID].trigger()
    click(shell, POLYLINE)
    assert drawn(shell)
    shell.window.actions[PATH_CANCEL_ID].trigger()
    assert drawn(shell) == []


def test_probe_during_a_pick_clears_the_drawing(shell) -> None:
    shell.window.actions[PATH_ID].trigger()
    click(shell, POLYLINE)
    assert drawn(shell)
    shell.window.actions[PROBE_ID].setChecked(True)
    assert not shell.charts.path_active
    assert drawn(shell) == []


def test_drawing_stays_while_the_chart_is_open(shell) -> None:
    shell.window.actions[PATH_ID].trigger()
    click(shell, POLYLINE)
    shell.window.actions[PATH_FINISH_ID].trigger()
    (chart,) = shell.charts.windows
    assert len(markers(drawn(shell))) == 3 and len(polylines(drawn(shell))) == 1
    chart.close()
    assert drawn(shell) == []


def test_failed_finish_keeps_picking_and_drawing(shell) -> None:
    shell.window.actions[PATH_ID].trigger()
    click(shell, POLYLINE[:1])
    shell.window.actions[PATH_FINISH_ID].trigger()  # needs two vertices
    assert shell.charts.path_active
    assert len(markers(drawn(shell))) == 1


def test_a_new_pick_replaces_the_kept_drawing(shell) -> None:
    shell.window.actions[PATH_ID].trigger()
    click(shell, POLYLINE)
    shell.window.actions[PATH_FINISH_ID].trigger()
    assert drawn(shell)
    shell.window.actions[PATH_ID].trigger()  # new pick: the old drawing goes at once
    assert drawn(shell) == []
    click(shell, [(0.2, 0.1), (0.3, 0.4)])
    assert [(m.x, m.y) for m in markers(drawn(shell))] == [(0.2, 0.1), (0.3, 0.4)]
    # closing the first chart no longer touches the new drawing
    shell.charts.windows[0].close()
    assert len(markers(drawn(shell))) == 2
