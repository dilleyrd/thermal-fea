"""Live residual chart of the solve progress dialog (Plan M8.9).

One of the few GUI modules allowed to import Matplotlib (see ``tests/unit/test_layers.py``).
It builds its own :class:`~matplotlib.figure.Figure` and never imports ``pyplot``. The
chart plots the final residual norm of every step (log axis) against the step number; the
plotted numbers are exposed as :attr:`ResidualPlot.steps` and :attr:`ResidualPlot.residuals`.

Redraws are coalesced: :meth:`add_point` only stores the point and (re)starts a single-shot
timer, so a solver that reports thousands of steps per second costs one redraw per
interval. :meth:`flush` draws at once, so the final state is never lost.
"""

from __future__ import annotations

import math

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

REDRAW_INTERVAL_MS = 100
#: Smallest residual drawn on the log axis [W]; a zero residual is plotted here.
FLOOR = 1e-30


class ResidualPlot(QWidget):
    """Residual per step on a logarithmic axis.

    Parameters
    ----------
    parent : QWidget, optional
    interval_ms : int
        Minimum time between two redraws.

    Attributes
    ----------
    steps : list of int
        Step number of every point added.
    residuals : list of float
        Residual norm [W] of every point added (as given).
    draw_count : int
        How many times the figure was actually redrawn.
    figure : Figure
    canvas : FigureCanvasQTAgg
    axes : Axes
    """

    def __init__(
        self, parent: QWidget | None = None, interval_ms: int = REDRAW_INTERVAL_MS
    ) -> None:
        super().__init__(parent)
        self.steps: list[int] = []
        self.residuals: list[float] = []
        self.draw_count = 0
        self.figure = Figure(figsize=(4.0, 2.4), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111)
        (self._line,) = self.axes.semilogy([], [], "o-", color="#4a7fb0", markersize=3)
        self.axes.set_xlabel("Step")
        self.axes.set_ylabel("Residual [W]")
        self.axes.grid(True, alpha=0.3)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setMinimumHeight(160)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self.flush)
        self._dirty = False

    def add_point(self, step: int, residual: float) -> None:
        """Record one point; the redraw is deferred (see :meth:`flush`)."""
        self.steps.append(int(step))
        self.residuals.append(float(residual))
        self._dirty = True
        if not self._timer.isActive():
            self._timer.start()

    def clear(self) -> None:
        """Remove every point."""
        self.steps.clear()
        self.residuals.clear()
        self._dirty = True
        self.flush()

    def flush(self) -> None:
        """Draw the points now if any were added since the last draw."""
        self._timer.stop()
        if not self._dirty:
            return
        self._dirty = False
        values = [r if math.isfinite(r) and r > 0.0 else FLOOR for r in self.residuals]
        self._line.set_data(self.steps, values)
        self.axes.relim()
        self.axes.autoscale_view()
        self.draw_count += 1
        self.canvas.draw_idle()
