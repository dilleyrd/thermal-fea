"""M8.2: document, undo commands and their wiring into the main window."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import make_settings
from thermalfea import api
from thermalfea.core.functions import Constant
from thermalfea.gui.commands import ModelEditCommand
from thermalfea.gui.document import Document, classify_change
from thermalfea.gui.main_window import MainWindow
from thermalfea.model.bcs import HeatFlux
from thermalfea.model.model import Model
from thermalfea.model.serialize import to_json


def small_model() -> Model:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5)
    model.mesh_settings.global_size = 0.25
    return model


def flags(doc: Document) -> tuple[bool, bool, bool]:
    return doc.geometry_stale, doc.mesh_stale, doc.results_stale


def fresh_document(qtbot) -> Document:
    """A document with a built, meshed and solved small model; nothing stale."""
    doc = Document(small_model())
    built = api.build(doc.model)
    api.select_curves(doc.model, built, "hot", where=lambda cv: abs(cv.center[1] - 0.5) < 1e-9)
    api.assign_region(doc.model, "all", material="Copper (pure)")
    doc.model.bcs.append(HeatFlux("load", "hot", q=Constant(100.0)))
    doc.model.bcs.append(HeatFlux("load2", "hot", q=Constant(50.0)))
    doc.set_built(built)
    return doc


def solved_document(qtbot, tmp_path: Path) -> Document:
    doc = fresh_document(qtbot)
    mesh = api.mesh(doc.model, doc.built)
    doc.set_mesh(mesh)
    doc.set_results(tmp_path / "r.h5")
    return doc


def set_global_size(size: float):
    def mutate(model: Model) -> None:
        model.mesh_settings.global_size = size

    return mutate


def rename(name: str):
    def mutate(model: Model) -> None:
        model.name = name

    return mutate


def add_bc(model: Model) -> None:
    model.bcs.append(HeatFlux("extra", "hot", q=Constant(1.0)))


def add_rectangle(model: Model) -> None:
    api.Geometry(model).rectangle(2.0, 0.0, 1.0, 0.5)


# ----------------------------------------------------------------------- editing


def test_edit_undo_redo(qtbot) -> None:
    doc = Document(small_model())
    original = to_json(doc.model)
    with qtbot.waitSignal(doc.model_changed, timeout=1000):
        assert doc.edit("Rename", rename("other"))
    assert doc.model.name == "other"
    assert doc.undo_stack.count() == 1
    assert doc.undo_stack.undoText() == "Rename"
    doc.undo_stack.undo()
    assert to_json(doc.model) == original
    doc.undo_stack.redo()
    assert doc.model.name == "other"


def test_edit_emits_model_changed_once(qtbot) -> None:
    doc = Document(small_model())
    seen: list[int] = []
    doc.model_changed.connect(lambda: seen.append(1))
    doc.edit("Rename", rename("x"))
    assert len(seen) == 1
    doc.undo_stack.undo()
    assert len(seen) == 2


def test_undo_equals_original_model(qtbot) -> None:
    doc = Document(small_model())
    original = doc.model
    doc.edit("Size", set_global_size(0.1))
    assert doc.model is not original
    doc.undo_stack.undo()
    assert doc.model == original


def test_noop_edit_pushes_nothing(qtbot) -> None:
    doc = Document(small_model())
    seen: list[int] = []
    doc.model_changed.connect(lambda: seen.append(1))
    assert doc.edit("Nothing", lambda m: None) is False
    assert doc.edit("Same", rename("plate")) is False
    assert doc.undo_stack.count() == 0
    assert not seen and not doc.modified


def test_failing_mutate_leaves_document_untouched(qtbot) -> None:
    doc = Document(small_model())
    before = to_json(doc.model)
    model_obj = doc.model

    def bad(model: Model) -> None:
        model.name = "half-done"
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        doc.edit("Bad", bad)
    assert doc.model is model_obj
    assert to_json(doc.model) == before
    assert doc.undo_stack.count() == 0


def test_ten_edits_undo_redo(qtbot) -> None:
    doc = Document(small_model())
    states = [to_json(doc.model)]
    for i in range(10):
        doc.edit(f"Rename {i}", rename(f"n{i}"))
        states.append(to_json(doc.model))
    for i in range(10, 0, -1):
        assert to_json(doc.model) == states[i]
        doc.undo_stack.undo()
    assert to_json(doc.model) == states[0]
    for i in range(1, 11):
        doc.undo_stack.redo()
        assert to_json(doc.model) == states[i]


def test_command_snapshots_are_immutable_text(qtbot) -> None:
    doc = Document(small_model())
    doc.edit("Rename", rename("z"))
    command = doc.undo_stack.command(0)
    assert isinstance(command, ModelEditCommand)
    assert isinstance(command.before, str) and isinstance(command.after, str)
    doc.model.name = "mutated outside"
    doc.undo_stack.undo()
    assert doc.model.name == "plate"


# --------------------------------------------------------------------- staleness


def test_classify_change() -> None:
    base = to_json(small_model())
    assert classify_change(base, base) == "none"
    other = small_model()
    other.mesh_settings.global_size = 0.1
    assert classify_change(base, to_json(other)) == "mesh"
    other = small_model()
    api.Geometry(other).rectangle(2, 0, 1, 1)
    assert classify_change(base, to_json(other)) == "geometry"
    other = small_model()
    other.name = "x"
    assert classify_change(base, to_json(other)) == "results"


def test_geometry_edit_marks_everything_stale(qtbot, tmp_path: Path) -> None:
    doc = solved_document(qtbot, tmp_path)
    assert flags(doc) == (False, False, False)
    doc.edit("Add rectangle", add_rectangle)
    assert flags(doc) == (True, True, True)


def test_mesh_settings_edit(qtbot, tmp_path: Path) -> None:
    doc = solved_document(qtbot, tmp_path)
    doc.edit("Size", set_global_size(0.1))
    assert flags(doc) == (False, True, True)


def test_load_edit_only_results_stale(qtbot, tmp_path: Path) -> None:
    doc = solved_document(qtbot, tmp_path)
    doc.edit("Add load", add_bc)
    assert flags(doc) == (False, False, True)


def test_undo_applies_same_rule(qtbot, tmp_path: Path) -> None:
    doc = solved_document(qtbot, tmp_path)
    doc.edit("Add load", add_bc)
    doc.undo_stack.undo()
    assert flags(doc) == (False, False, True)
    doc = solved_document(qtbot, tmp_path)
    doc.edit("Size", set_global_size(0.1))
    doc.set_mesh(api.mesh(doc.model, doc.built))
    doc.set_results(tmp_path / "r2.h5")
    assert flags(doc) == (False, False, False)
    doc.undo_stack.undo()
    assert flags(doc) == (False, True, True)
    doc.set_mesh(api.mesh(doc.model, doc.built))
    doc.set_results(tmp_path / "r3.h5")
    doc.undo_stack.redo()
    assert flags(doc) == (False, True, True)
    doc.undo_stack.undo()
    doc = solved_document(qtbot, tmp_path)
    doc.edit("Add rectangle", add_rectangle)
    doc.set_built(api.build(doc.model))
    doc.set_mesh(api.mesh(doc.model, doc.built))
    doc.set_results(tmp_path / "r4.h5")
    doc.undo_stack.undo()
    assert flags(doc) == (True, True, True)


def test_stale_changed_signal(qtbot, tmp_path: Path) -> None:
    doc = solved_document(qtbot, tmp_path)
    with qtbot.waitSignal(doc.stale_changed, timeout=1000):
        doc.edit("Add load", add_bc)


# ----------------------------------------------------------------- build products


def test_set_built_mesh_results(qtbot, tmp_path: Path) -> None:
    doc = Document(small_model())
    assert flags(doc) == (True, True, True)
    built = api.build(doc.model)
    with qtbot.waitSignal(doc.geometry_built, timeout=1000):
        doc.set_built(built)
    assert doc.built is built
    assert flags(doc) == (False, True, True)
    mesh = api.mesh(doc.model, built)
    with qtbot.waitSignal(doc.mesh_changed, timeout=1000):
        doc.set_mesh(mesh)
    assert doc.mesh is mesh and flags(doc) == (False, False, True)
    path = tmp_path / "x.h5"
    with qtbot.waitSignal(doc.results_changed, timeout=1000):
        doc.set_results(path)
    assert doc.results_path == path and flags(doc) == (False, False, False)


def test_rebuild_drops_old_mesh(qtbot, tmp_path: Path) -> None:
    doc = solved_document(qtbot, tmp_path)
    doc.set_built(api.build(doc.model))
    assert doc.mesh is None and flags(doc) == (False, True, True)


def test_set_built_with_edit_in_between_stays_geometry_stale(qtbot) -> None:
    doc = Document(small_model())
    worker_copy = Document(small_model()).model
    built = api.build(worker_copy)
    doc.edit("Add rectangle", add_rectangle)
    doc.set_built(built, worker_copy)
    assert doc.geometry_stale


def test_set_model_resets(qtbot, tmp_path: Path) -> None:
    doc = solved_document(qtbot, tmp_path)
    doc.edit("Rename", rename("q"))
    new = small_model()
    seen = {n: 0 for n in ("model", "geometry", "mesh", "results")}
    doc.model_changed.connect(lambda: seen.__setitem__("model", seen["model"] + 1))
    doc.geometry_built.connect(lambda: seen.__setitem__("geometry", seen["geometry"] + 1))
    doc.mesh_changed.connect(lambda: seen.__setitem__("mesh", seen["mesh"] + 1))
    doc.results_changed.connect(lambda: seen.__setitem__("results", seen["results"] + 1))
    doc.set_model(new, tmp_path / "m.json")
    assert doc.model is new and doc.path == tmp_path / "m.json"
    assert doc.built is None and doc.mesh is None and doc.results_path is None
    assert doc.undo_stack.count() == 0 and not doc.modified
    assert flags(doc) == (True, True, True)
    assert all(v == 1 for v in seen.values())
    doc.new()
    assert doc.model is not new and doc.path is None


# ------------------------------------------------------------------- selections


def test_rebuild_is_not_an_edit_and_selections_survive_undo(qtbot, tmp_path: Path) -> None:
    doc = fresh_document(qtbot)
    doc.edit("Add rectangle", add_rectangle)
    count = doc.undo_stack.count()
    built = api.build(doc.model)  # builds on the live model, rewriting its selections
    doc.set_built(built)
    assert doc.undo_stack.count() == count  # the rebuild registered no command
    tags_after_build = list(doc.model.selections["hot"].tags)
    assert set(doc.model.selections["all"].tags) == set(built.surfaces)
    # a load edit after the build, then undo/redo: selections still resolved
    doc.edit("Add load", add_bc)
    doc.undo_stack.undo()
    doc.undo_stack.redo()
    doc.undo_stack.undo()
    assert doc.model.selections["hot"].tags == tags_after_build
    assert set(doc.model.selections["all"].tags) == set(built.surfaces)
    assert set(tags_after_build) <= set(built.entities(1))
    # undo of the geometry edit restores the old geometry; after rebuild the selection works
    doc.undo_stack.undo()
    assert doc.geometry_stale
    built2 = api.build(doc.model)
    doc.set_built(built2)
    assert set(doc.model.selections["hot"].tags) <= set(built2.entities(1))
    assert not doc.geometry_stale


def test_selection_tags_do_not_count_as_edit(qtbot) -> None:
    doc = fresh_document(qtbot)
    base = to_json(doc.model)
    other = to_json(doc.model)
    other["selections"]["hot"]["tags"] = [99]
    other["selections"].pop("all")
    assert classify_change(base, other) == "none"


# ----------------------------------------------------------------------- modified


def test_modified_follows_clean_state(qtbot) -> None:
    doc = Document(small_model())
    assert not doc.modified
    doc.edit("Rename", rename("a"))
    assert doc.modified
    doc.undo_stack.undo()
    assert not doc.modified
    doc.undo_stack.redo()
    doc.mark_saved()
    assert not doc.modified
    doc.edit("Rename", rename("b"))
    assert doc.modified
    doc.undo_stack.undo()
    assert not doc.modified


# ------------------------------------------------------------------------ window


def test_window_undo_redo_actions(qtbot, settings_path: Path) -> None:
    window = MainWindow(settings=make_settings(settings_path))
    qtbot.addWidget(window)
    doc = Document(small_model())
    window.set_document(doc)
    undo, redo = window.actions["edit.undo"], window.actions["edit.redo"]
    assert not undo.isEnabled() and not redo.isEnabled()
    doc.edit("Rename", rename("w"))
    assert undo.isEnabled() and not redo.isEnabled()
    assert "Rename" in undo.text()
    undo.trigger()
    assert doc.model.name == "plate"
    assert not undo.isEnabled() and redo.isEnabled()
    assert "Rename" in redo.text()
    redo.trigger()
    assert doc.model.name == "w"
    assert undo.isEnabled() and not redo.isEnabled()


def test_window_title(qtbot, settings_path: Path) -> None:
    window = MainWindow(settings=make_settings(settings_path))
    qtbot.addWidget(window)
    assert window.windowTitle() == "ThermalFEA"
    doc = Document(small_model())
    window.set_document(doc)
    assert window.windowTitle().startswith("plate - ")
    doc.edit("Rename", rename("renamed"))
    assert window.windowTitle().startswith("renamed* - ")
    doc.undo_stack.undo()
    assert window.windowTitle().startswith("plate - ")
    doc.edit("Rename", rename("saved"))
    doc.mark_saved()
    assert window.windowTitle().startswith("saved - ")


def test_window_document_replaced(qtbot, settings_path: Path) -> None:
    window = MainWindow(settings=make_settings(settings_path))
    qtbot.addWidget(window)
    first, second = Document(small_model()), Document(small_model())
    window.set_document(first)
    window.set_document(second)
    first.edit("Rename", rename("a"))
    assert not window.actions["edit.undo"].isEnabled()
    second.edit("Rename", rename("b"))
    assert window.actions["edit.undo"].isEnabled()
    window.set_document(None)
    assert not window.actions["edit.undo"].isEnabled()
    assert window.document is None
