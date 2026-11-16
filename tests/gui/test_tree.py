"""M8.4: the model tree, its context-menu actions and the registry-generated Add entries."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from PySide6.QtWidgets import QLabel, QScrollArea

from thermalfea import api
from thermalfea.core import registry
from thermalfea.core.functions import Constant, Function
from thermalfea.gui.document import Document
from thermalfea.gui.panels import PropertyController, attach_tree
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.tree import SECTIONS, ModelTree
from thermalfea.model import bcs
from thermalfea.model.bcs import Convection, HeatFlux
from thermalfea.model.serialize import from_json, to_json


@pytest.fixture
def doc(qtbot) -> Document:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5, id="plate")
    model.bcs.append(HeatFlux("Flux 1", "hot", q=Constant(100.0)))
    model.bcs.append(Convection("Conv 1", "cold", h=Constant(10.0), T_inf=Constant(300.0)))
    return Document(model)


@pytest.fixture
def tree(qtbot, doc) -> ModelTree:
    t = ModelTree(doc)
    qtbot.addWidget(t)
    return t


def texts(tree: ModelTree, key: str) -> list[str]:
    item = tree.section_item(key)
    return [item.child(i).text(0) for i in range(item.childCount())]


def by_data(actions, kind: str):
    return [a for a in actions if a.data() and a.data()[0] == kind]


def test_top_level_nodes(tree) -> None:
    titles = [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]
    assert titles == [
        "Geometry", "Materials", "Regions", "Mesh", "Initial Condition",
        "Loads & Boundary Conditions", "Contacts", "Flow", "Enclosures", "Analysis Settings",
        "Solution",
    ]  # fmt: skip
    assert titles == [t for _, t in SECTIONS]
    assert texts(tree, "geometry") == ["plate"]
    assert texts(tree, "loads") == ["Flux 1", "Conv 1"]
    flow = tree.section_item("flow")
    assert [flow.child(i).text(0) for i in range(flow.childCount())] == ["Streams", "Network"]


def test_add_actions_come_from_the_registry(tree) -> None:
    actions = tree.actions_for(tree.section_item("loads"))
    adds = by_data(actions, "add_bc")
    assert [a.data()[1] for a in adds] == registry.bc_tags()
    assert "Add Convection" in [a.text() for a in adds]
    assert "Add Fixed Temperature" in [a.text() for a in adds]
    assert tree.actions_for(tree.section_item("geometry")) == []
    menu = tree.build_menu(tree.section_item("loads"))
    assert [a.text() for a in menu.actions()] == ["Add"]


def test_add_bc_is_one_undo_step(tree, doc) -> None:
    actions = tree.actions_for(tree.section_item("loads"))
    add = next(a for a in actions if a.text() == "Add Convection")
    add.trigger()
    assert [b.name for b in doc.model.bcs] == ["Flux 1", "Conv 1", "Convection 1"]
    assert isinstance(doc.model.bcs[2], Convection)
    assert doc.undo_stack.count() == 1 and doc.undo_stack.undoText() == "Add Convection"
    assert texts(tree, "loads")[-1] == "Convection 1"
    assert tree.address_of(tree.currentItem()) == ("bcs", 2)
    tree.add_bc("convection")
    assert doc.model.bcs[3].name == "Convection 2"
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert [b.name for b in doc.model.bcs] == ["Flux 1", "Conv 1"]
    assert texts(tree, "loads") == ["Flux 1", "Conv 1"]


def test_rename_duplicate_suppress_delete(tree, doc) -> None:
    item = tree.item_for(("bcs", 1))
    actions = {a.data()[0]: a for a in tree.actions_for(item)}
    assert set(actions) == {"rename", "duplicate", "suppress", "delete"}
    assert actions["suppress"].text() == "Suppress"

    # rename: one undo step, names stay unique
    assert tree.rename(("bcs", 1), "Cooling")
    assert doc.model.bcs[1].name == "Cooling" and doc.undo_stack.count() == 1
    with pytest.raises(Exception, match="already used"):
        tree.rename(("bcs", 1), "Flux 1")
    with pytest.raises(Exception, match="empty"):
        tree.rename(("bcs", 1), "  ")
    assert doc.undo_stack.count() == 1
    assert texts(tree, "loads") == ["Flux 1", "Cooling"]

    # duplicate
    actions = {a.data()[0]: a for a in tree.actions_for(tree.item_for(("bcs", 1)))}
    actions["duplicate"].trigger()
    assert [b.name for b in doc.model.bcs] == ["Flux 1", "Cooling", "Cooling 2"]
    assert doc.model.bcs[2].h == doc.model.bcs[1].h and doc.model.bcs[2] is not doc.model.bcs[1]
    assert doc.undo_stack.count() == 2
    assert tree.address_of(tree.currentItem()) == ("bcs", 2)

    # suppress / unsuppress
    actions = {a.data()[0]: a for a in tree.actions_for(tree.item_for(("bcs", 2)))}
    actions["suppress"].trigger()
    assert doc.model.bcs[2].active is False and doc.undo_stack.count() == 3
    assert tree.item_for(("bcs", 2)).font(0).italic()
    actions = {a.data()[0]: a for a in tree.actions_for(tree.item_for(("bcs", 2)))}
    assert actions["suppress"].text() == "Unsuppress"
    actions["suppress"].trigger()
    assert doc.model.bcs[2].active is True and doc.undo_stack.count() == 4
    assert not tree.item_for(("bcs", 2)).font(0).italic()

    # delete
    actions = {a.data()[0]: a for a in tree.actions_for(tree.item_for(("bcs", 0)))}
    actions["delete"].trigger()
    assert [b.name for b in doc.model.bcs] == ["Cooling", "Cooling 2"]
    assert doc.undo_stack.count() == 5

    # undo restores the model and the tree, step by step
    doc.undo_stack.undo()
    assert [b.name for b in doc.model.bcs] == ["Flux 1", "Cooling", "Cooling 2"]
    assert texts(tree, "loads") == ["Flux 1", "Cooling", "Cooling 2"]
    for _ in range(4):
        doc.undo_stack.undo()
    assert [b.name for b in doc.model.bcs] == ["Flux 1", "Conv 1"]
    assert texts(tree, "loads") == ["Flux 1", "Conv 1"]


def test_inline_rename_commits_and_rejects(tree, doc) -> None:
    item = tree.item_for(("bcs", 0))
    item.setText(0, "Heat in")
    assert doc.model.bcs[0].name == "Heat in"
    errors = []
    tree.error_occurred.connect(errors.append)
    tree.item_for(("bcs", 0)).setText(0, "Conv 1")  # duplicate name: refused
    assert doc.model.bcs[0].name == "Heat in" and errors
    assert texts(tree, "loads")[0] == "Heat in"


def test_materials_and_regions(qtbot) -> None:
    model = api.new_model()
    api.Geometry(model).rectangle(0, 0, 1, 1)
    built = api.build(model)
    api.assign_region(model, "all", "Copper (pure)")
    doc = Document(model)
    doc.set_built(built)
    tree = ModelTree(doc)
    qtbot.addWidget(tree)
    assert texts(tree, "materials") == ["Copper (pure)"]
    assert texts(tree, "regions") == ["all -> Copper (pure)"]
    tree.rename(("materials", "Copper (pure)"), "Cu")
    assert list(doc.model.materials) == ["Cu"] and doc.model.materials["Cu"].name == "Cu"
    assert doc.model.regions[0].material == "Cu"
    tree.duplicate(("materials", "Cu"))
    assert list(doc.model.materials) == ["Cu", "Cu 2"]
    tree.delete(("materials", "Cu 2"))
    tree.delete(("regions", 0))
    assert doc.model.regions == [] and texts(tree, "regions") == []
    assert doc.undo_stack.count() == 4


def test_rebuild_keeps_expansion_and_current_item(tree, doc) -> None:
    loads = tree.section_item("loads")
    loads.setExpanded(False)
    geometry = tree.section_item("geometry")
    tree.setCurrentItem(tree.item_for(("bcs", 1)))
    selected = []
    tree.object_selected.connect(selected.append)
    tree.rename(("bcs", 0), "A")
    assert not tree.section_item("loads").isExpanded()
    assert tree.section_item("geometry").isExpanded()
    assert geometry is not tree.section_item("geometry")  # items were rebuilt
    assert tree.address_of(tree.currentItem()) == ("bcs", 1)
    assert selected == []  # a rebuild is not a user selection


def test_selecting_emits_address(tree) -> None:
    got = []
    tree.object_selected.connect(got.append)
    tree.setCurrentItem(tree.item_for(("bcs", 1)))
    tree.setCurrentItem(tree.section_item("mesh"))
    tree.setCurrentItem(tree.section_item("materials"))
    assert got == [("bcs", 1), ("mesh_settings",), ("section", "materials")]


# ------------------------------------------------------- Plan §7 rule 6: no GUI edit needed


def test_newly_registered_load_appears_in_tree_and_gets_a_panel(qtbot, doc, window) -> None:
    @dataclass
    class WallPower(bcs.BoundaryCondition):
        power: Function
        efficiency: float = 0.9

    registry.register_bc("test_wall_power", WallPower)
    try:
        tree, controller = attach_tree(window, doc)
        assert isinstance(controller, PropertyController)
        adds = by_data(tree.actions_for(tree.section_item("loads")), "add_bc")
        action = next(a for a in adds if a.data()[1] == "test_wall_power")
        assert action.text() == "Add Wall Power"
        action.trigger()
        assert isinstance(doc.model.bcs[-1], WallPower)
        assert doc.model.bcs[-1].name == "Wall Power 1"
        assert doc.undo_stack.count() == 1

        # the new object is selected, so the property dock shows its generated form
        panel = controller.panel
        assert isinstance(panel, FormPanel) and controller.current_address == ("bcs", 2)
        assert isinstance(window.property_widget, QScrollArea)
        assert {"selection", "power", "efficiency"} == set(panel.editors)

        # ... and the panel works: editing a field goes through the undo stack
        panel.editors["efficiency"].setText("0.5")
        panel.editors["efficiency"].editingFinished.emit()
        assert doc.model.bcs[-1].efficiency == 0.5 and doc.undo_stack.count() == 2

        # it saves and loads like any built-in load
        again = from_json(to_json(doc.model))
        assert type(again.bcs[-1]) is WallPower and again.bcs[-1].efficiency == 0.5
    finally:
        registry._CLASSES["bc"].pop("test_wall_power")
        registry._BCS.pop("test_wall_power")


def test_controller_shows_placeholder_when_object_vanishes(qtbot, doc, window) -> None:
    tree, controller = attach_tree(window, doc)
    tree.setCurrentItem(tree.item_for(("bcs", 1)))
    assert controller.panel is not None
    tree.delete(("bcs", 1))
    assert controller.panel is None
    assert isinstance(window.property_widget, QLabel)
    doc.undo_stack.undo()
    tree.setCurrentItem(tree.item_for(("bcs", 1)))
    assert controller.panel is not None
    tree.setCurrentItem(tree.section_item("loads"))
    assert controller.panel is None


def test_settings_nodes_show_derived_forms(qtbot, doc, window) -> None:
    tree, controller = attach_tree(window, doc)
    tree.setCurrentItem(tree.section_item("mesh"))
    assert controller.panel is not None and "global_size" in controller.panel.editors
    tree.setCurrentItem(tree.section_item("analysis"))
    assert "kind" in controller.panel.editors and "end_time" in controller.panel.editors
    tree.setCurrentItem(tree.section_item("initial"))
    assert "kind" in controller.panel.editors
