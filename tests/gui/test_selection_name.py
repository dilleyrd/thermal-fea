"""M11.55: the selection editor names the selection at Apply and refuses bad names atomically."""

from __future__ import annotations

import pytest
from test_selection_editor import SPEC, FakeView, built_doc, top_curve  # noqa: F401

from thermalfea.core.forms import form_for
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.selection_editor import SelectionEditor
from thermalfea.model.bcs import Convection
from thermalfea.model.serialize import to_json


def _panel(qtbot, doc):
    view = FakeView()
    p = FormPanel(form_for(Convection), doc, ("bcs", 0), view)
    qtbot.addWidget(p)
    editor = p.editors["selection"]
    editor.pick_button.setChecked(True)
    view.pick(1, [top_curve(doc)])
    return p, editor, view


def test_suggestion_is_unused(qtbot, built_doc) -> None:  # noqa: F811
    p, editor, _ = _panel(qtbot, built_doc)
    assert editor.name_edit.placeholderText() == "selection name"
    assert editor.name_edit.text() == "Conv selection"
    built_doc.model.selections.update({})  # no-op: the model is shared by the editor
    assert editor.apply() == "Conv selection"
    other = SelectionEditor(built_doc, FakeView(), SPEC)
    qtbot.addWidget(other)
    other.name_hint = "Conv selection"
    assert other.name_edit.text() == "Conv selection 2"


def test_custom_name_is_stored_and_assigned(qtbot, built_doc) -> None:  # noqa: F811
    p, editor, _ = _panel(qtbot, built_doc)
    editor.name_edit.setText("Hot face")
    editor.name_edit.textEdited.emit("Hot face")
    editor.refresh()
    assert editor.name_edit.text() == "Hot face"  # typed text survives a refresh
    assert editor.apply() == "Hot face"
    assert built_doc.model.bcs[0].selection == "Hot face"
    assert "Hot face" in built_doc.model.selections
    assert built_doc.undo_stack.count() == 1


def test_reapply_onto_own_selection_replaces_it(qtbot, built_doc) -> None:  # noqa: F811
    p, editor, view = _panel(qtbot, built_doc)
    assert editor.apply() == "Conv selection"
    ents = built_doc.built.entities(1)
    bottom = min(ents, key=lambda t: ents[t].center[1])
    view.pick(1, [bottom])
    editor.name_edit.setText("Conv selection")
    assert editor.apply() == "Conv selection"
    assert built_doc.model.selections["Conv selection"].tags == [bottom]
    assert built_doc.model.bcs[0].selection == "Conv selection"
    assert len(built_doc.model.selections) == 2  # "all" and the replaced one


def _refused(qtbot, doc, text: str) -> None:
    p, editor, _ = _panel(qtbot, doc)
    editor.name_edit.setText(text)
    editor.name_edit.textEdited.emit(text)
    before = to_json(doc.model)
    count = doc.undo_stack.count()
    assert editor.apply() is None
    assert to_json(doc.model) == before
    assert doc.undo_stack.count() == count
    assert editor.error_text() and editor.status_label.text() == editor.error_text()
    assert editor.name_edit.text() == text  # the typed name stays
    assert doc.model.bcs[0].selection == ""


def test_collision_with_another_selection_is_refused(qtbot, built_doc) -> None:  # noqa: F811
    p, editor, _ = _panel(qtbot, built_doc)
    editor.apply()
    built_doc.undo_stack.clear()
    built_doc.edit("Unset", lambda m: setattr(m.bcs[0], "selection", ""))
    built_doc.undo_stack.clear()
    editor.set_value("")
    _refused_existing(qtbot, built_doc)


def _refused_existing(qtbot, doc) -> None:
    # "Conv selection" now belongs to nobody but is a selection: a new name may not reuse it
    p, editor, _ = _panel(qtbot, doc)
    editor.name_edit.setText("Conv selection")
    editor.name_edit.textEdited.emit("Conv selection")
    before = to_json(doc.model)
    count = doc.undo_stack.count()
    assert editor.apply() is None
    assert to_json(doc.model) == before and doc.undo_stack.count() == count
    assert "already used" in editor.error_text()


@pytest.mark.parametrize("text", ["all", "", "   "])
def test_reserved_and_empty_names_are_refused(qtbot, built_doc, text) -> None:  # noqa: F811
    _refused(qtbot, built_doc, text)


def test_dangling_mesh_key_is_refused(qtbot, built_doc) -> None:  # noqa: F811
    built_doc.edit("Size", lambda m: m.mesh_settings.curve_sizes.update({"Dangling": 0.1}))
    built_doc.undo_stack.clear()
    p, editor, _ = _panel(qtbot, built_doc)
    assert editor.name_edit.text() == "Conv selection"
    _refused(qtbot, built_doc, "Dangling")


def test_selection_list_appends_the_new_name(qtbot, built_doc) -> None:  # noqa: F811
    from thermalfea.core.functions import Constant
    from thermalfea.model.bcs import Stream

    built_doc.edit(
        "Add stream",
        lambda m: m.streams.append(
            Stream(
                name="S", fluid="Water", mode="in_plane", walls=[], flow_area=1e-4,
                wetted_perimeter=0.04, cross_section="circular", T_inlet=Constant(300.0),
            )
        ),
    )
    view = FakeView()
    p = FormPanel(form_for(Stream), built_doc, ("streams", 0), view)
    qtbot.addWidget(p)
    walls = p.editors["walls"]
    walls.pick_button.setChecked(True)
    view.pick(1, [top_curve(built_doc)])
    walls.name_edit.setText("Wall A")
    walls.name_edit.textEdited.emit("Wall A")
    assert walls.apply() == "Wall A"
    assert built_doc.model.streams[0].walls == ["Wall A"]
    ents = built_doc.built.entities(1)
    view.pick(1, [min(ents, key=lambda t: ents[t].center[1])])
    assert walls.name_edit.text() == "S walls"  # name_hint base, unused
    walls.name_edit.setText("Wall A")  # a list never replaces
    assert walls.apply() is None
    assert built_doc.model.streams[0].walls == ["Wall A"]
