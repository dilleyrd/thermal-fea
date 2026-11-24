"""M10.4: unit systems in the GUI: dialog, forms, stale flags, colour bar, charts.

A small transient plate is solved once per module. Everything is offscreen; the dialog is
never executed modally (``apply`` / ``accept`` are called directly).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal

from thermalfea import api
from thermalfea.core.forms import form_for
from thermalfea.core.functions import Constant, Table
from thermalfea.core.units import PRESETS, UnitSettings
from thermalfea.gui.chart_tools import ENERGY_ID, attach_charts
from thermalfea.gui.dialogs.new_stream import NewStreamDialog
from thermalfea.gui.dialogs.units import CUSTOM, UnitsDialog
from thermalfea.gui.document import Document, classify_change
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.function_editor import FunctionEditor
from thermalfea.gui.property_panels.mesh import parse_refinement
from thermalfea.gui.results_tools import ContourObject, attach_results
from thermalfea.gui.units_tools import attach_units
from thermalfea.model import bcs
from thermalfea.model.model import Model
from thermalfea.model.serialize import to_json
from thermalfea.model.settings import MeshSettings, SolutionSettings

INCH = 0.0254


class FakeView(QObject):
    """A SceneView stand-in that records the fields it is given."""

    selection_changed = Signal(int, list)
    point_picked = Signal(float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.fields: list[Any] = []

    def widget(self) -> Any:  # pragma: no cover - never shown
        raise NotImplementedError

    def set_field(self, spec: Any) -> None:
        self.fields.append(spec)

    def set_geometry(self, built: Any) -> None: ...
    def set_mesh(self, mesh: Any, color_by: Any = None) -> None: ...
    def set_symbols(self, symbols: Any) -> None: ...
    def set_overlay(self, layer: str, items: Any) -> None: ...
    def set_selection_mode(self, mode: Any) -> None: ...
    def highlight(self, dim: int, tags: Any) -> None: ...
    def fit(self) -> None: ...
    def save_image(self, path: str, dpi: int = 200) -> None: ...


@pytest.fixture(scope="module")
def case(tmp_path_factory: pytest.TempPathFactory) -> tuple[Model, Path]:
    model = api.new_model(name="plate-units")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5)
    model.mesh_settings.global_size = 0.25
    built = api.build(model)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs += [
        bcs.FixedTemperature("hot", "west", T=400.0),
        bcs.Convection("cool", "east", h=100.0, T_inf=300.0),
    ]
    model.solution = SolutionSettings(
        kind="transient", end_time=600.0, auto_timestep=False, initial_dt=60.0,
        output="every_n", output_every=1,
    )  # fmt: skip
    mesh = api.mesh(model, built)
    path = tmp_path_factory.mktemp("units") / "results.h5"
    api.solve(model, mesh, built=built, path=path)
    return model, path


@pytest.fixture
def shell(window, case, tmp_path):
    model, path = case
    document = Document(model)
    view = FakeView()
    tree, props = attach_tree(window, document, None)
    results = attach_results(window, document, view)
    charts = attach_charts(window, document, view, results)
    units = attach_units(window, document)
    local = tmp_path / "work.h5"
    shutil.copy(path, local)
    document.set_results(local)
    yield SimpleNamespace(
        window=window, doc=document, view=view, tree=tree, props=props, results=results,
        charts=charts, units=units, path=local,
    )
    results.pause()
    charts.close_windows()


def choose_units(shell, name: str | None = None, **overrides: str) -> bool:
    dialog = UnitsDialog(shell.doc)
    if name is not None:
        dialog.set_preset(name)
    for quantity, unit in overrides.items():
        dialog.set_unit(quantity, unit)
    changed = dialog.apply()
    dialog.deleteLater()
    return changed


# ------------------------------------------------------------------------------ dialog
def test_dialog_shows_the_model_units_and_presets_fill_the_combos(qtbot) -> None:
    doc = Document(Model())
    dialog = UnitsDialog(doc)
    qtbot.addWidget(dialog)
    assert dialog.settings() == UnitSettings()
    assert dialog.preset_combo.currentText() == "SI (m)"
    assert [dialog.preset_combo.itemText(i) for i in range(dialog.preset_combo.count())] == [
        *PRESETS, CUSTOM]
    dialog.set_preset("SI (mm)")
    assert dialog.settings() == UnitSettings.preset("SI (mm)")
    assert dialog.combos["length"].currentData() == "mm"
    assert dialog.combos["pressure"].currentText() == "MPa"
    assert dialog.preset_combo.currentText() == "SI (mm)"
    dialog.set_preset("US customary")
    assert dialog.combos["temperature"].currentText() == "°F"
    assert dialog.combos["conductivity"].currentText() == "BTU/(h ft °F)"
    assert dialog.preset_combo.currentText() == "US customary"
    # an individual override leaves the preset ("Custom"); the SI preset then drops degF
    dialog.set_unit("pressure", "kPa")
    assert dialog.preset_combo.currentText() == CUSTOM
    dialog.set_preset("SI (m)")
    assert dialog.combos["temperature"].currentData() == "degC"  # degF becomes degC
    assert dialog.preset_combo.currentText() == "SI (m)"  # the SI presets accept K or degC
    with pytest.raises(Exception, match="unknown"):
        dialog.set_unit("length", "furlong")


def test_every_unit_choice_is_in_a_combo(qtbot) -> None:
    from thermalfea.core.units import units_of

    dialog = UnitsDialog(Document(Model()))
    qtbot.addWidget(dialog)
    for quantity, combo in dialog.combos.items():
        assert [combo.itemData(i) for i in range(combo.count())] == list(units_of(quantity))


def test_apply_is_one_undoable_edit(qtbot) -> None:
    doc = Document(Model())
    dialog = UnitsDialog(doc)
    qtbot.addWidget(dialog)
    dialog.set_preset("US customary")
    assert dialog.apply() is True
    assert doc.model.display_units == UnitSettings.preset("US customary")
    assert doc.undo_stack.count() == 1 and doc.undo_stack.undoText() == "Change units"
    assert dialog.apply() is False  # nothing new: no second command
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert doc.model.display_units == UnitSettings()
    doc.undo_stack.redo()
    assert doc.model.display_units == UnitSettings.preset("US customary")


def test_accept_applies_and_closes(qtbot) -> None:
    doc = Document(Model())
    dialog = UnitsDialog(doc)
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.set_preset("SI (mm)")
    dialog.accept()
    assert doc.model.display_units.length == "mm" and not dialog.isVisible()
    reopened = UnitsDialog(doc)  # a new dialog shows the model's units
    qtbot.addWidget(reopened)
    assert reopened.preset_combo.currentText() == "SI (mm)"


def test_tools_menu_entry_shows_the_dialog_without_exec(shell) -> None:
    action = shell.window.actions["tools.units"]
    assert action in shell.window.menus["tools"].actions()
    action.trigger()
    dialog = shell.units.dialog
    assert dialog is not None and dialog.isVisible()
    shell.doc.edit("units", lambda m: setattr(m, "display_units", UnitSettings(length="in")))
    action.trigger()  # shown again, with the model's current units
    assert shell.units.dialog is dialog and dialog.combos["length"].currentData() == "in"
    dialog.close()


# ----------------------------------------------------------------------- forms and panels
def test_form_shows_25_mm_and_stores_0_025_m(qtbot) -> None:
    doc = Document(Model())
    choose_units(SimpleNamespace(doc=doc), "SI (mm)")
    panel = FormPanel(form_for(MeshSettings), doc, ("mesh_settings",))
    qtbot.addWidget(panel)
    edit = panel.editors["global_size"]
    assert panel._unit_labels["global_size"].text() == "mm"
    edit.setText("25")
    edit.editingFinished.emit()
    assert doc.model.mesh_settings.global_size == pytest.approx(0.025)
    assert float(edit.text()) == pytest.approx(25.0)
    # switching units re-displays the same stored value, and stores nothing new
    before = doc.model.mesh_settings.global_size
    choose_units(SimpleNamespace(doc=doc), length="in")
    assert panel._unit_labels["global_size"].text() == "in"
    assert float(edit.text()) == pytest.approx(0.025 / INCH)
    assert doc.model.mesh_settings.global_size == before
    choose_units(SimpleNamespace(doc=doc), "SI (m)")
    assert float(edit.text()) == pytest.approx(0.025)
    assert panel._unit_labels["global_size"].text() == "m"


def test_mapping_field_converts_and_shows_its_unit(qtbot) -> None:
    doc = Document(Model())
    choose_units(SimpleNamespace(doc=doc), "SI (mm)")
    panel = FormPanel(form_for(MeshSettings), doc, ("mesh_settings",))
    qtbot.addWidget(panel)
    line = panel.editors["curve_sizes"]
    assert panel._unit_labels["curve_sizes"].text() == "mm"
    line.setText("west=10, east=5")
    line.editingFinished.emit()
    assert doc.model.mesh_settings.curve_sizes == pytest.approx({"west": 0.01, "east": 0.005})
    choose_units(SimpleNamespace(doc=doc), length="in")
    assert line.text() == f"east={0.005 / INCH:.10g}, west={0.01 / INCH:.10g}"
    assert panel.editors["curve_divisions"].text() == ""  # no unit label without a quantity
    assert "curve_divisions" not in panel._unit_labels


def test_solution_panel_times_follow_the_time_unit(qtbot) -> None:
    doc = Document(Model())
    choose_units(SimpleNamespace(doc=doc), time="min")
    spec = form_for(SolutionSettings)
    panel = FormPanel(spec, doc, ("solution",))
    qtbot.addWidget(panel)
    edit = panel.editors["end_time"]
    edit.setText("2")
    edit.editingFinished.emit()
    assert doc.model.solution.end_time == pytest.approx(120.0)
    assert panel._unit_labels["end_time"].text() == "min"
    times = panel.editors["output_times"]
    times.setText("1, 2")
    times.editingFinished.emit()
    assert doc.model.solution.output_times == pytest.approx([60.0, 120.0])


def test_function_editor_converts_and_says_expressions_are_si(qtbot) -> None:
    editor = FunctionEditor("htc", PRESETS["SI (mm)"])
    qtbot.addWidget(editor)
    assert editor.unit_label.text() == "W/(mm^2 K)"
    assert not editor.si_note.isHidden()
    assert "SI" in editor.si_note.text() and "W/(m^2 K)" in editor.si_note.text()
    editor.value_edit.setText("2")
    editor.value_edit.editingFinished.emit()
    assert editor.function() == Constant(2.0e6)
    editor.set_units(UnitSettings())
    assert editor.si_note.isHidden() and editor.unit_label.text() == "W/(m^2 K)"
    assert float(editor.value_edit.text()) == pytest.approx(2.0e6)
    # a table against time in minutes and values in kW
    editor = FunctionEditor("power", UnitSettings(time="min", power="kW"))
    qtbot.addWidget(editor)
    editor.set_function(Table([0.0, 120.0], [1000.0, 3000.0], "t"))
    assert editor.grid.item(1, 0).text() == "2" and editor.grid.item(1, 1).text() == "3"
    assert "min" in editor.grid.horizontalHeaderItem(0).text()
    assert "kW" in editor.grid.horizontalHeaderItem(1).text()


def test_new_stream_dialog_and_refinement_rows_take_display_units(qtbot) -> None:
    us = PRESETS["US customary"]
    dialog = NewStreamDialog(units=us)
    qtbot.addWidget(dialog)
    dialog.fluid_box.setCurrentIndex(1)
    dialog.cross_box.setCurrentIndex(1)
    dialog.flow_area_edit.setText("1")
    dialog.wetted_edit.setText("4")
    dialog.inlet_edit.setText("212")
    stream = dialog.build_stream()
    assert stream.flow_area == pytest.approx(INCH**2)
    assert stream.wetted_perimeter == pytest.approx(4 * INCH)
    assert stream.T_inlet.value == pytest.approx(373.15)
    ref = parse_refinement(["west", "1", "2", "0", "5"], PRESETS["SI (mm)"])
    assert (ref.size_min, ref.size_max, ref.dist_min, ref.dist_max) == pytest.approx(
        (1e-3, 2e-3, 0.0, 5e-3))
    assert parse_refinement(["west", "1", "2", "0", "5"]).size_max == 2.0  # SI default


# ------------------------------------------------------------------------- stale flags
def test_changing_units_changes_nothing_stored_and_nothing_goes_stale(shell) -> None:
    doc = shell.doc
    before = to_json(doc.model)
    stale = (doc.geometry_stale, doc.mesh_stale, doc.results_stale)
    path = doc.results_path
    assert choose_units(shell, "US customary")
    after = to_json(doc.model)
    assert before.pop("display_units") != after.pop("display_units")
    assert before == after  # every other stored value is untouched, still SI
    assert (doc.geometry_stale, doc.mesh_stale, doc.results_stale) == stale
    assert not doc.results_stale
    assert doc.results_path == path
    assert classify_change(to_json(Model()), to_json(Model(display_units=UnitSettings(length="mm")))
                           ) == "none"
    # a real edit still marks the results stale
    doc.edit("size", lambda m: setattr(m.mesh_settings, "global_size", 0.2))
    assert doc.mesh_stale and doc.results_stale
    json.dumps(to_json(doc.model))  # the file stays plain JSON


# --------------------------------------------------------- colour bar, probe and charts
def test_colour_bar_label_and_values_follow_the_units(shell) -> None:
    ctrl = shell.results
    first = shell.view.fields[-1]
    assert first.label == "Temperature [K]"
    kelvin = first.values.copy()
    choose_units(shell, "US customary")
    spec = shell.view.fields[-1]
    assert spec.label == "Temperature [°F]"
    assert spec.values == pytest.approx((kelvin - 273.15) * 1.8 + 32.0)
    assert ctrl.displayed_range == pytest.approx((spec.values.min(), spec.values.max()))
    # probe text reads the length in inches
    reading = ctrl.probe_at(0.5, 0.25)
    assert reading is not None and reading.unit == "°F"
    assert f"x = {0.5 / INCH:.6g} in" in reading.text
    shell.doc.undo_stack.undo()
    assert shell.view.fields[-1].label == "Temperature [K]"
    assert shell.view.fields[-1].values == pytest.approx(kelvin)


def test_manual_colour_range_keeps_its_meaning_when_units_change(shell) -> None:
    ctrl = shell.results
    name = ctrl.shown
    ctrl.update(name, range_mode="manual", vmin=300.0, vmax=400.0)
    choose_units(shell, temperature="degC")
    obj = ctrl.get(name)
    assert isinstance(obj, ContourObject)
    assert (obj.vmin, obj.vmax) == pytest.approx((26.85, 126.85))
    assert ctrl.displayed_range == pytest.approx((26.85, 126.85))


def test_flux_labels_and_vectors(shell) -> None:
    ctrl = shell.results
    flux = ctrl.add_contour("qmag")
    assert shell.view.fields[-1].label == "Heat flux magnitude [W/m^2]"
    choose_units(shell, "US customary")
    assert shell.view.fields[-1].label == "Heat flux magnitude [BTU/(h ft^2)]"
    ctrl.show(ctrl.add_vectors())
    assert shell.view.fields[-1].vector_label == "Heat flux [BTU/(h ft^2)]"
    del flux


def test_open_charts_are_drawn_again_with_the_new_units(shell) -> None:
    chart = shell.charts.plot_energy_balance()
    assert chart is not None
    assert chart.axes.get_ylabel() == "Power [W]" and chart.axes.get_xlabel() == "Time [s]"
    seconds = chart.data.times.copy()
    choose_units(shell, time="min", power="kW")
    assert chart.axes.get_ylabel() == "Power [kW]" and chart.axes.get_xlabel() == "Time [min]"
    assert chart.data.times == pytest.approx(seconds / 60.0)
    path = chart.export_csv(shell.path.parent / "energy.csv")
    assert path is not None
    assert path.read_text(encoding="utf-8").splitlines()[0].startswith("Time [min],")
    # a nodal history picks the temperature unit too
    history = shell.charts.plot_history([0, 1])
    assert history is not None and history.axes.get_ylabel() == "Temperature [K]"
    choose_units(shell, temperature="degF")
    assert history.axes.get_ylabel() == "Temperature [°F]"
    assert shell.window.actions[ENERGY_ID].isEnabled()
    # an undone change redraws too
    shell.doc.undo_stack.undo()
    assert history.axes.get_ylabel() == "Temperature [K]"
