"""M11.55/M11.70: a new selection is named by the user and bad names are refused atomically."""

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
    editor = p.editors["selection"]
    qtbot.addWidget(p, before_close_func=lambda _w: editor.cancel_pick())  # frees the pick
    editor.new_button.click()
    view.pick(1, [top_curve(doc)])
    return p, editor, view


def _confirm(editor, name: str) -> None:
    editor.name_edit.setText(name)
    editor.strip.confirm_button.click()


def test_the_name_starts_empty_and_confirm_needs_a_valid_name(qtbot, built_doc) -> None:  # noqa: F811
    p, editor, _ = _panel(qtbot, built_doc)
    assert editor.name_edit.placeholderText()
    assert editor.name_edit.text() == ""  # no default name
    assert not editor.strip.confirm_button.isEnabled()
    editor.name_edit.setText("Conv selection")
    assert editor.strip.confirm_button.isEnabled()
    editor.strip.confirm_button.click()
    assert built_doc.model.selections["Conv selection"].tags == [top_curve(built_doc)]
    other = SelectionEditor(built_doc, FakeView(), SPEC)
    qtbot.addWidget(other, before_close_func=lambda _w: other.cancel_pick())
    other.new_button.click()
    assert other.name_edit.text() == ""  # not even a unique suggestion
    assert not other.strip.confirm_button.isEnabled()  # nothing picked yet, no name


def test_custom_name_is_stored_and_assigned(qtbot, built_doc) -> None:  # noqa: F811
    p, editor, _ = _panel(qtbot, built_doc)
    editor.name_edit.setText("Hot face")
    editor.name_edit.textEdited.emit("Hot face")
    editor.refresh()
    assert editor.name_edit.text() == "Hot face"  # typed text survives a refresh
    editor.strip.confirm_button.click()
    assert built_doc.model.bcs[0].selection == "Hot face"
    assert "Hot face" in built_doc.model.selections
    assert built_doc.undo_stack.count() == 1


def test_edit_replaces_the_entities_of_the_own_selection(qtbot, built_doc) -> None:  # noqa: F811
    p, editor, view = _panel(qtbot, built_doc)
    _confirm(editor, "Conv selection")
    count = built_doc.undo_stack.count()
    ents = built_doc.built.entities(1)
    bottom = min(ents, key=lambda t: ents[t].center[1])
    editor.edit_button.click()
    assert editor.picking == "edit"
    view.pick(1, [bottom])
    assert editor.strip.confirm_button.isEnabled()
    editor.strip.confirm_button.click()
    assert built_doc.model.selections["Conv selection"].tags == [bottom]
    assert built_doc.model.bcs[0].selection == "Conv selection"
    assert len(built_doc.model.selections) == 2  # "all" and the replaced one
    assert built_doc.undo_stack.count() == count + 1


def _refused(qtbot, doc, text: str, message: bool = True) -> None:
    p, editor, _ = _panel(qtbot, doc)
    editor.name_edit.setText(text)
    editor.name_edit.textEdited.emit(text)
    before = to_json(doc.model)
    count = doc.undo_stack.count()
    assert not editor.strip.confirm_button.isEnabled()
    assert not editor.confirm_pick()
    assert to_json(doc.model) == before
    assert doc.undo_stack.count() == count
    if message:
        assert editor.name_error.text()
    assert editor.name_edit.text() == text  # the typed name stays
    assert doc.model.bcs[0].selection == ""


def test_collision_with_another_selection_is_refused(qtbot, built_doc) -> None:  # noqa: F811
    p, editor, _ = _panel(qtbot, built_doc)
    _confirm(editor, "Conv selection")
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
    assert not editor.strip.confirm_button.isEnabled() and not editor.confirm_pick()
    assert to_json(doc.model) == before and doc.undo_stack.count() == count
    assert "already used" in editor.name_error.text()


@pytest.mark.parametrize("text", ["all", "", "   "])
def test_reserved_and_empty_names_are_refused(qtbot, built_doc, text) -> None:  # noqa: F811
    # an empty name has no message (nothing typed yet); a reserved one says why
    _refused(qtbot, built_doc, text, message=bool(text.strip()))


def test_dangling_mesh_key_is_refused(qtbot, built_doc) -> None:  # noqa: F811
    built_doc.edit("Size", lambda m: m.mesh_settings.curve_sizes.update({"Dangling": 0.1}))
    built_doc.undo_stack.clear()
    p, editor, _ = _panel(qtbot, built_doc)
    assert editor.name_edit.text() == ""
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
    walls = p.editors["walls"]
    qtbot.addWidget(p, before_close_func=lambda _w: walls.cancel_pick())
    walls.new_button.click()
    view.pick(1, [top_curve(built_doc)])
    walls.name_edit.setText("Wall A")
    walls.name_edit.textEdited.emit("Wall A")
    assert walls.strip.confirm_button.text() == "Create and add"
    walls.strip.confirm_button.click()
    assert built_doc.model.streams[0].walls == ["Wall A"]
    ents = built_doc.built.entities(1)
    walls.new_button.click()
    view.pick(1, [min(ents, key=lambda t: ents[t].center[1])])
    assert walls.name_edit.text() == ""  # no default name
    walls.name_edit.setText("Wall A")  # a list never replaces
    assert not walls.strip.confirm_button.isEnabled() and not walls.confirm_pick()
    assert built_doc.model.streams[0].walls == ["Wall A"]
