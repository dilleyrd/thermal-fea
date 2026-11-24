"""M11.9: adding a correlation convection or a radiation condition asks for its values."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.functions import Constant
from thermalfea.core.units import UnitSettings
from thermalfea.gui.dialogs.new_load import (
    NewCorrelationConvectionDialog,
    NewRadiationDialog,
    boundary_correlations,
)
from thermalfea.gui.document import Document
from thermalfea.gui.tree import ModelTree
from thermalfea.model.bcs import CorrelationConvection, RadiationAmbient


@pytest.fixture
def doc(qtbot) -> Document:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5, id="plate")
    return Document(model)


@pytest.fixture
def tree(qtbot, doc) -> ModelTree:
    t = ModelTree(doc)
    qtbot.addWidget(t)
    return t


def menu_add(tree: ModelTree, tag: str) -> None:
    actions = tree.actions_for(tree.section_item("loads"))
    next(a for a in actions if a.data() == ("add_bc", tag)).trigger()


def open_dialog(tree: ModelTree, qtbot, tag: str):
    menu_add(tree, tag)
    dialog = tree.load_dialog
    qtbot.addWidget(dialog)
    assert dialog.isVisible()
    return dialog


def test_adding_a_correlation_convection_opens_the_dialog(tree, doc, qtbot) -> None:
    dialog = open_dialog(tree, qtbot, "correlation_convection")
    assert isinstance(dialog, NewCorrelationConvectionDialog)
    assert doc.model.bcs == [] and doc.undo_stack.count() == 0  # nothing added yet
    assert dialog.correlation_box.currentText() == "" and dialog.fluid_box.currentText() == ""
    assert dialog.ambient_edit.text() == "" and not dialog.ok_button.isEnabled()
    items = [dialog.correlation_box.itemText(i) for i in range(dialog.correlation_box.count())]
    assert items[1:] == list(boundary_correlations()) and "duct_internal" not in items


def test_adding_a_radiation_condition_opens_the_dialog(tree, doc, qtbot) -> None:
    dialog = open_dialog(tree, qtbot, "radiation_ambient")
    assert isinstance(dialog, NewRadiationDialog)
    assert doc.model.bcs == []
    assert dialog.emissivity_edit.text() == "" and dialog.ambient_edit.text() == ""
    assert not dialog.ok_button.isEnabled()


def test_other_loads_are_still_added_at_once(tree, doc) -> None:
    menu_add(tree, "adiabatic")
    assert len(doc.model.bcs) == 1 and doc.undo_stack.count() == 1


def test_correlation_ok_waits_for_every_field(tree, doc, qtbot) -> None:
    d = open_dialog(tree, qtbot, "correlation_convection")
    d.correlation_box.setCurrentText("vplate_natural")
    assert not d.ok_button.isEnabled() and "fluid" in d.message_label.text()
    d.fluid_box.setCurrentText("Air")
    assert not d.ok_button.isEnabled() and "ambient" in d.message_label.text()
    d.ambient_edit.setText("abc")
    assert not d.ok_button.isEnabled()
    d.ambient_edit.setText("0")  # zero kelvin is not a valid ambient
    assert not d.ok_button.isEnabled()
    d.ambient_edit.setText("-5")
    assert not d.ok_button.isEnabled()
    d.ambient_edit.setText("300")
    assert d.ok_button.isEnabled() and d.message_label.text() == ""
    d.correlation_box.setCurrentIndex(0)
    assert not d.ok_button.isEnabled()
    assert doc.model.bcs == []


def test_power_law_needs_no_fluid(tree, qtbot) -> None:
    d = open_dialog(tree, qtbot, "correlation_convection")
    d.correlation_box.setCurrentText("power_law")
    d.ambient_edit.setText("300")
    assert d.ok_button.isEnabled()


@pytest.mark.parametrize("eps", ["", "0", "1.5", "-0.1", "x"])
def test_radiation_ok_waits_for_valid_values(tree, qtbot, eps) -> None:
    d = open_dialog(tree, qtbot, "radiation_ambient")
    d.ambient_edit.setText("300")
    d.emissivity_edit.setText(eps)
    assert not d.ok_button.isEnabled()
    d.emissivity_edit.setText("1")
    assert d.ok_button.isEnabled()
    d.ambient_edit.setText("")
    assert not d.ok_button.isEnabled()


def test_created_correlation_load_holds_the_typed_values_in_kelvin(tree, doc, qtbot) -> None:
    doc.edit("units", lambda m: setattr(m, "display_units", UnitSettings(temperature="degC")))
    before = doc.undo_stack.count()
    d = open_dialog(tree, qtbot, "correlation_convection")
    assert "[K]" not in d.form.labelForField(d.ambient_edit).text()  # shown in the display unit
    d.correlation_box.setCurrentText("vplate_natural")
    d.fluid_box.setCurrentText("Air")
    d.ambient_edit.setText("25")
    d.ok_button.click()
    (bc,) = doc.model.bcs
    assert isinstance(bc, CorrelationConvection)
    assert (bc.correlation, bc.fluid) == ("vplate_natural", "Air")
    assert isinstance(bc.T_inf, Constant) and bc.T_inf.value == pytest.approx(298.15)
    assert bc.selection == "" and bc.params == {} and bc.velocity is None
    assert bc.char_length is None and bc.multiplier == 1.0
    assert doc.undo_stack.count() == before + 1  # one step
    assert not d.isVisible()


def test_created_radiation_load_holds_the_typed_values(tree, doc, qtbot) -> None:
    d = open_dialog(tree, qtbot, "radiation_ambient")
    d.emissivity_edit.setText("0.85")
    d.ambient_edit.setText("293,5")
    d.ok_button.click()
    (bc,) = doc.model.bcs
    assert isinstance(bc, RadiationAmbient)
    assert bc.emissivity == Constant(0.85) and bc.T_inf == Constant(293.5)
    assert doc.undo_stack.count() == 1


def test_cancel_adds_nothing(tree, doc, qtbot) -> None:
    d = open_dialog(tree, qtbot, "radiation_ambient")
    d.emissivity_edit.setText("0.5")
    d.ambient_edit.setText("300")
    d.reject()
    d.close()
    assert not d.isVisible() and doc.model.bcs == [] and doc.undo_stack.count() == 0


def test_undo_removes_the_added_load_in_one_step(tree, doc, qtbot) -> None:
    d = open_dialog(tree, qtbot, "radiation_ambient")
    d.emissivity_edit.setText("0.5")
    d.ambient_edit.setText("300")
    d.ok_button.click()
    assert len(doc.model.bcs) == 1 and doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert doc.model.bcs == []
    doc.undo_stack.redo()
    assert len(doc.model.bcs) == 1


def test_a_second_load_gets_a_unique_name(tree, doc, qtbot) -> None:
    for _ in range(2):
        d = open_dialog(tree, qtbot, "radiation_ambient")
        d.emissivity_edit.setText("0.5")
        d.ambient_edit.setText("300")
        d.ok_button.click()
    assert len({bc.name for bc in doc.model.bcs}) == 2
