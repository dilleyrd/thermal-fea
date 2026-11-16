"""Mesh generation in the GUI (Plan M8.7): the Mesh menu entry and the generate controller.

:class:`MeshController` has one entry point, :meth:`MeshController.generate`. It is
synchronous for now (a later task moves it to a worker thread). :func:`attach_mesh_tools`
adds the action ``mesh.generate`` ("Generate mesh") to the Mesh menu; it is enabled only when
a current built geometry exists.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from thermalfea import api
from thermalfea.core.errors import ThermalFEAError
from thermalfea.gui.document import Document
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.scene import SceneView

_log = logging.getLogger(__name__)

ACTION_ID = "mesh.generate"


def can_generate(document: Document) -> bool:
    """True when a current built geometry exists (meshing needs one)."""
    return document.built is not None and not document.geometry_stale


class MeshController(QObject):
    """Owns the mesh generation of one window and document.

    Parameters
    ----------
    window : MainWindow
        Its Mesh menu receives the action; errors are shown through its error dialog.
    document : Document
    view : SceneView, optional
        The viewport; kept for the panels that colour the mesh (not used for meshing).

    Attributes
    ----------
    action : QAction
        The Mesh menu entry ``mesh.generate``.
    view : SceneView or None
    """

    def __init__(
        self, window: MainWindow, document: Document, view: SceneView | None = None
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.view = view
        self._busy = False
        self.action = QAction("Generate mesh", window)
        self.action.triggered.connect(lambda _checked=False: self.generate())
        window.actions[ACTION_ID] = self.action
        window.menus["mesh"].addAction(self.action)
        document.stale_changed.connect(self.update_action)
        document.geometry_built.connect(self.update_action)
        self.update_action()

    def update_action(self) -> None:
        """Enable the Mesh menu entry only when a current built geometry exists."""
        self.action.setEnabled(can_generate(self.document))

    def generate(self) -> bool:
        """Mesh the document's built geometry with its mesh settings and store the mesh.

        Refuses (with a status-bar message) when there is no built geometry or the geometry
        is stale. A meshing failure is logged, shown through ``window.show_error`` and leaves
        the previous mesh in place. A call made while one is running is ignored.

        Returns
        -------
        bool
            ``True`` if a new mesh was stored.
        """
        if self._busy:
            return False
        built = self.document.built
        if built is None:
            self.window.statusBar().showMessage("Build the geometry before meshing", 5000)
            return False
        if self.document.geometry_stale:
            self.window.statusBar().showMessage("Rebuild the geometry before meshing", 5000)
            return False
        self._busy = True
        try:
            mesh = api.mesh(self.document.model, built)
        except ThermalFEAError as exc:
            _log.error("Meshing failed: %s", exc)
            self.window.statusBar().showMessage("Meshing failed", 5000)
            self.window.show_error("Meshing failed", str(exc))
            return False
        finally:
            self._busy = False
        self.document.set_mesh(mesh)
        self.window.statusBar().showMessage(
            f"Mesh generated: {mesh.n_nodes} nodes, {mesh.n_elements} elements", 3000
        )
        return True


def attach_mesh_tools(
    window: MainWindow, document: Document, view: SceneView | None = None
) -> MeshController:
    """Install the mesh generation in a main window.

    Parameters
    ----------
    window : MainWindow
    document : Document
    view : SceneView, optional
        The viewport.

    Returns
    -------
    MeshController
    """
    return MeshController(window, document, view)
