"""M8.13: file handling - New, Open, Save, Save As, recent files, the unsaved-changes prompt,
results reattached on open, and the Examples menu.

Every file is written under pytest's ``tmp_path``. Choosers and the unsaved-changes question
are replaced by recorders, so no modal dialog is shown. The solve uses the real gmsh and
solver on a tiny plate (the same model as the solve tests).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QEvent, QObject

from conftest import make_settings
from thermalfea import api
from thermalfea.gui.document import Document
from thermalfea.gui.file_tools import (
    EXAMPLES_DIR,
    RECENT_LIMIT,
    FileController,
    attach_files,
    example_entries,
    results_match,
)
from thermalfea.gui.main_window import MainWindow
from thermalfea.model import bcs
from thermalfea.model.model import Model


# ------------------------------------------------------------------------------- helpers
def plate(size: float = 0.25) -> Model:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5)
    model.mesh_settings.global_size = size
    return model


def rename(name: str) -> Callable[[Model], None]:
    def mutate(model: Model) -> None:
        model.name = name

    return mutate


def write_plate(path: Path) -> Model:
    model = plate()
    api.save(model, path)
    return model


def write_solved(tmp_path: Path, name: str = "plate.tfea") -> tuple[Path, Model]:
    """Save a plate with its loads, then solve it into ``<model>.tfea.h5`` beside it."""
    model = plate()
    built = api.build(model)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs += [
        bcs.FixedTemperature("hot", "west", T=400.0),
        bcs.Convection("cool", "east", h=100.0, T_inf=300.0),
    ]
    model_path = tmp_path / name
    api.save(model, model_path)
    mesh = api.mesh(model, built)
    api.solve(model, mesh, built=built, path=api.results_path(model_path))
    return model_path, model


@pytest.fixture
def document(window: MainWindow) -> Document:
    doc = Document(api.new_model(name="plate"), window)  # owned by the window: no early delete
    window.set_document(doc)
    return doc


@pytest.fixture
def files(window: MainWindow, document: Document) -> FileController:
    controller = attach_files(window, document)
    asked: list[tuple[Any, str]] = []

    def ask(parent: Any, name: str) -> str:
        asked.append((parent, name))
        return "cancel"

    controller.asked = asked  # type: ignore[attr-defined]
    controller.ask_unsaved = ask
    controller.choose_save = lambda parent, suggested: None
    controller.choose_open = lambda parent: None
    return controller


def answer_with(files: FileController, answer: str) -> None:
    """Answer the unsaved-changes question with ``answer``; every question is recorded."""
    asked: list[tuple[Any, str]] = files.asked  # type: ignore[attr-defined]

    def ask(parent: Any, name: str) -> str:
        asked.append((parent, name))
        return answer

    files.ask_unsaved = ask


def modify(document: Document) -> None:
    document.edit("Rename", rename("edited"))


def no_prompt(parent: Any, name: str) -> str:
    raise AssertionError("the unsaved-changes question must not be asked")


# ----------------------------------------------------------------- round trip and titles
def test_new_open_save_save_as_round_trip(files, document, window, tmp_path) -> None:
    model_path = tmp_path / "other.tfea"
    written = write_plate(model_path)
    assert files.new() is True
    assert document.path is None and not document.modified
    files.choose_save = lambda parent, suggested: str(tmp_path / "saved")
    modify(document)
    assert document.modified
    assert files.save_as() is True
    saved = tmp_path / "saved.tfea"
    assert saved.is_file()
    assert document.path == saved
    assert not document.modified
    assert api.load(saved) == document.model
    assert window.windowTitle().startswith("saved - ")
    document.edit("Rename", rename("second"))
    assert window.windowTitle().startswith("saved* - ")
    assert files.save() is True  # the document has a path: no chooser
    assert api.load(saved) == document.model
    assert files.open(model_path) is True
    assert document.model == written and document.path == model_path
    assert not document.modified
    assert window.windowTitle().startswith("other - ")


def test_save_without_path_asks_for_a_location(files, document, tmp_path) -> None:
    asked: list[str] = []

    def choose(parent: Any, suggested: str) -> str:
        asked.append(suggested)
        return str(tmp_path / "chosen.tfea")

    files.choose_save = choose
    modify(document)
    assert files.save() is True
    assert asked == ["edited.tfea"]
    assert document.path == tmp_path / "chosen.tfea"


def test_save_as_appends_suffix_only_without_one(files, document, tmp_path) -> None:
    files.choose_save = lambda parent, suggested: str(tmp_path / "noext")
    assert files.save_as() is True
    assert document.path == tmp_path / "noext.tfea"
    assert (tmp_path / "noext.tfea").is_file()
    files.choose_save = lambda parent, suggested: str(tmp_path / "dotted.v2")
    assert files.save_as() is True  # a name with a suffix is kept as given
    assert document.path == tmp_path / "dotted.v2"
    assert (tmp_path / "dotted.v2").is_file()


def test_cancelled_choosers_change_nothing(files, document) -> None:
    modify(document)
    assert files.save_as() is False
    assert files.open() is False
    assert document.modified and document.path is None


def test_file_actions_are_enabled_and_connected(files, window, tmp_path) -> None:
    for key in ("file.new", "file.open", "file.save", "file.save_as"):
        assert window.actions[key].isEnabled()
    target = tmp_path / "a.tfea"
    write_plate(target)
    files.choose_open = lambda parent: str(target)
    window.actions["file.open"].trigger()
    assert window.document.path == target
    window.actions["file.new"].trigger()
    assert window.document.path is None


# --------------------------------------------------------------------- unsaved prompt
@pytest.mark.parametrize("answer", ["save", "discard", "cancel"])
def test_new_prompts_when_modified(files, document, tmp_path, answer) -> None:
    write_plate(tmp_path / "x.tfea")
    files.choose_save = lambda parent, suggested: str(tmp_path / "kept.tfea")
    modify(document)
    before = document.model
    answer_with(files, answer)
    done = files.new()
    assert len(files.asked) == 1 and files.asked[0][1] == "edited"  # type: ignore[attr-defined]
    if answer == "cancel":
        assert done is False and document.model is before and document.modified
        assert not (tmp_path / "kept.tfea").exists()
    elif answer == "discard":
        assert done is True and document.model is not before
        assert not (tmp_path / "kept.tfea").exists()
    else:
        assert done is True and document.model is not before
        assert (tmp_path / "kept.tfea").is_file()
    if answer != "cancel":
        assert not document.modified and document.path is None


@pytest.mark.parametrize("answer", ["save", "discard", "cancel"])
def test_open_prompts_when_modified(files, document, tmp_path, answer) -> None:
    target = tmp_path / "other.tfea"
    write_plate(target)
    files.choose_save = lambda parent, suggested: str(tmp_path / "kept.tfea")
    modify(document)
    before = document.model
    answer_with(files, answer)
    done = files.open(target)
    assert len(files.asked) == 1  # type: ignore[attr-defined]
    if answer == "cancel":
        assert done is False and document.model is before and document.path is None
    else:
        assert done is True and document.path == target
        assert (tmp_path / "kept.tfea").is_file() == (answer == "save")


@pytest.mark.parametrize("answer", ["save", "discard", "cancel"])
def test_close_prompts_when_modified(files, document, window, tmp_path, answer) -> None:
    files.choose_save = lambda parent, suggested: str(tmp_path / "closing.tfea")
    modify(document)
    answer_with(files, answer)
    closed = window.close()
    assert len(files.asked) == 1  # type: ignore[attr-defined]
    if answer == "cancel":
        assert closed is False
    else:
        assert closed is True
    assert (tmp_path / "closing.tfea").is_file() == (answer == "save")


def test_close_refused_when_save_fails(files, document, window, tmp_path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("not a folder", encoding="utf-8")
    files.choose_save = lambda parent, suggested: str(blocker / "m.tfea")
    modify(document)
    answer_with(files, "save")
    assert window.close() is False
    assert window.document.modified


def test_no_prompt_when_not_modified(files, document, window, tmp_path) -> None:
    write_plate(tmp_path / "x.tfea")
    files.ask_unsaved = no_prompt
    assert files.new() is True
    assert files.open(tmp_path / "x.tfea") is True
    assert files.open_example(example_entries()[0][0]) is True
    assert window.close() is True


@pytest.mark.parametrize("answer", ["cancel", "discard"])
def test_refused_close_does_not_reach_later_filters(
    qtbot, settings_path, answer
) -> None:
    """Filters installed earlier run after the file filter (the app attaches it last).

    The recorder stands in for the solve controller's close filter: a refused close must
    not reach it, an accepted close must.
    """
    window = MainWindow(settings=make_settings(settings_path))
    qtbot.addWidget(window)
    doc = Document(api.new_model(name="plate"), window)
    window.set_document(doc)
    seen: list[str] = []
    recorder = _Recorder(seen)  # kept alive by the local name
    window.installEventFilter(recorder)
    controller = attach_files(window, doc)
    controller.ask_unsaved = lambda parent, name: answer
    modify(doc)
    closed = window.close()
    assert closed is (answer == "discard")
    assert seen == (["close"] if answer == "discard" else [])


class _Recorder(QObject):
    """An event filter that notes that a close reached it."""

    def __init__(self, seen: list[str]) -> None:
        super().__init__()
        self.seen = seen

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        if event.type() == QEvent.Type.Close:
            self.seen.append("close")
        return False


# ------------------------------------------------------------------------------ errors
def test_open_missing_file_reports_and_keeps_model(files, document, dialogs, tmp_path) -> None:
    before = document.model
    assert files.open(tmp_path / "missing.tfea") is False
    assert len(dialogs.calls) == 1 and dialogs.calls[0][0] == "Open model"
    assert document.model is before and document.path is None


def test_open_corrupt_file_reports_and_keeps_model(files, document, dialogs, tmp_path) -> None:
    corrupt = tmp_path / "corrupt.tfea"
    corrupt.write_text("{not json", encoding="utf-8")
    before = document.model
    assert files.open(corrupt) is False
    assert len(dialogs.calls) == 1
    assert document.model is before and document.path is None


def test_save_to_unwritable_location_reports_and_stays_modified(
    files, document, dialogs, tmp_path
) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("a regular file", encoding="utf-8")
    files.choose_save = lambda parent, suggested: str(blocker / "m.tfea")
    modify(document)
    assert files.save_as() is False
    assert len(dialogs.calls) == 1 and dialogs.calls[0][0] == "Save model"
    assert document.modified and document.path is None


# ------------------------------------------------------------------------- recent files
def test_recent_order_no_duplicates_and_limit(files, tmp_path) -> None:
    paths = []
    for i in range(RECENT_LIMIT + 2):
        path = tmp_path / f"m{i}.tfea"
        write_plate(path)
        paths.append(path)
        files.add_recent(path)
    recent = files.recent_files()
    assert len(recent) == RECENT_LIMIT
    assert recent[0] == str(paths[-1])
    assert recent == [str(p) for p in reversed(paths[-RECENT_LIMIT:])]
    files.add_recent(paths[5])
    recent = files.recent_files()
    assert recent[0] == str(paths[5]) and len(recent) == len(set(recent)) == RECENT_LIMIT


def test_recent_files_persist_across_windows(files, settings_path, tmp_path, qtbot) -> None:
    a, b = tmp_path / "a.tfea", tmp_path / "b.tfea"
    write_plate(a)
    write_plate(b)
    files.add_recent(a)
    files.add_recent(b)
    files.window.settings.sync()
    second = MainWindow(settings=make_settings(settings_path))
    qtbot.addWidget(second)
    other = attach_files(second, Document(api.new_model(), second))
    assert other.recent_files() == [str(b), str(a)]


def test_missing_recent_files_are_dropped(files, tmp_path) -> None:
    keep, gone = tmp_path / "keep.tfea", tmp_path / "gone.tfea"
    write_plate(keep)
    write_plate(gone)
    files.add_recent(keep)
    files.add_recent(gone)
    gone.unlink()
    files.refresh_recent_menu()
    assert files.recent_files() == [str(keep)]
    assert [a.text() for a in files.recent_actions] == [str(keep)]


def test_clear_recent(files, tmp_path) -> None:
    path = tmp_path / "c.tfea"
    write_plate(path)
    files.add_recent(path)
    files.clear_action.trigger()
    assert files.recent_files() == []
    assert files.recent_actions == []
    texts = [a.text() for a in files.recent_menu.actions() if not a.isSeparator()]
    assert texts == ["(none)", "Clear"]


def test_recent_action_opens_the_file(files, document, tmp_path) -> None:
    path = tmp_path / "r.tfea"
    write_plate(path)
    files.add_recent(path)
    files.refresh_recent_menu()
    assert files.recent_actions[0].text() == str(path)
    files.recent_actions[0].trigger()
    assert document.path == path


def test_recent_menu_refreshes_before_showing(files, tmp_path) -> None:
    path = tmp_path / "s.tfea"
    write_plate(path)
    files.add_recent(path)
    files.recent_menu.aboutToShow.emit()
    assert len(files.recent_actions) == 1


# ----------------------------------------------------------------------- results_match
def test_results_match_after_build_refreshed_tags(tmp_path) -> None:
    model_path, model = write_solved(tmp_path)
    assert results_match(api.load(model_path), api.results_path(model_path))
    reopened = api.load(model_path)
    built = api.build(reopened)  # refreshes the selection tags inside the model
    assert built is not None
    assert results_match(reopened, api.results_path(model_path))


def test_results_match_ignores_selection_tags(tmp_path) -> None:
    model_path, _ = write_solved(tmp_path)
    loaded = api.load(model_path)
    loaded.selections["west"].tags = [999999]
    assert results_match(loaded, api.results_path(model_path))


def test_results_match_detects_a_changed_load(tmp_path) -> None:
    model_path, _ = write_solved(tmp_path)
    loaded = api.load(model_path)
    loaded.bcs[0].T = 350.0
    assert not results_match(loaded, api.results_path(model_path))


def test_results_match_false_without_results_file(tmp_path) -> None:
    model_path = tmp_path / "lonely.tfea"
    model = write_plate(model_path)
    assert not results_match(model, api.results_path(model_path))
    assert not results_match(model, tmp_path / "nothing.tfea.h5")


# ---------------------------------------------------------------------------- reattach
def test_matching_results_are_reattached_once_meshed(files, document, tmp_path) -> None:
    model_path, _ = write_solved(tmp_path)
    results = api.results_path(model_path)
    assert files.open(model_path) is True
    assert files.pending_results == results
    assert document.results_path is None
    built = api.build(document.model)
    document.set_built(built)
    document.set_mesh(api.mesh(document.model, built))
    assert document.results_path == results
    assert document.results_stale is False
    assert files.pending_results is None


def test_different_results_are_not_attached(files, document, tmp_path) -> None:
    model_path, _ = write_solved(tmp_path)
    changed = api.load(model_path)
    changed.bcs[0].T = 350.0
    api.save(changed, model_path)  # the results file now belongs to another model
    assert files.open(model_path) is True
    assert files.pending_results is None
    built = api.build(document.model)
    document.set_built(built)
    document.set_mesh(api.mesh(document.model, built))
    assert document.results_path is None


def test_editing_before_meshing_drops_pending_results(files, document, tmp_path) -> None:
    model_path, _ = write_solved(tmp_path)
    files.open(model_path)
    assert files.pending_results is not None
    document.edit("Rename", rename("changed"))
    assert files.pending_results is None


# ---------------------------------------------------------------------------- examples
def test_index_lists_existing_files() -> None:
    entries = example_entries()
    assert entries
    for file_name, title in entries:
        assert (EXAMPLES_DIR / file_name).is_file()
        assert title


def test_every_shipped_example_loads() -> None:
    shipped = sorted(EXAMPLES_DIR.glob("*.tfea"))
    assert len(shipped) == len(example_entries())
    for path in shipped:
        assert isinstance(api.load(path), Model)


def test_examples_menu_has_one_action_per_entry(files, window) -> None:
    entries = example_entries()
    assert len(files.example_actions) == len(entries)
    assert len([a for a in window.menus["examples"].actions() if not a.isSeparator()]) == len(
        entries
    )


def test_example_action_replaces_document(files, document, dialogs) -> None:
    file_name, _title = example_entries()[0]
    files.example_actions[0].trigger()
    assert document.path is None and not document.modified
    assert document.model == api.load(EXAMPLES_DIR / file_name)
    assert dialogs.calls == []


def test_example_action_asks_when_modified(files, document, tmp_path) -> None:
    modify(document)
    answer_with(files, "cancel")
    before = document.model
    files.example_actions[0].trigger()
    assert document.model is before and document.modified
    assert len(files.asked) == 1  # type: ignore[attr-defined]


def test_example_replaces_a_document_with_a_path(files, document, tmp_path) -> None:
    path = tmp_path / "keep.tfea"
    write_plate(path)
    files.open(path)
    files.example_actions[0].trigger()
    assert document.path is None


def test_example_menu_entries_are_titles() -> None:
    titles = [title for _name, title in example_entries()]
    assert all(title and title == title.strip() for title in titles)

