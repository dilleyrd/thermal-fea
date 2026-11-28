"""Tutorials 2 and 3 of the user guide, built through the GUI widgets the pages name.

``guide/tutorials/fin-quench.md`` and ``guide/tutorials/cold-plate.md`` give numbered GUI
steps. These tests perform the same operations offscreen, through the same entry points a
user action reaches: the Geometry menu dialog, the Tools > Material library dialog, the
tree's Add actions, the property panels (selection editor, function editors, number and
choice fields, the correlation preview), the New stream dialog and the stream panel, the
Solve menu actions, and the Results menu and Flow results windows. The numbers reached are
those the example scripts (and so the pages) give; the model is never edited directly.

Nothing modal runs and every wait is bounded. Steps that need a real screen (what the
widgets look like, where to click, the colors) stay unverified here.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent

from conftest import DialogRecorder, make_settings
from thermalfea.core.functions import Constant
from thermalfea.gui.app import AppContext, build_application
from thermalfea.gui.property_panels.form import NumberEdit
from thermalfea.gui.solve_tools import CONTINUE_ID, RUN_ID, VALIDATE_ID
from thermalfea.model.bcs import Adiabatic, CorrelationConvection, HeatFlux, RadiationAmbient
from thermalfea.model.validate import errors
from thermalfea.post.results import Results

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"
if str(EXAMPLES) not in sys.path:
    sys.path.insert(0, str(EXAMPLES))

import tutorial_cold_plate as cold  # noqa: E402
import tutorial_fin_quench as fin  # noqa: E402

WAIT = 60000  # ms; every wait in this file is bounded


# ----------------------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def fin_reference() -> dict:
    """What ``examples/tutorial_fin_quench.py`` computes (the numbers of the page)."""
    return fin.run()


@pytest.fixture(scope="module")
def cold_reference() -> dict:
    """What ``examples/tutorial_cold_plate.py`` computes (the numbers of the page)."""
    return cold.run()


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
    ctx.materials.user_path = tmp_path / "user-materials.json"  # never the real user library

    def unexpected(*_args: Any) -> Any:
        raise AssertionError("a modal question or chooser would have been shown")

    ctx.files.ask_unsaved = lambda _parent, _name: "discard"
    ctx.files.choose_open = unexpected
    ctx.files.choose_save = unexpected
    ctx.charts.choose_save = unexpected
    qtbot.addWidget(ctx.window)
    ctx.view.widget().resize(640, 480)
    yield ctx
    for window in list(ctx.charts.windows):
        window.close()
    assert ctx.shutdown(5000)


# ------------------------------------------------------------------------------ helpers


def trigger(ctx: AppContext, action_id: str) -> None:
    """Trigger a menu action; it must be enabled, as a click on the menu entry needs."""
    action = ctx.window.actions[action_id]
    assert action.isEnabled(), f"{action_id} is disabled"
    action.trigger()


def tree_action(ctx: AppContext, section: str, data: tuple) -> None:
    """Trigger the context-menu action of a tree node whose ``data()`` is ``data``."""
    actions = ctx.tree.actions_for(ctx.tree.section_item(section))
    next(a for a in actions if a.data() == data).trigger()


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
    """Type a value into a function field (mode Constant, switching to it if needed)."""
    panel = open_panel(ctx, address)
    editor = panel.editors[name]
    if editor.mode != "constant":  # an optional field starts as "None"
        editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("constant"))
    steps = ctx.document.undo_stack.count()
    enter(editor.value_edit, text)
    assert panel.error_text() == "" and editor.error_text() == ""
    assert ctx.document.undo_stack.count() == steps + 1, (address, name, text)


def set_number(ctx: AppContext, address: tuple, name: str, text: str) -> None:
    """Type a value into a number field; one undo step."""
    panel = open_panel(ctx, address)
    editor = panel.editors[name]
    assert isinstance(editor, NumberEdit)
    steps = ctx.document.undo_stack.count()
    enter(editor, text)
    assert panel.error_text() == "" and editor.error_text() == ""
    assert ctx.document.undo_stack.count() == steps + 1, (address, name, text)


def choose(ctx: AppContext, address: tuple, name: str, text: str) -> None:
    """Choose an entry of a list field (a combo box) by its text."""
    panel = open_panel(ctx, address)
    combo = panel.editors[name]
    index = combo.findText(text)
    assert index >= 0, (name, text, [combo.itemText(i) for i in range(combo.count())])
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def click(view: Any, x: float, y: float, ctrl: bool = False) -> None:
    """Press and release the left button at the data position ``(x, y)`` [m]."""
    for name in ("button_press_event", "button_release_event"):
        px, py = view.axes.transData.transform((x, y)) + 1e-6
        MouseEvent(
            name, view.canvas, px, py, button=1, modifiers=["ctrl"] if ctrl else None
        )._process()


def pick_in_viewport(
    ctx: AppContext, qtbot: Any, panel: Any, points: list[tuple[float, float]], mode: str,
    field: str = "selection",
) -> tuple[int, list[int]]:
    """"Pick in viewport", toolbar mode, click the points (Ctrl after the first), "Apply"."""
    editor = panel.editors[field]
    ctx.view.canvas.draw()  # the equal-aspect limits are final before the data are mapped
    editor.pick_button.setChecked(True)
    trigger(ctx, f"select.{mode}")
    for index, (x, y) in enumerate(points):
        with qtbot.waitSignal(ctx.view.selection_changed, timeout=WAIT):
            click(ctx.view, x, y, ctrl=index > 0)
    dim, tags = editor.picked()
    assert editor.apply_button.isEnabled(), (dim, tags)
    editor.apply_button.click()
    editor.pick_button.setChecked(False)
    return dim, tags


def draw_rectangle(ctx: AppContext, qtbot: Any, width: float, height: float) -> None:
    """Geometry > Rectangle...: x = 0, y = 0, the given size, OK; wait for the rebuild."""
    trigger(ctx, "geometry.rectangle")
    dialog = ctx.geometry.active_dialog
    assert dialog is not None
    for name, value in (("x", 0.0), ("y", 0.0), ("width", width), ("height", height)):
        dialog.editors[name].setText(str(value))
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    with qtbot.waitSignal(ctx.geometry.rebuilt, timeout=WAIT) as blocker:
        ok.click()
    assert blocker.args == [True], ctx.geometry.last_error
    assert dialog.error_label.text() == ""
    trigger(ctx, "view.fit")
    ctx.view.canvas.draw()


def copy_library_material(ctx: AppContext, name: str) -> None:
    """Tools > Material library...: select a built-in solid, "Copy into model"."""
    trigger(ctx, "tools.material_library")
    dialog = ctx.materials.dialog
    assert dialog is not None and dialog.isVisible()
    items = dialog.builtin_list.findItems(name, Qt_MatchExactly())
    assert len(items) == 1
    dialog.builtin_list.setCurrentItem(items[0])
    assert dialog.selected_material() is not None
    dialog.copy_button.click()
    assert name in ctx.document.model.materials, dialog.status.text()
    dialog.close()


def Qt_MatchExactly() -> Any:  # noqa: N802 (a flag, spelled like Qt spells it)
    from PySide6.QtCore import Qt

    return Qt.MatchFlag.MatchExactly


def add_region(ctx: AppContext, material: str, thickness: float) -> None:
    """Parts > Add part: Selection "all", the material, Thickness."""
    tree_action(ctx, "regions", ("add_region", None))
    panel = ctx.properties.panel
    assert "all" in panel.editors["selection"].allowed_names()
    panel.editors["selection"].choose("all")
    choose(ctx, ("regions", 0), "material", material)
    set_number(ctx, ("regions", 0), "thickness", str(thickness))
    region = ctx.document.model.regions[0]
    assert region.selection == "all" and region.material == material
    assert region.thickness == pytest.approx(thickness)


def generate_mesh(ctx: AppContext, qtbot: Any, size: float) -> None:
    """Mesh node: Global element size, then Mesh > Generate mesh."""
    set_number(ctx, ("mesh_settings",), "global_size", str(size))
    panel = open_panel(ctx, ("mesh_settings",))
    assert panel.generate_button.isEnabled()
    with qtbot.waitSignal(ctx.mesh.meshed, timeout=WAIT) as blocker:
        panel.generate_button.click()
    assert blocker.args == [True], ctx.errors.calls  # type: ignore[attr-defined]
    assert ctx.document.mesh is not None and not ctx.document.mesh_stale


def solve(ctx: AppContext, qtbot: Any, action: str = RUN_ID) -> None:
    """Solve > Validate (no errors), then Solve > Solve (or Continue) on the solve thread."""
    trigger(ctx, VALIDATE_ID)
    assert not errors(ctx.solve.last_issues), ctx.solve.last_issues
    with qtbot.waitSignal(ctx.solve.solve_finished, timeout=WAIT) as blocker:
        trigger(ctx, action)
    assert blocker.args == ["finished"], (ctx.solve.message, ctx.errors.calls)  # type: ignore[attr-defined]
    assert ctx.document.results_path is not None
    assert not ctx.document.results_stale and not ctx.solve.running


def results_of(ctx: AppContext) -> Results:
    """The results file the document now points to."""
    path = ctx.document.results_path
    assert path is not None
    return Results(path)


def centre_node(results: Results) -> int:
    """The node nearest the plate centre of the fin (the node the page plots)."""
    return int(np.argmin(np.linalg.norm(results.mesh.nodes[:, :2] - fin.PROBE, axis=1)))


# --------------------------------------------------------------------- tutorial 2: fin


def test_fin_quench_in_the_gui(
    app: AppContext, qtbot, caplog: pytest.LogCaptureFixture, fin_reference: dict
) -> None:
    ctx, doc = app, app.document
    ref = fin_reference
    caplog.set_level(logging.WARNING, logger="thermalfea")
    caplog.set_level(logging.INFO, logger="thermalfea.solver.run")

    # step: geometry, material from the library, region
    draw_rectangle(ctx, qtbot, fin.THICKNESS, fin.HEIGHT)
    copy_library_material(ctx, fin.MATERIAL)
    add_region(ctx, fin.MATERIAL, fin.DEPTH)

    # step: correlation convection on the two long faces, with the h preview
    t, h = fin.THICKNESS, fin.HEIGHT
    # (the dialog that opens asks for the correlation, the fluid and the ambient temperature)
    tree_action(ctx, "loads", ("add_bc", "correlation_convection"))
    assert doc.model.bcs == []  # added when the dialog is accepted
    dialog = ctx.tree.load_dialog
    dialog.correlation_box.setCurrentText(fin.CORRELATION)
    dialog.fluid_box.setCurrentText(fin.FLUID)
    dialog.ambient_edit.setText(str(fin.T_AMBIENT))
    dialog.ok_button.click()
    panel = ctx.properties.panel
    assert doc.model.bcs[0].name == fin.CONVECTION
    dim, tags = pick_in_viewport(ctx, qtbot, panel, [(0.0, h / 2), (t, h / 2)], "curve")
    assert dim == 1 and len(tags) == 2
    convection = ("bcs", 0)
    set_number(ctx, convection, "char_length", str(fin.HEIGHT))
    panel = open_panel(ctx, convection)
    assert panel.needed_inputs() == ["T_surface"]  # everything else the condition defines
    panel.set_preview_input("T_surface", fin.T_INIT)
    assert panel.preview_h == pytest.approx(ref["hand"]["h_conv"], rel=1e-9)
    assert panel.preview_text.splitlines() == [
        "h = 8.57576 W/(m^2 K)", "Nu = 25.3721", "Ra = 4.851e+06", "Pr = 0.6903",
        "Regime: single correlation", "T_film = 400 K", "Length used = 0.1 m",
    ]
    assert "Churchill" in panel.title_label_info.text()
    assert "Warning" not in panel.preview_text
    assert f"{ref['hand']['h_conv']:.6g}" in panel.preview_text

    # step: radiation on the same two curves (chosen from the list), emissivity, ambient
    tree_action(ctx, "loads", ("add_bc", "radiation_ambient"))
    dialog = ctx.tree.load_dialog
    dialog.emissivity_edit.setText(str(fin.EMISSIVITY))
    dialog.ambient_edit.setText(str(fin.T_AMBIENT))
    dialog.ok_button.click()
    assert doc.model.bcs[1].name == fin.RADIATION
    editor = ctx.properties.panel.editors["selection"]
    faces = doc.model.bcs[0].selection
    assert faces in editor.allowed_names()
    editor.choose(faces)

    # step: insulated ends
    tree_action(ctx, "loads", ("add_bc", "adiabatic"))
    pick_in_viewport(ctx, qtbot, ctx.properties.panel, [(t / 2, 0.0), (t / 2, h)], "curve")
    kinds = [type(bc) for bc in doc.model.bcs]
    assert kinds == [CorrelationConvection, RadiationAmbient, Adiabatic]
    assert doc.model.bcs[0].selection == doc.model.bcs[1].selection
    assert doc.model.bcs[0].T_inf == Constant(fin.T_AMBIENT)
    assert doc.model.bcs[1].emissivity == Constant(fin.EMISSIVITY)

    # step: mesh
    generate_mesh(ctx, qtbot, fin.MESH_SIZE)
    assert (doc.mesh.n_nodes, doc.mesh.n_elements) == (66, 86)
    assert doc.mesh.n_nodes == ref["mesh"].n_nodes

    # step: initial condition and transient settings
    set_function(ctx, ("initial_condition",), "value", str(fin.T_INIT))
    choose(ctx, ("solution",), "kind", "transient")
    set_number(ctx, ("solution",), "end_time", str(fin.END_TIME))
    solution_panel = open_panel(ctx, ("solution",))
    assert solution_panel.is_field_shown("initial_dt") and solution_panel.is_field_shown("theta")
    assert doc.model.solution.auto_timestep and doc.model.solution.output == "all"

    # the suggested first step triggers the oscillation warning on this mesh (the page says so)
    trigger(ctx, VALIDATE_ID)
    assert not errors(ctx.solve.last_issues)
    set_number(ctx, ("solution",), "initial_dt", str(fin.INITIAL_DT))
    assert doc.model.solution.initial_dt == pytest.approx(fin.INITIAL_DT)
    assert doc.model.solution.end_time == pytest.approx(fin.END_TIME)

    # step: solve (nothing may be warned about), then look at the results
    caplog.clear()
    solve(ctx, qtbot)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    assert ctx.solve.message.startswith("Solve finished at t = 3600 s: 218 stored step(s)")
    log = [r.getMessage() for r in caplog.records if r.name == "thermalfea.solver.run"]
    done = "step(s), 0 rejected, 0 Newton failure(s)"
    assert f"transient run finished at t = 3600 s: 217 {done}" in log
    assert any(m.startswith("energy balance [W]") and "relative imbalance" in m for m in log)
    assert any("relative imbalance            -2.821e-07" in m for m in log)
    results = results_of(ctx)
    node = centre_node(results)
    assert node == ref["node"]
    assert results.n_steps == ref["n_steps_3600"]
    assert float(results.temperature()[node]) == pytest.approx(ref["T_end"], rel=1e-6)
    assert [o.name for o in ctx.results.objects] == ["Temperature 1"]
    reading = ctx.results.probe_at(fin.PROBE[0], fin.PROBE[1])
    assert reading is not None and reading.inside
    assert reading.value == pytest.approx(ref["T_end"], abs=0.01)  # the nodal spread is 1 mK
    assert ctx.charts.plot_heat_flows() is not None
    assert ctx.charts.plot_energy_balance() is not None
    # Results > Nodal history...: the first choice asks for nodes, the second one plots them
    assert ctx.charts.request_history() is None and ctx.charts.history_pending
    x, y = (float(v) for v in results.mesh.nodes[node, :2])
    with qtbot.waitSignal(ctx.view.selection_changed, timeout=WAIT):
        click(ctx.view, x, y)
    assert ctx.charts.selected_nodes == [node]
    chart = ctx.charts.request_history()
    assert chart is not None and not ctx.charts.history_pending
    heat = {name: float(results.heat_flow(name)[1]) for name in results.heat_flow_names}
    assert -heat[fin.CONVECTION] == pytest.approx(ref["split_first"]["conv"], rel=1e-6)
    assert -heat[fin.RADIATION] == pytest.approx(ref["split_first"]["rad"], rel=1e-6)

    # Tools > HTC calculator...: the same h as the preview, computed as the reader types
    trigger(ctx, "tools.htc")
    calc = ctx.flow.htc_window
    assert calc is not None and calc.isVisible()
    calc.correlation_box.setCurrentIndex(calc.correlation_box.findText(fin.CORRELATION))
    calc.fluid_box.setCurrentIndex(calc.fluid_box.findText(fin.FLUID))
    calc.t_surface_edit.setText(str(fin.T_INIT))
    calc.t_inf_edit.setText(str(fin.T_AMBIENT))
    assert calc.visible_inputs() == ["length"]
    calc.input_edits["length"].setText(str(fin.HEIGHT))
    calc.calculate_button.click()
    assert calc.message == "" and calc.result is not None
    assert calc.result.h == pytest.approx(ref["hand"]["h_conv"], rel=1e-12)
    assert calc.result_label.text().splitlines()[0] == "h = 8.57576 W/(m^2 K)"
    shown = calc.result_label.text()
    assert "Nu = 25.3721" in shown and "Ra = 4.851e+06" in shown

    # step: continue to a later end time. Editing the end time marks the results out of date.
    set_number(ctx, ("solution",), "end_time", str(fin.LATER_END_TIME))
    assert doc.results_stale
    first_path = doc.results_path
    solve(ctx, qtbot, CONTINUE_ID)
    assert doc.results_path == first_path
    assert ctx.solve.message.startswith("Solve finished at t = 7200 s: 248 stored step(s)")
    log = [r.getMessage() for r in caplog.records if r.name == "thermalfea.solver.run"]
    assert any(m.startswith("continuing ") and m.endswith(" from t = 3600 s to t = 7200 s")
               for m in log)
    assert log[-1] == f"transient run finished at t = 7200 s: 30 {done}"
    results = results_of(ctx)
    assert results.n_steps == ref["n_steps_7200"]
    assert float(results.times[-1]) == pytest.approx(fin.LATER_END_TIME)
    assert float(results.temperature()[node]) == pytest.approx(ref["T_later"], rel=1e-6)
    conv, rad = (-float(results.heat_flow(n)[-1]) for n in (fin.CONVECTION, fin.RADIATION))
    assert rad / (conv + rad) == pytest.approx(ref["split_later"]["rad_share"], rel=1e-6)
    relative = results.energy_balance()["relative_imbalance"]
    assert np.abs(relative[np.isfinite(relative)]).max() < 1e-5
    assert ctx.errors.calls == []  # type: ignore[attr-defined]
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


# ---------------------------------------------------------------- tutorial 3: cold plate


def test_cold_plate_in_the_gui(
    app: AppContext, qtbot, caplog: pytest.LogCaptureFixture, cold_reference: dict
) -> None:
    ctx, doc = app, app.document
    ref = cold_reference
    caplog.set_level(logging.WARNING, logger="thermalfea")
    length, thickness = cold.LENGTH, cold.THICKNESS

    # steps: geometry, material, region
    draw_rectangle(ctx, qtbot, length, thickness)
    copy_library_material(ctx, cold.MATERIAL)
    add_region(ctx, cold.MATERIAL, cold.DEPTH)

    # step: the heat flux of the components on the top edge, insulated ends
    tree_action(ctx, "loads", ("add_bc", "heat_flux"))
    assert doc.model.bcs[0].name == "Heat Flux 1"
    dim, tags = pick_in_viewport(
        ctx, qtbot, ctx.properties.panel, [(length / 2, thickness)], "curve"
    )
    assert dim == 1 and len(tags) == 1
    set_function(ctx, ("bcs", 0), "q", str(cold.FLUX))
    tree_action(ctx, "loads", ("add_bc", "adiabatic"))
    pick_in_viewport(
        ctx, qtbot, ctx.properties.panel,
        [(0.0, thickness / 2), (length, thickness / 2)], "curve",
    )
    assert [type(bc) for bc in doc.model.bcs] == [HeatFlux, Adiabatic]
    assert doc.model.bcs[0].q == Constant(cold.FLUX)

    # step: Flow > Streams > Add stream opens the New stream dialog
    assert doc.model.streams == []
    # no contact, stream or network yet: the folded line offers Add stream (M11.51)
    tree_action(ctx, "folded", ("add_stream", None))
    dialog = ctx.tree.stream_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.flow_area_edit.text() == "" and "Flow area [m^2]" in _row_labels(dialog)
    dialog.submit()  # nothing typed yet: refused, the dialog says what is missing
    assert dialog.message_label.text() != "" and doc.model.streams == []
    dialog.fluid_box.setCurrentIndex(dialog.fluid_box.findText(cold.FLUID))
    dialog.flow_area_edit.setText(f"{cold.flow_area():.6g}")
    dialog.wetted_edit.setText(f"{cold.wetted_perimeter():.6g}")
    dialog.cross_box.setCurrentIndex(dialog.cross_box.findText(cold.CROSS_SECTION))
    dialog.inlet_edit.setText(str(cold.T_INLET))
    assert dialog.submit()
    assert not dialog.isVisible()
    stream = doc.model.streams[0]
    assert stream.name == cold.STREAM and stream.mode == "in_plane" and stream.walls == []
    assert stream.mass_flow is None and stream.path is None
    assert ctx.properties.current_address == ("streams", 0)

    # step: the stream panel: walls, path, mass flow
    address = ("streams", 0)
    panel = open_panel(ctx, address)
    pick_in_viewport(ctx, qtbot, panel, [(length / 2, 0.0)], "curve", field="walls")
    assert len(doc.model.streams[0].walls) == 1
    assert doc.model.streams[0].walls == ["Stream 1 walls"]
    path_edit = open_panel(ctx, address).editors["path"]
    enter(path_edit, f"0, 0; {length}, 0")
    assert doc.model.streams[0].path == [(0.0, 0.0), (length, 0.0)]
    assert open_panel(ctx, address).path_label.text() == "2 path points"
    set_function(ctx, address, "mass_flow", str(cold.MASS_FLOW))
    stream = doc.model.streams[0]
    assert stream.mass_flow == Constant(cold.MASS_FLOW)
    assert (stream.roughness, stream.nu_option, stream.h_multiplier) == (0.0, "auto", 1.0)

    # steps: mesh, solve (steady is the default), results
    generate_mesh(ctx, qtbot, cold.MESH_SIZE)
    solve(ctx, qtbot)
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []
    # a steady solve has no time to report (M11.8, Q26.4(f))
    assert ctx.solve.message.startswith("Solve finished: 1 stored step(s)")
    assert (doc.mesh.n_nodes, doc.mesh.n_elements) == (126, 166)
    results = results_of(ctx)
    assert float(results.temperature().max()) == pytest.approx(ref["T_max"], rel=1e-9)
    flow_window = ctx.flow.show_flow()
    assert flow_window is not None and flow_window.isVisible()
    assert [flow_window.table.item(0, c).text() for c in range(10)] == (
        flow_window.row_texts(flow_window.rows[0])
    )
    assert flow_window.row_texts(flow_window.rows[0]) == [
        "Stream 1", "in_plane", "0.02", "923.245", "laminar", "772.433", "72.3679",
        "300", "302.392", "200",
    ]
    assert int(results.iterations[-1]) == ref["iterations"] == 3
    summary = flow_window.rows[0]
    assert summary.regime == ref["regime"] == "laminar"
    assert summary.Re == pytest.approx(ref["Re"], rel=1e-9)
    assert summary.h_mean == pytest.approx(ref["h_mean"], rel=1e-9)
    assert summary.dp == pytest.approx(ref["dp"], rel=1e-9)
    assert summary.T_out == pytest.approx(ref["T_out"], rel=1e-9)
    assert summary.heat == pytest.approx(ref["heat"], rel=1e-9)
    flow_window.table.selectRow(0)
    assert flow_window.plot_selected() is not None
    flow_window.plot_windows[0].close()

    # step: what-if. A new mass flow makes the results out of date; solve again.
    set_function(ctx, address, "mass_flow", str(cold.WHAT_IF[1]))
    assert doc.results_stale
    solve(ctx, qtbot)
    again = ctx.flow.show_flow().rows[0]
    other = ref["what_if"][1]
    assert again.regime == other["regime"] == "turbulent"
    assert again.Re == pytest.approx(other["Re"], rel=1e-9)
    assert again.h_mean == pytest.approx(other["h_mean"], rel=1e-9)
    assert again.T_out == pytest.approx(other["T_out"], rel=1e-9)
    assert float(results_of(ctx).temperature().max()) == pytest.approx(other["T_max"], rel=1e-9)
    assert ctx.errors.calls == []  # type: ignore[attr-defined]
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


def _row_labels(dialog: Any) -> list[str]:
    """The labels of the form rows of the New stream dialog."""
    from PySide6.QtWidgets import QFormLayout, QLabel

    form = dialog.findChild(QFormLayout)
    labels = []
    for row in range(form.rowCount()):
        item = form.itemAt(row, QFormLayout.ItemRole.LabelRole)
        if item is not None and isinstance(item.widget(), QLabel):
            labels.append(item.widget().text())
    return labels
