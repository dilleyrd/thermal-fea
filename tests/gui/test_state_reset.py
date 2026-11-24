"""M11.25: GUI state on New, Open and remesh (REVIEW-2.md 2.1-15, 16, 18, 19, solve dialog).

Every test reproduces one review defect offscreen. Waits are bounded and every worker
thread is joined before the test ends.
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal

from thermalfea import api
from thermalfea.core.meshgen import rect_mesh
from thermalfea.gui import worker as worker_module
from thermalfea.gui.chart_tools import attach_charts
from thermalfea.gui.dialogs.solve_progress import SolveProgressDialog
from thermalfea.gui.document import Document
from thermalfea.gui.geometry_tools import attach_geometry_tools
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.results import RESULT_ADDRESS
from thermalfea.gui.results_tools import attach_results
from thermalfea.gui.scene import NODE_DIM
from thermalfea.gui.viewport_mpl import MplSceneView
from thermalfea.gui.worker import BackgroundTask, SerialWorker
from thermalfea.model import bcs
from thermalfea.model.model import Model

WAIT = 30000  # ms


class FakeView(QObject):
    """A SceneView stand-in (selection and pick signals, no drawing)."""

    selection_changed = Signal(int, list)
    point_picked = Signal(float, float, float)

    def widget(self) -> Any:  # pragma: no cover - never shown
        raise NotImplementedError

    def set_field(self, spec: Any) -> None: ...
    def set_geometry(self, built: Any) -> None: ...
    def set_mesh(self, mesh: Any, color_by: Any = None) -> None: ...
    def set_symbols(self, symbols: Any) -> None: ...
    def set_entity_colors(self, dim, colors, legend) -> None: ...

    def set_overlay(self, layer: str, items: Any) -> None: ...
    def set_selection_mode(self, mode: Any) -> None: ...
    def highlight(self, dim: int, tags: Any) -> None: ...
    def fit(self) -> None: ...
    def save_image(self, path: str, dpi: int = 200) -> None: ...


def plate(name: str = "plate", width: float = 1.0) -> tuple[Model, Any]:
    model = api.new_model(name=name)
    api.Geometry(model).rectangle(0.0, 0.0, width, 0.5)
    model.mesh_settings.global_size = 0.1
    built = api.build(model)
    return model, built


@pytest.fixture(scope="module")
def solved(tmp_path_factory: pytest.TempPathFactory) -> tuple[Model, Path]:
    model, built = plate("plate-reset")
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs += [
        bcs.FixedTemperature("hot", "west", T=400.0),
        bcs.Convection("cool", "east", h=100.0, T_inf=300.0),
    ]
    mesh = api.mesh(model, built)
    path = tmp_path_factory.mktemp("reset") / "results.h5"
    api.solve(model, mesh, built=built, path=path)
    return model, path


@pytest.fixture
def shell(window, solved, tmp_path):
    model, path = solved
    document = Document(model)
    view = FakeView()
    tree, props = attach_tree(window, document, None)
    results = attach_results(window, document, view)
    charts = attach_charts(window, document, view, results)
    local = tmp_path / "work.h5"
    shutil.copy(path, local)
    document.set_results(local)
    out = SimpleNamespace(
        window=window, doc=document, view=view, tree=tree, props=props, ctrl=results,
        charts=charts, path=local,
    )
    yield out
    results.pause()
    charts.close_windows()


# --------------------------------------------------------------- 2.1-15 results on New/Open
@pytest.mark.parametrize("how", ["new", "set_model"])
def test_replacing_the_document_clears_results_objects_probes_and_panel(shell, how) -> None:
    ctrl, doc = shell.ctrl, shell.doc
    ctrl.add_vectors()
    assert len(ctrl.objects) == 2
    ctrl.probe_at(0.5, 0.25)
    assert ctrl.probes
    shell.props.show_object((RESULT_ADDRESS, ctrl.objects[1].name))
    assert shell.props.result_panel is not None
    if how == "new":
        doc.new()
    else:
        doc.set_model(plate("other")[0])
    assert ctrl.results is None
    assert ctrl.objects == [] and ctrl.shown is None and ctrl.probes == []
    assert shell.props.result_panel is None
    assert not shell.window.actions["results.probe"].isChecked()


def test_a_new_solve_of_the_same_model_keeps_the_result_objects(shell) -> None:
    ctrl = shell.ctrl
    ctrl.add_vectors()
    names = [o.name for o in ctrl.objects]
    shell.doc.set_results(shell.path)  # a re-solve of the same document
    assert [o.name for o in ctrl.objects] == names


# ------------------------------------------------------------------ 2.1-18 stale selections
def test_viewport_drops_node_and_element_tags_with_a_new_mesh(qtbot) -> None:
    view = MplSceneView()
    qtbot.addWidget(view.widget())
    model, built = plate()
    view.set_geometry(built)
    view.set_mesh(rect_mesh(0.0, 0.0, 1.0, 0.5, 4, 2, "T3"))
    view.highlight(NODE_DIM, [0, 1, 2])
    view.set_mesh(rect_mesh(0.0, 0.0, 1.0, 0.5, 1, 1, "T3"))
    assert view.selection[1] == []
    tag = sorted(built.curves)[0]
    view.highlight(1, [tag])
    view.set_geometry(None)
    assert view.selection[1] == []


def test_charts_forget_selected_nodes_with_a_new_mesh_or_model(shell) -> None:
    shell.view.selection_changed.emit(NODE_DIM, [3, 4])
    assert shell.charts.selected_nodes == [3, 4]
    shell.doc.mesh_changed.emit()
    assert shell.charts.selected_nodes == []
    shell.view.selection_changed.emit(NODE_DIM, [3, 4])
    shell.doc.new()
    assert shell.charts.selected_nodes == []


# ----------------------------------------------------------------------- 2.1-16 async builds
def _geometry_env(window, worker: SerialWorker):
    model, built = plate("gm")
    document = Document(model)
    document.set_built(built)
    attach_tree(window, document, None)
    geometry = attach_geometry_tools(window, document, None)
    geometry.worker = worker
    return document, geometry


def test_build_does_not_overwrite_selections_edited_during_it(window, qtbot) -> None:
    worker = SerialWorker(window, "test-state-worker1")
    try:
        document, geometry = _geometry_env(window, worker)
        assert geometry.rebuild()
        built = document.built
        document.edit(
            "select",
            lambda m: api.select_curves(
                m, built, "west", where=lambda c: abs(c.center[0]) < 1e-9
            ),
        )
        qtbot.waitUntil(lambda: not geometry._busy, timeout=WAIT)
        qtbot.waitUntil(lambda: not worker.busy, timeout=WAIT)
        assert "west" in document.model.selections
        assert document.built is not None
    finally:
        assert worker.shutdown(10000)


def test_build_of_a_replaced_model_is_not_attached(window, qtbot, monkeypatch) -> None:
    from thermalfea.gui import geometry_tools

    worker = SerialWorker(window, "test-state-worker2")
    try:
        document, geometry = _geometry_env(window, worker)
        produced: list[Any] = []
        real_build = api.build

        def build(model):
            produced.append(real_build(model))
            return produced[-1]

        monkeypatch.setattr(geometry_tools.api, "build", build)
        seen: list[Any] = []
        document.geometry_built.connect(lambda: seen.append(document.built))
        other = api.new_model(name="b")
        api.Geometry(other).rectangle(0.0, 0.0, 2.0, 0.5)
        assert geometry.rebuild()
        document.set_model(other)
        qtbot.waitUntil(
            lambda: not geometry._busy and not worker.busy and not document.geometry_stale,
            timeout=WAIT,
        )
        assert len(produced) == 2  # model A's build, then model B's
        assert produced[0] not in seen  # never attached, not even transiently
        assert document.built is produced[1]
    finally:
        assert worker.shutdown(10000)


def test_failed_build_keeps_the_rebuild_queued_behind_it(window, qtbot) -> None:
    worker = SerialWorker(window, "test-state-worker3")
    try:
        document, geometry = _geometry_env(window, worker)
        window.error_dialog = lambda *_a: None
        document.edit("break", lambda m: setattr(m.geometry[0], "width", -1.0))
        assert geometry._busy  # the failing build runs
        document.edit("fix", lambda m: setattr(m.geometry[0], "width", 2.0))  # ignored: busy
        qtbot.waitUntil(
            lambda: not geometry._busy and not worker.busy and not document.geometry_stale,
            timeout=WAIT,
        )
        assert document.built is not None and not document.geometry_stale
    finally:
        assert worker.shutdown(10000)


# -------------------------------------------------------------------- 2.1-19 shutdown
def _ended(thread: Any) -> bool:
    try:
        return not thread.isRunning()
    except RuntimeError:  # deleted after it finished
        return True


def test_background_task_shutdown_parks_a_thread_that_does_not_end(qtbot) -> None:
    release = threading.Event()
    task = BackgroundTask(lambda _c: release.wait(20), name="stubborn")
    task.start()
    thread = None
    try:
        qtbot.waitUntil(lambda: task.thread_alive, timeout=5000)
        thread = task._thread
        assert not task.shutdown(100)
        assert thread in worker_module._PARKED
        assert thread is not None and thread.isRunning()
    finally:
        release.set()
        if thread is not None:  # the GUI event loop must deliver the end of the task
            qtbot.waitUntil(lambda: _ended(thread), timeout=10000)


# ---------------------------------------------------------------------- solve dialog close
def test_closing_the_dialog_of_a_running_solve_requests_the_cancel(qtbot) -> None:
    dialog = SolveProgressDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    requests: list[int] = []
    dialog.cancel_requested.connect(lambda: requests.append(1))
    dialog.close()
    assert requests == [1] and dialog.isVisible()
    dialog.set_state("cancelling")
    dialog.close()
    assert dialog.isVisible() and requests == [1]
    dialog.set_state("cancelled", "done")
    dialog.close()
    assert not dialog.isVisible()


def test_escape_on_a_running_dialog_requests_the_cancel(qtbot) -> None:
    dialog = SolveProgressDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    requests: list[int] = []
    dialog.cancel_requested.connect(lambda: requests.append(1))
    dialog.reject()
    assert requests == [1] and dialog.isVisible()
    dialog.set_state("finished")
    dialog.reject()
    assert not dialog.isVisible()
