"""M8.6: material and region panels, tree add actions, the library dialog and its menu entry.

Dialogs are constructed and driven without ``exec()``; every user library file is a
temporary path, never the real user library.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thermalfea import api
from thermalfea.gui.dialogs.material_library import MaterialLibraryDialog
from thermalfea.gui.document import Document
from thermalfea.gui.materials_tools import ACTION_ID, attach_materials
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.region import RegionPanel
from thermalfea.gui.tree import ModelTree
from thermalfea.materials import library

COPPER = "Copper (pure)"


def same_properties(material, other) -> bool:
    """True when two materials have the same properties (the names may differ)."""
    return {**material.to_json(), "name": ""} == {**other.to_json(), "name": ""}


@pytest.fixture
def doc(qtbot) -> Document:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0, 0, 1, 1)
    built = api.build(model)
    api.assign_region(model, "all", COPPER, thickness=0.01)
    document = Document(model)
    document.set_built(built)
    return document


@pytest.fixture
def user_path(tmp_path: Path) -> Path:
    return tmp_path / "user" / "materials.json"


@pytest.fixture
def shell(qtbot, window, doc):
    """Tree and property controller attached to the window (as in the application)."""
    tree, controller = attach_tree(window, doc)
    return tree, controller


def enter(edit, text: str) -> None:
    edit.setText(text)
    edit.editingFinished.emit()


def action_named(tree: ModelTree, section: str, text: str):
    actions = tree.actions_for(tree.section_item(section))
    return next(a for a in actions if a.text() == text)


# ---------------------------------------------------------------- tree add actions


def test_add_material_is_one_undo_step_with_unique_names(shell, doc) -> None:
    tree, _ = shell
    template = next(iter(library.solids().values()))
    action_named(tree, "materials", "Add material").trigger()
    assert list(doc.model.materials) == [COPPER, "Material 1"]
    new = doc.model.materials["Material 1"]
    assert new.k == template.k and new.rho == template.rho and new.cp == template.cp
    assert new.name == "Material 1"
    assert doc.undo_stack.count() == 1 and doc.undo_stack.undoText() == "Add material"
    assert tree.address_of(tree.currentItem()) == ("materials", "Material 1")

    action_named(tree, "materials", "Add material").trigger()
    assert list(doc.model.materials) == [COPPER, "Material 1", "Material 2"]
    doc.undo_stack.undo()
    doc.undo_stack.undo()
    assert list(doc.model.materials) == [COPPER]
    assert tree.item_for(("materials", COPPER)) is not None


def test_add_region_is_one_undo_step(shell, doc) -> None:
    tree, _ = shell
    action_named(tree, "regions", "Add region").trigger()
    assert len(doc.model.regions) == 2
    region = doc.model.regions[1]
    assert region.selection == "" and region.material == COPPER
    assert region.thickness == 1.0 and region.material_angle == 0.0
    assert doc.undo_stack.count() == 1 and doc.undo_stack.undoText() == "Add region"
    doc.undo_stack.undo()
    assert len(doc.model.regions) == 1
    assert doc.model.regions[0].selection == "all"


def test_selecting_material_and_region_shows_their_forms(window, shell, doc) -> None:
    tree, controller = shell
    tree.select_address(("materials", COPPER))
    assert isinstance(controller.panel, FormPanel)
    assert controller.current_address == ("materials", COPPER)
    assert list(controller.panel.editors) == ["k", "rho", "cp", "k2"]
    assert window.property_widget is not None

    tree.select_address(("regions", 0))
    assert isinstance(controller.panel, RegionPanel)
    fields = ["selection", "material", "thickness", "material_angle"]
    assert list(controller.panel.editors) == fields


# ------------------------------------------------------------------- material panel


def test_editing_conductivity_changes_the_model_in_one_step(shell, doc) -> None:
    tree, controller = shell
    tree.select_address(("materials", COPPER))
    panel = controller.panel
    enter(panel.editors["k"].value_edit, "200")
    assert doc.model.materials[COPPER].k.value == pytest.approx(200.0)
    assert doc.undo_stack.count() == 1 and doc.undo_stack.undoText() == "Edit Thermal conductivity"
    doc.undo_stack.undo()
    assert doc.model.materials[COPPER].k.value == pytest.approx(401.0)


def test_negative_density_is_refused(shell, doc) -> None:
    tree, controller = shell
    tree.select_address(("materials", COPPER))
    enter(controller.panel.editors["rho"].value_edit, "-1")
    assert doc.model.materials[COPPER].rho.value == pytest.approx(8933.0)
    assert doc.undo_stack.count() == 0


# ------------------------------------------------------------------- region panel


def test_region_material_combo_lists_model_materials(shell, doc) -> None:
    tree, controller = shell
    action_named(tree, "materials", "Add material").trigger()
    tree.select_address(("regions", 0))
    panel = controller.panel
    combo = panel.editors["material"]
    names = [combo.itemText(i) for i in range(combo.count())]
    assert names == [COPPER, "Material 1"]
    assert combo.currentText() == COPPER


def test_choosing_another_material_updates_the_region(shell, doc) -> None:
    tree, controller = shell
    action_named(tree, "materials", "Add material").trigger()
    tree.select_address(("regions", 0))
    panel = controller.panel
    combo = panel.editors["material"]
    before = doc.undo_stack.count()
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert doc.model.regions[0].material == "Material 1"
    assert doc.undo_stack.count() == before + 1
    assert tree.item_for(("regions", 0)).text(0) == "all -> Material 1"
    doc.undo_stack.undo()
    assert doc.model.regions[0].material == COPPER


def test_region_thickness_and_angle_edits(shell, doc) -> None:
    tree, controller = shell
    tree.select_address(("regions", 0))
    panel = controller.panel
    enter(panel.editors["thickness"], "0.02")
    assert doc.model.regions[0].thickness == pytest.approx(0.02)
    enter(panel.editors["material_angle"], "0.5")
    assert doc.model.regions[0].material_angle == pytest.approx(0.5)
    assert doc.undo_stack.count() == 2
    doc.undo_stack.undo()
    assert doc.model.regions[0].material_angle == pytest.approx(0.0)
    doc.undo_stack.undo()
    assert doc.model.regions[0].thickness == pytest.approx(0.01)


def test_negative_region_thickness_is_refused(shell, doc) -> None:
    tree, controller = shell
    tree.select_address(("regions", 0))
    enter(controller.panel.editors["thickness"], "-0.1")
    assert doc.model.regions[0].thickness == pytest.approx(0.01)
    assert doc.undo_stack.count() == 0


# --------------------------------------------------------------- library dialog


@pytest.fixture
def dialog(qtbot, doc, user_path) -> MaterialLibraryDialog:
    d = MaterialLibraryDialog(doc, user_path)
    qtbot.addWidget(d)
    return d


def select_text(list_widget, text: str) -> None:
    for row in range(list_widget.count()):
        if list_widget.item(row).text() == text:
            list_widget.setCurrentRow(row)
            return
    raise AssertionError(f"{text!r} not listed")


def test_builtin_tab_lists_the_library(dialog) -> None:
    names = [dialog.builtin_list.item(i).text() for i in range(dialog.builtin_list.count())]
    assert names and names == list(library.solids())
    assert dialog.tabs.tabText(0) == "Built-in" and dialog.tabs.tabText(1) == "User"
    select_text(dialog.builtin_list, COPPER)
    assert "401" in dialog.summary.toPlainText()  # read-only property summary


def test_copy_into_model_adds_equal_copies_with_unique_names(dialog, doc) -> None:
    # the model already holds Copper (pure) (from the region fixture): copies get new names
    select_text(dialog.builtin_list, COPPER)
    assert dialog.copy_into_model() is True
    first = f"{COPPER} 2"
    assert same_properties(doc.model.materials[first], library.solid(COPPER))
    assert doc.model.materials[first].name == first
    select_text(dialog.builtin_list, COPPER)
    assert dialog.copy_into_model() is True
    second = f"{COPPER} 3"
    assert same_properties(doc.model.materials[second], library.solid(COPPER))
    assert doc.undo_stack.count() == 2


def test_copy_without_selection_is_refused_in_status(dialog, doc) -> None:
    dialog.builtin_list.setCurrentRow(-1)
    assert dialog.copy_into_model() is False
    assert "Select" in dialog.status.text()
    assert doc.undo_stack.count() == 0


def test_save_to_user_library_and_reopen_shows_it_under_user(qtbot, doc, user_path) -> None:
    first = MaterialLibraryDialog(doc, user_path)
    qtbot.addWidget(first)
    first.model_combo.setCurrentText(COPPER)
    assert first.save_to_user_library() is True
    assert user_path.exists()
    assert set(json.loads(user_path.read_text(encoding="utf-8"))) == {"solids", "fluids"}

    second = MaterialLibraryDialog(doc, user_path)
    qtbot.addWidget(second)
    assert second.user_path == user_path
    users = [second.user_list.item(i).text() for i in range(second.user_list.count())]
    assert users == [COPPER]

    # the same name cannot be saved twice
    second.model_combo.setCurrentText(COPPER)
    assert second.save_to_user_library() is False
    assert "already" in second.status.text()


def test_user_material_can_be_copied_and_removed(qtbot, doc, user_path) -> None:
    d = MaterialLibraryDialog(doc, user_path)
    qtbot.addWidget(d)
    d.model_combo.setCurrentText(COPPER)
    d.save_to_user_library()
    select_text(d.user_list, COPPER)
    assert d.copy_into_model() is True
    assert same_properties(doc.model.materials[f"{COPPER} 2"], doc.model.materials[COPPER])

    select_text(d.user_list, COPPER)
    assert d.remove_from_user_library() is True
    reopened = MaterialLibraryDialog(doc, user_path)
    qtbot.addWidget(reopened)
    assert reopened.user_list.count() == 0
    assert d.remove_from_user_library() is False  # nothing selected any more
    assert "Select" in d.status.text()


def test_remove_only_touches_the_given_user_file(qtbot, doc, user_path) -> None:
    d = MaterialLibraryDialog(doc, user_path)
    qtbot.addWidget(d)
    d.model_combo.setCurrentText(COPPER)
    d.save_to_user_library()
    select_text(d.user_list, COPPER)
    d.remove_from_user_library()
    data = json.loads(user_path.read_text(encoding="utf-8"))
    assert data == {"fluids": [], "solids": []}


def test_attach_materials_adds_action_and_shows_dialog(qtbot, window, doc, user_path) -> None:
    controller = attach_materials(window, doc, user_path)
    action = window.actions[ACTION_ID]
    assert action.text() == "Material library..."
    assert action in window.menus["tools"].actions()
    action.trigger()
    dialog = controller.dialog
    assert dialog is not None
    qtbot.addWidget(dialog)
    assert dialog.isVisible()  # shown, and the call returned (not exec())
    assert dialog.user_path == user_path
    dialog.close()
