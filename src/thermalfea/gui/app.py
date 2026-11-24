"""Application bootstrap: QApplication, global exception hook, ``main``."""

from __future__ import annotations

import argparse
import logging
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType

from PySide6.QtCore import QCoreApplication, QSettings
from PySide6.QtWidgets import QApplication

from thermalfea.core.errors import ThermalFEAError
from thermalfea.gui.chart_tools import ChartController, attach_charts
from thermalfea.gui.document import Document
from thermalfea.gui.file_tools import FileController, attach_files
from thermalfea.gui.flow_results import FlowController, attach_flow
from thermalfea.gui.geometry_tools import GeometryController, attach_geometry_tools
from thermalfea.gui.load_symbols import LoadSymbolController, attach_loads
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.materials_tools import MaterialLibraryController, attach_materials
from thermalfea.gui.mesh_tools import MeshController, attach_mesh_tools
from thermalfea.gui.overlay_labels import attach_labels
from thermalfea.gui.panels import PropertyController, attach_tree
from thermalfea.gui.part_colors import attach_part_colors
from thermalfea.gui.results_tools import ResultController, attach_results
from thermalfea.gui.solve_tools import SolveController, attach_solve
from thermalfea.gui.tree import ModelTree
from thermalfea.gui.units_tools import UnitsController, attach_units
from thermalfea.gui.viewport_mpl import MplSceneView, attach_viewport
from thermalfea.gui.worker import JOIN_TIMEOUT_MS, SerialWorker

ORGANIZATION = "ThermalFEA"
APPLICATION = "ThermalFEA"

_log = logging.getLogger("thermalfea.gui.app")


