"""M8.4: FormPanel (generated forms), unit conversion, limits and undo refresh."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.forms import form_for
from thermalfea.core.functions import Constant, Expression
from thermalfea.core.units import UnitSettings
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.form import FormPanel, format_dict, parse_dict
from thermalfea.model.bcs import Convection, CorrelationConvection
from thermalfea.model.settings import MeshSettings, SolutionSettings


@pytest.fixture
def doc() -> Document:
    model = api.new_model(name="plate")
    model.display_units = UnitSettings(temperature="degC")
    model.bcs.append(Convection("Conv", "cold", h=Constant(10.0), T_inf=Constant(300.0)))
    model.bcs.append(
        CorrelationConvection("Corr", "cold", "natural", "Air", T_inf=Constant(293.15))
    )
    return Document(model)


def panel_for(qtbot, doc, address) -> FormPanel:
    obj = doc.model.bcs[address[1]] if address[0] == "bcs" else getattr(doc.model, address[0])
    p = FormPanel(form_for(type(obj)), doc, address)
    qtbot.addWidget(p)
    return p


def enter(edit, text: str) -> None:
    edit.setText(text)
    edit.editingFinished.emit()


def test_builds_one_editor_per_field(qtbot, doc) -> None:
    p = panel_for(qtbot, doc, ("bcs", 0))
    assert list(p.editors) == ["selection", "h", "T_inf"]
    assert "Convection" in p.title_label.text() and "Conv" in p.title_label.text()
    assert float(p.editors["T_inf"].value_edit.text()) == pytest.approx(26.85)  # degC display
    assert p.editors["h"].value_edit.text() == "10"
    assert p._unit_labels == {}  # function editors carry their own unit label
    assert p.editors["T_inf"].unit_label.text() == "°C"


def test_function_edit_converts_units_and_pushes_one_command(qtbot, doc) -> None:
    p = panel_for(qtbot, doc, ("bcs", 0))
    changes = []
    p.value_changed.connect(lambda n, v: changes.append(n))
    enter(p.editors["T_inf"].value_edit, "25")
    assert doc.model.bcs[0].T_inf.value == pytest.approx(298.15)
    assert doc.undo_stack.count() == 1 and doc.undo_stack.undoText() == "Edit Fluid temperature T∞"
    assert changes == ["T_inf"]
    # the stored model value is in kelvin; the box still shows what was typed (as degC)
    assert float(p.editors["T_inf"].value_edit.text()) == pytest.approx(25.0)
    enter(p.editors["h"].value_edit, "10")  # unchanged: nothing pushed
    assert doc.undo_stack.count() == 1
    enter(p.editors["T_inf"].value_edit, "-300")  # below absolute zero: rejected
    assert doc.undo_stack.count() == 1 and doc.model.bcs[0].T_inf.value == pytest.approx(298.15)
    assert p.editors["T_inf"].error_text()


def test_expression_and_table_edits_through_the_form(qtbot, doc) -> None:
    p = panel_for(qtbot, doc, ("bcs", 0))
    ed = p.editors["h"]
    ed.mode_combo.setCurrentIndex(ed.mode_combo.findData("expression"))
    assert doc.model.bcs[0].h == Expression("10")  # the constant is carried over
    assert doc.undo_stack.count() == 1
    ed.expr_edit.setText("10 +")  # invalid while typing: not applied
    enter(ed.expr_edit, "10 +")
    assert doc.undo_stack.count() == 1 and ed.error_text()
    enter(ed.expr_edit, "10 + t")
    assert doc.model.bcs[0].h == Expression("10 + t")
    ed.mode_combo.setCurrentIndex(ed.mode_combo.findData("table"))
    ed.paste_text("0\t10\n5\t20")
    assert doc.model.bcs[0].h.ys == [10.0, 20.0]
    assert doc.undo_stack.count() == 3  # constant -> expression, edit, table


def test_numeric_field_limits_and_parsing(qtbot, doc) -> None:
    p = panel_for(qtbot, doc, ("bcs", 1))
    length = p.editors["char_length"]
    assert length.text() == ""  # optional, None
    enter(length, "abc")
    assert doc.undo_stack.count() == 0 and length.error_text()
    assert "background" in length.styleSheet()
    enter(length, "-1")
    assert doc.undo_stack.count() == 0 and "at least" in length.error_text()
    enter(length, "0.5")
    assert doc.model.bcs[1].char_length == 0.5 and doc.undo_stack.count() == 1
    assert length.error_text() == "" and length.styleSheet() == ""
    enter(length, "")
    assert doc.model.bcs[1].char_length is None and doc.undo_stack.count() == 2
    enter(p.editors["multiplier"], "-2")
    assert doc.model.bcs[1].multiplier == 1.0
    enter(p.editors["multiplier"], "2,5")  # decimal comma
    assert doc.model.bcs[1].multiplier == 2.5


def test_choice_bool_str_dict_fields(qtbot, doc) -> None:
    p = panel_for(qtbot, doc, ("bcs", 1))
    combo = p.editors["wall_T_mode"]
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert doc.model.bcs[1].wall_T_mode == "average"
    face = p.editors["face_direction"]
    assert [face.itemText(i) for i in range(face.count())] == [
        "Facing up", "Facing down", "(automatic)",
    ]
    face.setCurrentIndex(1)
    face.activated.emit(1)
    assert doc.model.bcs[1].face_direction == "down"
    face.setCurrentIndex(2)
    face.activated.emit(2)
    assert doc.model.bcs[1].face_direction is None
    enter(p.editors["fluid"], "Water")
    assert doc.model.bcs[1].fluid == "Water"
    enter(p.editors["params"], "theta_deg=30, C=0.5")
    assert doc.model.bcs[1].params == {"theta_deg": 30.0, "C": 0.5}
    enter(p.editors["params"], "oops")
    assert doc.model.bcs[1].params == {"theta_deg": 30.0, "C": 0.5}
    assert p.error_text("params")
    assert parse_dict(format_dict({"a": 1.5})) == {"a": 1.5}


def test_derived_settings_forms_and_model_errors(qtbot, doc) -> None:
    p = FormPanel(form_for(SolutionSettings), doc, ("solution",))
    qtbot.addWidget(p)
    box = p.editors["auto_timestep"]
    box.setChecked(False)
    assert doc.model.solution.auto_timestep is False and doc.undo_stack.count() == 1
    enter(p.editors["theta"], "2")  # the class itself rejects it
    assert doc.model.solution.theta == 1.0 and doc.undo_stack.count() == 1
    assert "theta" in p.error_text("theta")
    enter(p.editors["max_iterations"], "12.5")
    assert doc.model.solution.max_iterations == 30 and p.editors["max_iterations"].error_text()
    enter(p.editors["max_iterations"], "12")
    assert doc.model.solution.max_iterations == 12
    enter(p.editors["initial_dt"], "0.1")
    assert doc.model.solution.initial_dt == 0.1
    q = FormPanel(form_for(MeshSettings), doc, ("mesh_settings",))
    qtbot.addWidget(q)
    q.editors["order"].setCurrentIndex(1)
    q.editors["order"].activated.emit(1)
    assert doc.model.mesh_settings.order == 2


def test_undo_redo_refresh_without_new_commands(qtbot, doc) -> None:
    p = panel_for(qtbot, doc, ("bcs", 0))
    enter(p.editors["T_inf"].value_edit, "25")
    enter(p.editors["h"].value_edit, "55")
    assert doc.undo_stack.count() == 2
    doc.undo_stack.undo()
    assert p.editors["h"].value_edit.text() == "10"
    assert float(p.editors["T_inf"].value_edit.text()) == pytest.approx(25.0)
    doc.undo_stack.undo()
    assert float(p.editors["T_inf"].value_edit.text()) == pytest.approx(26.85)
    assert doc.undo_stack.count() == 2 and doc.undo_stack.index() == 0
    doc.undo_stack.redo()
    assert float(p.editors["T_inf"].value_edit.text()) == pytest.approx(25.0)
    assert doc.undo_stack.count() == 2 and doc.undo_stack.index() == 1


def test_number_field_undo_refresh(qtbot, doc) -> None:
    p = panel_for(qtbot, doc, ("bcs", 1))
    enter(p.editors["multiplier"], "3")
    enter(p.editors["multiplier"], "bad")
    assert p.editors["multiplier"].error_text()
    doc.undo_stack.undo()
    assert p.editors["multiplier"].text() == "1"
    assert p.editors["multiplier"].error_text() == ""
    assert doc.undo_stack.count() == 1


def test_display_unit_change_updates_the_widgets(qtbot, doc) -> None:
    p = panel_for(qtbot, doc, ("bcs", 0))
    doc.edit("Units", lambda m: setattr(m, "display_units", UnitSettings(temperature="K")))
    assert float(p.editors["T_inf"].value_edit.text()) == pytest.approx(300.0)
    assert p.editors["T_inf"].unit_label.text() == "K"


def test_panel_disables_when_object_disappears(qtbot, doc) -> None:
    p = panel_for(qtbot, doc, ("bcs", 1))
    doc.edit("Delete", lambda m: m.bcs.pop())
    assert not p.isEnabled()
    doc.undo_stack.undo()
    assert p.isEnabled()
