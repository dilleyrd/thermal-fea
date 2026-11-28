"""M11.76: nodal history items (held item 14; conventions C2, C3, C10; Data §3a).

A nodal history is a saved result item with a panel: the node list, a pick of the one
pick workflow in Node mode, the quantity, Plot and the eye toggle. It stores positions,
marks the nodes with their numbers in the view, and its chart is drawn from the item.
"""

# ruff: noqa: F811  (the fixture `case` is imported from test_charts)
from __future__ import annotations

import shutil
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from tests.gui.test_charts import FakeView, case  # noqa: F401

from thermalfea.gui.chart_tools import attach_charts
from thermalfea.gui.document import Document
from thermalfea.gui.history_tools import (
    HISTORY_ADDRESS,
    HistoryPanel,
    attach_history,
    history_layer,
)
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.results_tools import attach_results
from thermalfea.gui.scene import NODE_DIM, OverlayMarker
from thermalfea.model.result_items import HistoryItem
from thermalfea.model.serialize import from_json, to_json


class LayerView(FakeView):
    """Records the overlay layers and highlights."""

    def __init__(self) -> None:
        super().__init__()
        self.layers: dict[str, list[Any]] = {}
        self.highlights: list[tuple[int, list[int]]] = []

    def set_overlay(self, layer: str, items: Any) -> None:
        self.layers[layer] = list(items)

    def highlight(self, dim: int, tags: Any) -> None:
        self.highlights.append((dim, list(tags)))


@pytest.fixture
def shell(window, case, tmp_path):
    model, path = case
    document = Document(model)
    view = LayerView()
    tree, props = attach_tree(window, document, view)
    results = attach_results(window, document, view)
    charts = attach_charts(window, document, view, results)
    history = attach_history(window, document, view, results, charts)
    local = tmp_path / "work.h5"
    shutil.copy(path, local)
    document.set_results(local)
    yield SimpleNamespace(
        window=window, doc=document, view=view, tree=tree, props=props, results=results,
        charts=charts, history=history,
    )
    charts.close_windows()


def panel_of(shell, name: str) -> HistoryPanel:
    (panel,) = [p for p in shell.window.findChildren(HistoryPanel) if p.name == name]
    return panel


def test_an_item_is_saved_and_listed_in_the_tree(shell) -> None:
    doc, history = shell.doc, shell.history
    count = doc.undo_stack.count()
    name = history.add()
    (item,) = history.items()
    assert isinstance(item, HistoryItem) and item.name == name and item.points == []
    assert doc.undo_stack.count() == count + 1 and doc.modified
    assert shell.tree.item_for((HISTORY_ADDRESS, name)) is not None
    assert from_json(to_json(doc.model)).result_items == doc.model.result_items
    assert history.tree_summary((HISTORY_ADDRESS, name)) == "history · 0 nodes"


def test_picking_nodes_in_the_panel_stores_positions(shell) -> None:
    history, view = shell.history, shell.view
    name = history.add()
    panel = panel_of(shell, name)  # the tree selected it and the panel opened
    assert panel.start_pick() and panel.picking
    assert view.modes[-1] == "node"
    mesh = history.mesh()
    view.selection_changed.emit(NODE_DIM, [3, 7])
    assert panel.strip.count_label.text() == "2 nodes picked"
    QTest.keyClick(panel.strip, Qt.Key.Key_Return)  # Enter confirms (C2)
    item = history.get(name)
    assert item.points == [tuple(map(float, mesh.nodes[n, :2])) for n in (3, 7)]
    assert history.nodes_of(item) == [3, 7]
    # editing again starts from the stored nodes
    assert panel.start_pick()
    assert view.highlights[-1] == (NODE_DIM, [3, 7])
    QTest.keyClick(panel, Qt.Key.Key_Escape)
    assert not panel.picking and history.nodes_of(history.get(name)) == [3, 7]


def test_nodes_are_marked_with_their_numbers_and_the_eye_hides_them(shell) -> None:
    history, view = shell.history, shell.view
    mesh = history.mesh()
    name = history.add([tuple(mesh.nodes[5, :2])])
    markers = view.layers[history_layer(name)]
    assert [m.text for m in markers] == ["node 5"] and isinstance(markers[0], OverlayMarker)
    assert history.set_visible(name, False)
    assert view.layers[history_layer(name)] == []
    assert history.tree_summary((HISTORY_ADDRESS, name)).endswith("· hidden")


def test_the_chart_is_drawn_from_the_item(shell) -> None:
    history = shell.history
    mesh = history.mesh()
    name = history.add([tuple(mesh.nodes[2, :2])])
    chart = history.plot(name)
    assert chart is not None
    assert [line.get_label() for line in chart.axes.get_lines()][0].startswith("node 2 ")
    history.set_points(name, [tuple(mesh.nodes[n, :2]) for n in (2, 4)])
    labels = [line.get_label() for line in chart.axes.get_lines()]
    assert labels[0].startswith("node 2 ") and labels[1].startswith("node 4 ")
    shell.doc.set_results(shell.doc.results_path)  # a new solve: drawn again
    assert not chart.out_of_date


def test_the_results_menu_adds_an_item_and_starts_picking(shell) -> None:
    charts, history = shell.charts, shell.history
    assert charts.request_history() is None
    (item,) = history.items()
    assert panel_of(shell, item.name).picking
    panel_of(shell, item.name).cancel_pick()
    charts.selected_nodes = [1, 6]  # nodes already selected: added and plotted at once
    chart = charts.request_history()
    assert chart is not None and len(history.items()) == 2
    assert history.nodes_of(history.items()[-1]) == [1, 6]
