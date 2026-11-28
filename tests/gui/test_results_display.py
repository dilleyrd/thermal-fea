"""M8.10: result objects, display controls, probe and animation.

Two small solved models are built once per module (a steady one, in degC, and a short
transient one, in K). A recording fake ``SceneView`` shows what the controller hands to the
viewport; one smoke test uses the real ``MplSceneView``. Everything is offscreen, nothing is
executed modally, and every wait is bounded; the animation timer is stopped after each test.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.units import UnitSettings, from_si
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.results import ResultPanel
from thermalfea.gui.results_tools import (
    ContourObject,
    VectorObject,
    attach_results,
)
from thermalfea.gui.scene import FieldDisplay, SceneView
from thermalfea.gui.viewport_mpl import MplSceneView
from thermalfea.model import bcs
from thermalfea.model.model import Model
from thermalfea.model.serialize import to_json
from thermalfea.model.settings import SolutionSettings
from thermalfea.post.path import value_at
from thermalfea.post.plots import contour_data, display_value, field_range, vector_data
from thermalfea.post.results import Results

WAIT = 10000  # ms


class RecordingView(QObject):
    """A SceneView stand-in that records the fields it is given."""

    selection_changed = Signal(int, list)
    point_picked = Signal(float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.fields: list[FieldDisplay | None] = []

    @property
    def last(self) -> FieldDisplay | None:
        return self.fields[-1] if self.fields else None

    def widget(self) -> Any:  # pragma: no cover - never shown
        raise NotImplementedError

    def set_field(self, spec: FieldDisplay | None) -> None:
        self.fields.append(spec)

    def set_geometry(self, built: Any) -> None: ...
    def set_mesh(self, mesh: Any, color_by: Any = None) -> None: ...
    def set_symbols(self, symbols: Any) -> None: ...
    def set_entity_colors(self, dim, colors, legend) -> None: ...

    def set_overlay(self, layer: str, items: Any) -> None: ...
    def set_selection_mode(self, mode: Any) -> None: ...
    def set_axis_visible(self, visible: bool) -> None: ...
    def highlight(self, dim: int, tags: Any) -> None: ...
    def fit(self) -> None: ...
    def save_image(self, path: str, dpi: int = 200) -> None: ...


def solved(tmp_path_factory: pytest.TempPathFactory, kind: str) -> tuple[Model, Path]:
    """Solve a 1 m x 0.5 m copper plate, fixed 400 K on the west, convection on the east."""
    model = api.new_model(name=f"plate-{kind}")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5)
    model.mesh_settings.global_size = 0.1
    built = api.build(model)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs += [
        bcs.FixedTemperature("hot", "west", T=400.0),
        bcs.Convection("cool", "east", h=100.0, T_inf=300.0),
    ]
    if kind == "transient":
        model.solution = SolutionSettings(
            kind="transient", end_time=60.0, auto_timestep=False, initial_dt=10.0,
            output="every_n", output_every=1,
        )  # fmt: skip
    else:
        model.display_units = UnitSettings(temperature="degC")
    mesh = api.mesh(model, built)
    path = tmp_path_factory.mktemp(kind) / "results.h5"
    api.solve(model, mesh, built=built, path=path)
    return model, path


@pytest.fixture(scope="module")
def steady_case(tmp_path_factory: pytest.TempPathFactory) -> tuple[Model, Path]:
    return solved(tmp_path_factory, "steady")


@pytest.fixture(scope="module")
def transient_case(tmp_path_factory: pytest.TempPathFactory) -> tuple[Model, Path]:
    return solved(tmp_path_factory, "transient")


def make_shell(window, model: Model, path: Path, tmp_path: Path, view: Any = None):
    """Tree, property controller and result controller as in the application."""
    document = Document(model)
    view = view if view is not None else RecordingView()
    tree, props = attach_tree(window, document, None)
    ctrl = attach_results(window, document, view)
    local = tmp_path / "work.h5"
    shutil.copy(path, local)
    return SimpleNamespace(
        window=window, doc=document, view=view, tree=tree, props=props, ctrl=ctrl, path=local
    )


@pytest.fixture
def steady(window, steady_case, tmp_path):
    model, path = steady_case
    shell = make_shell(window, model, path, tmp_path)
    shell.doc.set_results(shell.path)
    yield shell
    shell.ctrl.pause()


@pytest.fixture
def transient(window, transient_case, tmp_path):
    model, path = transient_case
    shell = make_shell(window, model, path, tmp_path)
    shell.doc.set_results(shell.path)
    yield shell
    shell.ctrl.pause()


def open_panel(shell, name: str | None = None) -> ResultPanel:
    name = name or shell.ctrl.shown
    shell.props.show_object(("result", name))
    panel = shell.props.result_panel
    assert isinstance(panel, ResultPanel) and panel.name == name
    return panel


def choose(combo, data: Any) -> None:
    index = combo.findData(data)
    assert index >= 0
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def solution_actions(shell) -> dict[str, Any]:
    acts = shell.tree.actions_for(shell.tree.section_item("solution"))
    return {a.data()[1]: a for a in acts}


def object_actions(shell, name: str) -> dict[str, Any]:
    acts = shell.tree.actions_for(shell.tree.item_for(("result", name)))
    return {a.text(): a for a in acts}


# ----------------------------------------------------------------------------- the tree
def test_view_is_a_scene_view() -> None:
    assert isinstance(RecordingView(), SceneView)


def test_default_contour_appears_after_results_arrive(window, steady_case, tmp_path) -> None:
    model, path = steady_case
    shell = make_shell(window, model, path, tmp_path)
    assert shell.ctrl.objects == [] and shell.view.last is None
    assert not window.actions["results.add_contour"].isEnabled()
    shell.doc.set_results(shell.path)
    (obj,) = shell.ctrl.objects
    assert isinstance(obj, ContourObject) and obj.field == "T" and shell.ctrl.shown == obj.name
    assert shell.tree.item_for(("result", obj.name)) is not None
    spec = shell.view.last
    assert spec is not None and spec.label.startswith("Temperature") and "°C" in spec.label
    assert window.actions["results.add_contour"].isEnabled()
    # a second results notification does not add a second default object
    shell.doc.set_results(shell.path)
    assert len(shell.ctrl.objects) == 1


def test_add_rename_duplicate_show_delete_through_the_tree(steady) -> None:
    ctrl, tree = steady.ctrl, steady.tree
    first = ctrl.objects[0].name
    acts = solution_actions(steady)
    assert set(acts) == {"contour", "vector"}
    acts["contour"].trigger()
    acts["vector"].trigger()
    assert [o.kind for o in ctrl.objects] == ["contour", "contour", "vector"]
    assert len({o.name for o in ctrl.objects}) == 3
    vector = ctrl.objects[2]
    assert ctrl.shown == vector.name  # the new one is shown (and selected in the tree)
    assert steady.props.result_panel is not None and steady.props.result_panel.name == vector.name
    assert tree.address_of(tree.currentItem()) == ("result", vector.name)
    assert steady.view.last.vector_xy is not None

    # rename inline: refused names leave the object alone
    item = tree.item_for(("result", first))
    errors: list[str] = []
    tree.error_occurred.connect(errors.append)
    item.setText(0, vector.name)
    assert errors and ctrl.get(first) is not None
    item = tree.item_for(("result", first))
    item.setText(0, "Wall temperature")
    assert ctrl.get("Wall temperature") is not None and ctrl.get(first) is None
    assert tree.item_for(("result", "Wall temperature")) is not None

    # the object context menu
    names = set(object_actions(steady, "Wall temperature"))
    assert {"Show", "Duplicate", "Delete"} <= names
    object_actions(steady, "Wall temperature")["Show"].trigger()
    assert ctrl.shown == "Wall temperature"
    object_actions(steady, "Wall temperature")["Duplicate"].trigger()
    copy = ctrl.shown
    assert copy != "Wall temperature" and ctrl.get(copy).field == "T"
    original = ctrl.objects.index(ctrl.get("Wall temperature"))
    assert ctrl.objects.index(ctrl.get(copy)) == original + 1
    n = len(ctrl.objects)
    object_actions(steady, copy)["Delete"].trigger()
    assert len(ctrl.objects) == n - 1 and ctrl.get(copy) is None
    assert ctrl.shown is not None and ctrl.get(ctrl.shown) is not None
    assert tree.item_for(("result", copy)) is None
    # the open panel followed the displayed object
    assert steady.props.result_panel is not None
    assert steady.props.result_panel.name == ctrl.shown
    # deleting everything clears the display
    for obj in list(ctrl.objects):
        ctrl.delete(obj.name)
    assert ctrl.shown is None and steady.view.last is None


def test_result_objects_are_not_model_data(steady) -> None:
    doc, ctrl = steady.doc, steady.ctrl
    before = to_json(doc.model)
    stale = doc.results_stale
    count = doc.undo_stack.count()
    ctrl.add_contour("qmag")
    ctrl.add_vectors()
    ctrl.update(ctrl.shown, density=10)
    ctrl.rename_object(ctrl.shown, "Arrows")
    ctrl.duplicate("Arrows")
    ctrl.delete("Arrows")
    panel = open_panel(steady, ctrl.objects[0].name)
    panel.mesh_check.setChecked(True)
    assert to_json(doc.model) == before
    assert not doc.modified and doc.undo_stack.count() == count
    assert doc.results_stale == stale


# ---------------------------------------------------------------------------- the controls
def test_steady_result_panel_says_steady_state_not_a_time(steady) -> None:
    """M11.8 (Q26.4 f): the time box and the contour title of a steady file show no time."""
    panel = open_panel(steady)
    assert panel.time_edit.text() == "steady state" and panel.time_unit.text() == ""
    assert not panel.time_edit.isEnabled()
    assert "steady state" in steady.view.last.title and "t = " not in steady.view.last.title


def test_field_step_and_time_controls(transient) -> None:
    ctrl, view = transient.ctrl, transient.view
    results = Results(transient.path)
    assert results.n_steps >= 6 and ctrl.n_steps == results.n_steps
    name = ctrl.shown
    assert ctrl.get(name).step == results.n_steps - 1  # the last step is shown first
    panel = open_panel(transient)
    assert set(ctrl.fields()) == {"T", "qx", "qy", "qmag", "gradx", "grady", "gradmag"}
    offered = [panel.field_combo.itemData(i) for i in range(panel.field_combo.count())]
    assert offered == ctrl.fields()

    panel.step_spin.setValue(2)
    spec = view.last
    np.testing.assert_allclose(spec.values, results.temperature(2))  # model in K
    assert spec.title == contour_data(results, 2, "T").title
    assert panel.step_slider.value() == 2
    assert float(panel.time_edit.text()) == pytest.approx(results.times[2])

    panel.step_slider.setValue(4)
    assert ctrl.get(name).step == 4 and panel.step_spin.value() == 4
    np.testing.assert_allclose(view.last.values, results.temperature(4))

    # typing a time jumps to the nearest stored step
    target = 0.5 * (results.times[1] + results.times[2]) + 0.1 * (
        results.times[2] - results.times[1]
    )
    panel.time_edit.setText(f"{target:.6g}")
    panel.time_edit.editingFinished.emit()
    assert ctrl.get(name).step == 2
    panel.time_edit.setText("1e9")
    panel.time_edit.editingFinished.emit()
    assert ctrl.get(name).step == results.n_steps - 1
    panel.time_edit.setText("soon")
    panel.time_edit.editingFinished.emit()
    assert "not a number" in panel.message_label.text()
    panel.step_spin.setValue(0)
    assert ctrl.step_for_time(-5.0) == 0

    # the field
    choose(panel.field_combo, "qmag")
    data = contour_data(results, 0, "qmag")
    assert view.last.label == data.label
    assert view.last.vmin == pytest.approx(data.vmin) and view.last.vmax == pytest.approx(data.vmax)
    assert ctrl.get(name).field == "qmag"
    assert "W/m" in view.last.label


def test_temperature_values_in_display_units(steady) -> None:
    results = Results(steady.path)
    spec = steady.view.last
    expected = from_si(results.temperature(0), "temperature", UnitSettings(temperature="degC"))
    np.testing.assert_allclose(spec.values, expected)
    assert spec.vmin == pytest.approx(float(np.min(expected)))
    assert spec.vmax == pytest.approx(float(np.max(expected)))


def test_range_levels_smooth_mesh_and_markers(transient) -> None:
    ctrl, view = transient.ctrl, transient.view
    results = Results(transient.path)
    name = ctrl.shown
    panel = open_panel(transient)
    panel.step_spin.setValue(3)
    data = contour_data(results, 3, "T")
    spec = view.last

    # auto (this step) is the default
    assert (spec.vmin, spec.vmax) == pytest.approx((data.vmin, data.vmax))
    # auto (all steps): the extrema over every stored step, the same for every step
    choose(panel.range_combo, "auto_all")
    lo, hi = field_range(results, "T")
    assert (view.last.vmin, view.last.vmax) == pytest.approx((lo, hi))
    panel.step_spin.setValue(1)
    assert (view.last.vmin, view.last.vmax) == pytest.approx((lo, hi))
    assert lo <= contour_data(results, 1, "T").vmin
    # manual range: filled in from what was shown, then edited in display units
    choose(panel.range_combo, "manual")
    assert ctrl.get(name).vmin == pytest.approx(lo) and ctrl.get(name).vmax == pytest.approx(hi)
    panel.min_edit.setText("310")
    panel.max_edit.setText("390")
    panel.max_edit.editingFinished.emit()
    assert (view.last.vmin, view.last.vmax) == (310.0, 390.0)
    # a reversed range is refused and nothing changes
    panel.min_edit.setText("500")
    panel.min_edit.editingFinished.emit()
    assert "below" in panel.message_label.text()
    assert (ctrl.get(name).vmin, ctrl.get(name).vmax) == (310.0, 390.0)
    assert panel.min_edit.text() == "310"
    # back to auto
    choose(panel.range_combo, "auto_step")
    assert view.last.vmin == pytest.approx(contour_data(results, 1, "T").vmin)

    # levels and banded / smooth
    assert view.last.levels == 12
    panel.levels_spin.setValue(7)
    assert view.last.levels == 7
    panel.banded_check.setChecked(False)
    assert view.last.levels is None and not panel.levels_spin.isEnabled()
    panel.banded_check.setChecked(True)
    assert view.last.levels == 7

    # mesh overlay
    assert view.last.show_mesh is False
    panel.mesh_check.setChecked(True)
    assert view.last.show_mesh is True

    # min / max markers
    panel.step_spin.setValue(3)
    data = contour_data(results, 3, "T")
    assert len(view.last.markers) == 2
    (x0, y0, t0), (x1, y1, t1) = view.last.markers
    assert (x0, y0) == pytest.approx(tuple(data.xy_min)) and t0.startswith("min")
    assert (x1, y1) == pytest.approx(tuple(data.xy_max)) and t1.startswith("max")
    panel.markers_check.setChecked(False)
    assert view.last.markers == []


def test_changing_the_field_leaves_a_manual_range(steady) -> None:
    ctrl = steady.ctrl
    name = ctrl.shown
    ctrl.update(name, range_mode="manual", vmin=10.0, vmax=20.0)
    ctrl.update(name, field="qmag")
    obj = ctrl.get(name)
    assert obj.range_mode == "auto_step" and obj.vmin is None
    with pytest.raises(ModelError):
        ctrl.update(name, levels=0)
    with pytest.raises(ModelError):
        ctrl.update(name, field="nonsense")
    with pytest.raises(ModelError):
        ctrl.update(name, density=3)  # a contour has no density
    with pytest.raises(ModelError):
        ctrl.update("missing", step=1)


def test_vector_object(transient) -> None:
    ctrl, view = transient.ctrl, transient.view
    results = Results(transient.path)
    name = ctrl.add_vectors()
    assert isinstance(ctrl.get(name), VectorObject)
    panel = open_panel(transient, name)
    assert panel.scale_group.isHidden() and not panel.density_spin.isHidden()
    panel.step_spin.setValue(2)
    panel.density_spin.setValue(12)
    expected = vector_data(results, 2, 12)
    spec = view.last
    np.testing.assert_allclose(spec.vector_xy, expected.xy)
    np.testing.assert_allclose(spec.vector_uv, expected.q)
    np.testing.assert_allclose(spec.vector_values, expected.magnitude)
    assert spec.title == expected.title and spec.triangles.shape[0] == 0
    panel.mesh_check.setChecked(True)
    assert view.last.show_mesh
    # a contour panel shows the color-scale group
    contour = ctrl.add_contour("gradmag")
    other = open_panel(transient, contour)
    assert not other.scale_group.isHidden() and other.density_spin.isHidden()
    assert "K/m" in view.last.label or "°C/m" in view.last.label or "/m" in view.last.label


# ------------------------------------------------------------------------------- the probe
def test_probe_node_interior_and_outside(steady) -> None:
    ctrl, view, window = steady.ctrl, steady.view, steady.window
    results = Results(steady.path)
    # off: clicks do nothing
    view.point_picked.emit(0.5, 0.25, 0.0)
    assert ctrl.probes == []
    window.actions["results.probe"].setChecked(True)
    assert ctrl.probe_active

    centre = np.array([0.5, 0.25])
    nodes = results.mesh.nodes[:, :2]
    node = int(np.argmin(np.linalg.norm(nodes - centre, axis=1)))
    x, y = nodes[node]
    view.point_picked.emit(float(x), float(y), 0.0)
    reading = ctrl.probes[-1]
    expected = from_si(results.temperature(0)[node], "temperature", UnitSettings("degC"))
    assert reading.inside and reading.value == pytest.approx(float(expected), rel=1e-9)
    assert reading.unit == "°C" and "°C" in reading.text and "Temperature" in reading.text
    assert window.statusBar().currentMessage() == reading.text

    # an interior point equals post.path.value_at in display units
    px, py = 0.37, 0.19
    view.point_picked.emit(px, py, 0.0)
    si = value_at(results, 0, [px, py], "T")
    assert ctrl.probes[-1].value == pytest.approx(display_value(results, "T", si)[0])

    # flux magnitude for a flux contour
    ctrl.update(ctrl.shown, field="qmag")
    view.point_picked.emit(px, py, 0.0)
    assert ctrl.probes[-1].value == pytest.approx(value_at(results, 0, [px, py], "qmag"))
    assert ctrl.probes[-1].unit == "W/m^2"

    # outside the model
    view.point_picked.emit(10.0, 10.0, 0.0)
    out = ctrl.probes[-1]
    assert not out.inside and "outside" in out.text and np.isnan(out.value)
    assert "outside" in window.statusBar().currentMessage()

    # the panel shows the readout and follows the action
    panel = open_panel(steady)
    assert "outside" in panel.probe_label.text() and panel.probe_check.isChecked()
    panel.probe_check.setChecked(False)
    assert not window.actions["results.probe"].isChecked()
    count = len(ctrl.probes)
    view.point_picked.emit(px, py, 0.0)
    assert len(ctrl.probes) == count
    # a vector object is probed for the heat-flux magnitude
    ctrl.add_vectors()
    reading = ctrl.probe_at(px, py)
    assert reading.value == pytest.approx(value_at(results, 0, [px, py], "qmag"))


# --------------------------------------------------------------------------- the animation
def test_play_advances_and_stops_at_the_last_step(transient) -> None:
    ctrl = transient.ctrl
    name = ctrl.shown
    last = ctrl.n_steps - 1
    ctrl.set_interval(10)
    assert ctrl.interval_ms == 10 and ctrl.can_play and not ctrl.playing
    ctrl.update(name, step=1)
    states: list[bool] = []
    ctrl.playing_changed.connect(states.append)
    assert ctrl.play() and ctrl.playing
    seen = [ctrl.get(name).step]
    while ctrl.playing:
        ctrl.tick()
        seen.append(ctrl.get(name).step)
    assert seen == list(range(1, last + 1))  # stops on the last step, shown
    assert states == [True, False]
    ctrl.tick()  # a stray tick after the stop does nothing
    assert ctrl.get(name).step == last
    # playing from the last step starts again at step 0
    assert ctrl.play() and ctrl.get(name).step == 0
    ctrl.pause()
    assert not ctrl.playing
    # looping wraps instead of stopping
    ctrl.loop = True
    ctrl.update(name, step=last)
    ctrl.play()
    ctrl.update(name, step=last)
    ctrl.tick()
    assert ctrl.playing and ctrl.get(name).step == 0
    ctrl.pause()
    # each frame hands exactly one new field to the view
    n = len(transient.view.fields)
    ctrl.tick()
    assert len(transient.view.fields) == n + 1


def test_play_with_the_timer_and_the_panel(qtbot, transient) -> None:
    ctrl = transient.ctrl
    panel = open_panel(transient)
    panel.interval_spin.setValue(10)
    assert ctrl.interval_ms == 10
    panel.step_spin.setValue(0)
    panel.play_button.click()
    assert ctrl.playing and panel.play_button.text() == "Pause"
    assert transient.window.actions["results.play"].isChecked()
    qtbot.waitUntil(lambda: not ctrl.playing, timeout=WAIT)
    assert ctrl.get(ctrl.shown).step == ctrl.n_steps - 1
    assert panel.play_button.text() == "Play" and not panel.play_button.isChecked()
    # the menu action starts and stops it too
    transient.window.actions["results.play"].trigger()
    assert ctrl.playing
    transient.window.actions["results.play"].trigger()
    assert not ctrl.playing


def test_animation_stops_when_the_object_or_results_change(transient, steady_case) -> None:
    ctrl = transient.ctrl
    ctrl.update(ctrl.shown, step=0)
    ctrl.play()
    other = ctrl.add_contour("qmag")
    assert not ctrl.playing  # the displayed object changed
    ctrl.update(other, step=0)
    ctrl.play()
    assert ctrl.playing
    ctrl.delete(other)
    assert not ctrl.playing
    ctrl.update(ctrl.shown, step=0)
    ctrl.play()
    transient.doc.set_results(transient.path)
    assert not ctrl.playing
    # a steady result has nothing to animate
    assert not (ctrl.n_steps < 2 and ctrl.can_play)


# ------------------------------------------------------------------ results come and go
def test_results_replaced_by_a_shorter_file_clamp_the_step(transient, steady_case) -> None:
    ctrl, view = transient.ctrl, transient.view
    name = ctrl.shown
    ctrl.update(name, step=ctrl.n_steps - 1)
    assert ctrl.get(name).step > 0
    shutil.copy(steady_case[1], transient.path)  # one stored step, solved with degC display
    transient.doc.set_results(transient.path)
    assert ctrl.n_steps == 1 and ctrl.get(name).step == 0
    kelvin = Results(transient.path).temperature(0)
    np.testing.assert_allclose(view.last.values, kelvin - 273.15)  # the new file shows degC
    assert not ctrl.can_play


def test_results_cleared_clears_the_display(steady) -> None:
    ctrl, view = steady.ctrl, steady.view
    assert view.last is not None
    steady.doc.set_model(Model())
    assert view.last is None and view.fields[-1] is None and ctrl.display is None
    assert not steady.window.actions["results.add_contour"].isEnabled()
    assert not steady.window.actions["results.probe"].isEnabled()
    # a new model does not keep the old model's result objects (M11.25, REVIEW-2.md
    # 2.1-15); results from a new solve show again, with a default contour
    assert not ctrl.objects and not ctrl.probes
    steady.doc.set_results(steady.path)
    assert view.last is not None and ctrl.objects


def test_unreadable_results_show_nothing(steady, tmp_path) -> None:
    bad = tmp_path / "bad.h5"
    bad.write_bytes(b"not a results file")
    steady.doc.set_results(bad)
    assert steady.ctrl.results is None and steady.view.last is None
    assert "cannot be read" in steady.window.statusBar().currentMessage()


def test_stale_results_are_shown_with_a_note(steady) -> None:
    panel = open_panel(steady)
    assert panel.stale_label.isHidden()
    # the note follows the comparison with the stored model (M11.59), not the stale flag
    steady.doc.edit("h", lambda m: setattr(m.bcs[1], "h", 150.0))
    panel = open_panel(steady)
    assert not panel.stale_label.isHidden() and "out of date" in panel.stale_label.text()
    assert steady.view.last is not None  # still displayed
    steady.doc.undo_stack.undo()
    assert panel.stale_label.isHidden() or open_panel(steady).stale_label.isHidden()


def test_menu_actions_add_objects(steady) -> None:
    actions = steady.window.actions
    n = len(steady.ctrl.objects)
    actions["results.add_contour"].trigger()
    actions["results.add_vectors"].trigger()
    assert len(steady.ctrl.objects) == n + 2
    for key in ("results.add_contour", "results.add_vectors", "results.probe", "results.play"):
        assert actions[key] in steady.window.menus["results"].actions()


# --------------------------------------------------------------------- the real viewport
def test_real_viewport_axes_stay_put_while_stepping(
    window, qtbot, transient_case, tmp_path
) -> None:
    model, path = transient_case
    view = MplSceneView()
    qtbot.addWidget(view.widget())
    view.widget().resize(640, 480)
    shell = make_shell(window, model, path, tmp_path, view=view)
    shell.doc.set_results(shell.path)
    view.set_mesh(Results(shell.path).mesh)
    name = shell.ctrl.objects[0].name
    shell.ctrl.show(name)
    bounds = view.axes.get_position().bounds
    for k in range(10):
        shell.ctrl.update(name, step=(k + 1) % shell.ctrl.n_steps)
        assert view.axes.get_position().bounds == pytest.approx(bounds, abs=1e-9)
    shell.ctrl.pause()


def test_manual_scale_applies_on_a_uniform_field(steady, monkeypatch) -> None:
    ctrl, view = steady.ctrl, steady.view
    name = ctrl.shown
    # a uniform field: its automatic range is empty (min == max)
    monkeypatch.setattr(ctrl, "_auto_range", lambda obj: (5.0, 5.0))
    ctrl.update(name, range_mode="manual")  # must not be refused
    assert ctrl.get(name).range_mode == "manual"
    ctrl.update(name, vmin=300.0, vmax=400.0)
    assert (view.last.vmin, view.last.vmax) == (300.0, 400.0)
    # user limits that are not ordered are still refused
    with pytest.raises(ModelError):
        ctrl.update(name, vmin=400.0, vmax=300.0)
    with pytest.raises(ModelError):
        ctrl.update(name, vmin=300.0, vmax=300.0)
    assert (ctrl.get(name).vmin, ctrl.get(name).vmax) == (300.0, 400.0)


def test_real_viewport_draws_contour_then_vectors(window, qtbot, steady_case, tmp_path) -> None:
    model, path = steady_case
    view = MplSceneView()
    qtbot.addWidget(view.widget())
    view.widget().resize(640, 480)
    shell = make_shell(window, model, path, tmp_path, view=view)
    shell.doc.set_results(shell.path)
    view.set_mesh(Results(shell.path).mesh)
    shell.ctrl.show(shell.ctrl.objects[0].name)
    assert view.layer_artists("results")
    contour_artists = list(view.layer_artists("results"))
    png = tmp_path / "contour.png"
    view.save_image(str(png))
    assert png.stat().st_size > 0 and png.read_bytes()[:4] == b"\x89PNG"
    shell.ctrl.add_vectors()
    assert view.layer_artists("results")
    assert list(view.layer_artists("results")) != contour_artists
    png2 = tmp_path / "vectors.png"
    view.save_image(str(png2))
    assert png2.read_bytes()[:4] == b"\x89PNG"
    shell.ctrl.pause()
