"""M11.44: the "From library" box of the material panel.

The user library is always a temporary file (``user_library_path`` is monkeypatched), never
the real one.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from thermalfea import api
from thermalfea.core.functions import Constant
from thermalfea.gui.document import Document
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.material import USER_SUFFIX, MaterialPanel
from thermalfea.materials import library
from thermalfea.materials.material import Material, PhaseChange

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
    model.materials["Mine"] = Material(
        "Mine", Constant(0.0), Constant(0.0), Constant(0.0)
    )
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


def test_registered_for_a_material(window, doc, user_path) -> None:
    panel, controller = open_panel(window, doc)
    assert isinstance(panel, MaterialPanel)
    assert controller.current_address == ("materials", "Mine")


def test_list_is_builtins_then_user_entries_with_suffix(window, doc, user_path) -> None:
    save_user(user_path)
    panel, _ = open_panel(window, doc)
    builtin = list(library.solids())
    assert panel.library_names() == [*builtin, MINE + USER_SUFFIX]
    combo = panel.library_combo
    assert [combo.itemText(i) for i in range(combo.count())] == panel.library_names()


def test_equal_names_stay_distinct(window, doc, user_path) -> None:
    entry = save_user(user_path)
    entry.name = COPPER
    library.save_user_library({COPPER: entry}, {}, user_path)
    panel, _ = open_panel(window, doc)
    names = panel.library_names()
    assert COPPER in names and COPPER + USER_SUFFIX in names


def test_type_to_search_filters_by_contains(window, doc, user_path) -> None:
    panel, _ = open_panel(window, doc)
    completer = panel.library_combo.completer()
    completer.setCompletionPrefix("copper")
    model = completer.completionModel()
    shown = [model.data(model.index(r, 0)) for r in range(model.rowCount())]
    assert COPPER in shown
    assert any(s.startswith("Copper, ") for s in shown)
    assert all("copper" in s.casefold() for s in shown)
    assert not any(s.startswith("Aluminum") for s in shown)
    completer.setCompletionPrefix("PURE")  # contains, not prefix; case-insensitive
    model = completer.completionModel()
    assert COPPER in [model.data(model.index(r, 0)) for r in range(model.rowCount())]


def test_use_values_replaces_properties_in_one_undo_step(window, doc, user_path) -> None:
    panel, _ = open_panel(window, doc)
    reference = library.solids()[COPPER]
    panel.library_combo.setEditText(COPPER)
    assert panel.use_button.text() == "Use library values"
    panel.use_button.click()
    mat = doc.model.materials["Mine"]
    assert mat.name == "Mine"
    assert mat.k == reference.k and mat.rho == reference.rho and mat.cp == reference.cp
    assert mat.k2 == reference.k2 and mat.phase_change == reference.phase_change
    assert doc.model.regions[0].material == COPPER  # the region is untouched
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.undoText() == "Use library values"
    assert panel.error_text() == ""
    doc.undo_stack.undo()
    back = doc.model.materials["Mine"]
    assert back.k == Constant(0.0) and back.rho == Constant(0.0) and back.cp == Constant(0.0)
    assert back.k2 is None and back.phase_change is None


def test_the_copy_is_independent_of_the_library(window, doc, user_path) -> None:
    panel, _ = open_panel(window, doc)
    panel.library_combo.setEditText(COPPER)
    panel.use_button.click()
    assert doc.model.materials["Mine"].k is not library.solids()[COPPER].k


def test_a_region_that_uses_the_material_stays_assigned(window, doc, user_path) -> None:
    doc.model.regions[0].material = "Mine"
    panel, _ = open_panel(window, doc)
    panel.library_combo.setEditText("Copper, Cartridge brass")
    panel.use_button.click()
    assert doc.model.regions[0].material == "Mine"
    assert "Mine" in doc.model.materials


def test_user_library_entry_works(window, doc, user_path) -> None:
    entry = save_user(user_path)
    panel, _ = open_panel(window, doc)
    panel.library_combo.setEditText(MINE + USER_SUFFIX)
    panel.use_button.click()
    mat = doc.model.materials["Mine"]
    assert mat.name == "Mine"
    assert mat.k == entry.k and mat.rho == entry.rho and mat.cp == entry.cp
    assert mat.k2 == entry.k2 and mat.phase_change == entry.phase_change
    assert doc.undo_stack.count() == 1


def test_unreadable_user_library_shows_error_and_lists_builtins(
    window, doc, user_path
) -> None:
    user_path.parent.mkdir(parents=True)
    user_path.write_text("{ not json", encoding="utf-8")
    panel, _ = open_panel(window, doc)
    assert panel.error_text("library")
    assert "cannot read the user material library" in panel.error_label.text()
    assert panel.library_names() == list(library.solids())


def test_library_is_reread_on_refresh(window, doc, user_path) -> None:
    panel, _ = open_panel(window, doc)
    assert MINE + USER_SUFFIX not in panel.library_names()
    save_user(user_path)
    panel.refresh()
    assert MINE + USER_SUFFIX in panel.library_names()


@pytest.mark.parametrize("text", ["", "No such material"])
def test_nothing_chosen_is_an_error_and_no_edit(window, doc, user_path, text) -> None:
    panel, _ = open_panel(window, doc)
    panel.library_combo.setEditText(text)
    panel.use_button.click()
    assert panel.error_text("library-use")
    assert panel.error_label.text() != ""
    assert doc.undo_stack.count() == 0
    assert doc.model.materials["Mine"].k == Constant(0.0)
