"""M8.14: the V-10 model built, meshed, solved, edited, saved and reopened through the GUI.

The application is created by :func:`thermalfea.gui.app.build_application` with the real
wiring (real viewport, real gmsh thread, real solve thread), offscreen. Every step goes
through the entry point a user action reaches: menu actions (``QAction.trigger``), the
non-modal geometry dialogs (their OK button), the tree's own actions (``actions_for``), the
property panels' editors, synthetic Matplotlib mouse events on the viewport, and the
buttons of the panels. The model is never edited directly; ``thermalfea.api`` and
``thermalfea.post`` are used only to *check* results.

No modal dialog runs: the file choosers, the unsaved-changes question and the error dialog
are replaced, the progress dialog is not shown, and every wait is bounded. Files are written
under ``tmp_path`` only (including the temporary folder of a solve that has no model file).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent

from conftest import DialogRecorder, make_settings
from thermalfea import api
from thermalfea.core.functions import Constant
from thermalfea.gui.app import AppContext, build_application
from thermalfea.gui.document import _comparable
from thermalfea.gui.property_panels.form import NumberEdit
from thermalfea.model.bcs import Adiabatic, Convection, FixedTemperature
from thermalfea.model.model import Model
from thermalfea.model.serialize import from_json, to_json
from thermalfea.model.validate import errors
from thermalfea.post.results import Results

WAIT = 30000  # ms; every wait in this file is bounded

# The V-10 model (docs/verification.md, examples/v10_nafems_t4.py); temperatures are entered
# in kelvin because the GUI has no temperature-unit setting yet (display units: K).
W, HGT, YP = 0.6, 1.0, 0.2
K_T4, H_T4 = 52.0, 750.0
BASE_K, AMBIENT_K = 373.15, 273.15  # 100 degC and 0 degC
MESH_SIZE = 0.025
TARGET_C, TOL_C = 18.3, 0.15
BALANCE_LINEAR_STEADY = 1e-8  # V-34, as tests/verification/cases.py: check_balance


# ----------------------------------------------------------------------------- fixtures


@pytest.fixture
def app(qtbot, tmp_path: Path, monkeypatch) -> AppContext:
    """The whole application, offscreen; its threads are stopped (bounded) afterwards."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))  # a solve without a file
    ctx = build_application(make_settings(tmp_path / "s.ini"), install_hook=False)
    ctx.errors = DialogRecorder()  # type: ignore[attr-defined]
    ctx.window.error_dialog = ctx.errors  # type: ignore[attr-defined]
    ctx.solve.show_progress = False

    def unexpected(*_args: Any) -> Any:
        raise AssertionError("a modal question or chooser would have been shown")

    ctx.files.ask_unsaved = lambda _parent, _name: "discard"  # on window close only
    ctx.files.choose_open = unexpected
    ctx.files.choose_save = unexpected
    ctx.charts.choose_save = unexpected
    qtbot.addWidget(ctx.window)
    ctx.view.widget().resize(640, 480)
    yield ctx
    assert ctx.shutdown(5000)


# ------------------------------------------------------------------------------ helpers


def trigger(ctx: AppContext, action_id: str) -> None:
    """Trigger a menu action; it must be enabled, as a click on the menu entry needs."""
    action = ctx.window.actions[action_id]
    assert action.isEnabled(), f"{action_id} is disabled"
    action.trigger()


def tree_action(ctx: AppContext, section: str, data: tuple) -> None:
    """Trigger the context-menu action of a tree section whose ``data()`` is ``data``."""
    actions = ctx.tree.actions_for(ctx.tree.section_item(section))
    action = next(a for a in actions if a.data() == data)
    action.trigger()


def enter(editor: Any, text: str) -> None:
    """Type into a line edit and finish the edit (Enter)."""
    editor.setText(text)
    editor.editingFinished.emit()


def open_panel(ctx: AppContext, address: tuple) -> Any:
    """Select an object in the tree and return the property panel that shows it."""
    assert ctx.tree.select_address(address), address
    panel = ctx.properties.panel
    assert panel is not None and ctx.properties.current_address == address
    return panel


def set_function(ctx: AppContext, address: tuple, name: str, text: str) -> None:
    """Edit a function field (constant mode) through its panel; one undo step."""
    panel = open_panel(ctx, address)
    editor = panel.editors[name]
    assert editor.mode == "constant"
    steps = ctx.document.undo_stack.count()
    enter(editor.value_edit, text)
    assert panel.error_text() == "" and editor.error_text() == ""
    assert ctx.document.undo_stack.count() == steps + 1, (address, name, text)


