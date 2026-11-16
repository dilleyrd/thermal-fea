"""File handling in the GUI (Plan M8.13): New, Open, Save, Save As, recent files, the
unsaved-changes prompt, results reattached on open, and the Examples menu.

:class:`FileController` is installed by :func:`attach_files`. It

* enables and connects the File actions ``file.new``, ``file.open``, ``file.save`` and
  ``file.save_as`` (created disabled by :class:`~thermalfea.gui.main_window.MainWindow`);
* adds a "Recent files" submenu (up to :data:`RECENT_LIMIT` files, kept in the window's
  ``QSettings`` under :data:`RECENT_KEY`) and an "Examples" submenu (the verification models
  shipped in ``thermalfea/gui/examples``, listed by ``index.json``);
* asks about unsaved changes before New, Open, an example and window close (an event filter
  on the window refuses the close when the user answers "cancel" or a save fails).

Choosers and the unsaved-changes question are injectable attributes (``choose_open``,
``choose_save``, ``ask_unsaved``); tests replace them, so no modal dialog is shown there.

Results on open
---------------
After a model is opened from a file, the results file beside it
(:func:`thermalfea.api.results_path`) is attached when it belongs to that model
(:func:`results_match`). The results are attached to the document as soon as the document
has a current mesh (see :meth:`FileController.pending_results`).

Comparing models for results
----------------------------
The hash stored in a results file (``meta.model_hash``) is the SHA-256 of the JSON of the model
that was *solved*. :func:`thermalfea.api.build` rewrites selection tags (and the derived
selection ``"all"``) inside the model, so a model saved before a build and the same model
after it hash differently although they are the same model. :func:`results_match` therefore
does not compare hashes: it compares the model JSON without those caches
(:func:`thermalfea.gui.document._comparable`) of the opened model with the model JSON embedded
in the results file (:attr:`thermalfea.post.results.Results.model`). Any change of the model
that matters to the solution (geometry, materials, loads, settings, mesh settings, selection
definitions) makes them differ.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox, QWidget

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.gui.document import Document, _comparable
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.solve_tools import can_solve
from thermalfea.model.model import Model
from thermalfea.model.serialize import to_json
from thermalfea.post.results import Results

_log = logging.getLogger(__name__)

RECENT_KEY = "recentFiles"
RECENT_LIMIT = 10
MODEL_SUFFIX = ".tfea"
MODEL_FILTER = "ThermalFEA models (*.tfea);;All files (*)"
EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"
EXAMPLES_INDEX = "index.json"
#: Answers of :attr:`FileController.ask_unsaved`.
SAVE, DISCARD, CANCEL = "save", "discard", "cancel"


def results_match(model: Model, results_path: str | Path) -> bool:
    """True when a results file was computed from ``model``.

    See the module documentation for why the comparison is on the model JSON without the
    selection caches rather than on the stored hash.

    Parameters
    ----------
    model : Model
        The model to check (typically the one just opened).
    results_path : str or Path
        A results file (``<model>.tfea.h5``).

    Returns
    -------
    bool
        ``False`` if the file does not exist, cannot be read as results, or embeds no model
        (it was solved without one), or if the models differ.
    """
    path = Path(results_path)
    if not path.is_file():
        return False
    try:
        stored = Results(path).model
    except (ModelError, OSError, ValueError):
        return False
    if stored is None:
        return False
    return _comparable(to_json(model)) == _comparable(to_json(stored))


def example_entries(folder: Path = EXAMPLES_DIR) -> list[tuple[str, str]]:
    """The shipped example models as ``(file name, title)`` pairs, from ``index.json``.

    Parameters
    ----------
    folder : Path
        Folder holding the example files and ``index.json``.

    Returns
    -------
    list of (str, str)
        Empty if there is no index.
    """
    index = folder / EXAMPLES_INDEX
    if not index.is_file():
        return []
    data = json.loads(index.read_text(encoding="utf-8"))
    return [(str(entry["file"]), str(entry["title"])) for entry in data]


def _default_choose_open(parent: QWidget | None) -> str | None:
    path, _ = QFileDialog.getOpenFileName(parent, "Open model", "", MODEL_FILTER)
    return path or None


def _default_choose_save(parent: QWidget | None, suggested: str) -> str | None:
    path, _ = QFileDialog.getSaveFileName(parent, "Save model as", suggested, MODEL_FILTER)
    return path or None


def _default_ask_unsaved(parent: QWidget | None, name: str) -> str:
    choice = QMessageBox.question(
        parent,
        "Unsaved changes",
        f"Save the changes to {name} first?",
        QMessageBox.StandardButton.Save
        | QMessageBox.StandardButton.Discard
        | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Save,
    )
    if choice == QMessageBox.StandardButton.Save:
        return SAVE
    if choice == QMessageBox.StandardButton.Discard:
        return DISCARD
    return CANCEL


def _file_key(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class FileController(QObject):
    """New, Open, Save, Save As, recent files and examples for one window and document.

    Parameters
    ----------
    window : MainWindow
        Its File menu receives the submenus; errors go through ``window.show_error``.
    document : Document
    examples_dir : Path, optional
        Folder with the example models and ``index.json``.

    Attributes
    ----------
    choose_open : callable
        ``choose_open(parent) -> str or None``; the file to open (``None``: cancelled).
    choose_save : callable
        ``choose_save(parent, suggested) -> str or None``; the file to save to.
    ask_unsaved : callable
        ``ask_unsaved(parent, name) -> "save" | "discard" | "cancel"``.
    pending_results : Path or None
        A results file that belongs to the current model and waits for a current mesh before
        it is attached to the document.
    recent_actions : list of QAction
        The entries of the "Recent files" submenu, most recent first (not the Clear action).
    clear_action : QAction
        "Clear" in the "Recent files" submenu.
    example_actions : list of QAction
        One action per example model.
    recent_menu, examples_menu : QMenu
    """

    def __init__(
        self, window: MainWindow, document: Document, examples_dir: Path = EXAMPLES_DIR
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.examples_dir = examples_dir
        self.choose_open: Callable[[QWidget | None], str | None] = _default_choose_open
        self.choose_save: Callable[[QWidget | None, str], str | None] = _default_choose_save
        self.ask_unsaved: Callable[[QWidget | None, str], str] = _default_ask_unsaved
        self.pending_results: Path | None = None
        self.recent_actions: list[QAction] = []
        self.example_actions: list[QAction] = []
        self.actions: dict[str, QAction] = {}

        self._build_actions()
        self._build_menus()
        document.model_changed.connect(self._on_model_changed)
        document.mesh_changed.connect(self._on_mesh_changed)
        window.installEventFilter(self)

    # ----------------------------------------------------------------- actions
    def _build_actions(self) -> None:
        window = self.window
        slots: tuple[tuple[str, Callable[[], object]], ...] = (
            ("file.new", self.new),
            ("file.open", self.open),
            ("file.save", self.save),
            ("file.save_as", self.save_as),
        )
        for key, slot in slots:
            action = window.actions[key]
            action.setEnabled(True)
            action.triggered.connect(lambda _checked=False, s=slot: s())
            self.actions[key] = action

    def _build_menus(self) -> None:
        window = self.window
        file_menu = window.menus["file"]
        exit_action = window.actions["file.exit"]
        self.recent_menu = QMenu("Recent &files", window)
        self.recent_menu.aboutToShow.connect(self.refresh_recent_menu)
        self.examples_menu = QMenu("&Examples", window)
        for file_name, title in example_entries(self.examples_dir):
            action = QAction(title, self.examples_menu)
            action.triggered.connect(
                lambda _checked=False, f=file_name: self.open_example(f)
            )
            self.examples_menu.addAction(action)
            self.example_actions.append(action)
        if not self.example_actions:
            self.examples_menu.addAction("(no examples)").setEnabled(False)
        file_menu.insertMenu(exit_action, self.recent_menu)
        file_menu.insertMenu(exit_action, self.examples_menu)
        file_menu.insertSeparator(exit_action)
        window.menus["recent"] = self.recent_menu
        window.menus["examples"] = self.examples_menu
        self.clear_action = QAction("Clear", window)
        self.clear_action.triggered.connect(lambda _checked=False: self.clear_recent())
        self.refresh_recent_menu()

    def refresh_recent_menu(self) -> None:
        """Rebuild the "Recent files" submenu from the stored list (missing files dropped).

        Runs whenever the submenu is about to be shown; tests may call it directly.
        """
        menu = self.recent_menu
        if menu is None:
            return
        menu.clear()  # deletes the entries (owned by the menu); the Clear action survives
        self.recent_actions = []
        files = self.recent_files()
        for path in files:
            action = QAction(path, menu)
            action.triggered.connect(lambda _checked=False, p=path: self.open(p))
            menu.addAction(action)
            self.recent_actions.append(action)
        if not files:
            placeholder = menu.addAction("(none)")
            placeholder.setEnabled(False)
        menu.addSeparator()
        menu.addAction(self.clear_action)

    # ------------------------------------------------------------------ recent
    def recent_files(self) -> list[str]:
        """Stored recent files, most recent first; files that no longer exist are dropped.

        The stored list is rewritten when entries were dropped.
        """
        settings = self.window.settings
        raw: Any = settings.value(RECENT_KEY, [])
        if isinstance(raw, str):
            raw = [raw] if raw else []
        files = [str(p) for p in raw or []]
        kept = [p for p in files if Path(p).is_file()][:RECENT_LIMIT]
        if kept != files:
            self._store_recent(kept)
        return kept

    def add_recent(self, path: str | Path) -> None:
        """Put ``path`` at the top of the recent files (no duplicates, at most ten)."""
        absolute = os.path.abspath(path)
        key = _file_key(absolute)
        others = [p for p in self.recent_files() if _file_key(p) != key]
        self._store_recent([absolute, *others][:RECENT_LIMIT])

    def clear_recent(self) -> None:
        """Forget all recent files."""
        self._store_recent([])

    def _store_recent(self, files: list[str]) -> None:
        self.window.settings.setValue(RECENT_KEY, files)
        self.window.settings.sync()

    # --------------------------------------------------------------- queries
    def _document_name(self) -> str:
        path = self.document.path
        return path.name if path is not None else self.document.model.name

    def _status(self, text: str) -> None:
        self.window.statusBar().showMessage(text, 5000)

    def _confirm_discard(self) -> bool:
        """Ask about unsaved changes; ``True`` when the caller may replace the model."""
        if not self.document.modified:
            return True
        answer = self.ask_unsaved(self.window, self._document_name())
        if answer == SAVE:
            return self.save()
        return answer == DISCARD

    # ------------------------------------------------------------------ actions
    def new(self) -> bool:
        """Start an empty model (after the unsaved-changes question).

        Returns
        -------
        bool
            ``True`` if the document was replaced.
        """
        if not self._confirm_discard():
            return False
        self.pending_results = None
        self.document.new()
        self.window.update_title()
        return True

    def open(self, path: str | Path | None = None) -> bool:
        """Open a model file (after the unsaved-changes question).

        Without ``path`` the chooser asks for one. A file that cannot be read or understood is
        reported through ``window.show_error`` and the current document is kept. A results
        file beside the model that belongs to it is attached once the model has a mesh.

        Parameters
        ----------
        path : str or Path, optional

        Returns
        -------
        bool
            ``True`` if the model was opened.
        """
        if not self._confirm_discard():
            return False
        if path is None:
            chosen = self.choose_open(self.window)
            if not chosen:
                return False
            path = chosen
        target = Path(path)
        try:
            model = api.load(target)
        except ModelError as exc:
            self.window.show_error("Open model", str(exc))
            return False
        self.pending_results = None
        self.document.set_model(model, target)
        self.add_recent(target)
        self.window.update_title()
        self._reattach(model, api.results_path(target))
        self._status(f"Opened {target}")
        return True

    def save(self) -> bool:
        """Save to the document's file, or ask for one (see :meth:`save_as`).

        Returns
        -------
        bool
            ``True`` if the file was written.
        """
        if self.document.path is None:
            return self.save_as()
        return self._write(self.document.path)

    def save_as(self) -> bool:
        """Save to a file chosen by the user; ``.tfea`` is appended when there is no suffix.

        Returns
        -------
        bool
            ``True`` if the file was written; the document then refers to it.
        """
        current = self.document.path
        if current is not None:
            suggested = str(current)
        else:
            suggested = f"{self.document.model.name}{MODEL_SUFFIX}"
        chosen = self.choose_save(self.window, suggested)
        if not chosen:
            return False
        path = Path(chosen)
        if not path.suffix:
            path = path.with_name(path.name + MODEL_SUFFIX)
        return self._write(path)

    def open_example(self, file_name: str) -> bool:
        """Load one of the shipped example models as an untitled document.

        The document has no path, so Save asks for a location and the shipped file is never
        overwritten.

        Returns
        -------
        bool
            ``True`` if the example was loaded.
        """
        if not self._confirm_discard():
            return False
        try:
            model = api.load(self.examples_dir / file_name)
        except ModelError as exc:
            self.window.show_error("Open example", str(exc))
            return False
        self.pending_results = None
        self.document.set_model(model, None)
        self.window.update_title()
        self._status(f"Loaded example {file_name}")
        return True

    def _write(self, path: Path) -> bool:
        try:
            api.save(self.document.model, path)
        except (OSError, ValueError) as exc:
            _log.error("Saving %s failed: %s", path, exc)
            self.window.show_error("Save model", f"cannot write {path}: {exc}")
            return False
        self.document.path = path
        self.document.mark_saved()
        self.add_recent(path)
        self.window.update_title()
        self._status(f"Saved {path}")
        return True

    # ------------------------------------------------------------ results
    def _reattach(self, model: Model, results: Path) -> None:
        if not results.is_file():
            return
        if not results_match(model, results):
            _log.info("results file is from a different model: %s", results)
            self._status(f"results file {results.name} is from a different model; not attached")
            return
        self.pending_results = results
        self._attach_pending()

    def _attach_pending(self) -> None:
        results = self.pending_results
        if results is None or not can_solve(self.document):
            return
        if not results_match(self.document.model, results):
            self.pending_results = None
            return
        self.pending_results = None
        self.document.set_results(results)
        self._status(f"Results attached from {results.name}")

    def _on_mesh_changed(self) -> None:
        self._attach_pending()

    def _on_model_changed(self) -> None:
        if self.pending_results is not None and not results_match(
            self.document.model, self.pending_results
        ):
            self.pending_results = None

    # ------------------------------------------------------------------ close
    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt override)
        """Refuse closing the window while the unsaved-changes question is cancelled.

        Installed last, so it runs before the solve controller's filter: a refused close
        does not cancel a running solve.
        """
        if obj is self.window and event.type() == QEvent.Type.Close:
            if not self._confirm_discard():
                event.ignore()
                return True
        return False


def attach_files(
    window: MainWindow, document: Document, examples_dir: Path = EXAMPLES_DIR
) -> FileController:
    """Install file handling in a main window.

    Call it after the other ``attach_*`` functions of :func:`thermalfea.gui.app.main`.

    Parameters
    ----------
    window : MainWindow
    document : Document
    examples_dir : Path, optional

    Returns
    -------
    FileController
    """
    return FileController(window, document, examples_dir)
