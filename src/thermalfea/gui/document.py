"""The document: model, build products, undo stack and stale flags (Plan M8.2).

Staleness rules
---------------
What an edit (or an undo/redo, in either direction) invalidates is found by comparing the
model JSON (:func:`thermalfea.model.serialize.to_json`) before and after:

* top-level key ``"geometry"`` (the geometry operations) differs -> geometry, mesh and
  results are stale;
* otherwise ``"mesh_settings"`` or ``"analysis"`` differs, or a selection whose name is
  used as a key inside ``mesh_settings`` (curve/point sizes, divisions) was added,
  removed or redefined -> mesh and results are stale;
* otherwise any other difference (materials, regions, loads, streams, settings, other
  selections, ...) -> results are stale.

Selection ``tags`` and the derived selection ``"all"`` are ignored in the comparison:
they are caches that :func:`thermalfea.api.build` refreshes, not user input.

Selections and rebuilds
-----------------------
``api.build`` rewrites ``model.selections`` (tags, and the whole ``"all"`` selection).
That is not an edit: :meth:`Document.set_built` adopts the refreshed selections silently
(no undo command, no ``model_changed``) and remembers the geometry and selections of the
build. When a snapshot is applied by undo/redo and its geometry equals the built
geometry, the resolved tags (and ``"all"``) of the build are copied into it for every
selection whose definition (``dim`` and fingerprints) is unchanged, so selections stay
resolved against the current build. A snapshot with different geometry is stale anyway
and is refreshed by the next build (selections are found again by fingerprint).
"""

from __future__ import annotations

import copy
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoStack

from thermalfea.core.mesh import Mesh
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.gui.commands import ModelEditCommand
from thermalfea.model.model import Model
from thermalfea.model.serialize import from_json, to_json

_log = logging.getLogger(__name__)

ALL_SELECTION = "all"


def _dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True)


def _comparable(data: dict[str, Any]) -> dict[str, Any]:
    """Model JSON without the build-derived selection caches (tags, ``"all"``)."""
    out = dict(data)
    selections = {
        name: {k: v for k, v in sel.items() if k != "tags"}
        for name, sel in data.get("selections", {}).items()
        if name != ALL_SELECTION
    }
    out["selections"] = selections
    return out


def _dict_keys(value: Any) -> set[str]:
    """Every dict key found anywhere in ``value``."""
    keys: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            keys.add(k)
            keys |= _dict_keys(v)
    elif isinstance(value, list):
        for v in value:
            keys |= _dict_keys(v)
    return keys


