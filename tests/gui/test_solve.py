"""M8.9: analysis settings panel, issue list, worker threads, solve controller and dialog.

Real gmsh meshes a tiny rectangle and the real solver runs in a worker thread. Everything
is offscreen; no dialog is executed modally (the error dialog is the recording stand-in and
the progress dialog is shown non-modally). Every wait is bounded: ``waitSignal`` and
``waitUntil`` with a timeout, ``timeout`` on the command line, joins with a bound.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QPushButton

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Constant, Table
from thermalfea.gui import geometry_tools, mesh_tools
from thermalfea.gui.dialogs.solve_progress import SolveProgressDialog
from thermalfea.gui.document import Document
from thermalfea.gui.geometry_tools import attach_geometry_tools
from thermalfea.gui.issues import IssuePanel, address_for_issue
from thermalfea.gui.mesh_tools import attach_mesh_tools
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.solution import SolutionPanel
from thermalfea.gui.solve_tools import (
    CANCEL_ID,
    RUN_ID,
    VALIDATE_ID,
    attach_solve,
    initial_condition_conflict,
)
from thermalfea.gui.worker import BackgroundTask, SerialWorker, TaskCancelled
from thermalfea.materials.material import Material
from thermalfea.model import bcs
from thermalfea.model.model import InitialCondition, Model
from thermalfea.model.settings import SolutionSettings
from thermalfea.model.validate import Issue
from thermalfea.post.results import Results

WAIT = 30000  # ms; every wait in this file is bounded


def enter(editor: Any, text: str) -> None:
    editor.setText(text)
    editor.editingFinished.emit()


# ------------------------------------------------------------------------------- models
def make_model(
    kind: str = "steady", steps: int = 20, end_time: float = 200.0, every: int = 1
) -> Any:
    """A 1 m x 0.5 m copper plate, fixed 400 K on the west, convection on the east."""
    model = api.new_model(name="plate")
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
    if kind == "transient":
        model.solution = SolutionSettings(
            kind="transient", end_time=end_time, auto_timestep=False,
            initial_dt=end_time / steps, output="every_n", output_every=every,
        )  # fmt: skip
    return model, built


def make_document(kind: str = "steady", **options: Any) -> Document:
    model, built = make_model(kind, **options)
    document = Document(model)
    document.set_built(built)
    document.set_mesh(api.mesh(model, built))
    return document


def make_shell(window, document: Document, dialogs=None) -> SimpleNamespace:
    """Tree, property controller and solve controller as in the application."""
    tree, props = attach_tree(window, document, None)
    solve = attach_solve(window, document)
    props.solve_controller = solve
    solve.show_progress = False
    return SimpleNamespace(window=window, doc=document, tree=tree, props=props, solve=solve)


@pytest.fixture
def steady(window) -> SimpleNamespace:
    return make_shell(window, make_document())


def run_to_end(qtbot, shell: SimpleNamespace) -> str:
    """Start a solve and wait for its outcome (bounded)."""
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT) as blocker:
        assert shell.solve.solve()
    assert not shell.solve.running
    return str(blocker.args[0])


def finish_running(qtbot, shell: SimpleNamespace) -> None:
    """Cancel a running solve and wait for it, so no thread outlives the test."""
    if shell.solve.running:
        with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT):
            shell.solve.cancel()


# ------------------------------------------------------------------------ settings panel
def open_panel(shell: SimpleNamespace) -> SolutionPanel:
    shell.props.show_object(("solution",))
    panel = shell.props.panel
    assert isinstance(panel, SolutionPanel)
    return panel


def test_panel_covers_every_field_and_hides_transient_fields_when_steady(steady) -> None:
    panel = open_panel(steady)
    assert set(panel.editors) == set(SolutionSettings.__dataclass_fields__)
    transient_only = ("end_time", "initial_dt", "dt_min", "theta", "output", "time_tol")
    for name in transient_only:
        assert not panel.is_field_shown(name), name
    for name in ("kind", "rtol", "ttol", "max_iterations", "line_search"):
        assert panel.is_field_shown(name), name
    combo = panel.editors["kind"]
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert steady.doc.model.solution.kind == "transient"
    for name in transient_only:
        assert panel.is_field_shown(name), name
    assert not panel.is_field_shown("output_every") and not panel.is_field_shown("output_times")
    out = panel.editors["output"]
    out.setCurrentIndex(1)
    out.activated.emit(1)
    assert panel.is_field_shown("output_every") and not panel.is_field_shown("output_times")
    out.setCurrentIndex(2)
    out.activated.emit(2)
    assert panel.is_field_shown("output_times") and not panel.is_field_shown("output_every")
    steady.doc.undo_stack.undo()  # back to output "every_n"... then to steady
    steady.doc.undo_stack.undo()
    steady.doc.undo_stack.undo()
    assert steady.doc.model.solution.kind == "steady"
    assert not panel.is_field_shown("end_time")


def test_time_integration_is_a_choice_of_named_methods(steady) -> None:
    from thermalfea.gui.property_panels.solution import THETA_METHODS

    panel = open_panel(steady)
    combo = panel.editors["theta"]
    texts = [combo.itemText(i) for i in range(combo.count())]
    assert texts == [text for text, _theta, _tip in THETA_METHODS]
    assert texts[combo.currentIndex()].startswith("Backward Euler")
    assert all(combo.itemData(i, Qt.ItemDataRole.ToolTipRole) for i in range(combo.count()))
    doc, steps = steady.doc, steady.doc.undo_stack.count()
    combo.setCurrentIndex(2)
    combo.activated.emit(2)
    assert doc.model.solution.theta == 0.5 and doc.undo_stack.count() == steps + 1
    assert doc.undo_stack.undoText() == "Edit Time integration"
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert doc.model.solution.theta == pytest.approx(2.0 / 3.0)
    assert combo.currentText().startswith("Galerkin")
    # a value set outside the window is shown as "Custom" and kept, never replaced
    doc.edit("script", lambda m: setattr(m.solution, "theta", 0.6))
    assert combo.count() == len(THETA_METHODS) + 1
    assert combo.currentText() == "Custom (θ = 0.6)"
    assert doc.model.solution.theta == 0.6
    combo.setCurrentIndex(0)
    combo.activated.emit(0)
    assert doc.model.solution.theta == 1.0 and combo.count() == len(THETA_METHODS)
    doc.undo_stack.undo()
    assert combo.currentText() == "Custom (θ = 0.6)"


def test_panel_edits_units_output_times_and_rejects_bad_values(steady) -> None:
    panel = open_panel(steady)
    steps = steady.doc.undo_stack.count()
    enter(panel.editors["max_iterations"], "0")
    assert steady.doc.model.solution.max_iterations == 30
    assert steady.doc.undo_stack.count() == steps
    enter(panel.editors["max_iterations"], "12")
    assert steady.doc.model.solution.max_iterations == 12
    assert steady.doc.undo_stack.count() == steps + 1
    enter(panel.editors["end_time"], "-3")
    assert steady.doc.model.solution.end_time == 1.0
    enter(panel.editors["end_time"], "50")
    assert steady.doc.model.solution.end_time == 50.0
    enter(panel.editors["output_times"], "1, 2.5; 10")
    assert steady.doc.model.solution.output_times == [1.0, 2.5, 10.0]
    enter(panel.editors["output_times"], "1, x")
    assert steady.doc.model.solution.output_times == [1.0, 2.5, 10.0]
    assert panel.error_text("output_times")


def test_initial_condition_has_its_own_form(steady) -> None:
    steady.props.show_object(("initial_condition",))
    panel = steady.props.panel
    assert set(panel.editors) == {"kind", "value", "per_region", "results_path"}
    combo = panel.editors["kind"]
    combo.setCurrentIndex(2)
    combo.activated.emit(2)
    assert steady.doc.model.initial_condition.kind == "per_region"


def test_panel_buttons_follow_the_state(window, qtbot) -> None:
    document = make_document()
    shell = make_shell(window, document)
    panel = open_panel(shell)
    assert panel.validate_button.isEnabled() and panel.solve_button.isEnabled()
    document.edit("edit", lambda m: setattr(m.mesh_settings, "global_size", 0.2))  # mesh stale
    assert not panel.solve_button.isEnabled() and panel.validate_button.isEnabled()
    document.undo_stack.undo()
    document.set_mesh(api.mesh(document.model, document.built))
    assert panel.solve_button.isEnabled()
    button = next(b for b in panel.findChildren(QPushButton) if b.text() == "Solve")
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT):
        button.click()
    assert shell.solve.outcome == "finished"
    validate = next(b for b in panel.findChildren(QPushButton) if b.text() == "Validate")
    validate.click()
    assert shell.solve.last_issues == []


# ---------------------------------------------------------------------------- issue list
def broken_document() -> Document:
    """An error (BC on an unknown selection), an error on a region, and a table warning."""
    model, built = make_model()
    model.bcs.append(bcs.Convection("lost", "nowhere", h=10.0, T_inf=300.0))
    model.materials["Copper (pure)"] = Material(
        "Copper (pure)", Table([320.0, 380.0], [400.0, 390.0], "T"), 8960.0, 385.0
    )
    document = Document(model)
    document.set_built(built)
    document.set_mesh(api.mesh(model, built))
    return document


def test_validate_fills_the_issue_list_and_activate_selects_the_object(window) -> None:
    shell = make_shell(window, broken_document())
    panel: IssuePanel = shell.solve.issues
    issues = shell.solve.validate()
    assert {i.code for i in issues} == {"unknown-selection", "table-range"}
    assert panel.rowCount() == 2 and len(panel.issues) == 2
    assert [i.severity for i in panel.issues] == ["error", "warning"]  # errors first
    assert panel.item(0, 0).text() == "Error" and panel.item(1, 0).text() == "Warning"
    assert panel.item(0, 0).font().bold() and not panel.item(1, 0).font().bold()
    assert panel.item(0, 0).foreground().color() != panel.item(1, 0).foreground().color()
    assert "nowhere" in panel.item(0, 2).text()

    assert panel.activate(0)
    assert shell.props.current_address == ("bcs", 2)
    assert shell.props.panel.spec.title == "Convection"
    assert "lost" in shell.props.panel.title_label.text()
    assert panel.activate(1)
    assert shell.props.current_address == ("materials", "Copper (pure)")
    assert not panel.activate(5) and not panel.activate(-1)
    shell.props.show_object(("section", "none"))
    panel.cellDoubleClicked.emit(0, 1)  # the double click is wired to activate
    assert shell.props.current_address == ("bcs", 2)


def test_issue_kinds_map_to_tree_addresses() -> None:
    model, _built = make_model()
    model.streams = []
    cases = [
        (Issue("error", "x", "m", "bc", "cool"), ("bcs", 1)),
        (Issue("error", "x", "m", "bc", "gone"), None),
        (Issue("error", "x", "m", "boundary condition", "cool"), ("bcs", 1)),
        (Issue("error", "x", "m", "material", "Copper (pure)"), ("materials", "Copper (pure)")),
        (Issue("error", "x", "m", "region", "all"), ("regions", 0)),
        (Issue("error", "x", "m", "region", ""), ("section", "regions")),
        (Issue("error", "x", "m", "mesh", ""), ("mesh_settings",)),
        (Issue("error", "x", "m", "solution", ""), ("solution",)),
        (Issue("error", "x", "m", "model", "initial condition"), ("initial_condition",)),
        (Issue("error", "x", "m", "model", ""), None),
        (Issue("error", "x", "m", "selection", "west"), ("selections", "west")),
        (Issue("error", "x", "m", "selection", "nowhere"), None),
        (Issue("error", "x", "m", "contact", "c"), None),
        (Issue("error", "x", "m", "banana", "c"), None),
    ]
    for issue, expected in cases:
        assert address_for_issue(model, issue) == expected, issue


def test_network_issues_select_the_network_node() -> None:
    from thermalfea.model.bcs import FlowNetwork

    model, _built = make_model()
    issue = Issue("error", "bad-network", "m", "network", "b1")
    model.network = None
    assert address_for_issue(model, issue) is None
    model.network = FlowNetwork(nodes=[], branches=[])
    assert address_for_issue(model, issue) == ("network",)


def test_region_without_assignment_selects_the_regions_section(window) -> None:
    document = make_document()
    document.edit("drop", lambda m: m.regions.clear())
    shell = make_shell(window, document)
    shell.solve.validate()
    assert [i.code for i in shell.solve.last_issues] == ["no-region"]
    assert shell.solve.issues.activate(0)
    assert shell.props.current_address is None  # a section node: placeholder, no object
    assert shell.tree.currentItem() is shell.tree.section_item("regions")


def test_valid_model_has_an_empty_list_and_errors_block_the_solve(window) -> None:
    good = make_shell(window, make_document())
    assert good.solve.validate() == []
    assert good.solve.issues.rowCount() == 0
    assert "no issues" in good.window.statusBar().currentMessage()


def test_validate_action_without_geometry_reports_in_the_status_bar(window) -> None:
    shell = make_shell(window, Document())
    assert window.actions[VALIDATE_ID].isEnabled()
    window.actions[VALIDATE_ID].trigger()
    assert "Build the geometry" in window.statusBar().currentMessage()
    assert shell.solve.validate() is None


def test_solve_with_validation_errors_shows_the_list_and_does_not_start(window) -> None:
    shell = make_shell(window, broken_document())
    assert not shell.solve.solve()
    assert not shell.solve.running and shell.solve.dialog is None
    assert shell.solve.issues.rowCount() == 2
    assert shell.doc.results_path is None
    assert "error" in window.statusBar().currentMessage()


def test_issues_dock_is_tabified_with_messages_and_named(window) -> None:
    make_shell(window, make_document())
    dock = window.issues_dock
    assert dock.objectName() == "IssuesDock" and dock.windowTitle() == "Issues"
    assert dock in window.tabifiedDockWidgets(window.messages_dock)
    assert "view.dock.issues" in window.actions


# ------------------------------------------------------------------------------ worker
def test_task_reports_progress_and_returns_a_value(qtbot) -> None:
    seen: list[Any] = []
    flags: list[bool] = []

    def work(context) -> int:
        for i in range(5):
            assert context.report(i)
        return 42

    task = BackgroundTask(work, name="t")
    task.progress.connect(seen.append)
    task.finished.connect(lambda _v: flags.append(task.thread_alive))
    started: list[int] = []
    task.started.connect(lambda: started.append(1))
    with qtbot.waitSignal(task.finished, timeout=WAIT) as blocker:
        task.start()
    assert blocker.args == [42] and task.result == 42
    assert seen == [0, 1, 2, 3, 4] and started == [1]
    assert flags == [False]  # the thread had ended when "finished" was emitted
    assert not task.running and not task.thread_alive
    with pytest.raises(RuntimeError):
        task.start()


def test_task_runs_off_the_gui_thread(qtbot) -> None:
    ids: list[int] = []
    task = BackgroundTask(lambda _c: ids.append(threading.get_ident()))
    with qtbot.waitSignal(task.finished, timeout=WAIT):
        task.start()
    assert ids and ids[0] != threading.get_ident()


def test_task_raising_a_thermalfea_error_fails_with_a_readable_message(qtbot, caplog) -> None:
    def work(_context) -> None:
        raise ModelError("the model is wrong")

    task = BackgroundTask(work, name="t")
    with caplog.at_level("ERROR"), qtbot.waitSignal(task.failed, timeout=WAIT) as blocker:
        task.start()
    assert isinstance(blocker.args[0], ModelError) and str(task.error) == "the model is wrong"
    assert "the model is wrong" in caplog.text and "Traceback" not in caplog.text
    assert not task.running and task.result is None


def test_task_raising_another_exception_fails_and_logs_the_traceback(qtbot, caplog) -> None:
    def work(_context) -> None:
        raise ValueError("a bug")

    task = BackgroundTask(work, name="t")
    with caplog.at_level("ERROR"), qtbot.waitSignal(task.failed, timeout=WAIT) as blocker:
        task.start()
    assert isinstance(blocker.args[0], ValueError)
    assert "Traceback" in caplog.text and "a bug" in caplog.text


def test_cancelling_a_looping_task_emits_cancelled(qtbot) -> None:
    flags: list[bool] = []

    def work(context) -> str:
        for _ in range(2000):  # at most ~20 s; ends at the flag
            if context.cancelled:
                raise TaskCancelled
            time.sleep(0.01)
        return "done"

    task = BackgroundTask(work, name="t")
    task.cancelled.connect(lambda _v: flags.append(task.thread_alive))
    task.finished.connect(lambda _v: pytest.fail("must not finish"))
    with qtbot.waitSignal(task.cancelled, timeout=WAIT):
        task.start()
        QTimer.singleShot(50, task.cancel)
    assert flags == [False] and not task.running


def test_returning_after_a_cancel_request_is_a_cancel_with_the_value(qtbot) -> None:
    def work(context) -> str:
        while context.report(None):
            time.sleep(0.005)
        return "partial"

    task = BackgroundTask(work, name="t")
    with qtbot.waitSignal(task.progress, timeout=WAIT):
        task.start()
    task.cancel()
    with qtbot.waitSignal(task.cancelled, timeout=WAIT) as blocker:
        pass
    assert blocker.args == ["partial"] and task.cancel_requested


def test_shutdown_cancels_and_joins(qtbot) -> None:
    task = BackgroundTask(lambda c: [time.sleep(0.01) for _ in range(1000) if not c.cancelled])
    assert task.shutdown(1000)  # never started
    task.start()
    assert task.running
    assert task.shutdown(10000)
    assert not task.running and not task.thread_alive


def test_serial_worker_runs_jobs_in_order_on_one_thread(qtbot) -> None:
    worker = SerialWorker(name="test-worker")
    try:
        order: list[tuple[int, int]] = []
        tasks = [
            BackgroundTask(
                lambda _c, i=i: order.append((i, threading.get_ident())), executor=worker
            )
            for i in range(4)
        ]
        for task in tasks:
            task.start()
        assert worker.busy
        for task in tasks:
            assert task.wait(WAIT)
        assert [i for i, _ in order] == [0, 1, 2, 3]
        assert len({t for _, t in order}) == 1 and order[0][1] != threading.get_ident()
        qtbot.waitUntil(lambda: not worker.busy, timeout=WAIT)
        assert worker.is_running
    finally:
        assert worker.shutdown(10000)
    assert not worker.is_running


# --------------------------------------------------------------------------- solve steady
def test_steady_solve_runs_in_a_thread_and_stores_current_results(window, qtbot) -> None:
    shell = make_shell(window, make_document())
    ticks: list[int] = []
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(1)
    seen: list[Any] = []
    shell.solve.progress.connect(seen.append)
    assert shell.window.actions[RUN_ID].isEnabled()
    with qtbot.waitSignal(shell.doc.results_changed, timeout=WAIT):
        assert shell.solve.solve()
        assert shell.solve.running  # the GUI thread was not blocked
        assert not window.actions[RUN_ID].isEnabled()
        assert window.actions[CANCEL_ID].isEnabled()
    timer.stop()
    assert shell.doc.results_path is not None and shell.doc.results_path.exists()
    assert not shell.doc.results_stale
    assert Results(shell.doc.results_path).n_steps == 1
    dialog = shell.solve.dialog
    assert dialog.state == "finished" and dialog.n_reports == 1 and len(seen) == 1
    assert dialog.last_info.step == 0 and dialog.last_info.converged
    assert dialog.plot.steps == [0] and len(dialog.plot.residuals) == 1
    assert dialog.labels["converged"].text() == "yes" and dialog.labels["step"].text() == "0"
    assert shell.solve.outcome == "finished" and not shell.solve.running
    assert not window.actions[CANCEL_ID].isEnabled() and window.actions[RUN_ID].isEnabled()
    assert not shell.window.statusBar().currentMessage() == "Solving..."


def test_results_go_beside_the_model_file(window, qtbot, tmp_path) -> None:
    document = make_document()
    document.path = tmp_path / "plate.tfea"
    shell = make_shell(window, document)
    assert run_to_end(qtbot, shell) == "finished"
    assert document.results_path == api.results_path(tmp_path / "plate.tfea")
    assert document.results_path.is_file()


def test_run_action_needs_a_current_mesh(window) -> None:
    document = make_document()
    shell = make_shell(window, document)
    assert window.actions[RUN_ID].isEnabled() and not window.actions[CANCEL_ID].isEnabled()
    document.edit("mesh", lambda m: setattr(m.mesh_settings, "global_size", 0.2))
    assert not window.actions[RUN_ID].isEnabled()
    assert not shell.solve.solve()
    assert "mesh" in window.statusBar().currentMessage()
    empty = make_shell(window, Document())
    assert not empty.solve.can_solve()


# ------------------------------------------------------------------------ solve transient
def test_transient_progress_matches_step_info(window, qtbot) -> None:
    shell = make_shell(window, make_document("transient", steps=20, end_time=200.0))
    infos: list[Any] = []
    shell.solve.progress.connect(infos.append)
    assert run_to_end(qtbot, shell) == "finished"
    dialog = shell.solve.dialog
    assert dialog.transient and dialog.state == "finished"
    assert len(infos) == 20 and dialog.n_reports == 20  # one report per step (1..20)
    assert dialog.plot.steps == [i.step for i in infos]
    assert dialog.plot.residuals == pytest.approx([i.residual for i in infos])
    assert dialog.plot.steps == list(range(1, 21))
    final = dialog.last_info
    assert final.time == pytest.approx(200.0) and final.end_time == pytest.approx(200.0)
    assert dialog.bar.value() == dialog.bar.maximum()
    assert dialog.labels["time"].text().startswith("200")
    assert dialog.labels["iterations"].text() == str(final.iterations)
    assert dialog.plot.draw_count >= 1
    assert [i.time for i in infos] == sorted(i.time for i in infos)
    results = Results(shell.doc.results_path)
    assert results.n_steps == 21 and not shell.doc.results_stale


def test_progress_redraws_are_coalesced_but_the_last_state_is_shown(qtbot) -> None:
    from thermalfea.solver.run import StepInfo

    dialog = SolveProgressDialog(transient=True)
    qtbot.addWidget(dialog)
    for i in range(500):
        dialog.update_info(StepInfo(i, i * 0.1, 0.1, 2, True, 1.0 / (i + 1), 50.0))
    assert dialog.plot.draw_count < 50  # not one redraw per report
    assert dialog.plot.steps[-1] == 499 and dialog.n_reports == 500
    dialog.set_state("finished", "done")
    assert dialog.labels["step"].text() == "499"
    assert dialog.plot.draw_count >= 1
    assert dialog.message_label.text() == "done" and dialog.button.text() == "Close"


# --------------------------------------------------------------------- continue a run
def test_continue_adds_steps_to_the_same_results_file(window, qtbot, dialogs) -> None:
    from thermalfea.gui.solve_tools import CONTINUE_ID

    shell = make_shell(window, make_document("transient", steps=10, end_time=100.0))
    action = window.actions[CONTINUE_ID]
    assert not action.isEnabled()  # nothing to continue yet
    assert not shell.solve.continue_run()
    assert run_to_end(qtbot, shell) == "finished"
    path = shell.doc.results_path
    assert Results(path).n_steps == 11 and action.isEnabled()

    # the end time is reached: the run is refused, the results stay
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT) as blocker:
        assert shell.solve.continue_run()
    assert blocker.args == ["failed"] and "Set a later end time" in shell.solve.message
    assert shell.doc.results_path == path and Results(path).n_steps == 11

    shell.doc.edit("End time", lambda m: setattr(m.solution, "end_time", 160.0))
    infos: list[Any] = []
    shell.solve.progress.connect(infos.append)
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT) as blocker:
        action.trigger()
    assert blocker.args == ["finished"]
    assert [i.step for i in infos] == list(range(11, 17))
    results = Results(shell.doc.results_path)
    assert shell.doc.results_path == path and not shell.doc.results_stale
    assert results.n_steps == 17 and results.times[-1] == pytest.approx(160.0)


def test_continue_needs_a_transient_analysis(window, qtbot) -> None:
    shell = make_shell(window, make_document())
    assert run_to_end(qtbot, shell) == "finished"
    assert not shell.solve.continue_run()
    assert "transient" in window.statusBar().currentMessage()


# ------------------------------------------------------------------------------ cancel
def test_cancel_keeps_the_results_written_so_far(window, qtbot) -> None:
    shell = make_shell(
        window, make_document("transient", steps=100000, end_time=1000.0, every=1000)
    )
    infos: list[Any] = []
    shell.solve.progress.connect(infos.append)
    with qtbot.waitSignal(shell.solve.progress, timeout=WAIT):
        assert shell.solve.solve()
    assert shell.solve.cancel()
    assert not shell.solve.cancel()  # already asked
    assert shell.solve.dialog.state == "cancelling"
    assert not window.actions[CANCEL_ID].isEnabled()
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT) as blocker:
        pass
    assert blocker.args == ["cancelled"] and shell.solve.outcome == "cancelled"
    assert not shell.solve.running
    last = shell.solve.dialog.last_info
    assert last.time < last.end_time
    assert shell.solve.dialog.state == "cancelled"
    assert "cancelled at t =" in shell.solve.message
    results = Results(shell.doc.results_path)
    assert results.n_steps >= 1
    assert not shell.doc.results_stale
    assert window.actions[RUN_ID].isEnabled()


def test_dialog_cancel_button_requests_the_cancel(window, qtbot) -> None:
    shell = make_shell(
        window, make_document("transient", steps=100000, end_time=1000.0, every=1000)
    )
    with qtbot.waitSignal(shell.solve.progress, timeout=WAIT):
        assert shell.solve.solve()
    shell.solve.dialog.button.click()
    assert shell.solve.dialog.state == "cancelling"
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT):
        pass
    assert shell.solve.outcome == "cancelled"
    assert shell.solve.dialog.button.text() == "Close"


def test_cancel_reports_no_error_dialog(window, qtbot, dialogs) -> None:
    shell = make_shell(
        window, make_document("transient", steps=100000, end_time=1000.0, every=1000)
    )
    with qtbot.waitSignal(shell.solve.progress, timeout=WAIT):
        assert shell.solve.solve()
    shell.solve.cancel()
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT):
        pass
    assert dialogs.calls == []


def test_steady_finish_status_bar_has_no_time(steady, qtbot) -> None:
    """M11.8 (Q26.4 f): a steady solve is reported without "at t = 0 s"."""
    assert run_to_end(qtbot, steady) == "finished"
    message = steady.window.statusBar().currentMessage()
    assert message.startswith("Solve finished") and "1 stored step(s)" in message
    assert "t = " not in message


def test_steady_cancel_is_reported_as_cancelled(steady, qtbot) -> None:
    assert run_to_end(qtbot, steady) == "finished"
    info = steady.solve._last_info
    assert info is not None and info.time == info.end_time  # a steady run has no end to reach
    steady.solve._on_cancelled(None)  # the cancel of a steady run arrives after its last step
    assert steady.solve.outcome == "cancelled"
    assert "cancelled" in steady.solve.message and "finished" not in steady.solve.message


# ------------------------------------------------------------------------------ failure
def failing_document() -> Document:
    """Strong radiation with a single Newton iteration and a tight tolerance."""
    model, built = make_model()
    model.bcs[1] = bcs.RadiationAmbient("rad", "east", emissivity=0.9, T_inf=3.0)
    model.bcs[0].T = Constant(3000.0)
    model.solution = SolutionSettings(kind="steady", max_iterations=1, rtol=1e-14, ttol=1e-14)
    document = Document(model)
    document.set_built(built)
    document.set_mesh(api.mesh(model, built))
    return document


def test_failed_solve_reports_the_error_and_keeps_old_results(window, qtbot, dialogs) -> None:
    document = failing_document()
    shell = make_shell(window, document)
    document.set_results("old-results.h5")
    assert shell.solve.solve()
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT) as blocker:
        pass
    assert blocker.args == ["failed"] and not shell.solve.running
    assert len(dialogs.calls) == 1 and dialogs.calls[0][0] == "Solve failed"
    assert dialogs.calls[0][1] == shell.solve.message
    assert shell.solve.dialog.state == "failed"
    assert shell.solve.dialog.message_label.text() == shell.solve.message
    assert str(document.results_path) == "old-results.h5"
    assert window.actions[RUN_ID].isEnabled()
    assert isinstance(shell.solve.message, str) and shell.solve.message


def test_unexpected_exception_in_the_solver_is_reported(
    window, qtbot, dialogs, monkeypatch
) -> None:
    shell = make_shell(window, make_document())

    def boom(*_a: Any, **_k: Any) -> None:
        raise ZeroDivisionError("oops")

    monkeypatch.setattr("thermalfea.gui.solve_tools.api.solve", boom)
    assert run_to_end(qtbot, shell) == "failed"
    assert "ZeroDivisionError" in dialogs.calls[0][1] and "message log" in dialogs.calls[0][1]


# ------------------------------------------------------------------- model edited meanwhile
def test_results_are_marked_stale_when_the_model_changed_during_the_solve(window, qtbot) -> None:
    shell = make_shell(window, make_document("transient", steps=2000, end_time=200.0, every=200))
    assert shell.solve.solve()
    assert shell.solve.running
    shell.doc.edit("tweak", lambda m: setattr(m.bcs[1], "h", Constant(250.0)))  # while it runs
    assert shell.doc.results_stale
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT) as blocker:
        pass
    assert blocker.args == ["finished"]
    assert shell.doc.results_path is not None and shell.doc.results_path.exists()
    assert shell.doc.results_stale  # they belong to the earlier model
    assert "out of date" in shell.solve.message
    # the solve used its own copy: the file holds the 100 W/m2K solution
    assert Results(shell.doc.results_path).n_steps == 11


def test_results_are_discarded_when_the_document_was_replaced(window, qtbot) -> None:
    shell = make_shell(window, make_document("transient", steps=2000, end_time=200.0, every=200))
    assert shell.solve.solve()
    shell.doc.new()  # File > New while the solve runs
    with qtbot.waitSignal(shell.solve.solve_finished, timeout=WAIT) as blocker:
        pass
    assert blocker.args == ["discarded"]
    assert shell.doc.results_path is None and "discarded" in shell.solve.message


# ------------------------------------------------------------------------------ shutdown
def test_closing_the_window_cancels_the_solve_and_joins_the_thread(window, qtbot) -> None:
    shell = make_shell(
        window, make_document("transient", steps=100000, end_time=1000.0, every=1000)
    )
    with qtbot.waitSignal(shell.solve.progress, timeout=WAIT):
        assert shell.solve.solve()
    task = shell.solve._task
    started = time.monotonic()
    window.close()
    assert time.monotonic() - started < 15.0
    assert not shell.solve.running and not task.running and not task.thread_alive
    assert shell.solve.outcome == "cancelled"


def test_shutdown_without_a_solve_is_a_no_op(window) -> None:
    shell = make_shell(window, make_document())
    assert shell.solve.shutdown(100)


# ------------------------------------------------------------------- build / mesh worker
def _geometry_env(window):
    model = api.new_model(name="gm")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5)
    model.mesh_settings.global_size = 0.1
    document = Document(model)
    tree, props = attach_tree(window, document, None)
    geometry = attach_geometry_tools(window, document, None)
    mesh = attach_mesh_tools(window, document, None)
    return document, geometry, mesh


def test_gmsh_runs_only_on_the_one_worker_thread(window, qtbot, monkeypatch) -> None:
    """Build and mesh from the worker thread: all gmsh calls share one thread, GUI stays free."""
    document, geometry, mesh = _geometry_env(window)
    worker = SerialWorker(window, "test-gmsh-worker")
    geometry.worker = worker
    mesh.worker = worker
    idents: dict[str, int] = {}
    real_build, real_mesh = api.build, api.mesh

    def build(model):
        idents["build"] = threading.get_ident()
        return real_build(model)

    def make_mesh(model, built):
        idents["mesh"] = threading.get_ident()
        return real_mesh(model, built)

    monkeypatch.setattr(geometry_tools.api, "build", build)
    monkeypatch.setattr(mesh_tools.api, "mesh", make_mesh)
    try:
        with qtbot.waitSignal(geometry.rebuilt, timeout=WAIT) as built_signal:
            assert geometry.rebuild()
            assert geometry._busy  # started, not finished: the GUI thread was not blocked
        assert built_signal.args == [True]
        assert document.built is not None and not document.geometry_stale
        with qtbot.waitSignal(mesh.meshed, timeout=WAIT) as meshed_signal:
            assert mesh.generate()
        assert meshed_signal.args == [True]
        assert document.mesh is not None and not document.mesh_stale
        assert idents["build"] == idents["mesh"] != threading.get_ident()
        # a second round on the same thread (the process-wide gmsh session is reused)
        with qtbot.waitSignal(geometry.rebuilt, timeout=WAIT):
            geometry.rebuild()
        assert idents["build"] == idents["mesh"]
    finally:
        assert worker.shutdown(10000)


def test_worker_build_failure_is_reported_and_edits_during_a_build_rebuild(
    window, qtbot, dialogs
) -> None:
    document, geometry, _mesh = _geometry_env(window)
    worker = SerialWorker(window, "test-gmsh-worker2")
    geometry.worker = worker
    try:
        assert geometry.rebuild()
        assert not geometry.rebuild()  # one at a time
        # an edit that changes the geometry while the build runs: built again afterwards
        document.edit("move", lambda m: setattr(m.geometry[0], "x", 0.25))
        qtbot.waitUntil(
            lambda: not geometry._busy and document.built is not None
            and not document.geometry_stale,
            timeout=WAIT,
        )
        assert not document.geometry_stale
        # a build that fails
        document.edit("break", lambda m: setattr(m.geometry[0], "width", -1.0))
        qtbot.waitUntil(lambda: bool(dialogs.calls) and not geometry._busy, timeout=WAIT)
        assert dialogs.calls[0][0] == "Geometry build failed" and geometry.last_error
    finally:
        assert worker.shutdown(10000)


def test_worker_mesh_is_discarded_when_the_mesh_settings_change(window, qtbot) -> None:
    document, geometry, mesh = _geometry_env(window)
    assert geometry.rebuild()  # synchronous: no worker yet
    worker = SerialWorker(window, "test-gmsh-worker3")
    mesh.worker = worker
    try:
        assert mesh.generate()
        document.edit("size", lambda m: setattr(m.mesh_settings, "global_size", 0.2))
        with qtbot.waitSignal(mesh.meshed, timeout=WAIT) as blocker:
            pass
        assert blocker.args == [False] and document.mesh is None and document.mesh_stale
    finally:
        assert worker.shutdown(10000)


def test_loading_another_model_closes_the_finished_solve_dialog(steady, qtbot) -> None:
    """Seen on a real screen: the dialog of the previous model's run stayed open."""
    with qtbot.waitSignal(steady.solve.solve_finished, timeout=WAIT):
        assert steady.solve.solve()
    assert steady.solve.dialog is not None
    steady.doc.set_model(Model(), None)  # what New, Open and Examples do
    assert steady.solve.dialog is None


