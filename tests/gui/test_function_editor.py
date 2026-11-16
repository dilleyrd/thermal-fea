"""M8.4: the FunctionEditor widget (constant / table / expression)."""

from __future__ import annotations

import pytest

from thermalfea.core.functions import Constant, Expression, Table
from thermalfea.core.units import UnitSettings
from thermalfea.gui.property_panels.function_editor import FunctionEditor, parse_pasted


@pytest.fixture
def editor(qtbot) -> FunctionEditor:
    w = FunctionEditor(quantity="temperature", minimum=0.0)
    qtbot.addWidget(w)
    return w


def grid_text(w: FunctionEditor) -> list[tuple[str, str]]:
    return [(w.grid.item(r, 0).text(), w.grid.item(r, 1).text()) for r in range(w.grid.rowCount())]


def test_constant_round_trip(editor, qtbot) -> None:
    seen = []
    editor.function_changed.connect(seen.append)
    editor.value_edit.setText("350")
    editor.value_edit.editingFinished.emit()
    assert seen == [Constant(350.0)]
    editor.set_function(Constant(400.0))  # loading never emits
    assert editor.value_edit.text() == "400" and len(seen) == 1
    assert editor.function() == Constant(400.0)


def test_constant_in_display_units_and_limits(qtbot) -> None:
    w = FunctionEditor(quantity="temperature", settings=UnitSettings(temperature="degC"),
                       minimum=0.0)  # fmt: skip
    qtbot.addWidget(w)
    seen = []
    w.function_changed.connect(seen.append)
    w.value_edit.setText("25")
    w.value_edit.editingFinished.emit()
    assert seen[-1].value == pytest.approx(298.15)
    w.set_function(Constant(300.0))
    assert float(w.value_edit.text()) == pytest.approx(26.85)
    n = len(seen)
    w.value_edit.setText("-300")  # below absolute zero
    w.value_edit.editingFinished.emit()
    assert len(seen) == n and "at least" in w.error_text()
    w.value_edit.setText("abc")
    w.value_edit.editingFinished.emit()
    assert len(seen) == n and w.error_text()
    w.set_function(Constant(300.0))
    w.set_units(UnitSettings(temperature="K"))
    assert float(w.value_edit.text()) == pytest.approx(300.0)


def test_expression_validated_live_and_emitted_when_valid(editor) -> None:
    seen = []
    editor.function_changed.connect(seen.append)
    editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("expression"))
    assert seen == [] and editor.error_text()  # empty expression is invalid
    editor.expr_edit.setText("300 + foo(t)")
    assert "not allowed" in editor.error_text() or "unknown" in editor.error_text()
    editor.expr_edit.editingFinished.emit()
    assert seen == []
    assert "background" in editor.expr_edit.styleSheet()
    editor.expr_edit.setText("300 + 20*sin(2*pi*t/60)")
    assert editor.error_text() == ""
    assert editor.expr_edit.styleSheet() == ""
    editor.expr_edit.editingFinished.emit()
    assert seen == [Expression("300 + 20*sin(2*pi*t/60)")]


def test_set_function_expression_and_table(editor) -> None:
    editor.set_function(Expression("t*2"))
    assert editor.mode == "expression" and editor.expr_edit.text() == "t*2"
    editor.set_function(Table([0.0, 10.0], [20.0, 80.0], "t", "linear"))
    assert editor.mode == "table"
    assert grid_text(editor) == [("0", "20"), ("10", "80")]
    assert editor.extrapolate_combo.currentData() == "linear"
    assert editor.preview.n_points == 2


