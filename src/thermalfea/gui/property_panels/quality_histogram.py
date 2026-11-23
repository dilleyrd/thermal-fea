"""Histogram of one mesh quality measure (Plan M8.7).

This is one of the few GUI modules allowed to import Matplotlib (see
``tests/unit/test_layers.py``). It builds its own :class:`~matplotlib.figure.Figure` and
never imports ``pyplot``. The only numerics are :func:`numpy.histogram` and a finiteness
filter.
"""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from numpy import ndarray
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

DEFAULT_BINS = 20
EMPTY_TEXT = "No data"


class QualityHistogram(QWidget):
    """Bar chart of the finite values of one array.

    Parameters
    ----------
    parent : QWidget, optional
    bins : int
        Number of bars when there are values.

    Attributes
    ----------
    counts : ndarray of int, shape (bins,)
        Bar heights of the last :meth:`set_values` (empty when there was nothing to plot).
    edges : ndarray, shape (bins + 1,)
        Bar edges of the last :meth:`set_values` (empty when there was nothing to plot).
    n_values : int
        Number of values given to the last :meth:`set_values`.
    n_finite : int
        How many of them were finite (the others are not drawn).
    figure : Figure
    canvas : FigureCanvasQTAgg
    axes : Axes
    """

    def __init__(self, parent: QWidget | None = None, bins: int = DEFAULT_BINS) -> None:
        super().__init__(parent)
        self.bins = bins
        self.counts = np.zeros(0, dtype=int)
        self.edges = np.zeros(0)
        self.n_values = 0
        self.n_finite = 0
        self.figure = Figure(figsize=(3.0, 2.0), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.figure)
        self.axes = self.figure.add_subplot(111)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)
        self.setMinimumHeight(140)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.set_values(None, "")

    def set_values(self, values: ndarray | None, label: str) -> None:
        """Replace the histogram; ``None`` or no finite value shows the empty state.

        Parameters
        ----------
        values : ndarray or None
            Any shape; non-finite entries are not counted.
        label : str
            Axis label, e.g. "Minimum angle [deg]".
        """
        self.axes.clear()
        flat = np.zeros(0) if values is None else np.asarray(values, dtype=float).reshape(-1)
        finite = flat[np.isfinite(flat)]
        self.n_values = int(flat.size)
        self.n_finite = int(finite.size)
        if finite.size == 0:
            self.counts = np.zeros(0, dtype=int)
            self.edges = np.zeros(0)
            self.axes.text(
                0.5, 0.5, EMPTY_TEXT, ha="center", va="center", transform=self.axes.transAxes
            )
        else:
            lo, hi = float(finite.min()), float(finite.max())
            scale = max(abs(lo), abs(hi), 1.0)
            span = None
            if hi - lo <= 1e-9 * scale:  # equal values, also up to round-off: one bar
                span = (lo - 0.5e-3 * scale, lo + 0.5e-3 * scale)
            self.counts, self.edges = np.histogram(finite, bins=self.bins, range=span)
            self.axes.bar(
                self.edges[:-1], self.counts, width=np.diff(self.edges), align="edge",
                color="#4a7fb0", edgecolor="white",
            )  # fmt: skip
        self.axes.set_xlabel(label)
        self.axes.set_ylabel("Elements")
        self.axes.grid(True, alpha=0.3)
        self.canvas.draw_idle()