def set_number(ctx: AppContext, address: tuple, name: str, text: str) -> None:
    """Edit a number field through its panel; one undo step."""
    panel = open_panel(ctx, address)
    editor = panel.editors[name]
    assert isinstance(editor, NumberEdit)
    steps = ctx.document.undo_stack.count()
    enter(editor, text)
    assert panel.error_text() == "" and editor.error_text() == ""
    assert ctx.document.undo_stack.count() == steps + 1, (address, name, text)


def mouse(view: Any, name: str, x: float, y: float, ctrl: bool = False) -> None:
    """A synthetic Matplotlib mouse event at the data position ``(x, y)`` [m]."""
    px, py = view.axes.transData.transform((x, y)) + 1e-6  # events truncate to pixels
    button = None if name == "motion_notify_event" else 1
    MouseEvent(
        name, view.canvas, px, py, button=button, modifiers=["ctrl"] if ctrl else None
    )._process()


def click(view: Any, x: float, y: float, ctrl: bool = False) -> None:
    """Press and release the left button at ``(x, y)`` [m]."""
    mouse(view, "button_press_event", x, y, ctrl)
    mouse(view, "button_release_event", x, y, ctrl)


def pick_in_viewport(
    ctx: AppContext, qtbot: Any, panel: Any, points: list[tuple[float, float]], mode: str,
    name: str | None = None,
) -> tuple[int, list[int]]:
    """"+ New", choose the toolbar mode, click the points, type the name, "Create and use".

    Every click after the first one holds Ctrl (adds to the selection). The toolbar mode
    ("Curve", "Surface") is chosen explicitly because "+ New" starts in the first
    dimension its field allows (a fixed temperature starts in point mode). The name box
    starts empty, so the name is typed (default: one that is unused).

    Returns ``(dim, tags)`` as the selection editor collected them.
    """
    editor = panel.editors["selection"]
    ctx.view.canvas.draw()  # the equal-aspect limits are final before the data are mapped
    editor.new_button.click()
    assert editor.picking == "new" and editor.name_edit.text() == ""
    trigger(ctx, f"select.{mode}")
    for index, (x, y) in enumerate(points):
        with qtbot.waitSignal(ctx.view.selection_changed, timeout=WAIT):
            click(ctx.view, x, y, ctrl=index > 0)
    dim, tags = editor.picked()
    assert not editor.strip.confirm_button.isEnabled()  # a name is still needed
    editor.name_edit.setText(name or f"picked {len(ctx.document.model.selections)}")
    assert editor.strip.confirm_button.isEnabled(), (dim, tags)
    editor.strip.confirm_button.click()
    assert editor.picking is None
    return dim, tags


def curve_boxes(ctx: AppContext, tags: list[int]) -> set[tuple[float, ...]]:
    """Bounding boxes of curves of the current build (to identify picked curves)."""
    assert ctx.document.built is not None
    return {tuple(round(v, 6) for v in ctx.document.built.curves[t].bbox) for t in tags}


def wait_rebuilt(ctx: AppContext, qtbot: Any, action: Any) -> None:
    """Run ``action`` and wait (bounded) for the geometry build it starts."""
    with qtbot.waitSignal(ctx.geometry.rebuilt, timeout=WAIT) as blocker:
        action()
    assert blocker.args == [True], ctx.geometry.last_error
    assert not ctx.document.geometry_stale and ctx.document.built is not None


def generate_mesh(ctx: AppContext, qtbot: Any) -> None:
    """Press "Generate mesh" in the mesh panel and wait (bounded) for the mesh."""
    panel = open_panel(ctx, ("mesh_settings",))
    assert panel.generate_button.isEnabled()
    with qtbot.waitSignal(ctx.mesh.meshed, timeout=WAIT) as blocker:
        panel.generate_button.click()
    assert blocker.args == [True], ctx.errors.calls  # type: ignore[attr-defined]
    assert ctx.document.mesh is not None and not ctx.document.mesh_stale


def solve(ctx: AppContext, qtbot: Any) -> None:
    """Solve > Validate (no errors), then Solve > Solve on the solve thread (bounded)."""
    trigger(ctx, "solve.validate")
    assert not errors(ctx.solve.last_issues), ctx.solve.last_issues
    with qtbot.waitSignal(ctx.solve.solve_finished, timeout=WAIT) as blocker:
        trigger(ctx, "solve.run")
    assert blocker.args == ["finished"], (ctx.solve.message, ctx.errors.calls)  # type: ignore[attr-defined]
    assert ctx.document.results_path is not None
    assert not ctx.document.results_stale and not ctx.solve.running


