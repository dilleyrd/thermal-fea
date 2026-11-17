"""Flow results in the GUI (Plan M8.12): the stream table, the stream plot and the HTC tool.

Actions (all in ``window.actions``)
-----------------------------------
``results.flow``   Results > Flow results...  (enabled only when the results hold streams)
``tools.htc``      Tools > HTC calculator...

:class:`FlowResultsWindow` is a non-modal window with one row per stream of the displayed
step (:func:`thermalfea.post.flow.stream_summary`), a step spin box and a "Plot" button that
opens a :class:`~thermalfea.gui.charts.ChartWindow` for the selected in-plane stream. It
follows ``document.results_changed``: the results are read again, the step goes back to the
last stored step, and the table is refilled. The window stays open; with no results the table
is empty. Nothing in this module computes a number: every value comes from ``post.flow``.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ThermalFEAError
from thermalfea.core.forms import unit_label
from thermalfea.core.units import UnitSettings, from_si
from thermalfea.gui.charts import ChartWindow
from thermalfea.gui.dialogs.htc_calculator import HtcCalculator
from thermalfea.gui.document import Document
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.results_tools import ResultController
from thermalfea.gui.scene import SceneView
from thermalfea.post.flow import StreamSummary, stream_summary, summary_numbers
from thermalfea.post.results import Results

FLOW_ACTION_ID = "results.flow"
HTC_ACTION_ID = "tools.htc"

#: Table headers, one per column of :meth:`FlowResultsWindow.row_texts`.
COLUMNS = (
    "Stream", "Mode", "Mass flow [kg/s]", "Re", "Regime", "Mean h [W/(m^2 K)]", "dp [Pa]",
    "T_in [K]", "T_out [K]", "Heat [W]",
)  # fmt: skip
#: The quantity of each column of :data:`COLUMNS` (``None``: text or dimensionless).
COLUMN_QUANTITIES = (
    None, None, "mass_flow", None, None, "htc", "pressure", "temperature", "temperature", "power",
)


def column_headers(units: UnitSettings | None = None) -> list[str]:
    """The table headers with the unit labels of the display units (default: SI)."""
    units = units if units is not None else UnitSettings()
    out = []
    for header, quantity in zip(COLUMNS, COLUMN_QUANTITIES, strict=True):
        out.append(header if quantity is None else
                   f"{header.partition(' [')[0]} [{unit_label(quantity, units)}]")
    return out
_BLANK = "-"


def cell_text(value: float) -> str:
    """Text of one number of the table: six significant digits, ``-`` for NaN."""
    return _BLANK if math.isnan(value) else f"{value:.6g}"


class FlowResultsWindow(QWidget):
    """Non-modal table of the stream results of one step, with a plot button.

    Parameters
    ----------
    document : Document
        Its ``results_changed`` signal refills the window.
    results_controller : ResultController
        Provides the open :class:`~thermalfea.post.results.Results`.
    parent : QWidget, optional

    Attributes
    ----------
    table : QTableWidget
        One row per stream (see :data:`COLUMNS`).
    step_spin : QSpinBox
        Stored step (0-based index).
    plot_button : QPushButton
        Plots the selected in-plane stream.
    status_label : QLabel
    rows : list of StreamSummary
        The summaries shown in the table.
    plot_windows : list of ChartWindow
        Plots opened by the button, still open.
    """

    def __init__(
        self,
        document: Document,
        results_controller: ResultController,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Flow results")
        self.document = document
        self.results_controller = results_controller
        self.rows: list[StreamSummary] = []
        self.plot_windows: list[ChartWindow] = []

        self.step_spin = QSpinBox()
        self.step_label = QLabel("")
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(list(COLUMNS))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.plot_button = QPushButton("Plot")
        self.plot_button.setToolTip("Plot the fluid and wall temperatures of the selected stream.")
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #b00020;")
        self.status_label.setWordWrap(True)

        step_row = QHBoxLayout()
        step_row.addWidget(QLabel("Step"))
        step_row.addWidget(self.step_spin)
        step_row.addWidget(self.step_label, 1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.plot_button)
        layout = QVBoxLayout(self)
        layout.addLayout(step_row)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        layout.addWidget(self.status_label)
        self.resize(900, 360)

        self.step_spin.valueChanged.connect(lambda _v: self.fill())
        self.plot_button.clicked.connect(lambda _c=False: self.plot_selected())
        self._shown_units = document.model.display_units
        document.results_changed.connect(self.on_results_changed)
        document.model_changed.connect(self._on_model_changed)
        self.on_results_changed()

    # ------------------------------------------------------------------ results
    def results(self) -> Results | None:
        """The results the window shows (those of the results controller)."""
        return self.results_controller.results

    def on_results_changed(self) -> None:
        """Read the results again: last step selected, table refilled."""
        results = self.results()
        self.step_spin.blockSignals(True)
        try:
            last = max(results.n_steps - 1, 0) if results is not None else 0
            self.step_spin.setRange(0, last)
            self.step_spin.setValue(last)
            self.step_spin.setEnabled(results is not None)
        finally:
            self.step_spin.blockSignals(False)
        self.fill()

    def _on_model_changed(self) -> None:
        """Show the table again when the display units changed."""
        if self.document.model.display_units != self._shown_units:
            self.fill()

    def fill(self) -> None:
        """Fill the table with the stream summaries of the chosen step."""
        self.status_label.setText("")
        results = self.results()
        units = self.document.model.display_units
        self._shown_units = units
        self.table.setHorizontalHeaderLabels(column_headers(units))
        self.rows = []
        if results is not None:
            try:
                self.rows = stream_summary(results, self.step_spin.value())
                time = float(from_si(float(results.times[self.step_spin.value()]), "time", units))
                self.step_label.setText(f"t = {time:.6g} {unit_label('time', units)}")
            except (ThermalFEAError, OSError, KeyError) as exc:
                self.status_label.setText(f"Results cannot be read: {exc}")
        else:
            self.step_label.setText("No results")
        self.table.setRowCount(len(self.rows))
        for row, summary in enumerate(self.rows):
            for column, text in enumerate(self.row_texts(summary, units)):
                self.table.setItem(row, column, QTableWidgetItem(text))
        self.plot_button.setEnabled(results is not None)

    @staticmethod
    def row_texts(summary: StreamSummary, units: UnitSettings | None = None) -> list[str]:
        """The cell texts of one stream, in the order of :data:`COLUMNS` (display units)."""
        mass_flow, Re, h_mean, dp, T_in, T_out, heat = summary_numbers(summary, units)
        return [
            summary.name,
            summary.mode,
            cell_text(mass_flow),
            cell_text(Re),
            summary.regime or _BLANK,
            cell_text(h_mean),
            cell_text(dp),
            cell_text(T_in),
            cell_text(T_out),
            cell_text(heat),
        ]

    # --------------------------------------------------------------------- plot
    def plot_selected(self) -> ChartWindow | None:
        """Open a stream plot for the selected in-plane stream; ``None`` if not possible."""
        results = self.results()
        row = self.table.currentRow()
        if results is None or not 0 <= row < len(self.rows):
            self.status_label.setText("select an in-plane stream to plot")
            return None
        summary = self.rows[row]
        if summary.mode != "in_plane":
            self.status_label.setText(f"stream {summary.name!r} is through-plane: no plot")
            return None
        chart = ChartWindow(self)
        try:
            chart.show_stream(results, summary.name, self.step_spin.value())
        except (ThermalFEAError, OSError, KeyError) as exc:
            chart.deleteLater()
            self.status_label.setText(f"Plot failed: {exc}")
            return None
        self.plot_windows.append(chart)
        chart.show()
        chart.raise_()
        return chart


class FlowController(QObject):
    """Owns the flow results window and the HTC calculator of one main window.

    Parameters
    ----------
    window : MainWindow
        Receives the two actions.
    document : Document
    view : SceneView
        Kept for the viewport the windows belong to; the windows do not pick.
    results_controller : ResultController

    Attributes
    ----------
    action : QAction
        "Flow results..." in the Results menu.
    htc_action : QAction
        "HTC calculator..." in the Tools menu.
    flow_window : FlowResultsWindow or None
    htc_window : HtcCalculator or None
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
        self.flow_window: FlowResultsWindow | None = None
        self.htc_window: HtcCalculator | None = None
        self.action = QAction("Flow results...", window)
        self.action.triggered.connect(lambda _checked=False: self.show_flow())
        window.actions[FLOW_ACTION_ID] = self.action
        window.menus["results"].addAction(self.action)
        self.htc_action = QAction("HTC calculator...", window)
        self.htc_action.triggered.connect(lambda _checked=False: self.show_htc())
        window.actions[HTC_ACTION_ID] = self.htc_action
        window.menus["tools"].addAction(self.htc_action)
        document.results_changed.connect(self.update_actions)
        self.update_actions()

    def has_streams(self) -> bool:
        """True when the open results contain stored streams."""
        results = self.results_controller.results
        if results is None:
            return False
        try:
            return bool(results.streams)
        except (ThermalFEAError, OSError, KeyError):
            return False

    def update_actions(self) -> None:
        """Enable "Flow results..." only while the results hold streams."""
        self.action.setEnabled(self.has_streams())

    def show_flow(self) -> FlowResultsWindow | None:
        """Show the flow results window (non-modal); ``None`` without stream results."""
        if not self.has_streams():
            return None
        if self.flow_window is None:
            self.flow_window = FlowResultsWindow(
                self.document, self.results_controller, self.window
            )
        self.flow_window.show()
        self.flow_window.raise_()
        self.flow_window.activateWindow()
        return self.flow_window

    def show_htc(self) -> HtcCalculator:
        """Show the HTC calculator (non-modal)."""
        if self.htc_window is None:
            self.htc_window = HtcCalculator(self.window)
        self.htc_window.show()
        self.htc_window.raise_()
        self.htc_window.activateWindow()
        return self.htc_window


def attach_flow(
    window: MainWindow,
    document: Document,
    view: SceneView,
    results_controller: ResultController,
) -> FlowController:
    """Install the flow results and HTC calculator actions in a main window.

    Call it after :func:`~thermalfea.gui.results_tools.attach_results`.

    Parameters
    ----------
    window : MainWindow
    document : Document
    view : SceneView
    results_controller : ResultController

    Returns
    -------
    FlowController
    """
    return FlowController(window, document, view, results_controller)
