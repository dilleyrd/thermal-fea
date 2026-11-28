"""M11.70: the selection field (held item 12; conventions C1, C2, C6; decisions A and 12).

One row: the role as label, one dropdown with sizes, icon buttons. Choosing another
selection waits for Update (✓) and can be reverted (↶); New (the pick icon) picks a new
selection with an empty Name box and "Create and use"; ✎ edits the current selection's
entities ("Save", "Save as new"). A list field lists its entries with ✎ and ✕. Leaving
a panel with an unapplied change drops it with a status-bar note.
"""

# ruff: noqa: F811  (the fixture `built_doc` is imported from test_selection_editor)
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QWidget
from tests.gui.test_selection_editor import FakeView, built_doc, top_curve  # noqa: F401

from thermalfea.core.forms import FieldSpec, form_for
from thermalfea.core.functions import Constant
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.pick import manager_for
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.selection_editor import (
    DISCARDED_TEXT,
    NONE_TEXT,
    SelectionEditor,
    role_label,
    selection_label,
)
from thermalfea.model.bcs import Convection, FixedTemperature

SPEC = FieldSpec("selection", "Selection", "selection", selection_dims=(1,))
LIST_SPEC = FieldSpec("walls", "Walls", "selection_list", selection_dims=(1,))


def curves(doc: Document) -> list[int]:
    """The four edges, bottom, right, top, left (by centre)."""
    ents = doc.built.entities(1)
    return sorted(ents, key=lambda t: (ents[t].center[1], ents[t].center[0]))


def with_selections(doc: Document) -> tuple[int, int]:
    """Selections "top" and "bottom" (one edge each); returns their tags."""
    from thermalfea import api

    top = top_curve(doc)
    bottom = curves(doc)[0]
    doc.edit("sel", lambda m: api.select_curves(m, doc.built, "top", tags=[top]))
    doc.edit("sel", lambda m: api.select_curves(m, doc.built, "bottom", tags=[bottom]))
    return top, bottom


def load_panel(qtbot, doc: Document, view: FakeView) -> FormPanel:
    panel = FormPanel(form_for(Convection), doc, ("bcs", 0), view)
    qtbot.addWidget(panel)
    return panel


def texts(editor: SelectionEditor) -> list[str]:
    return [editor.combo.itemText(i) for i in range(editor.combo.count())]


def choose(editor: SelectionEditor, name: str) -> None:
    index = editor.combo.findData(name)
    assert index >= 0, (name, texts(editor))
    editor.combo.setCurrentIndex(index)
    editor.combo.activated.emit(index)


# ------------------------------------------------------------------------ one row
def test_one_row_with_the_role_and_sizes(qtbot, built_doc) -> None:
    with_selections(built_doc)
    panel = load_panel(qtbot, built_doc, FakeView())
    editor = panel.editors["selection"]
    assert isinstance(editor, SelectionEditor)
    label = panel._rows["selection"][0].labelForField(panel._rows["selection"][1])
    assert label.text() == "Boundary"
    assert texts(editor)[0] == NONE_TEXT
    assert sorted(texts(editor)[1:]) == ["bottom · 1 boundary", "top · 1 boundary"]
    assert editor.update_button.isHidden() and editor.revert_button.isHidden()
    assert editor.pending_label.isHidden() and editor.strip.isHidden()
    for button in (editor.update_button, editor.revert_button, editor.new_button,
                   editor.edit_button):  # fmt: skip
        assert button.text() == "" and button.toolTip() and button.accessibleName()
    model = built_doc.model
    assert role_label(model, (0, 1)) == "Boundary or point"
    assert role_label(model, (2,)) == "Part"
    assert selection_label(model, "top") == "top · 1 boundary"


