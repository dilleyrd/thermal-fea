"""M11.57: the library source of a material in the panel and the tree summary."""

from __future__ import annotations

from pathlib import Path

import pytest

from thermalfea import api
from thermalfea.core.functions import Constant
from thermalfea.core.units import UnitSettings
from thermalfea.gui import tree_summary as ts
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.material import USER_SUFFIX
from thermalfea.materials import library
from thermalfea.materials.material import Material, MaterialSource, PhaseChange

COPPER = "Copper (pure)"
MINE = "My alloy"


@pytest.fixture
def user_path(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "user" / "materials.json"
    monkeypatch.setattr(library, "user_library_path", lambda: path)
    return path


@pytest.fixture
def doc(qtbot) -> Document:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0, 0, 1, 1)
    built = api.build(model)
    api.assign_region(model, "all", COPPER, thickness=0.01)
    document = Document(model)
    document.set_built(built)
    model.materials["Mine"] = Material("Mine", Constant(0.0), Constant(0.0), Constant(0.0))
    document.set_built(built)
    return document


def open_panel(window, doc) -> tuple:
    tree, controller = attach_tree(window, doc)
    tree.select_address(("materials", "Mine"))
    return controller.panel, controller


def save_user(path: Path) -> Material:
    entry = Material(
        MINE,
        Constant(12.5),
        Constant(7000.0),
        Constant(450.0),
        k2=Constant(3.0),
        phase_change=PhaseChange(1500.0, 1600.0, 2.5e5),
    )
    library.save_user_library({MINE: entry}, {}, path)
    return entry


def use(panel, label: str) -> None:
    panel.library_combo.setEditText(label)
    panel.use_button.click()


def summary(doc) -> str:
    return ts.material_summary(doc.model.materials["Mine"], UnitSettings())


def test_use_sets_the_source_in_the_same_undo_step(window, doc, user_path) -> None:
    panel, _ = open_panel(window, doc)
    assert doc.model.materials["Mine"].source is None
    use(panel, COPPER)
    mat = doc.model.materials["Mine"]
    assert mat.source == MaterialSource("builtin", COPPER)
    assert mat.name == "Mine"
    assert doc.undo_stack.count() == 1
    doc.undo_stack.undo()
    assert doc.model.materials["Mine"].source is None


def test_same_name_in_both_libraries_keeps_distinct_sources(window, doc, user_path) -> None:
    entry = save_user(user_path)
    entry.name = COPPER
    entry.k = Constant(11.0)
    library.save_user_library({COPPER: entry}, {}, user_path)
    panel, _ = open_panel(window, doc)
    combo = panel.library_combo
    assert combo.itemData(combo.findText(COPPER)) == MaterialSource("builtin", COPPER)
    assert combo.itemData(combo.findText(COPPER + USER_SUFFIX)) == MaterialSource(
        "user", COPPER
    )
    use(panel, COPPER)
    assert doc.model.materials["Mine"].source == MaterialSource("builtin", COPPER)
    assert doc.model.materials["Mine"].k == library.solids()[COPPER].k
    use(panel, COPPER + USER_SUFFIX)
    mat = doc.model.materials["Mine"]
    assert mat.source == MaterialSource("user", COPPER)
    assert mat.k == Constant(11.0)
    assert "user library" in panel.source_label.text()


def test_states_in_panel_and_summary(window, doc, user_path) -> None:
    panel, _ = open_panel(window, doc)
    assert panel.source_label.text() == "Custom values"
    assert summary(doc).endswith(" · custom") and summary(doc).startswith("k ")
    assert not panel.restore_button.isEnabled()

    use(panel, COPPER)
    assert panel.source_label.text() == f"Values from the built-in library: {COPPER}"
    assert summary(doc) == f"{COPPER} · library"
    assert not panel.restore_button.isEnabled()

    doc.edit("edit", lambda m: setattr(m.materials["Mine"], "k", Constant(1.0)))
    doc.edit("edit", lambda m: setattr(m.materials["Mine"], "cp", Constant(1.0)))
    assert summary(doc) == f"{COPPER} · edited"
    assert "edited: k, cp" in panel.source_label.text()
    assert panel.restore_button.isEnabled()

    doc.edit(
        "src",
        lambda m: setattr(m.materials["Mine"], "source", MaterialSource("builtin", "Nope")),
    )
    assert summary(doc) == "Nope · library entry not found"
    assert "not found" in panel.source_label.text()
    assert not panel.restore_button.isEnabled()


def test_user_entry_states_and_unreadable_library(window, doc, user_path) -> None:
    save_user(user_path)
    panel, _ = open_panel(window, doc)
    use(panel, MINE + USER_SUFFIX)
    assert summary(doc) == f"{MINE} · library"
    assert panel.source_label.text() == f"Values from the user library: {MINE}"
    user_path.write_text("{ not json", encoding="utf-8")
    panel.refresh()
    assert summary(doc) == f"{MINE} · library entry not found"  # no crash
    user_path.unlink()
    assert summary(doc) == f"{MINE} · library entry not found"


def test_restore_is_one_undo_step_and_keeps_name_and_source(window, doc, user_path) -> None:
    panel, _ = open_panel(window, doc)
    use(panel, COPPER)
    doc.edit("edit", lambda m: setattr(m.materials["Mine"], "k", Constant(1.0)))
    count = doc.undo_stack.count()
    assert panel.restore_button.isEnabled()
    assert panel.restore_button.text() == "Restore library values"
    panel.restore_button.click()
    mat = doc.model.materials["Mine"]
    assert mat.k == library.solids()[COPPER].k
    assert mat.name == "Mine" and mat.source == MaterialSource("builtin", COPPER)
    assert doc.undo_stack.count() == count + 1
    assert summary(doc) == f"{COPPER} · library"
    assert not panel.restore_button.isEnabled()
    doc.undo_stack.undo()
    assert doc.model.materials["Mine"].k == Constant(1.0)


def test_saving_to_the_user_library_keeps_the_source(
    window, doc, user_path: Path
) -> None:
    from thermalfea.gui.dialogs.material_library import MaterialLibraryDialog

    panel, _ = open_panel(window, doc)
    use(panel, COPPER)
    dialog = MaterialLibraryDialog(doc, user_path=user_path)
    dialog.model_combo.setCurrentText("Mine")
    assert dialog.save_to_user_library()
    solids, _ = library.load_user_library(user_path)
    assert solids["Mine"].source == MaterialSource("builtin", COPPER)
    dialog.close()
