"""Small Matplotlib canvas showing a table function (Plan M8.4).

This is one of the few GUI modules allowed to import Matplotlib (see
``tests/unit/test_layers.py``). It builds its own :class:`~matplotlib.figure.Figure`; it
never imports ``pyplot``.
"""

from __future__ import annotations

from collections.abc import Sequence

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from PySide6.QtWidgets import QSizePolicy, QWidget


class FunctionPreview(FigureCanvasQTAgg):
    """A plot of ``ys`` against ``xs`` with axis labels.

    Parameters
    ----------
    parent : QWidget, optional
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        self.figure_ = Figure(figsize=(3.0, 2.0), layout="constrained")
        super().__init__(self.figure_)
        self.setParent(parent)
        self.axes = self.figure_.add_subplot(111)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.n_points = 0

    def plot(
        self,
        xs: Sequence[float],
        ys: Sequence[float],
        xlabel: str = "",
        ylabel: str = "",
    ) -> None:
        """Replace the plotted curve (empty sequences clear the plot)."""
        self.axes.clear()
        self.n_points = len(xs)
        if len(xs):
            self.axes.plot(list(xs), list(ys), "o-", markersize=3)
        self.axes.set_xlabel(xlabel)
        self.axes.set_ylabel(ylabel)
        self.axes.grid(True, alpha=0.3)
        self.draw_idle()