# -------------------------------------------------------------- Update and Revert
def test_a_new_choice_waits_for_update(qtbot, built_doc) -> None:
    with_selections(built_doc)
    built_doc.edit("use top", lambda m: setattr(m.bcs[0], "selection", "top"))
    panel = load_panel(qtbot, built_doc, FakeView())
    editor = panel.editors["selection"]
    count = built_doc.undo_stack.count()
    choose(editor, "bottom")
    assert built_doc.model.bcs[0].selection == "top"  # not applied yet
    assert built_doc.undo_stack.count() == count
    assert editor.has_pending() and not editor.update_button.isHidden()
    assert "bottom" in editor.pending_label.text() and "top" in editor.pending_label.text()
    assert not editor.new_button.isEnabled()  # no new pick on top of a pending change
    editor.revert_button.click()
    assert not editor.has_pending() and editor.combo.currentData() == "top"
    choose(editor, "bottom")
    editor.update_button.click()
    assert built_doc.model.bcs[0].selection == "bottom"
    assert built_doc.undo_stack.count() == count + 1
    assert not editor.has_pending() and editor.update_button.isHidden()


def test_an_unrelated_edit_keeps_the_pending_choice(qtbot, built_doc) -> None:
    with_selections(built_doc)
    panel = load_panel(qtbot, built_doc, FakeView())
    editor = panel.editors["selection"]
    choose(editor, "top")
    built_doc.edit("h", lambda m: setattr(m.bcs[0], "h", Constant(5.0)))
    assert editor.has_pending() and editor.pending_value() == "top"
    built_doc.undo_stack.undo()
    assert editor.has_pending()


# --------------------------------------------------------------------------- New
def test_new_selection_with_an_empty_name_and_create_and_use(qtbot, built_doc) -> None:
    view = FakeView()
    with_selections(built_doc)
    panel = load_panel(qtbot, built_doc, view)
    editor = panel.editors["selection"]
    count = built_doc.undo_stack.count()
    editor.new_button.click()
    assert editor.picking == "new" and not editor.strip.isHidden()
    assert view.mode == "curve" and editor.name_edit.text() == ""
    confirm = editor.strip.confirm_button
    assert confirm.text() == "Create and use" and not confirm.isEnabled()
    tag = curves(built_doc)[1]
    view.pick(1, [tag])
    assert editor.strip.count_label.text() == "1 boundary picked"
    assert not confirm.isEnabled()  # a name is needed
    editor.name_edit.setText("top")  # taken
    assert not confirm.isEnabled() and editor.name_error.text()
    editor.name_edit.setText("all")  # reserved
    assert not confirm.isEnabled() and editor.name_error.text()
    editor.name_edit.setText("right edge")
    assert confirm.isEnabled() and editor.name_error.text() == ""
    confirm.click()
    assert built_doc.model.selections["right edge"].tags == [tag]
    assert built_doc.model.bcs[0].selection == "right edge"
    assert built_doc.undo_stack.count() == count + 1  # created and used in one step
    assert editor.picking is None and editor.strip.isHidden() and view.mode == "none"
    built_doc.undo_stack.undo()
    assert "right edge" not in built_doc.model.selections
    assert built_doc.model.bcs[0].selection == ""


def test_cancel_and_esc_change_nothing(qtbot, built_doc) -> None:
    view = FakeView()
    panel = load_panel(qtbot, built_doc, view)
    editor = panel.editors["selection"]
    count = built_doc.undo_stack.count()
    editor.new_button.click()
    view.pick(1, [top_curve(built_doc)])
    editor.name_edit.setText("x")
    editor.strip.cancel_button.click()
    assert editor.picking is None and "x" not in built_doc.model.selections
    editor.new_button.click()
    QTest.keyClick(editor, Qt.Key.Key_Escape)
    assert editor.picking is None and manager_for(view).active is None
    assert built_doc.undo_stack.count() == count


def test_a_point_or_boundary_field_starts_in_boundary(qtbot, built_doc) -> None:
    view = FakeView()
    built_doc.edit(
        "fixed", lambda m: m.bcs.append(FixedTemperature("Fix", "", T=Constant(300.0)))
    )
    panel = FormPanel(form_for(FixedTemperature), built_doc, ("bcs", 1), view)
    qtbot.addWidget(panel)
    editor = panel.editors["selection"]
    label = panel._rows["selection"][0].labelForField(panel._rows["selection"][1])
    assert label.text() == "Boundary or point"
    editor.new_button.click()
    assert view.mode == "curve"
    view.pick(0, [1])  # points are accepted too
    assert editor.picked() == (0, [1])
    editor.cancel_pick()