def temperature_at_target_c(ctx: AppContext) -> tuple[float, float]:
    """T [degC] at (0.6, 0.2) and the relative energy imbalance, from the results file."""
    path = ctx.document.results_path
    assert path is not None
    results = Results(path)
    nodes = results.mesh.nodes[:, :2]
    distance = np.linalg.norm(nodes - [W, YP], axis=1)
    node = int(np.argmin(distance))
    assert distance[node] < 1e-9, "the mesh has no node at the target point"
    value = float(results.temperature()[node]) - 273.15
    imbalance = float(abs(results.energy_balance()["relative_imbalance"][-1]))
    return value, imbalance


def check_physics(ctx: AppContext) -> None:
    """V-10 within its tolerance and the V-34 limit for a linear steady case."""
    value, imbalance = temperature_at_target_c(ctx)
    assert abs(value - TARGET_C) < TOL_C, value
    assert imbalance < BALANCE_LINEAR_STEADY, imbalance


def undo_all(ctx: AppContext, count: int) -> None:
    for _ in range(count):
        trigger(ctx, "edit.undo")


def redo_all(ctx: AppContext, count: int) -> None:
    for _ in range(count):
        trigger(ctx, "edit.redo")


def snapshot(model: Model) -> Model:
    return from_json(to_json(model))


# ------------------------------------------------------------------------------ scenario


