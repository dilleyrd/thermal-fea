"""Solving in the GUI (Plan M8.9): validate, solve in a worker thread, progress and cancel.

:class:`SolveController` owns the Solve menu actions ``solve.validate``, ``solve.run`` and
``solve.cancel``, the issue list and the progress dialog of one window and document.
:func:`attach_solve` installs all of it.

Flow of :meth:`SolveController.solve`
-------------------------------------
1. Refuse (status-bar message) without a current mesh, or while a solve runs.
2. Validate; errors fill the issue list (and show its dock) and stop here.
3. Copy the model (``from_json(to_json(model))``) and start a
   :class:`~thermalfea.gui.worker.BackgroundTask` that calls :func:`thermalfea.api.solve`
   on the copy with the document's mesh and build (read-only). The task never touches the
   document or any widget; its progress callback is ``context.report``, which returns
   ``False`` after :meth:`cancel`.
4. Progress reports arrive in the GUI thread and go to the :class:`SolveProgressDialog`
   (which throttles its redraws).
5. The terminal signal is handled in the GUI thread (see below).

Outcomes
--------
finished
    ``document.set_results(path)``; the dialog shows "Finished" and stays open (the user
    closes it; its residual chart is worth a look), the status bar reports the run.
cancelled
    The steps written before the cancel are a valid, readable file: ``set_results`` stores
    it and the status bar says "cancelled at t = ... s". A cancel that arrives after the
    last step is reported as finished. If no step was written the old results are kept.
failed
    ``ConvergenceError``, ``SolverError``, ``ModelError`` (or any other exception): the
    message is shown in the dialog (which stays open) and through ``window.show_error``;
    the document's old results are untouched.

Results and a model that changed during the run
-----------------------------------------------
The task works on a copy, so edits made while it runs cannot race with it. When it ends the
document's model is compared with the copy's JSON (:func:`~thermalfea.gui.document.classify_change`,
which ignores selection tags). If they differ the results belong to an earlier model: the
path is stored, but with ``Document.set_results(path, stale=True)`` so ``results_stale``
stays ``True``. If the document's mesh or build object is no longer the one that was solved
(a new document was opened, the geometry was rebuilt), the results are discarded (the file
stays on disk) and a status message says so.

Closing the window
------------------
An event filter on the window cancels a running solve and joins its thread (bounded) when
the window closes; :meth:`SolveController.shutdown` does the same on demand.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QDockWidget, QWidget

from thermalfea import api
from thermalfea.core.errors import ThermalFEAError
from thermalfea.gui.dialogs.solve_progress import SolveProgressDialog
from thermalfea.gui.document import Document, classify_change
from thermalfea.gui.issues import IssuePanel
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.scene import SceneView
from thermalfea.gui.tree import ModelTree
from thermalfea.gui.worker import JOIN_TIMEOUT_MS, BackgroundTask, TaskContext
from thermalfea.meshing.node_sets import node_sets_of
from thermalfea.model.serialize import from_json, to_json
from thermalfea.model.validate import Issue, errors, validate
from thermalfea.post.results import Results
from thermalfea.solver.run import StepInfo

_log = logging.getLogger(__name__)

VALIDATE_ID = "solve.validate"
RUN_ID = "solve.run"
CANCEL_ID = "solve.cancel"
CONTINUE_ID = "solve.continue"
#: Relative tolerance of "the run had reached the end time".
_END_TOL = 1e-9

DialogFactory = Callable[[bool, "QWidget | None"], SolveProgressDialog]


def can_solve(document: Document) -> bool:
    """True when a current mesh (and so a current geometry) exists."""
    return (
        document.built is not None
        and document.mesh is not None
        and not document.geometry_stale
        and not document.mesh_stale
    )


def initial_condition_conflict(document: Document) -> str | None:
    """Message if the solve would overwrite the results file its initial condition reads.

    Parameters
    ----------
    document : Document

    Returns
    -------
    str or None
        The error message, or ``None`` when there is no conflict. A conflict is a
        transient analysis whose initial condition is read from the very file the solve
        writes (``api.results_path`` of the model file).
    """
    model = document.model
    ic = model.initial_condition
    if (
        model.solution.kind != "transient"
        or ic.kind != "from_results"
        or not ic.results_path
        or document.path is None
    ):
        return None
    written = api.results_path(document.path)
    if os.path.normcase(str(Path(ic.results_path).resolve())) != os.path.normcase(
        str(Path(written).resolve())
    ):
        return None
    return (
        f"The initial condition reads '{Path(ic.results_path).name}', the results file "
        "this solve writes; save the model under another name (File > Save As) before "
        "solving."
    )


def _default_dialog(transient: bool, parent: QWidget | None) -> SolveProgressDialog:
    return SolveProgressDialog(transient, parent)


class SolveController(QObject):
    """Validation and solving for one window and document.

    Parameters
    ----------
    window : MainWindow
        Its Solve menu receives the actions; errors go through ``window.show_error``.
    document : Document
    issues : IssuePanel, optional
        The issue list that validation fills.
    view : SceneView, optional
        Kept for later result display (not used for solving).

    Signals
    -------
    state_changed()
        A solve started or ended (read :attr:`running`).
    solve_finished(str)
        A solve ended; the argument is :attr:`outcome`.
    progress(object)
        A :class:`~thermalfea.solver.run.StepInfo` arrived (after the dialog got it).

    Attributes
    ----------
    running : bool
        ``True`` from :meth:`solve` until the end of the run is handled.
    outcome : str
        ``""`` before any run, then ``"finished"``, ``"cancelled"``, ``"failed"`` or
        ``"discarded"`` (finished, but the document no longer matches).
    message : str
        Text of the last outcome (also shown in the status bar or the dialog).
    dialog : SolveProgressDialog or None
        The dialog of the latest run.
    dialog_factory : callable
        ``factory(transient, parent) -> SolveProgressDialog``; replaceable in tests.
    show_progress : bool
        Show the dialog (with ``show()``, never ``exec()``); tests may switch it off.
    last_issues : list of Issue
        Result of the latest validation.
    """

    state_changed = Signal()
    solve_finished = Signal(str)
    progress = Signal(object)

    def __init__(
        self,
        window: MainWindow,
        document: Document,
        issues: IssuePanel | None = None,
        view: SceneView | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.issues = issues
        self.view = view
        self.running = False
        self.outcome = ""
        self.message = ""
        self.dialog: SolveProgressDialog | None = None
        self.dialog_factory: DialogFactory = _default_dialog
        self.show_progress = True
        self.last_issues: list[Issue] = []
        self.issues_dock: QDockWidget | None = None
        self._task: BackgroundTask | None = None
        self._mesh: Any = None
        self._built: Any = None
        self._snapshot: dict[str, Any] = {}
        self._last_info: StepInfo | None = None
        self._transient = False  # the analysis of the current run (set when it starts)

        self.actions: dict[str, QAction] = {}
        menu = window.menus["solve"]
        for key, text, slot in (
            (VALIDATE_ID, "Validate", self.validate),
            (RUN_ID, "Solve", self.solve),
            (CONTINUE_ID, "Continue transient run", self.continue_run),
            (CANCEL_ID, "Cancel solve", self.cancel),
        ):
            action = QAction(text, window)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            window.actions[key] = action
            self.actions[key] = action
            menu.addAction(action)
        for signal in (document.mesh_changed, document.geometry_built, document.stale_changed,
                       document.results_changed):
            signal.connect(self.update_actions)
        self.state_changed.connect(self.update_actions)
        self._generation = document.generation
        document.results_changed.connect(self._on_document_replaced)
        window.installEventFilter(self)
        self.update_actions()

    def _on_document_replaced(self) -> None:
        """Close a finished solve's dialog when another model is loaded (New, Open, Example).

        Its text and residual plot describe the previous model's run.
        """
        if self.document.generation == self._generation:
            return
        self._generation = self.document.generation
        if self.dialog is not None and not self.running:
            self.dialog.close()
            self.dialog.deleteLater()
            self.dialog = None

    # ----------------------------------------------------------------- state
    def can_solve(self) -> bool:
        """True when a solve could start now (a current mesh and none running)."""
        return not self.running and can_solve(self.document)

    def update_actions(self) -> None:
        """Set the enabled state of the Solve menu actions."""
        self.actions[VALIDATE_ID].setEnabled(True)
        self.actions[RUN_ID].setEnabled(self.can_solve())
        self.actions[CONTINUE_ID].setEnabled(
            self.can_solve() and self.document.results_path is not None
        )
        self.actions[CANCEL_ID].setEnabled(self.running and not self._cancel_requested())

    def _cancel_requested(self) -> bool:
        return self._task is not None and self._task.cancel_requested

    def _status(self, text: str, timeout_ms: int = 5000) -> None:
        self.window.statusBar().showMessage(text, timeout_ms)

    # -------------------------------------------------------------- validation
    def validate(self) -> list[Issue] | None:
        """Validate the model and show the findings in the issue list.

        Needs a current built geometry; without one a status message says so and ``None``
        is returned. The mesh is passed on when it is current.

        Returns
        -------
        list of Issue or None
        """
        document = self.document
        if document.built is None:
            self._status("Build the geometry before validating")
            return None
        if document.geometry_stale:
            self._status("Rebuild the geometry before validating")
            return None
        mesh = document.mesh if not document.mesh_stale else None
        try:
            found = validate(document.model, document.built, mesh)
        except ThermalFEAError as exc:
            _log.error("Validation failed: %s", exc)
            self.window.show_error("Validation failed", str(exc))
            return None
        conflict = initial_condition_conflict(document)
        if conflict is not None:
            found = [
                *found,
                Issue("error", "ic_results_overwrite", conflict, "model", "initial condition"),
            ]
        self.last_issues = found
        if self.issues is not None:
            self.issues.set_issues(found)
            if found and self.issues_dock is not None:
                self.issues_dock.show()
                self.issues_dock.raise_()
        n_err = len(errors(found))
        n_warn = len(found) - n_err
        self._status(
            "Validation: no issues" if not found
            else f"Validation: {n_err} error(s), {n_warn} warning(s)"
        )
        return found

    # ------------------------------------------------------------------- solve
    def continue_run(self) -> bool:
        """Continue the transient run of the current results to the end time of the model.

        The new steps are added to the results file (task M10.6). Returns ``True`` if
        the run was started; a run that cannot be continued (the end time is already
        reached, another mesh, ...) ends as a failed solve with the reason, and the
        results stay as they were.
        """
        return self.solve(restart=True)

    def solve(self, restart: bool = False) -> bool:
        """Validate, then solve in a worker thread.

        Parameters
        ----------
        restart : bool
            Continue the transient run stored in the current results file instead of
            starting again.

        Returns
        -------
        bool
            ``True`` if a solve was started; the outcome arrives through
            :attr:`solve_finished` (and ``document.results_changed`` on success).
        """
        if self.running:
            return False
        document = self.document
        if restart and (document.results_path is None or not document.results_path.is_file()):
            self._status("There are no results to continue; use Solve")
            return False
        if restart and document.model.solution.kind != "transient":
            self._status("Only a transient analysis can be continued")
            return False
        if document.built is None or document.mesh is None:
            self._status("Generate the mesh before solving")
            return False
        if document.geometry_stale or document.mesh_stale:
            self._status("The mesh is out of date; regenerate it before solving")
            return False
        found = self.validate()
        if found is None:
            return False
        if errors(found):
            self._status(f"Not solved: the model has {len(errors(found))} error(s)")
            return False

        model = from_json(to_json(document.model))
        self._snapshot = to_json(document.model)
        self._mesh, self._built = document.mesh, document.built
        if restart:
            path = document.results_path
        else:
            path = api.results_path(document.path) if document.path is not None else None
        built = document.built
        # selections added, renamed or redefined since meshing need their node sets in the
        # results file; they are found again on the same mesh (the mesh itself is unchanged)
        mesh = dataclasses.replace(
            document.mesh, node_sets=node_sets_of(document.mesh, model, built)
        )

        def work(context: TaskContext) -> Results:
            return api.solve(model, mesh, context.report, built=built, path=path, restart=restart)

        self._transient = model.solution.kind == "transient"
        self._open_dialog(self._transient)
        self._last_info = None
        self.outcome = ""
        self.message = ""
        task = BackgroundTask(work, self, name="Solve")
        task.progress.connect(self._on_progress)
        task.finished.connect(self._on_finished)
        task.cancelled.connect(self._on_cancelled)
        task.failed.connect(self._on_failed)
        self._task = task
        self.running = True
        task.start()
        self.state_changed.emit()
        self._status("Solving...", 0)
        return True

    def cancel(self) -> bool:
        """Ask a running solve to stop after its current step.

        Returns
        -------
        bool
            ``True`` if a running solve was asked to stop.
        """
        if not self.running or self._task is None or self._task.cancel_requested:
            return False
        self._task.cancel()
        if self.dialog is not None:
            self.dialog.set_state("cancelling")
        self._status("Cancelling the solve...", 0)
        self.update_actions()
        return True

    def shutdown(self, timeout_ms: int = JOIN_TIMEOUT_MS) -> bool:
        """Cancel a running solve and wait (bounded) for its thread.

        Returns
        -------
        bool
            ``True`` if no solve is running afterwards.
        """
        task = self._task
        if task is None:
            return True
        ended = task.shutdown(timeout_ms)
        if not ended:
            _log.error("the solve thread did not end within %d ms", timeout_ms)
        return ended

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        """Cancel and join a running solve when the main window closes."""
        if obj is self.window and event.type() == QEvent.Type.Close and self.running:
            self.shutdown()
        return False

    # ------------------------------------------------------------------ dialog
    def _open_dialog(self, transient: bool) -> None:
        if self.dialog is not None:
            self.dialog.close()
            self.dialog.deleteLater()
        dialog = self.dialog_factory(transient, self.window)
        dialog.cancel_requested.connect(self.cancel)
        self.dialog = dialog
        if self.show_progress:
            dialog.show()

    # ---------------------------------------------------------------- progress
    def _on_progress(self, info: object) -> None:
        if isinstance(info, StepInfo):
            self._last_info = info
            if self.dialog is not None:
                self.dialog.update_info(info)
        self.progress.emit(info)

    def _end(self, outcome: str, message: str) -> None:
        self.running = False
        self.outcome = outcome
        self.message = message
        self._task = None

    def _store(self, results: Results | None) -> bool:
        """Hand results to the document unless it no longer matches; return ``True`` if kept."""
        document = self.document
        if results is None or not results.path.is_file():
            return False
        if document.mesh is not self._mesh or document.built is not self._built:
            return False
        stale = classify_change(self._snapshot, to_json(document.model)) != "none"
        document.set_results(results.path, stale=stale)
        return True

    def _on_finished(self, results: object) -> None:
        self._complete(results, cancelled=False)

    def _on_cancelled(self, results: object) -> None:
        info = self._last_info
        # A steady run has no end time to reach (its StepInfo.end_time equals its time), so a
        # cancel of a steady run is always a cancel.
        reached_end = (
            self._transient
            and info is not None
            and info.time >= info.end_time * (1.0 - _END_TOL)
        )
        self._complete(results, cancelled=not reached_end)

    def _complete(self, results: object, cancelled: bool) -> None:
        run = results if isinstance(results, Results) else None
        info = self._last_info
        n_steps = _n_steps(run)
        if cancelled and n_steps < 1:
            run = None
        # a steady run has no time to report (its one step is "steady state", not t = 0 s)
        at = f" at t = {info.time:.6g} s" if info is not None and self._transient else ""
        if cancelled:
            text = (
                f"Solve cancelled{at}; the {n_steps} step(s) written so far were kept"
                if run is not None else f"Solve cancelled{at}; no results were written"
            )
            outcome, state = "cancelled", "cancelled"
        else:
            text = f"Solve finished{at}: {n_steps} stored step(s)"
            outcome, state = "finished", "finished"
        kept = self._store(run)
        if run is not None and not kept:
            outcome = "discarded"
            text += "; the document changed, so the results were discarded"
        elif kept and self.document.results_stale:
            text += "; the model changed meanwhile, so the results are marked out of date"
        if kept:
            text += f" ({run.path})"  # type: ignore[union-attr]
        if self.dialog is not None:
            self.dialog.set_state(state, text)
        self._end(outcome, text)
        _log.info("%s", text)
        self._status(text, 8000)
        self.state_changed.emit()
        self.solve_finished.emit(outcome)

    def _on_failed(self, exc: object) -> None:
        if isinstance(exc, ThermalFEAError):
            text = str(exc)
        else:
            text = f"Unexpected error: {type(exc).__name__}: {exc} (see the message log)"
        if self.dialog is not None:
            self.dialog.set_state("failed", text)
        self._end("failed", text)
        self._status("Solve failed", 8000)
        self.state_changed.emit()
        self.window.show_error("Solve failed", text)
        self.solve_finished.emit("failed")


def _n_steps(results: Results | None) -> int:
    """Stored steps of a results file (0 if there is none or it cannot be read)."""
    if results is None:
        return 0
    try:
        return int(results.n_steps)
    except ThermalFEAError:
        return 0
    except OSError:
        return 0


def attach_solve(
    window: MainWindow, document: Document, view: SceneView | None = None
) -> SolveController:
    """Install validation and solving in a main window.

    Creates the "Issues" dock (tabified with the Messages dock) and the Solve menu actions.
    Call it after :func:`~thermalfea.gui.panels.attach_tree`.

    Parameters
    ----------
    window : MainWindow
    document : Document
    view : SceneView, optional

    Returns
    -------
    SolveController
    """
    tree = window.tree_widget
    if not isinstance(tree, ModelTree):
        raise RuntimeError("attach_solve needs the model tree: call attach_tree first")
    panel = IssuePanel(tree)
    dock = QDockWidget("Issues", window)
    dock.setObjectName("IssuesDock")
    dock.setWidget(panel)
    window.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, dock)
    window.tabifyDockWidget(window.messages_dock, dock)
    window.issues_dock = dock  # type: ignore[attr-defined]
    window.actions["view.dock.issues"] = dock.toggleViewAction()
    window.menus["view"].addAction(window.actions["view.dock.issues"])
    controller = SolveController(window, document, panel, view)
    controller.issues_dock = dock
    panel.activated_address.connect(lambda _address: _show_properties(window))
    return controller


def _show_properties(window: MainWindow) -> None:
    window.properties_dock.show()
    window.properties_dock.raise_()
