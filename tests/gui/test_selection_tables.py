"""M11.71: value-per-selection tables (held item 13; conventions C1, C6, C10, C11).

Boundary and point sizes, boundary divisions, temperature per part and the refinements are
tables: one row per selection with a dropdown and value boxes; a changed selection waits
for Update, Enter applies a whole row, + adds a draft row, + New picks a new selection; the
focused row's selection is highlighted; errors are shown under their row.
"""

# ruff: noqa: F811  (the fixture `built_doc` is imported from test_selection_editor)
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFocusEvent
from PySide6.QtWidgets import QApplication
from tests.gui.test_selection_editor import FakeView, built_doc, top_curve  # noqa: F401

from thermalfea import api
from thermalfea.core.forms import form_for
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.mesh import MeshPanel
from thermalfea.gui.property_panels.selection_table import CHOOSE_TEXT, SelectionTable
from thermalfea.model.settings import MeshSettings


class HighlightView(FakeView):
    """Records what the table highlights."""

    def __init__(self) -> None:
        super().__init__()
        self.highlighted: list[tuple[int, list[int]]] = []

    def highlight(self, dim, tags) -> None:
        self.highlighted.append((dim, list(tags)))


def edges(doc: Document) -> list[int]:
    ents = doc.built.entities(1)
    return sorted(ents, key=lambda t: (ents[t].center[1], ents[t].center[0]))


def two_selections(doc: Document) -> None:
    bottom, top = edges(doc)[0], top_curve(doc)
    doc.edit("s", lambda m: api.select_curves(m, doc.built, "bottom", tags=[bottom]))
    doc.edit("s", lambda m: api.select_curves(m, doc.built, "top", tags=[top]))


def mesh_panel(qtbot, doc: Document, view=None) -> MeshPanel:
    panel = MeshPanel(form_for(MeshSettings), doc, ("mesh_settings",), view or FakeView())
    qtbot.addWidget(panel)
    return panel


def choose(table: SelectionTable, r: int, name: str) -> None:
    combo = table.row_widgets(r).combo
    index = combo.findData(name)
    assert index >= 0, name
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def enter(table: SelectionTable, r: int, *texts: str) -> None:
    edits = table.row_widgets(r).edits
    for edit, text in zip(edits, texts, strict=False):
        edit.setText(text)
    edits[0].returnPressed.emit()


def header(table: SelectionTable) -> list[str]:
    return [
        table.grid.itemAtPosition(0, c).widget().text()
        for c in range(table.grid.columnCount())
        if table.grid.itemAtPosition(0, c) is not None
    ]


def test_divisions_are_a_table_in_the_structured_mesh_box(qtbot, built_doc) -> None:
    two_selections(built_doc)
    panel = mesh_panel(qtbot, built_doc)
    table = panel.editors["curve_divisions"]
    assert isinstance(table, SelectionTable)
    box = panel.sections["Structured mesh"]
    assert panel._rows["curve_divisions"][0] is box.form
    assert panel._rows["structured_surfaces"][0] is box.form
    count = built_doc.undo_stack.count()
    r = table.add_row()
    assert table.row_widgets(r).combo.itemText(0) == CHOOSE_TEXT
    assert header(table) == ["Boundary", "Elements"]
    choose(table, r, "top")
    enter(table, r, "40")
    assert built_doc.model.mesh_settings.curve_divisions == {"top": 40}
    assert isinstance(built_doc.model.mesh_settings.curve_divisions["top"], int)
    assert built_doc.undo_stack.count() == count + 1
    assert table.rows() == [("top", (40.0,))]


def test_a_changed_selection_waits_for_update(qtbot, built_doc) -> None:
    two_selections(built_doc)
    built_doc.edit("d", lambda m: m.mesh_settings.curve_divisions.update({"top": 8}))
    panel = mesh_panel(qtbot, built_doc)
    table = panel.editors["curve_divisions"]
    count = built_doc.undo_stack.count()
    choose(table, 0, "bottom")
    w = table.row_widgets(0)
    assert built_doc.model.mesh_settings.curve_divisions == {"top": 8}
    assert table.has_pending() and not w.update_button.isHidden()
    table.revert_row(0)
    assert not table.has_pending()
    choose(table, 0, "bottom")
    enter(table, 0, "12")  # Enter applies the whole row: selection and value
    assert built_doc.model.mesh_settings.curve_divisions == {"bottom": 12}
    assert built_doc.undo_stack.count() == count + 1