def test_v10_end_to_end(app: AppContext, qtbot, tmp_path: Path) -> None:
    ctx, doc = app, app.document

    # (a) the application starts empty
    assert doc.model == Model() and doc.built is None and not doc.modified
    assert ctx.gmsh_worker is not None and ctx.gmsh_worker.is_running
    assert ctx.geometry.worker is ctx.gmsh_worker and ctx.mesh.worker is ctx.gmsh_worker
    assert ctx.window.windowTitle().endswith("ThermalFEA")

    # (b) geometry: two rectangles through the Geometry menu, rebuilt on the gmsh thread
    for y, height in ((0.0, YP), (YP, HGT - YP)):
        trigger(ctx, "geometry.rectangle")
        dialog = ctx.geometry.active_dialog
        assert dialog is not None
        for name, value in (("x", 0.0), ("y", y), ("width", W), ("height", height)):
            dialog.editors[name].setText(str(value))
        ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
        wait_rebuilt(ctx, qtbot, ok.click)
        assert dialog.error_label.text() == ""
    assert [type(op).__name__ for op in doc.model.geometry] == ["Rectangle", "Rectangle"]
    assert len(doc.built.surfaces) == 2 and len(doc.built.curves) == 7
    assert ctx.view.layer_artists("geometry")
    # the view is fitted only when the first shape appears: View > Fit view shows both
    trigger(ctx, "view.fit")
    ctx.view.canvas.draw()
    ymin, ymax = ctx.view.axes.get_ylim()
    assert ymin < 0.0 and ymax > HGT

    # (c, e) loads: add through the tree, pick the curves in the viewport, store them
    tree_action(ctx, "loads", ("add_bc", "fixed_temperature"))
    panel = ctx.properties.panel
    boxes = {
        "bottom": [(0.3, 0.0)],
        "cooled": [(W, 0.1), (W, 0.6), (0.3, HGT)],  # right (two curves) and top
        "left": [(0.0, 0.1), (0.0, 0.6)],
    }
    dim, tags = pick_in_viewport(ctx, qtbot, panel, boxes["bottom"], "curve")
    assert dim == 1 and len(tags) == 1
    assert doc.model.bcs[0].selection != ""
    assert curve_boxes(ctx, doc.model.selections[doc.model.bcs[0].selection].tags) == {
        (0.0, 0.0, 0.0, W, 0.0, 0.0)
    }
    set_function(ctx, ("bcs", 0), "T", str(BASE_K))

    tree_action(ctx, "loads", ("add_bc", "convection"))
    panel = ctx.properties.panel
    dim, tags = pick_in_viewport(ctx, qtbot, panel, boxes["cooled"], "curve")
    assert dim == 1 and len(tags) == 3
    cooled = doc.model.selections[doc.model.bcs[1].selection]
    assert curve_boxes(ctx, cooled.tags) == {
        (W, 0.0, 0.0, W, YP, 0.0),
        (W, YP, 0.0, W, HGT, 0.0),
        (0.0, HGT, 0.0, W, HGT, 0.0),
    }
    set_function(ctx, ("bcs", 1), "h", str(H_T4))
    set_function(ctx, ("bcs", 1), "T_inf", str(AMBIENT_K))

    tree_action(ctx, "loads", ("add_bc", "adiabatic"))
    panel = ctx.properties.panel
    dim, tags = pick_in_viewport(ctx, qtbot, panel, boxes["left"], "curve")
    assert dim == 1 and len(tags) == 2
    assert [type(bc) for bc in doc.model.bcs] == [FixedTemperature, Convection, Adiabatic]
    assert doc.model.bcs[0].T == Constant(BASE_K)
    assert doc.model.bcs[1].h == Constant(H_T4)
    assert doc.model.bcs[1].T_inf == Constant(AMBIENT_K)
    assert ctx.view.layer_artists("symbols")  # the load symbols follow the loads

    # (d) material k = 52 (tree action, then its panel) and the region of both surfaces
    tree_action(ctx, "materials", ("add_material", None))
    material = next(iter(doc.model.materials))
    set_function(ctx, ("materials", material), "k", str(K_T4))
    assert doc.model.materials[material].k == Constant(K_T4)
    tree_action(ctx, "regions", ("add_region", None))
    panel = ctx.properties.panel
    dim, tags = pick_in_viewport(ctx, qtbot, panel, [(0.3, 0.1), (0.3, 0.6)], "surface")
    assert dim == 2 and len(tags) == 2
    combo = panel.editors["material"]
    combo.setCurrentIndex(combo.findText(material))
    combo.activated.emit(combo.currentIndex())
    region = doc.model.regions[0]
    assert region.material == material and region.selection != ""
    assert sorted(doc.model.selections[region.selection].tags) == sorted(doc.built.surfaces)

    # (f) mesh size 0.025 in the mesh panel, then "Generate mesh" on the gmsh thread
    set_number(ctx, ("mesh_settings",), "global_size", str(MESH_SIZE))
    assert doc.mesh_stale
    generate_mesh(ctx, qtbot)
    assert ctx.view.layer_artists("mesh")

    # (g, h) validate, solve on the solve thread, compare with the benchmark
    solve(ctx, qtbot)
    check_physics(ctx)

    # (i) a default contour is displayed; levels and smooth shading change it; PNG export
    assert [o.name for o in ctx.results.objects] == ["Temperature 1"]
    assert ctx.results.display is not None and ctx.view.layer_artists("results")
    assert ctx.results.display.levels == 12
    assert ctx.tree.select_address(("result", "Temperature 1"))
    result_panel = ctx.properties.result_panel
    assert result_panel is not None
    before = len(ctx.view.layer_artists("results"))
    result_panel.levels_spin.setValue(7)
    assert ctx.results.display.levels == 7
    result_panel.banded_check.setChecked(False)
    assert ctx.results.display.levels is None  # smooth shading
    assert ctx.view.layer_artists("results") and before > 0
    ctx.charts.choose_save = lambda _parent, _caption, _filter: str(tmp_path / "contour.png")
    trigger(ctx, "export.image")
    png = tmp_path / "contour.png"
    assert png.is_file() and png.stat().st_size > 1000
    assert png.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"

    # (j) ten edits through the panels, undo all, redo all; stale flags
    model_before = snapshot(doc.model)
    steps_before = doc.undo_stack.count()
    bcs = {"fixed": ("bcs", 0), "conv": ("bcs", 1)}
    mesh, region_a, mat = ("mesh_settings",), ("regions", 0), ("materials", material)
    edits = [
        lambda: set_function(ctx, bcs["conv"], "h", "800"),
        lambda: set_number(ctx, mesh, "global_size", "0.03"),
        lambda: set_number(ctx, region_a, "thickness", "2"),
        lambda: set_function(ctx, mat, "k", "60"),
        lambda: set_function(ctx, bcs["conv"], "h", "700"),
        lambda: set_number(ctx, mesh, "global_size", "0.02"),
        lambda: set_function(ctx, bcs["fixed"], "T", "380"),
        lambda: set_function(ctx, bcs["conv"], "T_inf", "280"),
        lambda: set_number(ctx, region_a, "thickness", "1.5"),
        lambda: set_function(ctx, bcs["conv"], "h", "650"),
    ]
    edits[0]()
    assert doc.results_stale and not doc.mesh_stale and not doc.geometry_stale
    edits[1]()
    assert doc.mesh_stale and doc.results_stale and not doc.geometry_stale
    for edit in edits[2:]:
        edit()
    assert doc.undo_stack.count() == steps_before + 10
    model_after = snapshot(doc.model)
    assert model_after != model_before
    assert doc.model.bcs[1].h == Constant(650.0) and doc.model.mesh_settings.global_size == 0.02
    assert doc.modified

    undo_all(ctx, 10)
    assert doc.undo_stack.count() == steps_before + 10 and doc.undo_stack.index() == steps_before
    assert doc.model == model_before
    redo_all(ctx, 10)
    assert doc.undo_stack.index() == steps_before + 10
    assert doc.model == model_after
    undo_all(ctx, 10)
    assert doc.model == model_before
    # the flags only ever rise: the results are out of date and the mesh must be remade
    assert doc.results_stale and doc.mesh_stale and not doc.geometry_stale
    assert not ctx.window.actions["solve.run"].isEnabled()
    generate_mesh(ctx, qtbot)
    solve(ctx, qtbot)
    check_physics(ctx)

    # (k) save through File > Save As (injected chooser); solve once more beside the file
    path = tmp_path / "v10.tfea"
    ctx.files.choose_save = lambda _parent, _suggested: str(path)
    trigger(ctx, "file.save_as")
    assert path.is_file() and doc.path == path and not doc.modified
    assert ctx.window.windowTitle() == "v10 - ThermalFEA"
    solve(ctx, qtbot)
    results_file = api.results_path(path)
    assert doc.results_path == results_file and results_file.is_file()
    check_physics(ctx)
    saved_model = snapshot(doc.model)

    ctx.files.ask_unsaved = lambda _parent, _name: pytest.fail("asked about unsaved changes")
    with qtbot.waitSignal(ctx.geometry.rebuilt, timeout=WAIT):  # even an empty model is built
        trigger(ctx, "file.new")
    assert doc.model == Model() and doc.mesh is None
    assert doc.results_path is None and doc.path is None
    assert ctx.results.results is None and not ctx.view.layer_artists("results")

    ctx.files.choose_open = lambda _parent: str(path)
    trigger(ctx, "file.open")
    qtbot.waitUntil(lambda: not doc.geometry_stale, timeout=WAIT)  # rebuilt on its own
    assert doc.built is not None and len(doc.built.surfaces) == 2
    assert doc.path == path and not doc.modified
    assert _comparable(to_json(doc.model)) == _comparable(to_json(saved_model))
    assert doc.model == saved_model
    assert ctx.window.windowTitle() == "v10 - ThermalFEA"
    assert doc.results_path is None and ctx.files.pending_results == results_file
    generate_mesh(ctx, qtbot)  # the results beside the model attach once a mesh exists
    assert doc.results_path == results_file and not doc.results_stale
    assert ctx.files.pending_results is None
    check_physics(ctx)
    assert ctx.results.display is not None and ctx.view.layer_artists("results")
    assert not doc.modified

    # (l) shutdown leaves no thread running and no error was reported on the way
    assert ctx.shutdown(5000)
    assert not ctx.solve.running and not ctx.gmsh_worker.is_running
    assert ctx.errors.calls == []  # type: ignore[attr-defined]


