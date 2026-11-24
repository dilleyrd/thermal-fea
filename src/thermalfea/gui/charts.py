"""Chart window of the GUI (Plan M8.11): the one GUI module that draws line charts.

One of the few GUI modules allowed to import Matplotlib (see ``tests/unit/test_layers.py``).
It builds its own :class:`~matplotlib.figure.Figure` and never imports ``pyplot``.

A :class:`ChartWindow` is a non-modal top-level widget holding a Matplotlib canvas, a
"Save image..." and an "Export CSV..." button. It contains **no numerics**: the series it
draws come from :mod:`thermalfea.post.plots` (``history_data``, ``heat_flow_history_data``,
``path_data``) or from :meth:`thermalfea.post.results.Results.energy_balance`, and are drawn
by the post drawing functions into the window's axes. The plotted data stay on the window
(:attr:`ChartWindow.data`) and are what the CSV export writes, through
:func:`thermalfea.post.export.series_csv`, in the same display units as the chart.

File choosers are injectable: ``choose_save(parent, caption, filter) -> str | None``
(``None`` means cancelled). The default uses ``QFileDialog.getSaveFileName``; tests replace
it, so nothing here is ever modal under test.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ThermalFEAError
from thermalfea.core.forms import unit_label
from thermalfea.core.units import from_si
from thermalfea.post import export as post_export
from thermalfea.post import plots
from thermalfea.post.flow import stream_curves
from thermalfea.post.results import Results

_log = logging.getLogger(__name__)

#: ``choose_save(parent, caption, filter) -> path or None``.
SaveChooser = Callable[["QWidget | None", str, str], "str | None"]

IMAGE_FILTER = "PNG image (*.png);;PDF (*.pdf);;SVG (*.svg)"
CSV_FILTER = "CSV table (*.csv)"
#: Columns of ``Results.energy_balance()`` that are powers [W] and are drawn. The imbalance is
#: many orders smaller than the flows (it only clutters the chart; M11.47): it is in the table
#: and the CSV, not in the chart. ``relative_imbalance`` is dimensionless.
ENERGY_POWER_COLUMNS = ("heat_in", "heat_out", "net", "stored_rate")
#: Power columns of the window's data (what Export CSV writes): the drawn ones and the imbalance.
ENERGY_CSV_COLUMNS = (*ENERGY_POWER_COLUMNS, "imbalance")
#: Columns of the energy table, in order; those the file lacks are left out.
ENERGY_TABLE_COLUMNS = (*ENERGY_CSV_COLUMNS, "relative_imbalance")
ENERGY_STEADY_TITLE = "Energy balance (steady state)"
IMAGE_DPI = 200


def default_choose_save(parent: QWidget | None, caption: str, file_filter: str) -> str | None:
    """Ask for a file name with the standard save dialog (modal; never used by tests)."""
    from PySide6.QtWidgets import QFileDialog

    path, _selected = QFileDialog.getSaveFileName(parent, caption, "", file_filter)
    return path or None


def energy_data(results: Results) -> plots.HistoryData:
    """The stored energy-balance columns of a results file as history data.

    No computation: the arrays are those of :meth:`Results.energy_balance`.

    Parameters
    ----------
    results : Results

    Returns
    -------
    thermalfea.post.plots.HistoryData
        One series per power column (:data:`ENERGY_CSV_COLUMNS` that the file has, the
        imbalance included: this is what Export CSV writes; the chart leaves the imbalance
        out), in the display power unit of the results (W by default), against time in the
        display unit.
    """
    units = results.display_units
    columns = results.energy_balance()
    series = {
        name: np.asarray(from_si(np.asarray(columns[name], dtype=float), "power", units),
                         dtype=float)
        for name in ENERGY_CSV_COLUMNS
        if name in columns
    }
    return plots.HistoryData(
        times=np.asarray(from_si(np.asarray(results.times, dtype=float), "time", units),
                         dtype=float),
        series=series,
        ylabel=f"Power [{unit_label('power', units)}]",
        title=ENERGY_STEADY_TITLE if plots.is_steady(results) else "Energy balance",
        xlabel=f"Time [{unit_label('time', units)}]",
    )


def energy_table(results: Results) -> tuple[list[str], list[list[str]]]:
    """Headers and text cells of the energy-balance table (one row per stored step).

    No computation: the values are those of :meth:`Results.energy_balance`, converted to the
    display units (powers and time) and formatted with 6 significant digits; the relative
    imbalance is a plain number.
    """
    units = results.display_units
    columns = results.energy_balance()
    names = [name for name in ENERGY_TABLE_COLUMNS if name in columns]
    time_unit = unit_label("time", units)
    power_unit = unit_label("power", units)
    headers = [f"time [{time_unit}]"] + [
        f"{name} [-]" if name == "relative_imbalance" else f"{name} [{power_unit}]"
        for name in names
    ]
    values = [np.asarray(from_si(np.asarray(results.times, dtype=float), "time", units))]
    for name in names:
        raw = np.asarray(columns[name], dtype=float)
        values.append(raw if name == "relative_imbalance"
                      else np.asarray(from_si(raw, "power", units), dtype=float))
    rows = [[_cell(float(col[i])) for col in values] for i in range(len(values[0]))]
    return headers, rows


#: Text of a table cell with no stored value (a NaN, e.g. the initial row of a transient).
NO_VALUE = "—"


def _cell(value: float) -> str:
    return f"{value:.6g}" if np.isfinite(value) else NO_VALUE


class ChartWindow(QWidget):
    """A non-modal window with one line chart.

    Parameters
    ----------
    parent : QWidget, optional
        Owner (the main window); the chart is still a separate top-level window.
    choose_save : callable, optional
        ``choose_save(parent, caption, filter) -> str | None`` used by the buttons.

    Signals
    -------
    failed(str, str)
        ``(title, message)``: an export raised ``ThermalFEAError`` or ``OSError``.
    saved(str)
        A file was written (its path).
    closed(object)
        The window was closed (the window itself).

    Attributes
    ----------
    kind : str
        ``""`` before anything is shown, then ``"history"``, ``"path"``, ``"heat_flow"`` or
        ``"energy"``.
    data : HistoryData or PathData or None
        What is plotted (display units); the CSV export writes exactly this.
    nodes : list of int
        Node indices of a nodal history (empty for the other kinds).
    out_of_date : bool
        ``True`` after :meth:`mark_out_of_date`.
    figure : Figure
    canvas : FigureCanvasQTAgg
    axes : Axes
    """

    failed = Signal(str, str)
    saved = Signal(str)
    closed = Signal(object)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        """Announce the close so the owner can forget the window."""
        super().closeEvent(event)
        self.closed.emit(self)

    def __init__(
        self, parent: QWidget | None = None, choose_save: SaveChooser = default_choose_save
    ) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.choose_save = choose_save
        self.kind = ""
        self.data: plots.HistoryData | plots.PathData | None = None
        self.nodes: list[int] = []
        self.stream_curves: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        #: Redraws the chart from the same results with the current display units; set by
        #: the owner (``None``: the chart cannot be redrawn).
        self.redraw: Callable[[], None] | None = None
        self.out_of_date = False
        self._title = "Chart"
        self.figure = Figure(figsize=(7.0, 4.5), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111)
        self.save_button = QPushButton("Save image...")
        self.csv_button = QPushButton("Export CSV...")
        self.save_button.clicked.connect(lambda _c=False: self.save_image())
        self.csv_button.clicked.connect(lambda _c=False: self.export_csv())
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.save_button)
        buttons.addWidget(self.csv_button)
        self.table = QTableWidget(0, 0)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_menu)
        self.table.installEventFilter(self)
        self.table.hide()
        layout = QVBoxLayout(self)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        self.resize(720, 520)
        self._set_title("Chart")

    # ------------------------------------------------------------------ drawing
    def _set_title(self, text: str) -> None:
        self._title = text
        self.setWindowTitle(text + (" (out of date)" if self.out_of_date else ""))

    def _chart_mode(self) -> None:
        """Show the chart alone (hide the energy table), as for every kind but the energy one."""
        self.table.hide()
        self.canvas.show()
        self.save_button.show()
        self.csv_button.setEnabled(True)
        self.csv_button.setToolTip("")

    # ------------------------------------------------------------------ energy table
    def eventFilter(self, obj, event):  # noqa: N802, ANN001, ANN201 (Qt override)
        """Ctrl+C in the table copies the selected cells."""
        from PySide6.QtCore import QEvent

        if (obj is self.table and event.type() == QEvent.Type.KeyPress
                and event.matches(QKeySequence.StandardKey.Copy)):
            self.copy_table()
            return True
        return super().eventFilter(obj, event)

    def table_text(self) -> str:
        """The selected cells as tab-separated text under the header row (all if none)."""
        table = self.table
        cells = table.selectedIndexes()
        rows = sorted({i.row() for i in cells}) or list(range(table.rowCount()))
        cols = sorted({i.column() for i in cells}) or list(range(table.columnCount()))
        header = [table.horizontalHeaderItem(c).text() for c in cols]
        lines = ["\t".join(header)]
        for r in rows:
            lines.append("\t".join(table.item(r, c).text() for c in cols))
        return "\n".join(lines) + "\n"

    def copy_table(self) -> None:
        """Put the selected table cells on the clipboard (tab-separated, with headers)."""
        QGuiApplication.clipboard().setText(self.table_text())

    def _table_menu(self, pos) -> None:  # noqa: ANN001
        menu = QMenu(self.table)
        menu.addAction("Copy", self.copy_table)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _fill_table(self, headers: list[str], rows: list[list[str]]) -> None:
        table = self.table
        table.clear()
        table.setColumnCount(len(headers))
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(headers)
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()

    def _fresh_axes(self) -> None:
        self._chart_mode()
        self.figure.clear()
        self.axes = self.figure.add_subplot(111)

    def _finish(self, kind: str, data: plots.HistoryData | plots.PathData) -> None:
        self.kind = kind
        self.data = data
        self.out_of_date = False
        self._set_title(data.title)
        self.canvas.draw_idle()

    def show_history(self, data: plots.HistoryData, kind: str = "history") -> None:
        """Draw history data (one line per series) with the post drawing function.

        Parameters
        ----------
        data : HistoryData
            From ``post.plots.history_data`` / ``heat_flow_history_data`` or
            :func:`energy_data`.
        kind : str
            Label kept in :attr:`kind`.
        """
        self._fresh_axes()
        plots.draw_history(data, self.axes, None, "chart")
        self._finish(kind, data)

    def show_nodal_history(self, results: Results, nodes: Sequence[int]) -> None:
        """Temperature against time at mesh nodes (``post.plots.history_data``).

        Parameters
        ----------
        results : Results
        nodes : sequence of int
            Node indices (0-based rows of ``mesh.nodes``).
        """
        data = plots.history_data(results, nodes=[int(n) for n in nodes])
        self.show_history(data, "history")
        self.nodes = [int(n) for n in nodes]

    def show_heat_flows(self, results: Results, bc_names: Sequence[str] | None = None) -> None:
        """Heat flow through boundary conditions against time (all of them by default)."""
        self.show_history(plots.heat_flow_history_data(results, bc_names), "heat_flow")

    def show_term_results(self, results: Results, quantity: str) -> None:
        """A kind of term result (``contact_heat`` or ``h_mean``) against time."""
        self.show_history(plots.term_history_data(results, quantity), quantity)

    def show_energy_balance(self, results: Results) -> None:
        """The stored energy-balance columns against time, and a table of every step.

        The chart draws :data:`ENERGY_POWER_COLUMNS` (not the imbalance); :attr:`data` keeps
        every power column for Export CSV. A steady result shows the table only.
        """
        data = energy_data(results)
        headers, rows = energy_table(results)
        if plots.is_steady(results):
            self._chart_mode()
            self.figure.clear()
            self.axes = self.figure.add_subplot(111)
            self.canvas.hide()
            self.save_button.hide()  # nothing to draw
            self._finish("energy", data)
        else:
            drawn = plots.HistoryData(
                times=data.times,
                series={k: v for k, v in data.series.items() if k in ENERGY_POWER_COLUMNS},
                ylabel=data.ylabel, title=data.title, xlabel=data.xlabel,
            )
            self._fresh_axes()
            plots.draw_history(drawn, self.axes, None, "chart")
            self._finish("energy", data)
        self._fill_table(headers, rows)
        self.table.show()

    def show_path(
        self,
        results: Results,
        polyline: Sequence[Sequence[float]],
        step: int,
        field: str = "T",
        n: int = 200,
    ) -> None:
        """A field against distance along a polyline (``post.plots.path``).

        Parameters
        ----------
        results : Results
        polyline : sequence of (x, y)
            Vertices [m].
        step : int
            Stored step.
        field : str
            A key of ``post.plots.FIELDS``.
        n : int
            Number of sample points.
        """
        data = plots.path_data(results, step, polyline, n, field)
        self._fresh_axes()
        plots.path(results, polyline, step, field, n, ax=self.axes)
        self._finish("path", data)

    def show_stream(self, results: Results, stream: str, step: int = -1) -> None:
        """Fluid and mean wall temperature of an in-plane stream against ``s``.

        Draws the same two curves as ``post.flow.plot_stream``, from the data of
        ``post.flow.wall_temperature`` and ``Results.fluid_temperature``. The curves are kept
        in :attr:`stream_curves` (label -> (s, T), in display units); :attr:`data` stays
        ``None`` (no CSV).

        Parameters
        ----------
        results : Results
        stream : str
            Name of an in-plane stream in the results.
        step : int
            Stored step; negative counts from the end.
        """
        (s_fluid, t_fluid), (s_wall, t_wall), units = stream_curves(results, stream, step)
        self._fresh_axes()
        self.axes.plot(s_fluid, t_fluid, label="fluid")
        self.axes.plot(s_wall, t_wall, label="mean wall")
        self.axes.set_xlabel(f"s [{unit_label('length', units)}]")
        self.axes.set_ylabel(f"T [{unit_label('temperature', units)}]")
        self.axes.grid(True)
        self.axes.legend()
        self.stream_curves = {"fluid": (s_fluid, t_fluid), "mean wall": (s_wall, t_wall)}
        self.data = None
        self.kind = "stream"
        self.out_of_date = False
        # The two curves have their own s grids, so they do not form one CSV table.
        self.csv_button.setEnabled(False)
        self.csv_button.setToolTip(
            "Stream plots have no CSV export: the two curves have different s values."
        )
        self._set_title(f"Stream {stream}")
        self.canvas.draw_idle()

    def mark_out_of_date(self) -> None:
        """Say in the title that the results this chart shows were replaced."""
        self.out_of_date = True
        self._set_title(self._title)

    # ------------------------------------------------------------------ export
    def _target(self, caption: str, file_filter: str, suffix: str) -> Path | None:
        chosen = self.choose_save(self, caption, file_filter)
        if not chosen:
            return None
        path = Path(chosen)
        return path if path.suffix else path.with_suffix(suffix)

    def save_image(self, path: str | Path | None = None) -> Path | None:
        """Save the chart as an image (PNG, PDF or SVG by the file suffix).

        Parameters
        ----------
        path : str or Path, optional
            Target; if ``None`` the chooser is asked and ``None`` is returned on cancel.

        Returns
        -------
        Path or None
            The file written, or ``None`` if cancelled or failed (``failed`` is emitted).
        """
        target = Path(path) if path is not None else self._target(
            "Save chart image", IMAGE_FILTER, ".png"
        )
        if target is None:
            return None
        try:
            self.figure.savefig(target, dpi=IMAGE_DPI)
        except (ThermalFEAError, OSError, ValueError) as exc:
            self.failed.emit("Save image failed", str(exc))
            return None
        self.saved.emit(str(target))
        return target

    def export_csv(self, path: str | Path | None = None) -> Path | None:
        """Write the plotted series to a CSV file (header line, then one row per point).

        Parameters
        ----------
        path : str or Path, optional
            Target; if ``None`` the chooser is asked and ``None`` is returned on cancel.

        Returns
        -------
        Path or None
            The file written, or ``None`` if cancelled, empty or failed.
        """
        data = self.data
        if data is None:
            return None
        target = Path(path) if path is not None else self._target(
            "Export chart data", CSV_FILTER, ".csv"
        )
        if target is None:
            return None
        try:
            if isinstance(data, plots.PathData):
                written = post_export.series_csv(
                    target, data.xlabel, data.s, {data.ylabel: data.values}
                )
            else:
                written = post_export.series_csv(target, data.xlabel, data.times, data.series)
        except (ThermalFEAError, OSError) as exc:
            self.failed.emit("Export CSV failed", str(exc))
            return None
        self.saved.emit(str(written))
        return written