def create_app(argv: list[str] | None = None) -> QApplication:
    """Return the ``QApplication``, creating it if none exists.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments; defaults to ``sys.argv``.

    Returns
    -------
    QApplication
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(sys.argv if argv is None else argv))
    QCoreApplication.setOrganizationName(ORGANIZATION)
    QCoreApplication.setApplicationName(APPLICATION)
    return app  # type: ignore[return-value]


def install_exception_hook(window: MainWindow) -> Callable[[], None]:
    """Replace ``sys.excepthook`` so uncaught errors are logged and shown.

    A :class:`ThermalFEAError` is logged and its message shown through
    ``window.show_error``; any other exception is logged with its traceback and shown
    as an unexpected error. The hook never raises.

    Parameters
    ----------
    window : MainWindow
        Window whose error dialog is used.

    Returns
    -------
    Callable[[], None]
        Function restoring the previous ``sys.excepthook``.
    """
    previous = sys.excepthook

    def hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        try:
            if issubclass(exc_type, KeyboardInterrupt):
                previous(exc_type, exc, tb)
                return
            if isinstance(exc, ThermalFEAError):
                _log.error("%s", exc)
                window.show_error("ThermalFEA error", str(exc))
            else:
                text = "".join(traceback.format_exception(exc_type, exc, tb))
                _log.error("Unexpected error:\n%s", text)
                window.show_error(
                    "Unexpected error", f"{exc_type.__name__}: {exc}\n\nSee the message log."
                )
        except Exception:  # the hook must never raise
            try:
                sys.__stderr__.write("exception hook failed\n")  # type: ignore[union-attr]
            except Exception:
                pass

    sys.excepthook = hook

    def restore() -> None:
        sys.excepthook = previous

    return restore


@dataclass
class AppContext:
    """Everything :func:`build_application` wires together.

    Attributes
    ----------
    window : MainWindow
    document : Document
    view : MplSceneView
        The viewport.
    tree : ModelTree
    properties : PropertyController
    geometry : GeometryController
    materials : MaterialLibraryController
    mesh : MeshController
    loads : LoadSymbolController
    solve : SolveController
    results : ResultController
    charts : ChartController
    flow : FlowController
    files : FileController
    gmsh_worker : SerialWorker or None
        The long-lived thread of gmsh (build and mesh); ``None`` when not threaded.
    restore_hook : callable or None
        Restores ``sys.excepthook``; ``None`` when no hook was installed.
    units : UnitsController or None
        The Tools > Units... entry and dialog.
    """

    window: MainWindow
    document: Document
    view: MplSceneView
    tree: ModelTree
    properties: PropertyController
    geometry: GeometryController
    materials: MaterialLibraryController
    mesh: MeshController
    loads: LoadSymbolController
    solve: SolveController
    results: ResultController
    charts: ChartController
    flow: FlowController
    files: FileController
    gmsh_worker: SerialWorker | None = None
    restore_hook: Callable[[], None] | None = None
    units: UnitsController | None = None

    def shutdown(self, timeout_ms: int = JOIN_TIMEOUT_MS) -> bool:
        """Stop the worker threads (bounded waits) and restore the exception hook.

        Cancels a running solve and waits for it, then stops the gmsh thread. Safe to call
        more than once.

        Parameters
        ----------
        timeout_ms : int
            Bound of each wait [ms].

        Returns
        -------
        bool
            ``True`` if no thread of the application is running afterwards.
        """
        ended = self.solve.shutdown(timeout_ms)
        if self.gmsh_worker is not None:
            ended = self.gmsh_worker.shutdown(timeout_ms) and ended
        if self.restore_hook is not None:
            self.restore_hook()
            self.restore_hook = None
        return ended


def build_application(
    settings: QSettings | None = None,
    *,
    threaded: bool = True,
    install_hook: bool = True,
) -> AppContext:
    """Create the window, the document and every controller, wired as in the real program.

    A ``QApplication`` must exist (see :func:`create_app`). The window is not shown.

    Parameters
    ----------
    settings : QSettings, optional
        Where the window keeps its geometry and recent files; default the application's own
        settings. Tests pass a temporary ini file.
    threaded : bool
        ``True`` (what the program uses): geometry builds and meshing run on one long-lived
        gmsh thread, a solve on a thread of its own. ``False``: builds and meshing run
        synchronously in the calling thread (a solve is always threaded).
    install_hook : bool
        Install the global exception hook (:func:`install_exception_hook`); it is restored
        by :meth:`AppContext.shutdown`.

    Returns
    -------
    AppContext
    """
    window = MainWindow(settings=settings)
    document = Document(parent=window)  # lives as long as the window that listens to it
    window.set_document(document)
    view = attach_viewport(window, document)
    tree, properties = attach_tree(window, document, view)
    geometry = attach_geometry_tools(window, document, view)
    materials = attach_materials(window, document)
    units = attach_units(window, document)
    mesh_tools = attach_mesh_tools(window, document, view)
    properties.generate_mesh = mesh_tools.generate
    loads = attach_loads(window, document, view)
    attach_labels(window, document, view)
    attach_part_colors(window, document, view)
    solve = attach_solve(window, document, view)
    properties.solve_controller = solve
    results_controller = attach_results(window, document, view)
    charts = attach_charts(window, document, view, results_controller)
    flow = attach_flow(window, document, view, results_controller)
    # attached last: its close filter runs first, so a refused close cancels no solve
    files = attach_files(window, document)
    gmsh_worker: SerialWorker | None = None
    if threaded:
        # gmsh is driven from one long-lived thread for the whole session (see gui/worker.py)
        gmsh_worker = SerialWorker(window, "gmsh-worker")
        geometry.worker = gmsh_worker
        mesh_tools.worker = gmsh_worker
    window.restore_state()  # docks created after the window was constructed
    restore_hook = install_exception_hook(window) if install_hook else None
    return AppContext(
        window=window,
        document=document,
        view=view,
        tree=tree,
        properties=properties,
        geometry=geometry,
        materials=materials,
        mesh=mesh_tools,
        loads=loads,
        solve=solve,
        results=results_controller,
        charts=charts,
        flow=flow,
        files=files,
        gmsh_worker=gmsh_worker,
        restore_hook=restore_hook,
        units=units,
    )


def main(argv: list[str] | None = None) -> int:
    """Run the GUI.

    Options (Qt's own options are passed on to Qt): ``--smoke-test MODEL`` opens MODEL,
    meshes and solves it, writes a one-line JSON status to the ``--smoke-out PATH`` file
    (standard output without it) and exits, 0 only on success. It is a hook for testing a
    built program, see :mod:`thermalfea.gui.smoke`.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments, program name first (default ``sys.argv``).

    Returns
    -------
    int
        Process exit code.
    """
    args = list(sys.argv if argv is None else argv)
    parser = argparse.ArgumentParser(prog="thermalfea-gui", add_help=False)
    parser.add_argument("--smoke-test", metavar="MODEL", default=None)
    parser.add_argument("--smoke-out", metavar="PATH", default=None)
    options, qt_args = parser.parse_known_args(args[1:])
    app = create_app([args[0], *qt_args])
    context = build_application()
    app.aboutToQuit.connect(context.shutdown)
    context.window.show()
    if options.smoke_test is None:
        return int(app.exec())
    from thermalfea.gui.smoke import run_smoke_test, write_status

    try:
        status = run_smoke_test(app, context, options.smoke_test)
    except Exception as exc:  # report every failure as a status, never a dialog
        status = {"ok": False, "stage": "exception", "error": f"{type(exc).__name__}: {exc}"}
    context.shutdown()
    write_status(status, options.smoke_out)
    return 0 if status["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