def test_selections_changed_after_meshing_reach_the_results(window, qtbot) -> None:
    """M11.53: a selection renamed or added after meshing gets its node set in the results
    file, without a remesh (the node sets are found again on the same mesh)."""
    from thermalfea.model.selections import rename_selection

    shell = make_shell(window, make_document())
    doc = shell.doc
    meshed = doc.mesh
    doc.edit("rename", lambda m: rename_selection(m, "east", "cooled"))
    doc.edit(
        "add",
        lambda m: api.select_curves(
            m, doc.built, "south", where=lambda c: abs(c.center[1]) < 1e-9
        ),
    )
    assert not doc.mesh_stale and doc.mesh is meshed  # no remesh needed
    assert run_to_end(qtbot, shell) == "finished"
    sets = Results(doc.results_path).mesh.node_sets
    assert {"cooled", "south", "west"} <= set(sets) and "east" not in sets
    assert set(meshed.node_sets) == {"all", "west", "east"}  # the document's mesh is untouched


# ------------------------------------------------- M11.67: initial condition vs results file
def from_results_document(tmp_path, results: str, kind: str = "transient") -> Document:
    document = make_document(kind)
    document.path = tmp_path / "plate.tfea"
    document.model.initial_condition = InitialCondition("from_results", results_path=results)
    return document