def test_unthreaded_application_builds_and_meshes_synchronously(
    qtbot, tmp_path: Path
) -> None:
    ctx = build_application(make_settings(tmp_path / "s.ini"), threaded=False, install_hook=False)
    qtbot.addWidget(ctx.window)
    ctx.files.ask_unsaved = lambda _parent, _name: "discard"
    try:
        assert ctx.gmsh_worker is None
        assert ctx.geometry.worker is None and ctx.mesh.worker is None
        trigger(ctx, "geometry.rectangle")
        dialog = ctx.geometry.active_dialog
        for name, value in (("x", 0.0), ("y", 0.0), ("width", 1.0), ("height", 0.5)):
            dialog.editors[name].setText(str(value))
        dialog.accept()
        assert ctx.document.built is not None and not ctx.document.geometry_stale
        assert ctx.mesh.generate() and ctx.document.mesh is not None
    finally:
        assert ctx.shutdown(5000)


def test_shutdown_restores_the_exception_hook(qtbot, tmp_path: Path) -> None:
    previous = sys.excepthook
    ctx = build_application(make_settings(tmp_path / "s.ini"), install_hook=True)
    qtbot.addWidget(ctx.window)
    ctx.files.ask_unsaved = lambda _parent, _name: "discard"
    try:
        assert sys.excepthook is not previous
        # the document lives as long as the window that listens to its undo stack
        assert ctx.document.parent() is ctx.window
    finally:
        assert ctx.shutdown(5000)
        assert ctx.restore_hook is None
        assert sys.excepthook is previous
        assert ctx.shutdown(5000)  # idempotent
