"""Progress dialog of a solve (Plan M8.9).

:class:`SolveProgressDialog` is a non-modal :class:`QDialog` (it is shown with ``show()``,
never ``exec()``). It shows time (and a progress bar towards the end time of a transient
analysis), the time step, the step number, the iterations of the last step, whether it
converged, and a live residual chart. The Cancel button emits :attr:`cancel_requested`; the
controller turns that into a cooperative cancel of the worker. When the run ends the dialog
shows the state ("finished", "cancelled", "failed") and the button becomes "Close".

Progress arrives from the worker as fast as the solver steps. :meth:`update_info` only
stores the newest :class:`~thermalfea.solver.run.StepInfo` and adds the point to the chart;
the labels and the bar are refreshed by a single-shot timer, and :meth:`set_state` always
refreshes them at once, so the final numbers are never lost.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermalfea.gui.dialogs.residual_plot import ResidualPlot
from thermalfea.solver.run import StepInfo

REFRESH_INTERVAL_MS = 50
#: Resolution of the progress bar.
BAR_STEPS = 1000
STATES: tuple[str, ...] = ("running", "cancelling", "finished", "cancelled", "failed")
_STATE_TEXT = {
    "running": "Running",
    "cancelling": "Cancelling...",
    "finished": "Finished",
    "cancelled": "Cancelled",
    "failed": "Failed",
}
_ERROR_STYLE = "color: #b00020;"


class SolveProgressDialog(QDialog):
    """Live view of a running solve.

    Parameters
    ----------
    transient : bool
        ``True`` shows the progress bar towards the end time.
    parent : QWidget, optional

    Signals
    -------
    cancel_requested()
        The user pressed Cancel while the solve was running.

    Attributes
    ----------
    state : str
        One of :data:`STATES`.
    last_info : StepInfo or None
        The newest progress report received.
    n_reports : int
        How many reports were received.
    plot : ResidualPlot
    labels : dict of str to QLabel
        The value labels: ``"time"``, ``"dt"``, ``"step"``, ``"iterations"``,
        ``"converged"``, ``"residual"``.
    bar : QProgressBar
    message_label : QLabel
        Result or error message shown below the numbers.
    button : QPushButton
        Cancel while running, Close afterwards.
    """

    cancel_requested = Signal()

    def __init__(
        self, transient: bool = False, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Solving")
        self.setModal(False)
        self.transient = transient
        self.state = "running"
        self.last_info: StepInfo | None = None
        self.n_reports = 0
        self._dirty = False

        layout = QVBoxLayout(self)
        self.state_label = QLabel()
        self.state_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self.state_label)
        self.bar = QProgressBar()
        self.bar.setRange(0, BAR_STEPS)
        self.bar.setVisible(transient)
        layout.addWidget(self.bar)
        form = QFormLayout()
        self.labels: dict[str, QLabel] = {}
        for key, title in (
            ("time", "Time"),
            ("dt", "Time step"),
            ("step", "Step"),
            ("iterations", "Iterations"),
            ("converged", "Converged"),
            ("residual", "Residual [W]"),
        ):
            label = QLabel("-")
            self.labels[key] = label
            form.addRow(title + ":", label)
        layout.addLayout(form)
        self.plot = ResidualPlot()
        layout.addWidget(self.plot)
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setVisible(False)
        layout.addWidget(self.message_label)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.button = QPushButton("Cancel")
        self.button.clicked.connect(lambda _checked=False: self._on_button())
        buttons.addWidget(self.button)
        layout.addLayout(buttons)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(REFRESH_INTERVAL_MS)
        self._timer.timeout.connect(self.refresh)
        self.resize(460, 520)
        self._show_state()

    # ------------------------------------------------------------------- input
    def update_info(self, info: StepInfo) -> None:
        """Take one progress report (cheap; the display is refreshed by a timer)."""
        self.last_info = info
        self.n_reports += 1
        self.plot.add_point(info.step, info.residual)
        self._dirty = True
        if not self._timer.isActive():
            self._timer.start()

    def set_state(self, state: str, message: str = "") -> None:
        """Change the state and show a message; refreshes everything at once.

        Parameters
        ----------
        state : str
            One of :data:`STATES`.
        message : str
            Result or error text ("" hides it).
        """
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        self.state = state
        self.message_label.setText(message)
        self.message_label.setVisible(bool(message))
        self.message_label.setStyleSheet(_ERROR_STYLE if state == "failed" else "")
        self._show_state()
        self.refresh()

    # ----------------------------------------------------------------- display
    def refresh(self) -> None:
        """Show the newest report now (labels, bar and chart)."""
        self._timer.stop()
        self.plot.flush()
        info = self.last_info
        if info is None or not self._dirty:
            return
        self._dirty = False
        shown = f"{info.time:.6g} s"
        if self.transient:
            shown += f" of {info.end_time:.6g} s"
        self.labels["time"].setText(shown)
        self.labels["dt"].setText(f"{info.dt:.6g} s" if self.transient else "-")
        self.labels["step"].setText(str(info.step))
        self.labels["iterations"].setText(str(info.iterations))
        self.labels["converged"].setText("yes" if info.converged else "no")
        self.labels["residual"].setText(f"{info.residual:.3e}")
        if self.transient and info.end_time > 0.0:
            fraction = min(1.0, max(0.0, info.time / info.end_time))
            self.bar.setValue(round(fraction * BAR_STEPS))

    def _show_state(self) -> None:
        self.state_label.setText(_STATE_TEXT[self.state])
        running = self.state in ("running", "cancelling")
        self.button.setText("Cancel" if running else "Close")
        self.button.setEnabled(self.state != "cancelling")

    def _on_button(self) -> None:
        if self.state == "running":
            self.cancel_requested.emit()
        elif self.state not in ("cancelling",):
            self.close()