def classify_change(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Return what a change between two model JSONs invalidates.

    Parameters
    ----------
    before, after : dict
        Model JSON data.

    Returns
    -------
    {"none", "results", "mesh", "geometry"}
        ``"geometry"`` invalidates geometry, mesh and results; ``"mesh"`` mesh and
        results; ``"results"`` only results; ``"none"`` nothing.
    """
    a, b = _comparable(before), _comparable(after)
    if a == b:
        return "none"
    if a.get("geometry") != b.get("geometry"):
        return "geometry"
    if a.get("mesh_settings") != b.get("mesh_settings") or a.get("analysis") != b.get(
        "analysis"
    ):
        return "mesh"
    used = _dict_keys(a.get("mesh_settings")) | _dict_keys(b.get("mesh_settings"))
    sa, sb = a["selections"], b["selections"]
    if any(sa.get(n) != sb.get(n) for n in used & (set(sa) | set(sb))):
        return "mesh"
    return "results"


class Document(QObject):
    """Owns the model and the products built from it; the one place the GUI edits.

    Signals (all without arguments; read the state from the document):

    ``model_changed``
        ``document.model`` was replaced (edit, undo, redo, :meth:`set_model`).
    ``geometry_built``
        :meth:`set_built` stored a new :class:`BuiltGeometry`.
    ``mesh_changed``
        :meth:`set_mesh` stored a new mesh, or :meth:`set_model` / :meth:`set_built`
        discarded the old one.
    ``results_changed``
        :meth:`set_results` stored a results path, or :meth:`set_model` cleared it.
    ``stale_changed``
        Any of the three stale flags changed value.

    Attributes
    ----------
    model : Model
        The current model. It is *replaced* (not mutated) by every edit/undo/redo, so
        keep a reference to the document, not to the model.
    built : BuiltGeometry or None
    mesh : Mesh or None
    results_path : Path or None
    path : Path or None
        The model file, if any (file handling is later work).
    undo_stack : QUndoStack
    geometry_stale, mesh_stale, results_stale : bool
        The corresponding product is missing or no longer matches the model.
    """

    model_changed = Signal()
    geometry_built = Signal()
    mesh_changed = Signal()
    results_changed = Signal()
    stale_changed = Signal()

    def __init__(self, model: Model | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.undo_stack = QUndoStack(self)
        self.model: Model = model if model is not None else Model()
        self.path: Path | None = None
        self.built: BuiltGeometry | None = None
        self.mesh: Mesh | None = None
        self.results_path: Path | None = None
        self.geometry_stale = True
        self.mesh_stale = True
        self.results_stale = True
        self._built_geometry: Any = None
        self._built_selections: dict[str, Any] = {}

    # ------------------------------------------------------------------ queries
    @property
    def modified(self) -> bool:
        """``True`` when the model differs from the last clean (saved) state."""
        return not self.undo_stack.isClean()

    def mark_saved(self) -> None:
        """Declare the current undo state as saved (clears :attr:`modified`)."""
        self.undo_stack.setClean()

    # ------------------------------------------------------------------ editing
    def edit(self, text: str, mutate: Callable[[Model], None]) -> bool:
        """Change the model through ``mutate`` as one undoable step.

        ``mutate`` receives a working copy; if it raises, the exception propagates and
        the document and undo stack are untouched.

        Parameters
        ----------
        text : str
            Name of the command ("Undo <text>").
        mutate : callable
            ``mutate(model)`` edits the given model in place.

        Returns
        -------
        bool
            ``True`` if the model changed and a command was pushed.
        """
        before = _dumps(to_json(self.model))
        working = from_json(json.loads(before))
        mutate(working)
        after = _dumps(to_json(working))
        if after == before:
            return False
        self.undo_stack.push(ModelEditCommand(self, text, before, after))
        return True

    def apply_snapshot(self, snapshot: str, previous: str) -> None:
        """Make ``snapshot`` the model; called by :class:`ModelEditCommand`.

        Parameters
        ----------
        snapshot : str
            Model JSON text to apply.
        previous : str
            Model JSON text it replaces (used to decide what becomes stale).
        """
        data = json.loads(snapshot)
        change = classify_change(json.loads(previous), data)
        self._carry_build_selections(data)
        self.model = from_json(data)
        self._invalidate(change)
        self.model_changed.emit()

    def _carry_build_selections(self, data: dict[str, Any]) -> None:
        """Copy the resolved tags of the current build into a snapshot (see module doc)."""
        if self.built is None or data.get("geometry") != self._built_geometry:
            return
        selections = data.setdefault("selections", {})
        built_all = self._built_selections.get(ALL_SELECTION)
        if built_all is None:
            selections.pop(ALL_SELECTION, None)
        else:
            selections[ALL_SELECTION] = copy.deepcopy(built_all)
        for name, sel in selections.items():
            ref = self._built_selections.get(name)
            if (
                name != ALL_SELECTION
                and ref is not None
                and ref["dim"] == sel["dim"]
                and ref["fingerprints"] == sel["fingerprints"]
            ):
                sel["tags"] = list(ref["tags"])

    # -------------------------------------------------------------------- stale
    def _set_stale(self, geometry: bool, mesh: bool, results: bool) -> None:
        """Raise flags (never clears); emit ``stale_changed`` on a change."""
        new = (
            self.geometry_stale or geometry,
            self.mesh_stale or mesh,
            self.results_stale or results,
        )
        old = (self.geometry_stale, self.mesh_stale, self.results_stale)
        self.geometry_stale, self.mesh_stale, self.results_stale = new
        if new != old:
            self.stale_changed.emit()

    def _invalidate(self, change: str) -> None:
        if change == "geometry":
            self._set_stale(True, True, True)
        elif change == "mesh":
            self._set_stale(False, True, True)
        elif change == "results":
            self._set_stale(False, False, True)

    def _clear_stale(self, geometry: bool | None, mesh: bool | None, results: bool | None) -> None:
        old = (self.geometry_stale, self.mesh_stale, self.results_stale)
        if geometry is not None:
            self.geometry_stale = geometry
        if mesh is not None:
            self.mesh_stale = mesh
        if results is not None:
            self.results_stale = results
        if (self.geometry_stale, self.mesh_stale, self.results_stale) != old:
            self.stale_changed.emit()

    # ----------------------------------------------------------- build products
    def set_built(self, built: BuiltGeometry, model: Model | None = None) -> None:
        """Store a finished build.

        The geometry is stale only if the document's geometry operations changed since
        the build started (``model`` is the model the build ran on; default: the current
        one). A new build invalidates the old mesh and results: the mesh is dropped and
        mesh and results are marked stale. If ``model`` is a different object (a worker's
        copy), its refreshed selections replace the document's (no undo step).

        Parameters
        ----------
        built : BuiltGeometry
        model : Model, optional
            The model ``api.build`` ran on.
        """
        source = model if model is not None else self.model
        source_json = to_json(source)
        current = to_json(self.model)
        geometry_stale = source_json["geometry"] != current["geometry"]
        self.built = built
        self.mesh = None
        if not geometry_stale:
            if source is not self.model:
                self.model.selections = copy.deepcopy(source.selections)
                current = to_json(self.model)
            self._built_geometry = current["geometry"]
            self._built_selections = copy.deepcopy(current["selections"])
        else:
            self._built_geometry = source_json["geometry"]
            self._built_selections = copy.deepcopy(source_json["selections"])
        self._clear_stale(geometry_stale, True, True)
        self.geometry_built.emit()
        self.mesh_changed.emit()

    def set_mesh(self, mesh: Mesh) -> None:
        """Store a finished mesh: the mesh becomes current, the results stale."""
        self.mesh = mesh
        self._clear_stale(None, False, True)
        self.mesh_changed.emit()

    def set_results(self, path: Path | str) -> None:
        """Store the path of finished results and mark them current."""
        self.results_path = Path(path)
        self._clear_stale(None, None, False)
        self.results_changed.emit()

    # ------------------------------------------------------------ whole document
    def set_model(self, model: Model, path: Path | str | None = None) -> None:
        """Replace the whole model; clears undo history, build, mesh and results.

        Parameters
        ----------
        model : Model
        path : Path or str, optional
            The file the model came from.
        """
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self.model = model
        self.path = Path(path) if path is not None else None
        self.built = None
        self.mesh = None
        self.results_path = None
        self._built_geometry = None
        self._built_selections = {}
        self._clear_stale(True, True, True)
        self.model_changed.emit()
        self.geometry_built.emit()
        self.mesh_changed.emit()
        self.results_changed.emit()

    def new(self, model: Model | None = None) -> None:
        """Start an empty document (or one for ``model``)."""
        self.set_model(model if model is not None else Model())