def test_ic_reading_the_results_file_of_the_solve_is_an_error(window, tmp_path) -> None:
    written = api.results_path(tmp_path / "plate.tfea")
    shell = make_shell(window, from_results_document(tmp_path, str(written)))
    found = shell.solve.validate()
    hits = [i for i in found if i.code == "ic_results_overwrite"]
    assert len(hits) == 1 and hits[0].severity == "error"
    assert written.name in hits[0].message
    assert address_for_issue(shell.doc.model, hits[0]) == ("initial_condition",)
    assert not shell.solve.solve()
    assert not shell.solve.running


def test_ic_reading_another_file_is_no_conflict(window, tmp_path) -> None:
    other = tmp_path / "steady.tfea.h5"
    shell = make_shell(window, from_results_document(tmp_path, str(other)))
    found = shell.solve.validate()
    assert "ic_results_overwrite" not in {i.code for i in found}


def test_initial_condition_conflict_cases(tmp_path, monkeypatch) -> None:
    written = str(api.results_path(tmp_path / "plate.tfea"))
    steady_doc = from_results_document(tmp_path, written, kind="steady")
    assert initial_condition_conflict(steady_doc) is None
    no_path = from_results_document(tmp_path, written)
    no_path.path = None
    assert initial_condition_conflict(no_path) is None
    monkeypatch.chdir(tmp_path)
    relative = from_results_document(tmp_path, "plate.tfea.h5")
    message = initial_condition_conflict(relative)
    assert message is not None and "'plate.tfea.h5'" in message
    assert "File > Save As" in message
