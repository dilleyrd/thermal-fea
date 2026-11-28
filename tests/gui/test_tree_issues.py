"""M11.78: problems marked in the model tree (C13)."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QTreeWidgetItem

from thermalfea import api
from thermalfea.core.functions import Constant
from thermalfea.gui import icons
from thermalfea.gui.document import Document
from thermalfea.gui.tree import ModelTree
from thermalfea.gui.tree_issues import DEBOUNCE_MS, TreeIssueController, attach_tree_issues
from thermalfea.model.bcs import Convection, FixedTemperature

WAIT = 5000  # ms; every wait is bounded


@pytest.fixture
def doc(qtbot) -> Document:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0.0, 0.0, 0.6, 0.2, id="plate")
    built = api.build(model)
    api.select_curves(model, built, "cooled", lambda fp: abs(fp.center[1]) < 1e-9)
    api.select_surfaces(model, built, "body", lambda fp: True)
    api.assign_region(model, "body", "Copper (pure)")
    model.bcs.append(Convection("cool", "cooled", h=Constant(750.0), T_inf=Constant(273.15)))
    document = Document(model)
    document.set_built(built)
    return document


@pytest.fixture
def tree(qtbot, doc) -> ModelTree:
    t = ModelTree(doc)
    qtbot.addWidget(t)
    return t


@pytest.fixture
def marks(doc, tree) -> TreeIssueController:
    controller = TreeIssueController(doc, tree)
    controller.refresh()  # the first run, without the wait
    return controller


def marked(tree: ModelTree) -> list[QTreeWidgetItem]:
    """The items that carry the warning mark, in tree order."""
    key = icons.icon("warning").pixmap(16, 16).toImage()
    out: list[QTreeWidgetItem] = []

    def walk(item: QTreeWidgetItem) -> None:
        if item.icon(0).pixmap(16, 16).toImage() == key:
            out.append(item)
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tree.topLevelItemCount()):
        walk(tree.topLevelItem(i))
    return out


def wait_marked(qtbot, tree: ModelTree, count: int) -> None:
    qtbot.waitUntil(lambda: len(marked(tree)) == count, timeout=WAIT)


def test_warning_icon_is_in_the_icon_set() -> None:
    assert "warning" in icons.ICON_NAMES
    assert not icons.icon("warning").isNull()
    assert not icons.icon("warning").pixmap(16, 16).isNull()


def test_clean_model_has_no_marks(marks, tree) -> None:
    assert marks.issues == []
    assert marked(tree) == []


def test_load_without_selection_is_marked_and_fixing_it_clears_the_mark(
    qtbot, doc, tree, marks
) -> None:
    doc.edit("Add", lambda m: m.bcs.append(FixedTemperature("hot", "", T=400.0)))
    wait_marked(qtbot, tree, 1)
    item = tree.item_for(("bcs", 1))
    assert marked(tree) == [item]
    tip = item.toolTip(0)
    assert tip.startswith("error: ")
    assert "hot" in tip
    assert len(marks.issues) == 1
    assert tip.splitlines() == [f"error: {marks.issues[0].message}", "Fixed Temperature"]

    doc.edit("Fix", lambda m: setattr(m.bcs[1], "selection", "cooled"))
    wait_marked(qtbot, tree, 0)
    assert "error:" not in tree.item_for(("bcs", 1)).toolTip(0)


def test_marks_wait_for_the_debounce(qtbot, doc, tree, marks) -> None:
    doc.edit("Add", lambda m: m.bcs.append(FixedTemperature("hot", "", T=400.0)))
    assert marks.timer.isActive()
    assert marks.timer.interval() == DEBOUNCE_MS
    assert marked(tree) == []
    wait_marked(qtbot, tree, 1)


def test_part_without_material_is_marked_and_swatch_comes_back(qtbot, doc, tree, marks) -> None:
    address = ("regions", 0)
    before = tree.item_for(address).icon(0).cacheKey()
    tooltip = tree.item_for(address).toolTip(0)
    doc.edit("Break", lambda m: setattr(m.regions[0], "material", "Unobtainium"))
    wait_marked(qtbot, tree, 1)
    item = tree.item_for(address)
    assert marked(tree) == [item]
    assert "Unobtainium" in item.toolTip(0)
    assert item.toolTip(0).endswith("body -> Unobtainium")  # the tree's own tooltip, below

    doc.edit("Fix", lambda m: setattr(m.regions[0], "material", "Copper (pure)"))
    wait_marked(qtbot, tree, 0)
    item = tree.item_for(address)
    assert item.icon(0).cacheKey() == before
    assert item.toolTip(0) == tooltip


def test_material_swatch_comes_back(qtbot, doc, tree, marks) -> None:
    address = ("materials", "Copper (pure)")
    before = tree.item_for(address).icon(0).cacheKey()
    doc.edit("Break", lambda m: setattr(m.materials["Copper (pure)"], "k", Constant(0.0)))
    wait_marked(qtbot, tree, 1)
    assert marked(tree) == [tree.item_for(address)]
    doc.edit("Fix", lambda m: setattr(m.materials["Copper (pure)"], "k", Constant(390.0)))
    wait_marked(qtbot, tree, 0)
    assert tree.item_for(address).icon(0).cacheKey() == before


def test_marks_survive_a_rebuild(qtbot, doc, tree, marks) -> None:
    doc.edit("Add", lambda m: m.bcs.append(FixedTemperature("hot", "", T=400.0)))
    wait_marked(qtbot, tree, 1)
    tree.rebuild()  # new items at once, before any new validation
    assert [tree.address_of(i) for i in marked(tree)] == [("bcs", 1)]


def test_issue_without_item_marks_the_section(qtbot, doc, tree, marks) -> None:
    doc.edit("Remove", lambda m: m.bcs.clear())  # no temperature reference: no address
    wait_marked(qtbot, tree, 1)
    assert marked(tree) == [tree.section_item("loads")]
    assert "error:" in tree.section_item("loads").toolTip(0)


def test_works_without_a_build(qtbot, doc, tree, marks) -> None:
    doc.built = None
    doc.edit("Add", lambda m: m.bcs.append(FixedTemperature("hot", "", T=400.0)))
    wait_marked(qtbot, tree, 1)
    assert marked(tree) == [tree.item_for(("bcs", 1))]


def test_failing_validation_clears_the_marks(qtbot, doc, tree, marks, monkeypatch) -> None:
    from thermalfea.core.errors import ModelError
    from thermalfea.gui import tree_issues

    doc.edit("Add", lambda m: m.bcs.append(FixedTemperature("hot", "", T=400.0)))
    wait_marked(qtbot, tree, 1)

    def broken(*_args) -> None:
        raise ModelError("broken")

    monkeypatch.setattr(tree_issues, "validate", broken)
    monkeypatch.setattr(tree_issues, "validate_model", broken)
    doc.edit("Touch", lambda m: setattr(m, "name", "other"))
    wait_marked(qtbot, tree, 0)
    assert marks.issues == []


def test_attach_to_the_window(qtbot, window) -> None:
    document = Document()
    window.set_document(document)
    tree = ModelTree(document)
    qtbot.addWidget(tree)
    controller = attach_tree_issues(window, document, tree)
    assert window.tree_issues is controller
    assert controller.parent() is window