# -------------------------------------------------------------------------- Edit
def test_edit_starts_from_the_entities_and_saves(qtbot, built_doc) -> None:
    view = FakeView()
    top, bottom = with_selections(built_doc)
    built_doc.edit("use top", lambda m: setattr(m.bcs[0], "selection", "top"))
    built_doc.edit(
        "second", lambda m: m.bcs.append(Convection("Conv 2", "top", Constant(1.0),
                                                    Constant(300.0)))  # fmt: skip
    )
    panel = load_panel(qtbot, built_doc, view)
    editor = panel.editors["selection"]
    count = built_doc.undo_stack.count()
    editor.edit_button.click()
    assert editor.picking == "edit" and editor.picked() == (1, [top])
    assert "Also used by" in editor.strip.instruction_label.text()
    assert "Conv 2" in editor.strip.instruction_label.text()
    assert editor.strip.confirm_button.text() == "Save"
    view.pick(1, [top, bottom])
    editor.strip.confirm_button.click()
    assert sorted(built_doc.model.selections["top"].tags) == sorted([top, bottom])
    assert built_doc.undo_stack.count() == count + 1
    assert editor.picking is None


def test_save_as_new_leaves_the_shared_selection_alone(qtbot, built_doc) -> None:
    view = FakeView()
    top, bottom = with_selections(built_doc)
    built_doc.edit("use top", lambda m: setattr(m.bcs[0], "selection", "top"))
    panel = load_panel(qtbot, built_doc, view)
    editor = panel.editors["selection"]
    count = built_doc.undo_stack.count()
    editor.edit_button.click()
    view.pick(1, [bottom])
    assert not editor.save_as_button.isEnabled()  # a name is needed
    editor.name_edit.setText("lower")
    editor.save_as_button.click()
    assert built_doc.model.selections["top"].tags == [top]  # untouched
    assert built_doc.model.selections["lower"].tags == [bottom]
    assert built_doc.model.bcs[0].selection == "lower"
    assert built_doc.undo_stack.count() == count + 1


# ---------------------------------------------------------------------- list field
def test_a_list_field_lists_entries_and_waits_for_update(qtbot, built_doc) -> None:
    with_selections(built_doc)
    values: list[object] = []
    editor = SelectionEditor(built_doc, FakeView(), LIST_SPEC)
    qtbot.addWidget(editor)
    editor.value_changed.connect(values.append)
    editor.set_value(["top"])
    assert texts(editor) == ["(add a selection…)", "bottom · 1 boundary"]
    assert editor.findChild(QWidget, "entry_top") is not None
    choose(editor, "bottom")
    assert editor.pending_value() == ["top", "bottom"] and editor.value() == ["top"]
    assert values == []
    editor.update_button.click()
    assert values == [["top", "bottom"]]
    editor.set_value(["top", "bottom"])  # the form stores it and reloads
    editor.remove_entry("top")
    assert editor.has_pending() and editor.pending_value() == ["bottom"]
    editor.revert_button.click()
    assert editor.pending_value() == ["top", "bottom"] and not editor.has_pending()


# ------------------------------------------------------------- leaving the panel
def test_leaving_a_panel_drops_an_unapplied_change_with_a_note(qtbot, window, built_doc) -> None:
    view = FakeView()
    with_selections(built_doc)
    _tree, controller = attach_tree(window, built_doc, view)
    controller.show_object(("bcs", 0))
    editor = controller.panel.editors["selection"]
    choose(editor, "top")
    controller.show_object(("section", "none"))
    assert window.statusBar().currentMessage() == DISCARDED_TEXT
    assert built_doc.model.bcs[0].selection == ""


def test_the_toolbar_follows_the_pick(qtbot, window, built_doc) -> None:
    view = FakeView()
    _tree, controller = attach_tree(window, built_doc, view)
    controller.show_object(("bcs", 0))
    editor = controller.panel.editors["selection"]
    editor.new_button.click()
    assert window.actions["select.curve"].isChecked()
    editor.cancel_pick()
    assert window.actions["select.none"].isChecked()
    editor.new_button.click()
    controller.show_object(("section", "none"))  # a replaced panel ends its pick
    assert editor.picking is None and manager_for(view).active is None
