"""M11.68: the shared controls of the GUI conventions (C5-C8, C11, C12).

The icon set (C6), framed boxes with "More" lines and collapsed advanced boxes that count
changed values (C5, C12, decision C), hint text for empty boxes and named empty modes (C7),
readable dropdown texts (C8) and one error line under each field (C11), with the Analysis
Settings panel as the reference layout (held item 11, decision G).
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QComboBox

from thermalfea import api
from thermalfea.core.forms import form_for
from thermalfea.gui.document import Document
from thermalfea.gui.field_texts import NONE_TEXT, choice_text, empty_text
from thermalfea.gui.icons import ICON_NAMES, icon, icon_button
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.function_editor import FunctionEditor
from thermalfea.gui.property_panels.sections import (
    Box,
    SectionBox,
    changed_count,
    default_value,
    forget_open_state,
)
from thermalfea.gui.property_panels.solution import (
    CONVERGENCE_BOX,
    INTEGRATION_BOX,
    SolutionPanel,
)
from thermalfea.model.settings import SolutionSettings


@pytest.fixture(autouse=True)
def fresh_open_state():
    forget_open_state()
    yield
    forget_open_state()


@pytest.fixture
def doc() -> Document:
    return Document(api.new_model(name="plate"))


def solution_panel(qtbot, doc: Document) -> SolutionPanel:
    panel = SolutionPanel(form_for(SolutionSettings), doc, ("solution",))
    qtbot.addWidget(panel)
    return panel


def enter(edit, text: str) -> None:
    edit.setText(text)
    edit.editingFinished.emit()


def choose(combo: QComboBox, text: str) -> None:
    index = combo.findText(text)
    assert index >= 0, (text, [combo.itemText(i) for i in range(combo.count())])
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def placement(panel: FormPanel, name: str):
    return panel._rows[name][0]


# --------------------------------------------------------------------------- C6 icons
def test_every_icon_is_drawn_and_buttons_say_what_they_do(qtbot) -> None:
    assert ICON_NAMES == (
        "add", "remove", "edit", "update", "revert", "pick", "browse", "warning",
    )
    for name in ICON_NAMES:
        assert not icon(name).isNull()
        button = icon_button(name, f"Do {name}")
        qtbot.addWidget(button)
        assert button.toolTip() == f"Do {name}" and button.accessibleName() == f"Do {name}"
        assert not button.icon().isNull() and button.text() == ""
    with pytest.raises(KeyError):
        icon("star")
    with pytest.raises(ValueError):
        icon_button("add", "  ")


# ----------------------------------------------------------------- C5, C12 boxes
def test_boxes_more_lines_and_advanced_boxes(qtbot) -> None:
    plain = SectionBox(Box("Time", "How long.", ("end_time",)), "panel")
    advanced = SectionBox(Box("Convergence", "Defaults suit.", ("rtol",), advanced=True), "p")
    more = SectionBox(Box("Stepping", "", ("a",), more=("b",)), "panel")
    for box in (plain, advanced, more):
        qtbot.addWidget(box)
    assert plain.title_text() == "Time" and plain.is_open() and plain.more is None
    assert advanced.title_text() == "Convergence (advanced)" and not advanced.is_open()
    assert advanced.body.isHidden()
    advanced.set_summary("x")
    advanced.set_changed(2)
    assert advanced.title_text() == "Convergence (advanced) · x · 2 changed"
    assert more.more is not None and not more.more.is_open()
    more.more.set_changed(1)
    assert more.more.button.text() == "More · 1 changed"
    # the open state is remembered for the session, per panel and part
    advanced.set_open(True)
    again = SectionBox(Box("Convergence", "", ("rtol",), advanced=True), "p")
    qtbot.addWidget(again)
    assert again.is_open()
    other_panel = SectionBox(Box("Convergence", "", ("rtol",), advanced=True), "q")
    qtbot.addWidget(other_panel)
    assert not other_panel.is_open()


def test_changed_values_are_counted_against_the_defaults() -> None:
    settings = SolutionSettings()
    assert default_value(settings, "max_iterations") == settings.max_iterations
    assert changed_count(settings, ["rtol", "max_iterations"]) == 0
    settings.max_iterations = 12
    settings.line_search = not settings.line_search
    assert changed_count(settings, ["rtol", "max_iterations", "line_search"]) == 2


def test_analysis_settings_are_laid_out_in_boxes(qtbot, doc) -> None:
    panel = solution_panel(qtbot, doc)
    assert list(panel.sections) == [
        "Analysis", "Time", "Time stepping", INTEGRATION_BOX, "Results to store",
        CONVERGENCE_BOX,
    ]  # fmt: skip
    stepping = panel.sections["Time stepping"]
    assert stepping.more is not None
    for name in ("initial_dt", "dt_min", "time_tol", "max_dT_per_step"):
        assert placement(panel, name) is stepping.more.form, name
    assert placement(panel, "dt_max") is stepping.form
    assert placement(panel, "theta") is panel.sections[INTEGRATION_BOX].form
    assert panel.sections["Analysis"].form.rowCount() == 2  # Geometry type, Analysis type
    # steady: only the Analysis and Convergence boxes
    shown = {title for title, box in panel.sections.items() if not box.isHidden()}
    assert shown == {"Analysis", CONVERGENCE_BOX}
    choose(panel.editors["kind"], "Transient")
    assert doc.model.solution.kind == "transient"
    assert all(not box.isHidden() for box in panel.sections.values())
    # advanced parts start collapsed; the fields in them still apply
    assert not panel.sections[INTEGRATION_BOX].is_open()
    assert not panel.sections[CONVERGENCE_BOX].is_open()
    assert not stepping.more.is_open()
    assert panel.is_field_shown("initial_dt") and panel.is_field_shown("theta")
    # Time-step tolerance applies only with an adaptive time step
    assert panel.is_field_shown("time_tol")
    panel.editors["auto_timestep"].setChecked(False)
    assert doc.model.solution.auto_timestep is False and not panel.is_field_shown("time_tol")


def test_collapsed_parts_name_the_method_and_count_changes(qtbot, doc) -> None:
    doc.edit("transient", lambda m: setattr(m.solution, "kind", "transient"))
    panel = solution_panel(qtbot, doc)
    integration = panel.sections[INTEGRATION_BOX]
    assert integration.title_text() == "Integration (advanced) · Backward Euler"
    choose(panel.editors["theta"], "Crank-Nicolson (θ = 1/2)")
    assert integration.title_text() == "Integration (advanced) · Crank-Nicolson · 1 changed"
    convergence = panel.sections[CONVERGENCE_BOX]
    assert convergence.title_text() == "Convergence (advanced)"
    enter(panel.editors["max_iterations"], "12")
    assert convergence.title_text() == "Convergence (advanced) · 1 changed"
    more = panel.sections["Time stepping"].more
    assert more is not None and more.button.text() == "More"
    enter(panel.editors["dt_min"], "0.001")
    assert more.button.text() == "More · 1 changed"
    doc.undo_stack.undo()
    assert more.button.text() == "More"


# ---------------------------------------------------------------- C7, C8 texts
def test_empty_boxes_show_their_meaning_and_choices_are_readable(qtbot, doc) -> None:
    panel = solution_panel(qtbot, doc)
    assert panel.editors["initial_dt"].placeholderText() == "suggested from the mesh"
    assert panel.editors["dt_max"].placeholderText() == "no limit"
    assert panel.editors["max_dT_per_step"].placeholderText() == "no limit"
    assert panel.editors["end_time"].placeholderText() == ""  # not optional
    kinds = panel.editors["kind"]
    assert [kinds.itemText(i) for i in range(kinds.count())] == ["Steady", "Transient"]
    out = panel.editors["output"]
    assert [out.itemText(i) for i in range(out.count())] == [
        "All steps", "Every n-th step", "At given times",
    ]  # fmt: skip
    assert choice_text("Analysis settings", "output", "every_n") == "Every n-th step"
    assert choice_text("No form", "x", "raw_id") == "raw_id"
    assert choice_text("No form", "x", None) == NONE_TEXT
    assert empty_text("Analysis settings", "end_time") == ""


def test_an_optional_formula_names_its_empty_mode(qtbot) -> None:
    named = FunctionEditor("conductivity", optional=True, none_text="Isotropic")
    plain = FunctionEditor("conductivity", optional=True)
    for editor in (named, plain):
        qtbot.addWidget(editor)
    texts = [named.mode_combo.itemText(i) for i in range(named.mode_combo.count())]
    assert "Isotropic" in texts and "None" not in texts
    assert "None" in [plain.mode_combo.itemText(i) for i in range(plain.mode_combo.count())]


# ------------------------------------------------------------------ C11 errors
def test_an_error_is_shown_once_under_its_field(qtbot, doc) -> None:
    doc.edit("transient", lambda m: setattr(m.solution, "kind", "transient"))
    panel = solution_panel(qtbot, doc)
    enter(panel.editors["end_time"], "-3")  # the box's own limit
    line = panel.field_errors["end_time"]
    assert not line.isHidden() and "at least" in line.text()
    assert panel.error_label.isHidden() and panel.error_label.text() == ""
    enter(panel.editors["end_time"], "50")
    assert line.isHidden() and doc.model.solution.end_time == 50.0
    # a value the model refuses: also under the field
    plain = FormPanel(form_for(SolutionSettings), doc, ("solution",))
    qtbot.addWidget(plain)
    enter(plain.editors["theta"], "2")
    assert "theta" in plain.field_errors["theta"].text()
    assert not plain.field_errors["theta"].isHidden() and plain.error_label.text() == ""
