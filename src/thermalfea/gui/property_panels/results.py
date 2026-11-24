"""Property panel of a result object (Plan M8.10).

:class:`ResultPanel` edits one contour or vector object of the
:class:`~thermalfea.gui.results_tools.ResultController` and shows the controls of the task:
field, step slider and spin box, time box (typing a time jumps to the nearest stored step),
range (auto for this step / auto over all steps / manual, in display units), banded levels or
smooth shading, mesh overlay, min/max markers, vector density, Play/Pause with a frame
interval, and the probe read-out. The panel holds no numerics; every control calls
``controller.update`` and the panel redraws itself from the controller's state whenever
``display_changed`` fires.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import unit_label
from thermalfea.core.units import from_si, to_si
from thermalfea.post.plots import FIELDS, is_steady

if TYPE_CHECKING:
    from thermalfea.gui.results_tools import ResultController

#: First item of the address of a result object: ``("result", name)``.
RESULT_ADDRESS = "result"
MAX_LISTED_CHANGES = 20


def _changes_text(status: Any) -> str:
    """The out-of-date box: what changed since the solve (at most 20 lines)."""
    if not status.out_of_date:
        return ""
    shown = status.changes[:MAX_LISTED_CHANGES]
    n = len(status.changes)
    lines = [f"These results are out of date: the model changed since the solve ({n})."]
    lines += [f"• {c}" for c in shown]
    if len(status.changes) > len(shown):
        lines.append(f"… and {len(status.changes) - len(shown)} more")
    return "\n".join(lines)
_RANGE_TITLES = (
    ("auto_step", "Auto (this step)"),
    ("auto_all", "Auto (all steps)"),
    ("manual", "Manual"),
)


class ResultPanel(QWidget):
    """Controls of one result object.

    Parameters
    ----------
    controller : ResultController
    name : str
        Name of the object (it must exist).
    parent : QWidget, optional

    Attributes
    ----------
    name : str
    field_combo, range_combo : QComboBox
    step_slider : QSlider
    step_spin, levels_spin, density_spin, interval_spin : QSpinBox
    time_edit, min_edit, max_edit : QLineEdit
        Time [s] of the step; range limits in display units (editable in manual mode).
    banded_check, mesh_check, markers_check, loop_check, probe_check : QCheckBox
    play_button : QPushButton
    stale_label, message_label, probe_label : QLabel
    """

    def __init__(
        self, controller: ResultController, name: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.controller = controller
        self.name = name
        self._syncing = False
        self._build()
        controller.display_changed.connect(self._sync)
        controller.playing_changed.connect(self._sync)
        controller.probe_changed.connect(self._on_probe)
        controller.status_changed.connect(self._sync)
        self._sync()

    # ------------------------------------------------------------------ layout
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        self.header_label = QLabel("")
        self.header_label.setWordWrap(True)
        layout.addWidget(self.header_label)
        self.stale_label = QLabel("")
        self.stale_label.setWordWrap(True)
        self.stale_label.setStyleSheet(
            "background: #fff4c2; color: #6b4a00; border: 1px solid #e0c060; padding: 4px;"
        )
        layout.addWidget(self.stale_label)
        self.message_label = QLabel("")
        self.message_label.setWordWrap(True)
        self.message_label.setStyleSheet("color: #c0392b;")
        layout.addWidget(self.message_label)

        # --- what to show
        self.show_group = QGroupBox("Display")
        form = QFormLayout(self.show_group)
        self.field_combo = QComboBox()
        for key in self.controller.fields() or list(FIELDS):
            self.field_combo.addItem(FIELDS[key][3], key)
        self.field_combo.activated.connect(self._on_field)
        self.field_row = (QLabel("Field"), self.field_combo)
        form.addRow(*self.field_row)

        self.step_slider = QSlider(Qt.Orientation.Horizontal)
        self.step_spin = QSpinBox()
        step_row = QHBoxLayout()
        step_row.addWidget(self.step_slider, 1)
        step_row.addWidget(self.step_spin)
        form.addRow("Step", step_row)
        self.step_slider.valueChanged.connect(self._on_step)
        self.step_spin.valueChanged.connect(self._on_step)

        self.time_edit = QLineEdit()
        self.time_edit.setToolTip("Type a time; the nearest stored step is shown")
        self.time_edit.editingFinished.connect(self._on_time)
        self.time_unit = QLabel("s")
        time_row = QHBoxLayout()
        time_row.addWidget(self.time_edit, 1)
        time_row.addWidget(self.time_unit)
        form.addRow("Time", time_row)

        self.density_spin = QSpinBox()
        self.density_spin.setRange(1, 200)
        self.density_spin.valueChanged.connect(lambda v: self._apply(density=v))
        self.density_row = (QLabel("Arrows across"), self.density_spin)
        form.addRow(*self.density_row)

        self.mesh_check = QCheckBox("Mesh overlay")
        self.mesh_check.toggled.connect(lambda on: self._apply(show_mesh=on))
        form.addRow(self.mesh_check)
        layout.addWidget(self.show_group)

        # --- colour scale (contours only)
        self.scale_group = QGroupBox("Colour scale")
        scale = QFormLayout(self.scale_group)
        self.range_combo = QComboBox()
        for key, title in _RANGE_TITLES:
            self.range_combo.addItem(title, key)
        self.range_combo.activated.connect(self._on_range_mode)
        scale.addRow("Range", self.range_combo)
        self.min_edit = QLineEdit()
        self.max_edit = QLineEdit()
        self.min_edit.editingFinished.connect(self._on_limits)
        self.max_edit.editingFinished.connect(self._on_limits)
        limits = QHBoxLayout()
        limits.addWidget(self.min_edit)
        limits.addWidget(QLabel("to"))
        limits.addWidget(self.max_edit)
        scale.addRow("Min / max", limits)
        self.banded_check = QCheckBox("Banded (otherwise smooth)")
        self.banded_check.toggled.connect(lambda on: self._apply(banded=on))
        scale.addRow(self.banded_check)
        self.levels_spin = QSpinBox()
        self.levels_spin.setRange(1, 256)
        self.levels_spin.valueChanged.connect(lambda v: self._apply(levels=v))
        scale.addRow("Levels", self.levels_spin)
        self.markers_check = QCheckBox("Mark minimum and maximum")
        self.markers_check.toggled.connect(lambda on: self._apply(markers=on))
        scale.addRow(self.markers_check)
        layout.addWidget(self.scale_group)

        # --- animation
        animation = QGroupBox("Animation")
        anim = QFormLayout(animation)
        self.play_button = QPushButton("Play")
        self.play_button.setCheckable(True)
        self.play_button.clicked.connect(self._on_play)
        anim.addRow(self.play_button)
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 10000)
        self.interval_spin.setSuffix(" ms")
        self.interval_spin.setSingleStep(50)
        self.interval_spin.valueChanged.connect(self._on_interval)
        anim.addRow("Frame interval", self.interval_spin)
        self.loop_check = QCheckBox("Loop")
        self.loop_check.toggled.connect(self._on_loop)
        anim.addRow(self.loop_check)
        layout.addWidget(animation)

        # --- probe
        probe = QGroupBox("Probe")
        probe_layout = QVBoxLayout(probe)
        self.probe_check = QCheckBox("Click in the viewport to read the field")
        self.probe_check.toggled.connect(self._on_probe_toggled)
        self.controller.window.actions["results.probe"].toggled.connect(self._sync)
        probe_layout.addWidget(self.probe_check)
        self.probe_label = QLabel(self.controller.probe_text)
        self.probe_label.setWordWrap(True)
        self.probe_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        probe_layout.addWidget(self.probe_label)
        layout.addWidget(probe)
        layout.addStretch(1)

    # ------------------------------------------------------------------ helpers
    def _apply(self, **changes: object) -> None:
        """Hand an edit to the controller; show why if it is refused."""
        if self._syncing:
            return
        try:
            self.controller.update(self.name, **changes)
            self.message_label.setText("")
        except ModelError as exc:
            self.message_label.setText(str(exc))
        self._sync()

    @staticmethod
    def _number(text: str) -> float:
        try:
            return float(text.replace(",", "."))
        except ValueError:
            raise ModelError(f"{text!r} is not a number") from None

    # ----------------------------------------------------------------- handlers
    def _on_field(self, _index: int) -> None:
        self._apply(field=self.field_combo.currentData())

    def _on_step(self, value: int) -> None:
        self._apply(step=value)

    def _on_time(self) -> None:
        if self._syncing:
            return
        try:
            time = self._number(self.time_edit.text())
        except ModelError as exc:
            self.message_label.setText(str(exc))
            self._sync()
            return
        units = self.controller.document.model.display_units
        self._apply(step=self.controller.step_for_time(float(to_si(time, "time", units))))

    def _on_range_mode(self, _index: int) -> None:
        self._apply(range_mode=self.range_combo.currentData())

    def _on_limits(self) -> None:
        if self._syncing:
            return
        try:
            lo, hi = self._number(self.min_edit.text()), self._number(self.max_edit.text())
        except ModelError as exc:
            self.message_label.setText(str(exc))
            self._sync()
            return
        self._apply(range_mode="manual", vmin=lo, vmax=hi)

    def _on_play(self, checked: bool) -> None:
        if self._syncing:
            return
        if checked:
            self.controller.play()
        else:
            self.controller.pause()
        self._sync()

    def _on_interval(self, value: int) -> None:
        if not self._syncing:
            self.controller.set_interval(value)

    def _on_loop(self, on: bool) -> None:
        if not self._syncing:
            self.controller.loop = on

    def _on_probe_toggled(self, on: bool) -> None:
        if not self._syncing:
            self.controller.set_probe(on)

    def _on_probe(self, text: str) -> None:
        self.probe_label.setText(text)

    # --------------------------------------------------------------------- sync
    def _sync(self, *_args: object) -> None:
        """Show the controller's state (without feeding it back as edits)."""
        controller = self.controller
        obj = controller.get(self.name)
        if obj is None:
            return
        self._syncing = True
        try:
            is_contour = obj.kind == "contour"
            status = controller.status()
            self.header_label.setText("\n".join(status.lines))
            self.stale_label.setText(_changes_text(status))
            self.stale_label.setVisible(status.out_of_date)
            self.scale_group.setVisible(is_contour)
            for widget in self.field_row:
                widget.setVisible(is_contour)
            for widget in self.density_row:
                widget.setVisible(not is_contour)

            n = controller.n_steps
            self.step_slider.setRange(0, max(n - 1, 0))
            self.step_spin.setRange(0, max(n - 1, 0))
            self.step_slider.setValue(obj.step)
            self.step_spin.setValue(obj.step)
            self.step_slider.setEnabled(n > 1)
            self.step_spin.setEnabled(n > 1)
            units = controller.document.model.display_units
            if controller.results is not None and is_steady(controller.results):
                self.time_unit.setText("")
                self.time_edit.setText("steady state")  # a steady file has no time to show
            else:
                self.time_unit.setText(unit_label("time", units))
                shown_time = float(from_si(controller.time_of(obj.step), "time", units))
                self.time_edit.setText(f"{shown_time:.6g}")
            self.time_edit.setEnabled(n > 1)
            self.mesh_check.setChecked(obj.show_mesh)

            if is_contour:
                index = self.field_combo.findData(obj.field)
                if index >= 0:
                    self.field_combo.setCurrentIndex(index)
                self.range_combo.setCurrentIndex(self.range_combo.findData(obj.range_mode))
                shown = controller.displayed_range
                if obj.range_mode == "manual":
                    shown = (obj.vmin, obj.vmax)  # type: ignore[assignment]
                if shown is not None:
                    self.min_edit.setText(f"{shown[0]:.6g}")
                    self.max_edit.setText(f"{shown[1]:.6g}")
                self.min_edit.setReadOnly(obj.range_mode != "manual")
                self.max_edit.setReadOnly(obj.range_mode != "manual")
                self.banded_check.setChecked(obj.banded)
                self.levels_spin.setValue(obj.levels)
                self.levels_spin.setEnabled(obj.banded)
                self.markers_check.setChecked(obj.markers)
            else:
                self.density_spin.setValue(obj.density)

            self.play_button.setEnabled(controller.can_play)
            self.play_button.setChecked(controller.playing)
            self.play_button.setText("Pause" if controller.playing else "Play")
            self.interval_spin.setValue(controller.interval_ms)
            self.loop_check.setChecked(controller.loop)
            self.probe_check.setChecked(controller.probe_active)
            self.probe_check.setEnabled(controller.results is not None)
        finally:
            self._syncing = False
