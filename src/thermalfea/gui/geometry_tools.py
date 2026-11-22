"""Geometry tools of the GUI (Plan M8.5): the Geometry menu, dialogs and automatic rebuild.

:class:`GeometryController` is installed by :func:`attach_geometry_tools`. It

* fills the Geometry menu (action ids ``geometry.<tool>``, see
  :data:`thermalfea.gui.geometry_defs.TOOLS`, plus ``geometry.snap`` and
  ``geometry.rebuild``) and opens a non-modal :class:`GeometryOpDialog` per tool;
* follows the viewport selection and enables the selection-based tools (booleans,
  transforms, delete) only when it holds operations they can act on;
* rebuilds the geometry after every change of the geometry operations (:meth:`rebuild`).

Selection rule
--------------
The viewport reports gmsh entity tags. They are mapped back to operation ids with
:func:`thermalfea.model.geometry_edit.ops_for_entities` (the latest owner of every selected
entity). For Union, Cut and Intersect the *earliest* selected operation (history order) is
the object and the other selected operations are the tools; with only one operation
selected the tools stay empty until more shapes are selected and the dialog's
``Selection`` button is pressed. Transforms and Delete take every selected operation as a
target.

Rebuilding
----------
:meth:`rebuild` runs ``api.build`` on a copy of the model and hands the result to
:meth:`Document.set_built` (the worker-ready path: the document adopts the refreshed
selections). A failed build (``GeometryError``/``ModelError``) is logged, shown through
``window.show_error`` and the status bar; the old build stays, the geometry stays stale and
the offending operation stays in the history, so the user can edit or undo it. The same
broken geometry is not rebuilt again by unrelated edits.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QWidget

from thermalfea import api
from thermalfea.core.errors import ThermalFEAError
from thermalfea.gui.dialogs.geometry import GeometryOpDialog
from thermalfea.gui.document import Document
from thermalfea.gui.geometry_defs import TOOLS, ToolDef
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.scene import SceneView
from thermalfea.gui.tree import ModelTree
from thermalfea.gui.worker import BackgroundTask, SerialWorker
from thermalfea.model import geometry_edit as edit
from thermalfea.model.serialize import from_json, to_json

_log = logging.getLogger(__name__)

_SURFACE_DIM = 2
#: Menu layout: groups separated by a separator.
_MENU_GROUPS: tuple[tuple[str, ...], ...] = (
    ("point", "line", "arc", "spline", "rectangle", "circle", "polygon", "surface"),
    ("union", "cut", "intersect"),
    ("translate", "rotate", "mirror", "scale", "delete"),
    ("import",),
)


def _default_file_chooser(parent: QWidget | None) -> str | None:
    path, _ = QFileDialog.getOpenFileName(
        parent,
        "Import STEP/BREP/DXF",
        "",
        "CAD files (*.step *.stp *.brep *.dxf);;All files (*)",
    )
    return path or None


class GeometryController(QObject):
    """Owns the geometry tools of one window and document.

    Parameters
    ----------
    window : MainWindow
        Its Geometry menu receives the actions; its error dialog reports failures.
    document : Document
    view : SceneView, optional
        The viewport (``selection_changed`` and ``point_picked``).

    Signals
    -------
    rebuilt(bool)
        A rebuild finished (``True``) or failed (``False``).
    snap_changed()
        The grid snap settings changed.
    selection_changed()
        The viewport selection (and so the enabled tools) changed.

    Attributes
    ----------
    auto_rebuild : bool
        Rebuild after a change of the geometry operations; tests may switch it off.
    snap : GridSnap
    file_chooser : callable
        ``file_chooser(parent) -> path or None``; replaced in tests (never modal there).
    selection : tuple of (int, list of int)
        The viewport selection ``(dim, tags)``.
    last_error : str
        Message of the last failed rebuild ("" after a successful one).
    active_dialog : GeometryOpDialog or None
    tree : ModelTree or None
    worker : SerialWorker or None
        When set, builds run on this long-lived thread (the application sets it; see
        :meth:`rebuild`). ``None`` (the default) builds synchronously.
    """

    rebuilt = Signal(bool)
    snap_changed = Signal()
    selection_changed = Signal()

    def __init__(
        self, window: MainWindow, document: Document, view: SceneView | None = None
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.view = view
        self.tree: ModelTree | None = None
        self.auto_rebuild = True
        self.snap = edit.GridSnap()
        self.file_chooser: Callable[[QWidget | None], str | None] = _default_file_chooser
        self.selection: tuple[int, list[int]] = (_SURFACE_DIM, [])
        self.last_error = ""
        self.active_dialog: GeometryOpDialog | None = None
        self.worker: SerialWorker | None = None
        self._task: BackgroundTask | None = None
        self._busy = False
        self._failed_geometry: str | None = None
        self.actions: dict[str, QAction] = {}

        self._build_actions()
        document.model_changed.connect(self._on_model_changed)
        document.geometry_built.connect(self._on_geometry_built)
        if view is not None:
            view.selection_changed.connect(self._on_selection_changed)
        self.update_actions()

    # ---------------------------------------------------------------------- actions
    def _build_actions(self) -> None:
        menu = self.window.menus["geometry"]
        for group in _MENU_GROUPS:
            for key in group:
                tool = TOOLS[key]
                action = QAction(f"{tool.title}...", self.window)
                action.triggered.connect(lambda _c=False, k=key: self._trigger(k))
                self.window.actions[f"geometry.{key}"] = action
                self.actions[key] = action
                menu.addAction(action)
            menu.addSeparator()
        snap = QAction("Snap to grid", self.window)
        snap.setCheckable(True)
        snap.toggled.connect(lambda on: self.set_snap(enabled=bool(on)))
        rebuild = QAction("Rebuild geometry", self.window)
        rebuild.triggered.connect(lambda _c=False: self.rebuild())
        for key, action in (("snap", snap), ("rebuild", rebuild)):
            self.window.actions[f"geometry.{key}"] = action
            self.actions[key] = action
            menu.addAction(action)

    def _trigger(self, key: str) -> None:
        if key == "import":
            self.import_file()
        else:
            self.open_tool(key)

    def update_actions(self) -> None:
        """Enable the selection-based tools only when the selection suits them."""
        for key, tool in TOOLS.items():
            action = self.actions.get(key)
            if action is not None and tool.selection is not None:
                action.setEnabled(bool(self.selected_ops(self._allowed(tool))))

    @staticmethod
    def _allowed(tool: ToolDef) -> tuple[type, ...]:
        return edit.SURFACE_OPS if tool.selection == "boolean" else edit.ANY_OPS

    # -------------------------------------------------------------------- selection
    def _on_selection_changed(self, dim: int, tags: list[int]) -> None:
        self.selection = (int(dim), [int(t) for t in tags])
        self.update_actions()
        self.selection_changed.emit()

    def _on_geometry_built(self) -> None:
        self.selection = (self.selection[0], [])  # tags belong to the previous build
        self.update_actions()
        self.selection_changed.emit()

    def selected_ops(self, allowed: tuple[type, ...] | None = None) -> list[str]:
        """Operation ids owning the selected entities, in history order.

        Parameters
        ----------
        allowed : tuple of type, optional
            Only operations of these classes.
        """
        built = self.document.built
        dim, tags = self.selection
        if built is None or not tags:
            return []
        geometry = self.document.model.geometry
        ids = None if allowed is None else edit.candidate_ids(geometry, allowed)
        return edit.ops_for_entities(
            [op.id for op in geometry], built.op_entities, dim, tags, ids
        )

    # ------------------------------------------------------------------------ snap
    def set_snap(self, enabled: bool | None = None, spacing: float | None = None) -> None:
        """Change the grid snap (enabled flag and/or spacing in metres)."""
        if spacing is not None:
            self.snap = edit.GridSnap(spacing, self.snap.enabled)
        if enabled is not None:
            self.snap.enabled = enabled
        action = self.actions["snap"]
        if action.isChecked() != self.snap.enabled:
            action.blockSignals(True)
            action.setChecked(self.snap.enabled)
            action.blockSignals(False)
        self.snap_changed.emit()

    # ----------------------------------------------------------------------- tools
    def open_tool(self, key: str, preset: dict[str, Any] | None = None) -> GeometryOpDialog:
        """Open the (non-modal) dialog of a tool, prefilled from the selection.

        Parameters
        ----------
        key : str
            A key of :data:`thermalfea.gui.geometry_defs.TOOLS`.
        preset : dict, optional
            Field values (SI) that override the selection.
        """
        tool = TOOLS[key]
        values = self._selection_preset(tool)
        values.update(preset or {})
        if self.active_dialog is not None:
            self.active_dialog.close()
        dialog = GeometryOpDialog(self, tool, values, self.window)
        self.active_dialog = dialog
        dialog.finished.connect(lambda _r, d=dialog: self._dialog_closed(d))
        dialog.show()
        return dialog

    def _dialog_closed(self, dialog: GeometryOpDialog) -> None:
        if self.active_dialog is dialog:
            self.active_dialog = None

    def _selection_preset(self, tool: ToolDef) -> dict[str, Any]:
        if tool.selection is None:
            return {}
        ids = self.selected_ops(self._allowed(tool))
        if tool.selection == "boolean":
            return {"objects": ids[:1], "tools": ids[1:]}
        return {"targets": ids}

    def import_file(self) -> GeometryOpDialog | None:
        """Ask for a STEP/BREP/DXF file and open the import dialog for it.

        Returns
        -------
        GeometryOpDialog or None
            ``None`` if the chooser was cancelled or the file type is unknown (the
            latter is reported through the window's error dialog).
        """
        path = self.file_chooser(self.window)
        if not path:
            return None
        fmt = edit.import_format(path)
        if fmt is None:
            self.window.show_error(
                "Import", f"Cannot tell the format of {path}; use .step, .stp, .brep or .dxf."
            )
            return None
        return self.open_tool("import", {"path": path, "format": fmt})

    def add_operation(
        self, tool: ToolDef, values: dict[str, Any], op_id: str | None = None
    ) -> str:
        """Append an operation like a script would (one undo step); return its id.

        Raises
        ------
        ModelError
            If the id is taken or the values are invalid.
        """
        holder: list[str] = []

        def mutate(model: Any) -> None:
            holder.append(tool.add(api.Geometry(model), dict(values), op_id))

        self.document.edit(f"Add {tool.title}", mutate)
        return holder[0]

    # --------------------------------------------------------------------- rebuild
    def _on_model_changed(self) -> None:
        if not self.auto_rebuild or not self.document.geometry_stale:
            return
        if self._geometry_text() == self._failed_geometry:
            return  # the same broken geometry; do not report it again
        self.rebuild()

    def _geometry_text(self) -> str:
        return json.dumps(to_json(self.document.model)["geometry"], sort_keys=True)

    def rebuild(self) -> bool:
        """Build the geometry of the document's model and store it.

        The single entry point of geometry builds. Runs on a copy of the model and ignores
        a call made while one is running.

        Without a :attr:`worker` the build is synchronous and the return value says whether
        it succeeded and was stored. With a worker the build runs on its thread: the method
        returns ``True`` as soon as the build was started, and :attr:`rebuilt` reports the
        end (``True`` stored, ``False`` failed). A call made while a build runs is ignored;
        when the build ends and the geometry operations changed meanwhile, the build is
        repeated (the document marks the stored build stale, see
        :meth:`Document.set_built`).

        Returns
        -------
        bool
            ``True`` if the build succeeded and was stored (synchronous) or was started
            (worker).
        """
        if self._busy:
            return False
        if self.worker is not None:
            return self._rebuild_async(self.worker)
        self._busy = True
        try:
            text = self._geometry_text()
            working = from_json(to_json(self.document.model))
            try:
                built = api.build(working)
            except ThermalFEAError as exc:
                self._fail(str(exc), text)
                return False
            self._failed_geometry = None
            self.last_error = ""
            self.document.set_built(built, working)
            self.window.statusBar().showMessage("Geometry rebuilt", 3000)
        finally:
            self._busy = False
        self.rebuilt.emit(True)
        return True

    def _rebuild_async(self, worker: SerialWorker) -> bool:
        text = self._geometry_text()
        working = from_json(to_json(self.document.model))
        task = BackgroundTask(
            lambda _context: api.build(working), self, executor=worker, name="Geometry build"
        )
        stamp = (self.document.generation, self.document.selection_revision)
        task.finished.connect(lambda built: self._async_built(built, working, stamp))
        task.failed.connect(lambda exc: self._async_failed(exc, text, stamp))
        self._task = task
        self._busy = True
        task.start()
        self.window.statusBar().showMessage("Building geometry...", 0)
        return True

    def _async_built(
        self, built: Any, working: Any, stamp: tuple[int, int] | None = None
    ) -> None:
        self._busy = False
        self._task = None
        if stamp is not None and stamp != (
            self.document.generation, self.document.selection_revision
        ):
            # another model was opened, or the selections were edited, while the build
            # ran: its products (and resolved selection tags) must not be attached
            self.rebuilt.emit(False)
            if self.auto_rebuild:
                self.rebuild()
            return
        self._failed_geometry = None
        self.last_error = ""
        self.document.set_built(built, working)
        self.window.statusBar().showMessage("Geometry rebuilt", 3000)
        self.rebuilt.emit(True)
        if self.auto_rebuild and self.document.geometry_stale:
            self.rebuild()  # the operations changed while the build ran

    def _async_failed(
        self, exc: Any, geometry_text: str, stamp: tuple[int, int] | None = None
    ) -> None:
        self._busy = False
        self._task = None
        if stamp is not None and stamp[0] != self.document.generation:
            # the failure belongs to a model that was replaced: report nothing
            if self.auto_rebuild:
                self.rebuild()
            return
        message = str(exc) if isinstance(exc, ThermalFEAError) else f"Unexpected error: {exc}"
        self._fail(message, geometry_text)
        # an edit made while the failing build ran was ignored by _on_model_changed
        if (
            self.auto_rebuild
            and self.document.geometry_stale
            and self._geometry_text() != geometry_text
        ):
            self.rebuild()

    def _fail(self, message: str, geometry_text: str) -> None:
        _log.error("Geometry build failed: %s", message)
        self._failed_geometry = geometry_text
        self.last_error = message
        self.window.statusBar().showMessage("Geometry build failed", 5000)
        self.window.show_error("Geometry build failed", message)
        self.rebuilt.emit(False)

    # ------------------------------------------------------------------ history UI
    def show_properties(self, _address: object = None) -> None:
        """Bring the property dock to the front (after "Edit" in the tree)."""
        dock = self.window.properties_dock
        dock.show()
        dock.raise_()


def attach_geometry_tools(
    window: MainWindow, document: Document, view: SceneView | None = None
) -> GeometryController:
    """Install the geometry tools in a main window.

    Parameters
    ----------
    window : MainWindow
        Its Geometry menu is filled; if its tree is a :class:`ModelTree`, the tree's
        "Edit" action brings up the property dock.
    document : Document
    view : SceneView, optional
        The viewport; without one there is no click-to-place and no selection.

    Returns
    -------
    GeometryController
    """
    controller = GeometryController(window, document, view)
    tree = window.tree_widget
    if isinstance(tree, ModelTree):
        controller.tree = tree
        tree.edit_requested.connect(controller.show_properties)
    return controller
