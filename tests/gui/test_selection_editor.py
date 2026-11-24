"""M8.4: SelectionEditor (pick in viewport, then Apply) alone and inside a form."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QObject, Signal

from thermalfea import api
from thermalfea.core.forms import FieldSpec, form_for
from thermalfea.core.functions import Constant
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.selection_editor import SelectionEditor
from thermalfea.gui.scene import SceneView
from thermalfea.model.bcs import Convection


class FakeView(QObject):
    """A SceneView stand-in that records the selection mode."""

    selection_changed = Signal(int, list)
    point_picked = Signal(float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.mode = "none"

    def set_selection_mode(self, mode: str) -> None:
        self.mode = mode

    def widget(self): ...
    def set_geometry(self, built) -> None: ...
    def set_mesh(self, mesh, color_by=None) -> None: ...
    def set_field(self, spec) -> None: ...
    def set_symbols(self, symbols) -> None: ...
    def set_axis_visible(self, visible) -> None: ...
    def highlight(self, dim, tags) -> None: ...
    def fit(self) -> None: ...
    def save_image(self, path, dpi=200) -> None: ...

    def pick(self, dim: int, tags: list[int]) -> None:
        self.selection_changed.emit(dim, tags)


@pytest.fixture
def built_doc(qtbot) -> Document:
    model = api.new_model()
    api.Geometry(model).rectangle(0.0, 0.0, 4.0, 2.0)
    built = api.build(model)
    doc = Document(model)
    doc.set_built(built)
    model.bcs.append(Convection("Conv", "", h=Constant(1.0), T_inf=Constant(300.0)))
    return doc


def top_curve(doc: Document) -> int:
    ents = doc.built.entities(1)
    return max(ents, key=lambda t: ents[t].center[1])


SPEC = FieldSpec("selection", "Selection", "selection", selection_dims=(1,))


def test_pick_then_apply_stores_a_selection_in_one_undo_step(qtbot, built_doc) -> None:
    view = FakeView()
    assert isinstance(view, SceneView)
    editor = SelectionEditor(built_doc, view, SPEC)
    qtbot.addWidget(editor)
    editor.name_hint = "Top edge"
    assert editor.pick_button.isEnabled() and not editor.apply_button.isEnabled()

    editor.pick_button.setChecked(True)
    assert view.mode == "curve"
    tag = top_curve(built_doc)
    view.pick(0, [1])  # wrong dimension: ignored
    assert editor.picked() == (-1, [])
    view.pick(1, [tag])
    assert editor.picked() == (1, [tag]) and editor.apply_button.isEnabled()
    assert "1 curve" in editor.status_label.text()

    editor.apply_button.click()
    sel = built_doc.model.selections["Top edge"]
    assert sel.dim == 1 and sel.tags == [tag]
    assert len(sel.fingerprints) == 1 and sel.fingerprints[0].center[1] == pytest.approx(2.0)
    assert built_doc.undo_stack.count() == 1
    assert editor.value() == "Top edge"
    built_doc.undo_stack.undo()
    assert "Top edge" not in built_doc.model.selections
    assert "Top edge" not in [editor.combo.itemText(i) for i in range(editor.combo.count())]

    editor.pick_button.setChecked(False)
    assert view.mode == "none"
    view.pick(1, [tag])  # no longer listening
    assert editor.picked() == (1, [tag])  # unchanged from before


def test_second_apply_with_a_taken_name_gets_a_unique_one(qtbot, built_doc) -> None:
    view = FakeView()
    editor = SelectionEditor(built_doc, view, SPEC)
    qtbot.addWidget(editor)
    editor.name_hint = "Edge"
    editor.pick_button.setChecked(True)
    view.pick(1, [top_curve(built_doc)])
    assert editor.apply() == "Edge"
    assert editor.apply() == "Edge"  # re-applying replaces our own selection
    other = SelectionEditor(built_doc, view, SPEC)
    qtbot.addWidget(other)
    other.name_hint = "Edge"
    other._picked = editor._picked
    assert other.apply() == "Edge 2"


def test_choose_existing_selection_emits(qtbot, built_doc) -> None:
    view = FakeView()
    editor = SelectionEditor(built_doc, view, SPEC)
    qtbot.addWidget(editor)
    got = []
    editor.value_changed.connect(got.append)
    names = [editor.combo.itemText(i) for i in range(editor.combo.count())]
    assert "all" not in names  # "all" holds a surface; the field wants curves
    editor.pick_button.setChecked(True)
    view.pick(1, [top_curve(built_doc)])
    editor.apply()
    got.clear()
    editor.choose("")
    assert got == [""]


def test_picking_is_disabled_without_a_build(qtbot) -> None:
    doc = Document(api.new_model())
    editor = SelectionEditor(doc, FakeView(), SPEC)
    qtbot.addWidget(editor)
    assert not editor.pick_button.isEnabled()
    assert "Build the geometry" in editor.pick_button.toolTip()
    none_view = SelectionEditor(doc, None, SPEC)
    qtbot.addWidget(none_view)
    assert "No viewport" in none_view.pick_button.toolTip()


def test_form_panel_apply_creates_selection_and_sets_field_in_one_step(qtbot, built_doc) -> None:
    view = FakeView()
    p = FormPanel(form_for(Convection), built_doc, ("bcs", 0), view)
    qtbot.addWidget(p)
    editor = p.editors["selection"]
    assert isinstance(editor, SelectionEditor) and editor.spec.selection_dims == (1,)
    editor.pick_button.setChecked(True)
    assert view.mode == "curve"
    tag = top_curve(built_doc)
    view.pick(1, [tag])
    editor.apply_button.click()
    assert built_doc.model.bcs[0].selection == "Conv selection"
    assert built_doc.model.selections["Conv selection"].tags == [tag]
    assert built_doc.undo_stack.count() == 1
    assert editor.current_label.text() == "Conv selection"
    built_doc.undo_stack.undo()
    assert built_doc.model.bcs[0].selection == ""
    assert "Conv selection" not in built_doc.model.selections
    assert editor.current_label.text() == "(none)"
    built_doc.undo_stack.redo()
    assert built_doc.model.bcs[0].selection == "Conv selection"
    assert editor.current_label.text() == "Conv selection"


def test_selection_list_field_appends_and_clears(qtbot, built_doc) -> None:
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
    assert isinstance(walls, SelectionEditor)
    walls.pick_button.setChecked(True)
    view.pick(1, [top_curve(built_doc)])
    walls.apply()
    assert built_doc.model.streams[0].walls == ["S walls"]
    ents = built_doc.built.entities(1)
    bottom = min(ents, key=lambda t: ents[t].center[1])
    view.pick(1, [bottom])
    walls.apply()
    assert built_doc.model.streams[0].walls == ["S walls", "S walls 2"]
    walls.clear()
    assert built_doc.model.streams[0].walls == []


def test_failed_apply_leaves_the_label_unchanged(qtbot, built_doc) -> None:
    view = FakeView()
    p = FormPanel(form_for(Convection), built_doc, ("bcs", 0), view)
    qtbot.addWidget(p)
    editor = p.editors["selection"]
    assert editor.current_label.text() == "(none)"
    editor.pick_button.setChecked(True)
    view.pick(1, [987654])  # no such curve: the store fails
    assert editor.apply_button.isEnabled()
    editor.apply_button.click()
    assert editor.current_label.text() == "(none)" and editor.value() == ""
    assert built_doc.model.bcs[0].selection == "" and built_doc.undo_stack.count() == 0


def test_toolbar_shows_the_picking_mode(qtbot, window, built_doc) -> None:
    view = FakeView()
    tree, controller = attach_tree(window, built_doc, view)
    controller.show_object(("bcs", 0))
    editor = controller.panel.editors["selection"]
    assert isinstance(editor, SelectionEditor)
    editor.pick_button.setChecked(True)
    assert view.mode == "curve"
    assert window.actions["select.curve"].isChecked()
    editor.pick_button.setChecked(False)
    assert view.mode == "none"
    assert window.actions["select.none"].isChecked()


def test_changing_the_panel_ends_picking(qtbot, window, built_doc) -> None:
    view = FakeView()
    tree, controller = attach_tree(window, built_doc, view)
    controller.show_object(("bcs", 0))
    editor = controller.panel.editors["selection"]
    editor.pick_button.setChecked(True)
    assert view.mode == "curve"
    controller.show_object(("section", "none"))  # another tree item: the panel is replaced
    assert view.mode == "none"
    assert window.actions["select.none"].isChecked()
    assert not editor.pick_button.isChecked()
    view.pick(1, [top_curve(built_doc)])  # the dead editor gets no pick
    assert editor.picked() == (-1, [])