def test_a_value_alone_applies_and_errors_show_under_the_row(qtbot, built_doc) -> None:
    two_selections(built_doc)
    built_doc.edit("d", lambda m: m.mesh_settings.curve_divisions.update({"top": 8}))
    panel = mesh_panel(qtbot, built_doc)
    table = panel.editors["curve_divisions"]
    count = built_doc.undo_stack.count()
    enter(table, 0, "2.5")
    assert "whole number" in table.row_error(0)
    assert built_doc.undo_stack.count() == count
    enter(table, 0, "9")
    assert built_doc.model.mesh_settings.curve_divisions == {"top": 9}
    r = table.add_row()
    enter(table, r, "3")  # no selection chosen yet
    assert table.row_error(r) == "choose a selection"
    assert built_doc.undo_stack.count() == count + 1


def test_names_are_offered_once_and_rows_are_removed_in_one_step(qtbot, built_doc) -> None:
    two_selections(built_doc)
    built_doc.edit("d", lambda m: m.mesh_settings.curve_sizes.update({"top": 0.5}))
    panel = mesh_panel(qtbot, built_doc)
    table = panel.editors["curve_sizes"]
    r = table.add_row()
    offered = [table.row_widgets(r).combo.itemData(i)
               for i in range(table.row_widgets(r).combo.count())]  # fmt: skip
    assert "top" not in offered and "bottom" in offered
    table.revert_row(r)  # a draft row disappears
    assert len(table.rows()) == 1
    count = built_doc.undo_stack.count()
    table.row_widgets(0).remove_button.click()
    assert built_doc.model.mesh_settings.curve_sizes == {}
    assert built_doc.undo_stack.count() == count + 1


def test_the_focused_row_is_highlighted(qtbot, built_doc) -> None:
    two_selections(built_doc)
    built_doc.edit("d", lambda m: m.mesh_settings.curve_sizes.update({"top": 0.5}))
    view = HighlightView()
    panel = mesh_panel(qtbot, built_doc, view)
    table = panel.editors["curve_sizes"]
    edit = table.row_widgets(0).edits[0]
    QApplication.sendEvent(edit, QFocusEvent(QEvent.Type.FocusIn, Qt.FocusReason.TabFocusReason))
    assert view.highlighted[-1] == (1, [top_curve(built_doc)])


def test_refinements_use_the_same_table(qtbot, built_doc) -> None:
    two_selections(built_doc)
    panel = mesh_panel(qtbot, built_doc)
    table = panel.table
    assert isinstance(table, SelectionTable)
    count = built_doc.undo_stack.count()
    r = table.add_row()
    choose(table, r, "top")
    enter(table, r, "0.2", "0.1", "0", "1")  # size min > size max
    assert "size min <= size max" in table.row_error(r)
    assert built_doc.undo_stack.count() == count
    enter(table, r, "0.05", "0.2", "0", "1")
    (refinement,) = built_doc.model.mesh_settings.refinements
    assert (refinement.selection, refinement.size_min, refinement.dist_max) == ("top", 0.05, 1.0)
    assert built_doc.undo_stack.count() == count + 1
    r = table.add_row()  # the same selection may be refined twice
    offered = [table.row_widgets(r).combo.itemData(i)
               for i in range(table.row_widgets(r).combo.count())]  # fmt: skip
    assert "top" in offered


def test_new_picks_a_selection_and_adds_a_draft_row(qtbot, built_doc) -> None:
    view = FakeView()
    panel = mesh_panel(qtbot, built_doc, view)
    table = panel.editors["curve_sizes"]
    table.picker.new_button.click()
    assert view.mode == "curve"
    view.pick(1, [top_curve(built_doc)])
    table.picker.name_edit.setText("upper")
    table.picker.strip.confirm_button.click()
    assert "upper" in built_doc.model.selections
    assert table.has_pending()
    r = len(table.rows())  # the draft row follows the stored ones
    assert table.row_widgets(r).combo.currentData() == "upper"
    enter(table, r, "0.25")
    assert built_doc.model.mesh_settings.curve_sizes == {"upper": 0.25}