def test_table_edit_add_remove_rows(editor) -> None:
    seen = []
    editor.set_function(Table([0.0, 10.0], [20.0, 80.0], "t"))
    editor.function_changed.connect(seen.append)
    editor.grid.item(1, 1).setText("90")
    assert seen[-1] == Table([0.0, 10.0], [20.0, 90.0], "t")
    editor.add_row()
    assert len(seen) == 1  # a blank row changes nothing
    editor.grid.item(2, 0).setText("20")
    assert editor.error_text()  # half a row
    editor.grid.item(2, 1).setText("100")
    assert seen[-1] == Table([0.0, 10.0, 20.0], [20.0, 90.0, 100.0], "t")
    editor.grid.item(2, 0).setText("5")  # not increasing
    assert "increasing" in editor.error_text() and len(seen) == 2
    editor.grid.item(2, 0).setText("20")
    editor.grid.selectRow(2)
    editor.remove_selected_rows()
    assert seen[-1] == Table([0.0, 10.0], [20.0, 90.0], "t")


def test_paste_from_excel(editor) -> None:
    seen = []
    editor.function_changed.connect(seen.append)
    editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("table"))
    assert editor.paste_text("0\t20\n10\t80\n") is True
    assert grid_text(editor) == [("0", "20"), ("10", "80")]
    assert seen[-1] == Table([0.0, 10.0], [20.0, 80.0], "t")
    assert editor.preview.n_points == 2
    assert editor.paste_text("a\tb\nc\td\n") is False  # rejected, grid unchanged
    assert "paste rejected" in editor.error_text()
    assert grid_text(editor) == [("0", "20"), ("10", "80")]


def test_parse_pasted_rules() -> None:
    assert parse_pasted("0\t20\r\n10\t80\r\n") == [(0.0, 20.0), (10.0, 80.0)]
    assert parse_pasted("x;y\n0;1,5\n1;2,5") == [(0.0, 1.5), (1.0, 2.5)]  # header, decimal comma
    assert parse_pasted("0,1\n1,2") == [(0.0, 1.0), (1.0, 2.0)]  # comma is a separator
    assert parse_pasted("0 1\n\n2 3 4") == [(0.0, 1.0), (2.0, 3.0)]
    assert parse_pasted("1,5\t2,5") == [(1.5, 2.5)]
    for bad in ("", "just text", "0\t1\nfoo\tbar", "5"):
        with pytest.raises(ValueError):
            parse_pasted(bad)


def test_table_in_display_units(qtbot) -> None:
    w = FunctionEditor(quantity="temperature", settings=UnitSettings(temperature="degC"))
    qtbot.addWidget(w)
    seen = []
    w.function_changed.connect(seen.append)
    w.mode_combo.setCurrentIndex(w.mode_combo.findData("table"))
    w.variable_combo.setCurrentIndex(w.variable_combo.findData("T"))
    w.paste_text("0\t20\n100\t80")
    assert seen[-1].variable == "T"
    assert seen[-1].xs == pytest.approx([273.15, 373.15])
    assert seen[-1].ys == pytest.approx([293.15, 353.15])


def test_mode_switch_carries_constant_value(editor) -> None:
    seen = []
    editor.set_function(Constant(300.0))
    editor.function_changed.connect(seen.append)
    editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("table"))
    assert seen[-1] == Table([0.0], [300.0], "t")
    editor.set_function(Constant(300.0))
    editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("expression"))
    assert seen[-1] == Expression("300")


def test_optional_none_mode(qtbot) -> None:
    w = FunctionEditor(optional=True)
    qtbot.addWidget(w)
    seen = []
    w.set_function(Constant(1.0))
    w.function_changed.connect(seen.append)
    w.mode_combo.setCurrentIndex(w.mode_combo.findData("none"))
    assert seen == [None]
    w.set_function(None)
    assert w.mode == "none"


def test_preview_does_not_crash_offscreen(editor) -> None:
    editor.set_function(Table([0.0, 1.0, 2.0], [1.0, 4.0, 9.0], "T"))
    editor.preview.draw()
    editor.set_function(Table([0.0], [1.0], "t"))
    editor.grid.item(0, 0).setText("")
    editor.preview.draw()
    assert editor.preview.n_points == 0
