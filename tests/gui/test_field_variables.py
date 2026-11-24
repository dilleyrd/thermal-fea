"""M11.43: a function field's allowed variables (FieldSpec.variables)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QLabel

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec
from thermalfea.core.functions import Expression, Table
from thermalfea.gui.property_panels.function_editor import FunctionEditor
from thermalfea.model.bc_forms import BC_FORMS
from thermalfea.model.material_forms import MATERIAL_FORM


def _field(form, name: str) -> FieldSpec:
    return next(f for f in form.fields if f.name == name)


def _editor(qtbot, spec: FieldSpec) -> FunctionEditor:
    w = FunctionEditor(spec.quantity, variables=spec.variables)
    qtbot.addWidget(w)
    return w


def _variables(w: FunctionEditor) -> list[str]:
    return [w.variable_combo.itemData(i) for i in range(w.variable_combo.count())]


@pytest.mark.parametrize("name", ["k", "k2", "rho", "cp"])
def test_material_field_offers_temperature_only(qtbot, name) -> None:
    assert _variables(_editor(qtbot, _field(MATERIAL_FORM, name))) == ["T"]


def test_heat_power_and_heat_flow_offer_time_only(qtbot) -> None:
    assert _variables(_editor(qtbot, _field(BC_FORMS["heat_power"], "P"))) == ["t"]
    assert _variables(_editor(qtbot, _field(BC_FORMS["heat_flow"], "P"))) == ["t"]


def test_fixed_temperature_offers_time_only_in_a_table(qtbot) -> None:
    w = _editor(qtbot, _field(BC_FORMS["fixed_temperature"], "T"))
    assert _variables(w) == ["t"]


def test_unrestricted_field_offers_time_and_temperature(qtbot) -> None:
    w = _editor(qtbot, _field(BC_FORMS["convection"], "h"))
    assert _variables(w) == ["t", "T"]


def test_label_is_as_a_function_of(qtbot) -> None:
    w = _editor(qtbot, _field(MATERIAL_FORM, "k"))
    texts = [lab.text() for lab in w.findChildren(QLabel)]
    assert "As a function of" in texts
    assert "Against" not in texts


def test_material_expression_using_time_is_refused_live(qtbot) -> None:
    w = _editor(qtbot, _field(MATERIAL_FORM, "k"))
    seen: list = []
    w.function_changed.connect(seen.append)
    w.mode_combo.setCurrentIndex(w.mode_combo.findData("expression"))
    w.expr_edit.setText("300 + t")
    assert "temperature (T) only" in w.error_text()
    w.commit()
    assert seen == []
    w.expr_edit.setText("300 + 0.1*T")
    assert w.error_text() == ""
    w.commit()
    assert len(seen) == 1


def test_heat_power_refuses_temperature_expression(qtbot) -> None:
    w = _editor(qtbot, _field(BC_FORMS["heat_power"], "P"))
    seen: list = []
    w.function_changed.connect(seen.append)
    w.mode_combo.setCurrentIndex(w.mode_combo.findData("expression"))
    w.expr_edit.setText("T")
    assert "time (t) only" in w.error_text()
    w.commit()
    assert seen == []


def test_fixed_temperature_accepts_position_expression_and_refuses_T(qtbot) -> None:
    w = _editor(qtbot, _field(BC_FORMS["fixed_temperature"], "T"))
    seen: list = []
    w.function_changed.connect(seen.append)
    w.mode_combo.setCurrentIndex(w.mode_combo.findData("expression"))
    w.expr_edit.setText("300 + x")
    assert w.error_text() == ""
    w.commit()
    assert len(seen) == 1
    w.expr_edit.setText("300 + T")
    assert "time (t) and position (x, y) only" in w.error_text()


def test_old_file_material_table_against_time_is_shown_with_error(qtbot) -> None:
    w = _editor(qtbot, _field(MATERIAL_FORM, "k"))
    seen: list = []
    w.function_changed.connect(seen.append)
    table = Table([0.0, 10.0], [1.0, 2.0], "t")
    w.set_function(table)
    assert w.mode == "table"
    assert w.variable_combo.currentData() == "t"
    assert w.grid.rowCount() == 2
    assert "temperature (T) only" in w.error_text()
    assert w.function() is table
    assert seen == []


def test_old_file_expression_is_shown_with_error_and_unchanged(qtbot) -> None:
    w = _editor(qtbot, _field(MATERIAL_FORM, "k"))
    expr = Expression("1 + t")
    w.set_function(expr)
    assert w.expr_edit.text() == "1 + t"
    assert w.error_text()
    assert w.function() is expr


def test_fieldspec_refuses_bad_variables() -> None:
    with pytest.raises(ModelError):
        FieldSpec("a", "A", "function", variables=("z",))
    with pytest.raises(ModelError):
        FieldSpec("a", "A", "function", variables=())
    assert FieldSpec("a", "A", "function").variables is None
