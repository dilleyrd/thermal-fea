"""M11.77: path plot items (held item 15; conventions C1, C2, C3, C8, C10; Data §3a).

A path plot is a saved result item: a path defined by two points, along boundaries (the
mesh nodes on a boundary selection joined end to end) or by points; reversible; plotted for
one or several times against distance, x or y; drawn in the view with ends A and B. Its
boundary selection is a selection reference. Results > Path plot... adds one.
"""

# ruff: noqa: F811  (the fixture `case` is imported from test_charts)
from __future__ import annotations

import shutil
from types import SimpleNamespace

import numpy as np
import pytest
from tests.gui.test_charts import case  # noqa: F401
from tests.gui.test_history_items import LayerView

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.gui.chart_tools import attach_charts
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.path_tools import (
    PATH_ADDRESS,
    PathPanel,
    attach_paths,
    chain_polylines,
    path_layer,
    path_points,
)
from thermalfea.gui.results_tools import attach_results
from thermalfea.model.result_items import PathItem
from thermalfea.model.selections import delete_selection, rename_selection


@pytest.fixture
def shell(window, case, tmp_path):
    model, path = case
    document = Document(model)
    document.set_built(api.build(model))
    view = LayerView()
    tree, props = attach_tree(window, document, view)
    results = attach_results(window, document, view)
    charts = attach_charts(window, document, view, results)
    paths = attach_paths(window, document, view, results, charts)
    local = tmp_path / "work.h5"
    shutil.copy(path, local)
    document.set_results(local)
    yield SimpleNamespace(window=window, doc=document, view=view, tree=tree, results=results,
                          charts=charts, paths=paths)  # fmt: skip
    charts.close_windows()


def panel_of(shell, name: str) -> PathPanel:
    (panel,) = [p for p in shell.window.findChildren(PathPanel) if p.name == name]
    return panel


# -------------------------------------------------------------------- geometry
def test_curves_are_chained_end_to_end() -> None:
    a = np.array([[0.0, 0.0], [1.0, 0.0]])
    b = np.array([[2.0, 0.0], [1.0, 0.0]])  # reversed piece
    c = np.array([[0.0, 1.0], [0.0, 0.0]])  # joins at the start
    chain = chain_polylines([a, b, c])
    assert chain.tolist() == [[0.0, 1.0], [0.0, 0.0], [1.0, 0.0], [2.0, 0.0]]
    with pytest.raises(ModelError, match="do not join"):
        chain_polylines([a, np.array([[5.0, 5.0], [6.0, 5.0]])])


def test_two_points_snap_samples_and_reverse(shell) -> None:
    doc = shell.doc
    mesh = shell.paths.mesh()
    item = PathItem("p", kind="two_points", points=[(0.0, 0.25), (1.0, 0.25)], samples=11)
    xy, s = path_points(item, mesh, doc.built, doc.model)
    assert len(xy) == 11 and s[0] == 0.0 and s[-1] == pytest.approx(1.0)
    item.reverse = True
    xy_r, s_r = path_points(item, mesh, doc.built, doc.model)
    assert xy_r[0] == pytest.approx(xy[-1]) and s_r[0] == 0.0
    item.reverse, item.snap = False, True
    item.points = [(0.01, 0.01), (0.99, 0.49)]
    xy_s, _ = path_points(item, mesh, doc.built, doc.model)
    nodes = mesh.nodes[:, :2]
    for end in (xy_s[0], xy_s[-1]):
        assert np.min(np.linalg.norm(nodes - end, axis=1)) == pytest.approx(0.0, abs=1e-12)
    with pytest.raises(ModelError, match="two points"):
        path_points(PathItem("q", points=[(0.0, 0.0)]), mesh, doc.built, doc.model)


def test_along_boundaries_uses_the_mesh_nodes_in_order(shell) -> None:
    doc = shell.doc
    mesh = shell.paths.mesh()
    item = PathItem("w", kind="boundaries", selection="west")
    xy, s = path_points(item, mesh, doc.built, doc.model)
    nodes_y = sorted(float(mesh.nodes[n, 1]) for n in mesh.node_sets["west"])
    assert xy[:, 0] == pytest.approx(0.0)
    assert sorted(xy[:, 1]) == pytest.approx(nodes_y)  # exactly the mesh nodes on it
    steps = np.diff(xy[:, 1])  # in order along the curve, whichever way it runs
    assert np.all(steps > 0) or np.all(steps < 0)
    assert np.all(np.diff(s) > 0) and s[-1] == pytest.approx(0.5)
    item.reverse = True  # "Run from B to A" turns it round
    xy_r, _ = path_points(item, mesh, doc.built, doc.model)
    assert xy_r[0] == pytest.approx(xy[-1])


# ---------------------------------------------------------------------- items
def test_an_item_is_saved_drawn_and_plotted(shell) -> None:
    doc, paths, view = shell.doc, shell.paths, shell.view
    count = doc.undo_stack.count()
    name = paths.add()
    assert doc.undo_stack.count() == count + 1
    assert shell.tree.item_for((PATH_ADDRESS, name)) is not None
    paths.update(name, points=[(0.0, 0.25), (1.0, 0.25)], samples=21)
    layer = view.layers[path_layer(name)]
    assert [m.text for m in layer[1:]] == ["A", "B"]
    times = [float(t) for t in shell.results.times[1:3]]
    paths.update(name, times=times, axis="x")
    chart = paths.plot(name)
    assert chart is not None and len(chart.axes.get_lines()) == 2  # two times overlaid
    assert chart.axes.get_xlabel().startswith("x [")
    paths.update(name, times=None)  # the displayed step only: drawn again
    assert len(chart.axes.get_lines()) == 1
    paths.update(name, visible=False)
    assert view.layers[path_layer(name)] == []
    assert paths.tree_summary((PATH_ADDRESS, name)).endswith("· hidden")


def test_the_boundary_selection_is_a_reference(shell) -> None:
    doc, paths = shell.doc, shell.paths
    name = paths.add("boundaries")
    paths.update(name, selection="west")
    doc.edit("rename", lambda m: rename_selection(m, "west", "left edge"))
    assert paths.get(name).selection == "left edge"
    with pytest.raises(ModelError):
        doc.edit("delete", lambda m: delete_selection(m, "left edge"))


def test_the_panel_picks_point_a_and_shows_readable_choices(shell) -> None:
    paths, view = shell.paths, shell.view
    name = paths.add()
    panel = panel_of(shell, name)
    kinds = [panel.kind_combo.itemText(i) for i in range(panel.kind_combo.count())]
    assert kinds == ["Two points", "Along boundaries", "Points"]
    assert panel.times_edit.placeholderText() == "the displayed step"
    assert panel.start_pick("A") and view.modes[-1] == "none"
    view.point_picked.emit(0.2, 0.1, 0.0)
    assert panel.picking is None and paths.get(name).points[0] == pytest.approx((0.2, 0.1))
    assert panel.start_pick("B")
    view.point_picked.emit(0.8, 0.4, 0.0)
    assert paths.get(name).points == [pytest.approx((0.2, 0.1)), pytest.approx((0.8, 0.4))]
    assert panel.plot_button.isEnabled()


def test_the_results_menu_adds_a_path_item(shell) -> None:
    window, paths = shell.window, shell.paths
    assert shell.charts.request_path() is None
    assert len(paths.items()) == 1
    menu = window.menus["results"].actions()
    assert window.actions["results.path_finish"] not in menu
    assert window.actions["results.path_cancel"] not in menu
