"""Charts and export (Plan M8.11): chart windows, picking nodes and paths, file export.

Actions (all in ``window.actions``)
-----------------------------------
``results.history``       Results > Nodal history...
``results.path``          Results > Path plot...
``results.path_finish``   Results > Finish path plot (enabled while picking)
``results.path_cancel``   Results > Cancel path plot (enabled while picking)
``results.heat_flows``    Results > Heat-flow history
``results.contact_heat``  Results > Contact-heat history (enabled when the results store it)
``results.h_mean``        Results > Mean-h history (enabled when the results store it)
``results.energy``        Results > Energy balance
``export.image``          File > Export > Viewport image...
``export.csv``            File > Export > Nodal results (CSV)...
``export.vtu``            File > Export > ParaView (VTU)...
``export.gif``            File > Export > Animation (GIF)...
``export.report``         File > Export > Report (HTML)...

Picking nodes (nodal history)
-----------------------------
Triggering ``results.history`` with nodes selected in the viewport (node mode,
``selection_changed(NODE_DIM, tags)``) plots them at once. Without a selection the view is
switched to node selection mode, the status bar asks the user to pick nodes and the action
text becomes "Plot history of N selected nodes"; triggering it again plots whatever is
selected then. No modal dialog is involved.

Picking a path
--------------
``results.path`` starts the pick mode: the view's selection mode is set to ``"none"`` and each
``point_picked`` click adds a polyline vertex (the status bar lists the vertices). After every
click the viewport overlay layer ``"path"`` (``SceneView.set_overlay``) shows one numbered
marker per vertex and, from two vertices on, the polyline joining them. ``results.path_finish``
(or triggering ``results.path`` again) plots the displayed field of the displayed step against
distance; the drawing then stays while that chart window is open and is cleared when it
closes. ``results.path_cancel`` (also a cancel caused by the probe, a node pick or new
results) leaves without a window and clears the drawing; a new path pick replaces any
earlier drawing. Needs at least two vertices.

One click consumer at a time
----------------------------
The probe of :class:`~thermalfea.gui.results_tools.ResultController` and the path pick both
listen to ``point_picked``. Starting a path pick switches the probe off; switching the probe
on cancels a running path pick; and the path handler ignores clicks while the probe is on.
Starting either pick (nodes or path) cancels the other. The selection mode that was active
before is restored when a pick ends.

Chart windows and changing results
----------------------------------
Chart windows are non-modal, parented to the main window, kept in
:attr:`ChartController.windows` and closed with the main window. A chart keeps the data it
drew; when ``document.results_changed`` fires the open charts are *not* redrawn (their node
indices or boundary conditions may no longer exist): they are marked "(out of date)" in
their title, and a running pick is cancelled.

Export
------
Every export takes its target from an injectable chooser (``choose_save(parent, caption,
filter)``, ``choose_folder(parent, caption)``; ``None`` = cancelled), reports success in the
status bar and ``ThermalFEAError`` / ``OSError`` through ``window.show_error``. The GIF is
written **synchronously** in the GUI thread: ``post.export.animation`` shares the module
level display-mesh cache and the open HDF5 file of the results controller with the GUI, and
the background worker is only worth its complexity for the solver; a long animation blocks
the window for its duration (the status bar says so first).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QWidget

from thermalfea import api
from thermalfea.core.errors import ThermalFEAError
from thermalfea.core.units import from_si
from thermalfea.gui.charts import (
    CSV_FILTER,
    IMAGE_FILTER,
    ChartWindow,
    default_choose_save,
)
from thermalfea.gui.document import Document
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.pick import manager_for
from thermalfea.gui.results_tools import (
    PROBE_ID,
    VECTOR_PROBE_FIELD,
    ContourObject,
    ResultController,
)
from thermalfea.gui.scene import (
    NODE_DIM,
    OverlayItem,
    OverlayMarker,
    OverlayPolyline,
    SceneView,
)
from thermalfea.post.report import write_report
from thermalfea.post.results import Results

_log = logging.getLogger(__name__)

HISTORY_ID = "results.history"
PATH_ID = "results.path"
PATH_FINISH_ID = "results.path_finish"
PATH_CANCEL_ID = "results.path_cancel"
HEAT_FLOWS_ID = "results.heat_flows"
CONTACT_HEAT_ID = "results.contact_heat"
H_MEAN_ID = "results.h_mean"
ENERGY_ID = "results.energy"
EXPORT_IMAGE_ID = "export.image"
EXPORT_CSV_ID = "export.csv"
EXPORT_VTU_ID = "export.vtu"
EXPORT_GIF_ID = "export.gif"
EXPORT_REPORT_ID = "export.report"

GIF_FILTER = "GIF animation (*.gif)"
REPORT_FILTER = "HTML report (*.html)"
IMAGE_EXPORT_DPI = 200
#: Viewport overlay layer (``SceneView.set_overlay``) of the picked path.
PATH_OVERLAY_LAYER = "path"
#: Most vertices listed in the status bar while picking a path.
_LISTED_POINTS = 6

FolderChooser = Callable[["QWidget | None", str], "str | None"]


def default_choose_folder(parent: QWidget | None, caption: str) -> str | None:
    """Ask for a folder with the standard dialog (modal; never used by tests)."""
    from PySide6.QtWidgets import QFileDialog

    path = QFileDialog.getExistingDirectory(parent, caption)
    return path or None


class ChartController(QObject):
    """Chart windows, node/path picking and the export actions of one main window.

    Parameters
    ----------
    window : MainWindow
        Receives the actions; errors go through ``window.show_error``.
    document : Document
        ``results_changed`` and the stored results decide which actions are enabled.
    view : SceneView
        Sends ``selection_changed`` / ``point_picked``; takes ``set_selection_mode`` and
        ``save_image``.
    results_controller : ResultController
        Provides the open :class:`Results` and the displayed object and step.

    Attributes
    ----------
    windows : list of ChartWindow
        The open chart windows, oldest first.
    selected_nodes : list of int
        Nodes currently selected in the viewport in node mode.
    history_pending : bool
        The user was asked to pick nodes and has not plotted yet.
    path_active : bool
        A path pick is running.
    path_points : list of (float, float)
        Vertices picked so far [m].
    choose_save : callable
        ``choose_save(parent, caption, filter) -> str | None``; replaceable in tests.
    choose_folder : callable
        ``choose_folder(parent, caption) -> str | None``; replaceable in tests.
    """

    def __init__(
        self,
        window: MainWindow,
        document: Document,
        view: SceneView,
        results_controller: ResultController,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.view = view
        self.results_controller = results_controller
        self.choose_save: Callable[[QWidget | None, str, str], str | None] = default_choose_save
        self.choose_folder: FolderChooser = default_choose_folder
        self.windows: list[ChartWindow] = []
        self.selected_nodes: list[int] = []
        self.history_pending = False
        self.path_active = False
        self.path_points: list[tuple[float, float]] = []
        self._saved_mode: str | None = None
        self._path_chart: ChartWindow | None = None
        self._build_actions()
        view.selection_changed.connect(self._on_selection_changed)
        view.point_picked.connect(self._on_point_picked)
        window.actions[PROBE_ID].toggled.connect(self._on_probe_toggled)
        document.results_changed.connect(self._on_results_changed)
        self._units = document.model.display_units
        document.model_changed.connect(self._on_model_changed)
        for signal in (document.geometry_built, document.mesh_changed):
            signal.connect(self._on_mesh_replaced)
        window.installEventFilter(self)
        self.update_actions()

    # ---------------------------------------------------------------- actions
    def _build_actions(self) -> None:
        window = self.window
        results_menu = window.menus["results"]
        results_menu.addSeparator()
        specs: tuple[tuple[str, str, Callable[[], object], QMenu], ...] = (
            (HISTORY_ID, "Nodal &history...", self.request_history, results_menu),
            (PATH_ID, "Pat&h plot...", self.request_path, results_menu),
            (PATH_FINISH_ID, "Finish path plot", self.finish_path, results_menu),
            (PATH_CANCEL_ID, "Cancel path plot", self.cancel_path, results_menu),
            (HEAT_FLOWS_ID, "Heat-flow histor&y", self.plot_heat_flows, results_menu),
            (CONTACT_HEAT_ID, "Contact-he&at history", self.plot_contact_heat, results_menu),
            (H_MEAN_ID, "&Mean-h history", self.plot_h_mean, results_menu),
            (ENERGY_ID, "&Energy balance", self.plot_energy_balance, results_menu),
        )
        for key, text, slot, menu in specs:
            self._add_action(menu, key, text, slot)
        export_menu = QMenu("&Export", window)
        file_menu = window.menus["file"]
        file_menu.insertMenu(window.actions["file.exit"], export_menu)
        file_menu.insertSeparator(window.actions["file.exit"])
        window.menus["export"] = export_menu
        for key, text, slot in (
            (EXPORT_IMAGE_ID, "Viewport &image...", self.export_image),
            (EXPORT_CSV_ID, "Nodal results (&CSV)...", self.export_csv),
            (EXPORT_VTU_ID, "&ParaView (VTU)...", self.export_vtu),
            (EXPORT_GIF_ID, "Animation (&GIF)...", self.export_gif),
            (EXPORT_REPORT_ID, "&Report (HTML)...", self.export_report),
        ):
            self._add_action(export_menu, key, text, slot)

    def _add_action(self, menu: QMenu, key: str, text: str, slot: Callable[[], object]) -> None:
        action = QAction(text, self.window)
        action.triggered.connect(lambda _checked=False, s=slot: s())
        self.window.actions[key] = action
        menu.addAction(action)

    def update_actions(self) -> None:
        """Set the enabled state and texts of the chart and export actions."""
        results = self.results_controller.results
        has = results is not None
        actions = self.window.actions
        actions[HISTORY_ID].setEnabled(has)
        actions[PATH_ID].setEnabled(has)
        actions[PATH_FINISH_ID].setEnabled(self.path_active)
        actions[PATH_CANCEL_ID].setEnabled(self.path_active)
        actions[HEAT_FLOWS_ID].setEnabled(has and self._has_heat_flows())
        actions[CONTACT_HEAT_ID].setEnabled(has and self._has_term_results("contact_heat"))
        actions[H_MEAN_ID].setEnabled(has and self._has_term_results("h_mean"))
        actions[ENERGY_ID].setEnabled(has)
        actions[EXPORT_CSV_ID].setEnabled(has)
        actions[EXPORT_VTU_ID].setEnabled(has)
        actions[EXPORT_GIF_ID].setEnabled(has)
        actions[EXPORT_REPORT_ID].setEnabled(has)
        actions[EXPORT_IMAGE_ID].setEnabled(has or self.document.built is not None)
        if self.history_pending:
            n = len(self.selected_nodes)
            text = (
                f"Plot &history of {n} selected node{'s' if n != 1 else ''}"
                if n else "Plot &history (pick nodes first)"
            )
        else:
            text = "Nodal &history..."
        actions[HISTORY_ID].setText(text)

    def _has_heat_flows(self) -> bool:
        results = self.results_controller.results
        try:
            return results is not None and bool(results.heat_flow_names)
        except (ThermalFEAError, OSError, KeyError):
            return False

    def _has_term_results(self, quantity: str) -> bool:
        results = self.results_controller.results
        try:
            return results is not None and any(
                k.partition(":")[0] == quantity for k in results.term_result_names
            )
        except (ThermalFEAError, OSError, KeyError):
            return False

    # ----------------------------------------------------------------- helpers
    def _status(self, text: str, timeout_ms: int = 8000) -> None:
        self.window.statusBar().showMessage(text, timeout_ms)

    def _error(self, title: str, message: str) -> None:
        _log.error("%s: %s", title, message)
        self.window.show_error(title, message)

    def _set_mode(self, mode: str) -> None:
        """Set the view's selection mode and the toolbar action that mirrors it."""
        self.view.set_selection_mode(mode)  # type: ignore[arg-type]
        action = self.window.actions.get(f"select.{mode}")
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _enter_pick(self, mode: str) -> None:
        # one pick at a time (C2): end a pick of the pick manager first (it restores its
        # mode), and stop this pick when the manager starts another
        manager = manager_for(self.view)
        manager.cancel_active()
        if self._stop_for_other not in manager.on_start:
            manager.on_start.append(self._stop_for_other)
        if self._saved_mode is None:
            self._saved_mode = self.window.selection_mode
        self._set_mode(mode)

    def _leave_pick(self) -> None:
        manager = manager_for(self.view)
        if self._stop_for_other in manager.on_start:
            manager.on_start.remove(self._stop_for_other)
        if self._saved_mode is not None:
            self._set_mode(self._saved_mode)
            self._saved_mode = None

    def _stop_for_other(self) -> None:
        """Another pick starts: end a running path pick or pending node pick (no chart)."""
        if self.path_active:
            self.cancel_path()
        if self.history_pending:
            self.history_pending = False
            self._leave_pick()
            self.update_actions()

    def _displayed(self) -> tuple[int, str]:
        """Step and field of the displayed result object (last step, ``T`` if none)."""
        ctrl = self.results_controller
        obj = ctrl.get(ctrl.shown)
        if obj is None:
            return max(ctrl.n_steps - 1, 0), "T"
        return obj.step, obj.field if isinstance(obj, ContourObject) else VECTOR_PROBE_FIELD

    def _new_window(self) -> ChartWindow:
        chart = ChartWindow(
            self.window, lambda parent, caption, flt: self.choose_save(parent, caption, flt)
        )
        chart.failed.connect(self._error)
        chart.saved.connect(lambda path: self._status(f"Wrote {path}"))
        chart.closed.connect(self._on_chart_closed)
        self.windows.append(chart)
        return chart

    def _on_chart_closed(self, chart: object) -> None:
        if chart is self._path_chart:
            self._clear_path_drawing()
        if chart in self.windows:
            self.windows.remove(chart)  # type: ignore[arg-type]
            chart.deleteLater()  # type: ignore[attr-defined]

    def _current_results(self) -> Results:
        """The current results (for charts that draw again after a new solve)."""
        results = self.results_controller.results
        if results is None:
            raise ThermalFEAError("there are no results")
        return results

    def _open_renewable(self, draw: Callable[[ChartWindow], None]) -> ChartWindow | None:
        """Open a chart whose ``draw`` reads the current results: a new solve draws it
        again instead of marking it out of date (M11.75)."""
        chart = self._open(draw)
        if chart is not None:
            chart.renewable = True  # type: ignore[attr-defined]
        return chart

    def _open(self, draw: Callable[[ChartWindow], None]) -> ChartWindow | None:
        """Create a chart window, draw into it, show it; errors go to ``show_error``."""
        chart = self._new_window()
        try:
            draw(chart)
        except (ThermalFEAError, OSError, KeyError) as exc:
            self.windows.remove(chart)
            chart.deleteLater()
            self._error("Chart failed", str(exc))
            return None
        chart.redraw = lambda: draw(chart)
        chart.show()
        chart.raise_()
        return chart

    # ----------------------------------------------------------- nodal history
    def _on_selection_changed(self, dim: int, tags: list) -> None:
        self.selected_nodes = [int(t) for t in tags] if dim == NODE_DIM else []
        if self.history_pending:
            self.update_actions()

    def request_history(self) -> ChartWindow | None:
        """The "Nodal history..." action: plot the selected nodes, or ask for a selection.

        Returns
        -------
        ChartWindow or None
            The new window, or ``None`` when the user was asked to pick nodes first.
        """
        if self.results_controller.results is None:
            return None
        if self.selected_nodes:
            return self.plot_history(self.selected_nodes)
        self.cancel_path()
        self.history_pending = True
        self._enter_pick("node")
        self.update_actions()
        self._status("Pick the nodes to plot in the viewport, then choose the action again", 15000)
        return None

    def plot_history(self, nodes: list[int]) -> ChartWindow | None:
        """Open a window with the temperature history of the given nodes.

        Parameters
        ----------
        nodes : list of int
            Node indices.
        """
        results = self.results_controller.results
        if results is None:
            return None
        chart = self._open(lambda w: w.show_nodal_history(results, nodes))
        self.history_pending = False
        self._leave_pick()
        self.update_actions()
        return chart

    # ---------------------------------------------------------------- path plot
    def request_path(self) -> ChartWindow | None:
        """The "Path plot..." action: start picking, or finish when already picking."""
        if self.path_active:
            return self.finish_path()
        if self.results_controller.results is None:
            return None
        self.history_pending = False
        self.results_controller.set_probe(False)
        self.path_points = []
        self._clear_path_drawing()  # a new pick replaces the drawing kept for a chart
        self.path_active = True
        self._enter_pick("none")
        self.update_actions()
        self._status("Path plot: click the polyline vertices in the viewport, then Finish", 15000)
        return None

    def _on_point_picked(self, x: float, y: float, _z: float) -> None:
        if not self.path_active or self.results_controller.probe_active:
            return
        self.path_points.append((float(x), float(y)))
        shown = self.path_points[-_LISTED_POINTS:]
        more = "... " if len(self.path_points) > _LISTED_POINTS else ""
        units = self.document.model.display_units
        listing = more + "; ".join(
            f"({float(from_si(px, 'length', units)):.6g}, "
            f"{float(from_si(py, 'length', units)):.6g})"
            for px, py in shown
        )
        self._status(f"Path: {len(self.path_points)} vertex(es): {listing}", 30000)
        self._draw_path()

    def _draw_path(self) -> None:
        """Draw the numbered vertices and, from two vertices on, the polyline joining them."""
        items: list[OverlayItem] = [
            OverlayMarker(px, py, text=str(i)) for i, (px, py) in enumerate(self.path_points, 1)
        ]
        if len(self.path_points) >= 2:
            items.append(OverlayPolyline(list(self.path_points)))
        self.view.set_overlay(PATH_OVERLAY_LAYER, items)

    def _clear_path_drawing(self) -> None:
        self._path_chart = None
        self.view.set_overlay(PATH_OVERLAY_LAYER, [])

    def _on_probe_toggled(self, on: bool) -> None:
        if on and self.path_active:
            self.cancel_path()

    def finish_path(self) -> ChartWindow | None:
        """End the pick and plot the displayed field along the picked polyline.

        Returns
        -------
        ChartWindow or None
            ``None`` if no pick is running or fewer than two vertices were picked (the pick
            continues in that case).
        """
        results = self.results_controller.results
        if not self.path_active or results is None:
            return None
        if len(self.path_points) < 2:
            self._status("Path plot: pick at least two vertices", 8000)
            return None
        polyline = list(self.path_points)
        step, field = self._displayed()
        self._end_path()
        chart = self._open(lambda w: w.show_path(results, polyline, step, field))
        if chart is None:
            self._clear_path_drawing()
        else:
            self._path_chart = chart  # the drawing stays while this window is open
        return chart

    def cancel_path(self) -> None:
        """Leave the path pick without plotting; the drawing is cleared."""
        if self.path_active:
            self._end_path()
            self._clear_path_drawing()
            self._status("Path plot cancelled", 5000)

    def _end_path(self) -> None:
        self.path_active = False
        self.path_points = []
        self._leave_pick()
        self.update_actions()

    # --------------------------------------------------- heat flow and energy
    def plot_heat_flows(self, bc_names: list[str] | None = None) -> ChartWindow | None:
        """Open a window with the heat flow through boundary conditions (all by default)."""
        if self.results_controller.results is None:
            return None
        return self._open_renewable(
            lambda w: w.show_heat_flows(self._current_results(), bc_names)
        )

    def plot_contact_heat(self) -> ChartWindow | None:
        """Open a window with the heat across every contact (side A to side B)."""
        if self.results_controller.results is None:
            return None
        return self._open_renewable(
            lambda w: w.show_term_results(self._current_results(), "contact_heat")
        )

    def plot_h_mean(self) -> ChartWindow | None:
        """Open a window with the mean heat-transfer coefficient of correlation loads."""
        if self.results_controller.results is None:
            return None
        return self._open_renewable(
            lambda w: w.show_term_results(self._current_results(), "h_mean")
        )

    def plot_energy_balance(self) -> ChartWindow | None:
        """Open a window with the stored energy-balance columns against time."""
        if self.results_controller.results is None:
            return None
        return self._open_renewable(lambda w: w.show_energy_balance(self._current_results()))

    # ------------------------------------------------------------ results change
    def _on_model_changed(self) -> None:
        """Draw the open charts again when the display units changed."""
        units = self.document.model.display_units
        if units == self._units:
            return
        self._units = units
        for chart in self.windows:
            if chart.redraw is None or chart.out_of_date:
                continue
            try:
                chart.redraw()
            except (ThermalFEAError, OSError, KeyError) as exc:
                self._error("Chart failed", str(exc))

    def _on_mesh_replaced(self) -> None:
        """Node numbers belong to one mesh: forget them when the mesh or geometry changed."""
        self.selected_nodes = []
        self.update_actions()

    def _on_results_changed(self) -> None:
        # heat-flow, contact-heat, mean-h and energy charts draw again from the new results;
        # the others (and those that cannot) are marked out of date
        for chart in self.windows:
            if getattr(chart, "renewable", False) and chart.redraw is not None:
                try:
                    chart.redraw()
                    continue
                except (ThermalFEAError, OSError, KeyError, ValueError):
                    pass
            chart.mark_out_of_date()
        if self.history_pending:
            self.history_pending = False
            self._leave_pick()
        self.cancel_path()
        self.update_actions()

    def close_windows(self) -> None:
        """Close every chart window."""
        for chart in list(self.windows):
            chart.close()
        self.windows.clear()

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        """Close the chart windows when the main window closes."""
        if obj is self.window and event.type() == QEvent.Type.Close:
            self.close_windows()
        return False

    # ------------------------------------------------------------------ export
    def _target(self, caption: str, file_filter: str, suffix: str) -> Path | None:
        chosen = self.choose_save(self.window, caption, file_filter)
        if not chosen:
            return None
        path = Path(chosen)
        return path if path.suffix else path.with_suffix(suffix)

    def export_image(self) -> Path | None:
        """Save the viewport image (``view.save_image``); returns the file or ``None``."""
        target = self._target("Export viewport image", IMAGE_FILTER, ".png")
        if target is None:
            return None
        try:
            self.view.save_image(str(target), IMAGE_EXPORT_DPI)
        except (ThermalFEAError, OSError, ValueError) as exc:
            self._error("Export image failed", str(exc))
            return None
        self._status(f"Viewport image written to {target}")
        return target

    def export_csv(self) -> Path | None:
        """Write the nodal temperature and flux of every step to CSV (``api.export_csv``)."""
        results = self.results_controller.results
        if results is None:
            return None
        target = self._target("Export nodal results", CSV_FILTER, ".csv")
        if target is None:
            return None
        try:
            written = api.export_csv(results, target)
        except (ThermalFEAError, OSError, KeyError) as exc:
            self._error("Export CSV failed", str(exc))
            return None
        self._status(f"Nodal results written to {written}")
        return written

    def export_vtu(self) -> Path | None:
        """Write one VTU file per step plus a ``.pvd`` index into a chosen folder."""
        results = self.results_controller.results
        if results is None:
            return None
        chosen = self.choose_folder(self.window, "Export VTU files to folder")
        if not chosen:
            return None
        try:
            written = api.export_vtu(results, chosen)
        except (ThermalFEAError, OSError, KeyError) as exc:
            self._error("Export VTU failed", str(exc))
            return None
        self._status(f"VTU series written to {written.parent}")
        return written

    def export_gif(self) -> Path | None:
        """Write an animation of the displayed field over all steps (synchronously)."""
        results = self.results_controller.results
        if results is None:
            return None
        target = self._target("Export animation", GIF_FILTER, ".gif")
        if target is None:
            return None
        _step, field = self._displayed()
        self._status("Writing the animation; the window is busy until it is done...", 0)
        try:
            written = api.export_animation(results, target, field)
        except (ThermalFEAError, OSError, KeyError) as exc:
            self._error("Export animation failed", str(exc))
            return None
        self._status(f"Animation written to {written}")
        return written

    def export_report(self) -> Path | None:
        """Write the HTML report with the displayed step and field (``write_report``)."""
        results = self.results_controller.results
        if results is None:
            return None
        target = self._target("Export report", REPORT_FILTER, ".html")
        if target is None:
            return None
        step, field = self._displayed()
        try:
            written = write_report(results, target, step, (field,))
        except (ThermalFEAError, OSError, KeyError) as exc:
            self._error("Export report failed", str(exc))
            return None
        self._status(f"HTML report written to {written}")
        return written


def attach_charts(
    window: MainWindow,
    document: Document,
    view: SceneView,
    results_controller: ResultController,
) -> ChartController:
    """Install the chart windows and export actions in a main window.

    Call it after :func:`~thermalfea.gui.results_tools.attach_results`.

    Parameters
    ----------
    window : MainWindow
    document : Document
    view : SceneView
    results_controller : ResultController

    Returns
    -------
    ChartController
    """
    return ChartController(window, document, view, results_controller)
