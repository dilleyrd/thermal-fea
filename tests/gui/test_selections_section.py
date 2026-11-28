"""M11.54: the Selections section, its highlight, panel, stepping and issue navigation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest

from thermalfea import api
from thermalfea.core.functions import Constant
from thermalfea.gui.document import Document
from thermalfea.gui.issues import IssuePanel, address_for_issue
from thermalfea.gui.load_symbols import attach_loads
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.selection_panel import SelectionPanel
from thermalfea.model.bcs import Convection
from thermalfea.model.model import RegionAssignment
from thermalfea.model.selections import Fingerprint
from thermalfea.model.validate import Issue


class FakeView(QObject):
    """A SceneView stand-in recording highlights and the selection mode."""

    selection_changed = Signal(int, list)
    point_picked = Signal(float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.mode = "none"
        self.highlights: list[tuple[int, list[int]]] = []

    def set_selection_mode(self, mode: str) -> None:
        self.mode = mode

    def highlight(self, dim: int, tags: list[int]) -> None:
        self.highlights.append((dim, list(tags)))

    def set_symbols(self, symbols: Any) -> None: ...

    def set_entity_colors(self, dim, colors, legend) -> None: ...

    def set_overlay(self, layer: str, items: list[Any]) -> None: ...

    def pick(self, dim: int, tags: list[int]) -> None:
        self.selection_changed.emit(dim, tags)


def curve_at(built, y: float) -> int:
    ents = built.entities(1)
    return min(ents, key=lambda t: abs(ents[t].center[1] - y) + abs(ents[t].center[0] - 0.5))


@pytest.fixture
def shell(window) -> SimpleNamespace:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5, id="plate")
    built = api.build(model)
    api.select_surfaces(model, built, "plate", where=lambda fp: True)
    top, bottom = curve_at(built, 0.5), curve_at(built, 0.0)
    api.select_curves(model, built, "cooled", tags=[top, bottom])
    api.select_curves(model, built, "spare", tags=[top])
    model.regions.append(RegionAssignment("plate", "Al", 1.0, 0.0))
    model.bcs.append(Convection("cooling", "cooled", h=Constant(10.0), T_inf=Constant(300.0)))
    doc = Document(model)
    doc.set_built(built)
    view = FakeView()
    tree, props = attach_tree(window, doc, view)
    loads = attach_loads(window, doc, view)
    return SimpleNamespace(
        window=window, doc=doc, view=view, tree=tree, props=props, loads=loads,
        top=top, bottom=bottom,
    )  # fmt: skip


def names(tree) -> list[str]:
    item = tree.section_item("selections")
    return [item.child(i).text(0) for i in range(item.childCount())]


def summary(tree, name: str) -> str:
    return tree.item_for(("selections", name)).text(1)


def panel(shell, name: str) -> SelectionPanel:
    shell.tree.select_address(("selections", name))
    assert isinstance(shell.props.panel, SelectionPanel)
    return shell.props.panel


def test_section_lists_every_selection_with_summaries(shell) -> None:
    tree = shell.tree
    titles = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert titles.index("Selections") == titles.index("Parts") + 1
    assert names(tree) == ["plate", "cooled", "spare", "all"]
    assert tree.section_item("selections").text(1) == "4"
    assert summary(tree, "cooled") == "2 boundaries · convection cooling"
    assert summary(tree, "spare") == "1 boundary · unused"
    assert summary(tree, "plate").startswith("1 part · ")
    assert tree.item_for(("selections", "cooled")).icon(0).isNull() is False


def test_selecting_highlights_in_the_current_build(shell) -> None:
    shell.tree.select_address(("selections", "cooled"))
    assert shell.view.highlights[-1] == (1, sorted([shell.top, shell.bottom]))
    shell.tree.select_address(("selections", "plate"))
    assert shell.view.highlights[-1][0] == 2


def test_stale_selection_is_cleared_with_a_message(shell) -> None:
    sel = shell.doc.model.selections["spare"]
    sel.fingerprints[0] = Fingerprint(1, (9.0, 9.0, 0.0), 0.3, (9, 9, 0, 9.3, 9, 0))
    shell.doc.model_changed.emit()
    assert summary(shell.tree, "spare") == "stale"
    shell.tree.select_address(("selections", "spare"))
    assert shell.view.highlights[-1] == (1, [])
    assert shell.window.statusBar().currentMessage() == "spare: not found in the current geometry"


def test_inline_rename_updates_the_load_in_one_undo_step(shell) -> None:
    doc, tree = shell.doc, shell.tree
    count = doc.undo_stack.count()
    item = tree.item_for(("selections", "cooled"))
    item.setText(0, "chilled")
    assert doc.undo_stack.count() == count + 1
    assert doc.model.bcs[0].selection == "chilled"
    assert "cooled" not in doc.model.selections
    assert tree.address_of(tree.currentItem()) == ("selections", "chilled")
    doc.undo_stack.undo()
    assert doc.model.bcs[0].selection == "cooled"
    assert "cooled" in doc.model.selections


def test_all_is_not_renameable_or_deletable(shell) -> None:
    item = shell.tree.item_for(("selections", "all"))
    assert not item.flags() & Qt.ItemFlag.ItemIsEditable
    actions = shell.tree.actions_for(item)
    assert [a.text() for a in actions] == ["Delete"]
    assert not actions[0].isEnabled()


def test_panel_rename_is_one_undo_step_and_refusals_change_nothing(shell) -> None:
    doc = shell.doc
    p = panel(shell, "cooled")
    count = doc.undo_stack.count()
    before = dict(doc.model.selections)
    for bad in ("spare", "all", ""):
        p.name_edit.setText(bad)
        assert p.rename() is False
        assert p.message_label.text()
        assert doc.undo_stack.count() == count
        assert list(doc.model.selections) == list(before)
    p.name_edit.setText("chilled")
    assert p.rename() is True
    assert doc.undo_stack.count() == count + 1
    assert doc.model.bcs[0].selection == "chilled"
    assert isinstance(shell.props.panel, SelectionPanel)
    assert shell.props.panel.name == "chilled"
    doc.undo_stack.undo()
    assert doc.model.bcs[0].selection == "cooled"


def test_panel_content(shell) -> None:
    p = panel(shell, "cooled")
    assert p.kind_label.text() == "Boundary · 2 curves"
    assert "total length" in p.entities_label.text()
    assert p.bounds_label.text() == "plate"
    assert [b.text() for b in p.user_buttons] == ["convection cooling"]
    assert not p.delete_button.isEnabled()
    assert "convection cooling" in p.delete_button.toolTip()


def test_delete_refused_while_used_allowed_when_unused(shell) -> None:
    doc = shell.doc
    count = doc.undo_stack.count()
    with pytest.raises(Exception, match="used by"):
        shell.tree.delete_selection_item(("selections", "cooled"))
    assert doc.undo_stack.count() == count
    assert "cooled" in doc.model.selections
    p = panel(shell, "spare")
    assert p.delete_button.isEnabled()
    p.delete_button.click()
    assert "spare" not in doc.model.selections
    assert doc.undo_stack.count() == count + 1
    doc.undo_stack.undo()
    assert "spare" in doc.model.selections
    assert not panel(shell, "all").delete_button.isEnabled()


def test_used_by_link_selects_the_load(shell) -> None:
    p = panel(shell, "cooled")
    p.user_buttons[0].click()
    assert shell.tree.address_of(shell.tree.currentItem()) == ("bcs", 0)


def test_used_by_link_selects_mesh_settings(shell) -> None:
    shell.doc.edit("size", lambda m: m.mesh_settings.curve_sizes.update({"spare": 0.1}))
    p = panel(shell, "spare")
    assert [b.text() for b in p.user_buttons] == ["mesh: boundary size"]
    p.user_buttons[0].click()
    assert shell.tree.address_of(shell.tree.currentItem()) == ("mesh_settings",)


def test_add_and_remove_from_viewport(shell) -> None:
    doc, view = shell.doc, shell.view
    p = panel(shell, "spare")
    assert p.add_button.isEnabled()
    count = doc.undo_stack.count()
    p.add_button.click()  # M11.69 (C2): a pick with a strip, confirmed by "Add"
    assert view.mode == "curve" and not p.strip.isHidden()
    assert not p.add_button.isEnabled()  # one pick at a time
    view.pick(1, [shell.bottom])
    view.pick(2, [1])  # another dimension is ignored
    assert p.picked() == [shell.bottom]
    assert p.strip.count_label.text() == "1 boundary picked"
    p.strip.confirm_button.click()
    assert view.mode == "none" and p.strip.isHidden()
    assert doc.undo_stack.count() == count + 1
    sel = doc.model.selections["spare"]
    assert sorted(sel.tags) == sorted([shell.top, shell.bottom])
    assert len(sel.fingerprints) == 2
    p = shell.props.panel
    p.remove_button.click()
    assert p.strip.confirm_button.text() == "Remove"
    view.pick(1, [shell.top])
    p.strip.confirm_button.click()
    assert doc.model.selections["spare"].tags == [shell.bottom]
    assert doc.undo_stack.count() == count + 2
    doc.undo_stack.undo()
    assert sorted(doc.model.selections["spare"].tags) == sorted([shell.top, shell.bottom])


def test_cancel_leaves_the_selection_unchanged(shell) -> None:
    doc, view = shell.doc, shell.view
    p = panel(shell, "spare")
    count = doc.undo_stack.count()
    p.add_button.click()
    view.pick(1, [shell.bottom])
    p.strip.cancel_button.click()
    assert doc.undo_stack.count() == count and doc.model.selections["spare"].tags == [shell.top]
    assert view.mode == "none" and p.strip.isHidden() and p.add_button.isEnabled()


def test_removing_everything_is_refused(shell) -> None:
    doc = shell.doc
    p = panel(shell, "spare")
    count = doc.undo_stack.count()
    p.remove_button.click()
    shell.view.pick(1, [shell.top])
    p.strip.confirm_button.click()
    assert doc.undo_stack.count() == count
    assert doc.model.selections["spare"].tags == [shell.top]
    assert p.message_label.text()


def test_all_cannot_be_edited_from_the_viewport(shell) -> None:
    p = panel(shell, "all")
    assert not p.add_button.isEnabled()
    assert not p.remove_button.isEnabled()


def test_page_down_and_up_step_through_selections(shell) -> None:
    tree = shell.tree
    tree.select_address(("selections", "plate"))
    tree.setFocus()
    QTest.keyClick(tree, Qt.Key.Key_PageDown)
    assert tree.address_of(tree.currentItem()) == ("selections", "cooled")
    QTest.keyClick(tree, Qt.Key.Key_PageDown)
    QTest.keyClick(tree, Qt.Key.Key_PageDown)
    assert tree.address_of(tree.currentItem()) == ("selections", "all")
    QTest.keyClick(tree, Qt.Key.Key_PageDown)  # at the end: stays
    assert tree.address_of(tree.currentItem()) == ("selections", "all")
    QTest.keyClick(tree, Qt.Key.Key_PageUp)
    assert tree.address_of(tree.currentItem()) == ("selections", "spare")


def test_issue_activation_navigates_to_the_selection(shell) -> None:
    model = shell.doc.model
    issue = Issue("error", "stale-selection", "gone", "selection", "cooled")
    assert address_for_issue(model, issue) == ("selections", "cooled")
    assert address_for_issue(model, Issue("error", "x", "m", "selection", "nope")) is None
    issues = IssuePanel(shell.tree)
    issues.set_issues([issue])
    assert issues.activate(0)
    assert shell.tree.address_of(shell.tree.currentItem()) == ("selections", "cooled")
