"""Result displays: contour and vector objects, probe and animation (Plan M8.10).

Result objects are *view state*, not model data
-----------------------------------------------
A :class:`ContourObject` or :class:`VectorObject` says how some results are shown (which
field, which step, the color range, ...). The model file format has no place for them and
they describe a view of a solve, not the model, so they live only here, in the
:class:`ResultController` that the application owns:

* they are **not** in ``to_json(document.model)``, creating or editing one never marks the
  document modified and never makes the results stale;
* edits are **not** undoable (they are not on ``document.undo_stack``): a slider that is
  dragged or an animation that plays must not fill the undo history. Delete and re-add is
  the way back;
* they are not saved with the model; a new model starts without them.

The tree shows them under the Solution node (the controller is the tree's *provider*, see
:meth:`~thermalfea.gui.tree.ModelTree.add_provider`) with addresses ``("result", name)``;
selecting one shows its :class:`~thermalfea.gui.property_panels.results.ResultPanel` and
makes it the displayed object. One object is displayed at a time (the viewport has one
field layer). All numbers come from :mod:`thermalfea.post`; this module only chooses
what to ask for and hands the arrays to the viewport through ``SceneView.set_field``.

Range modes of a contour
------------------------
``"auto_step"``
    the extrema of the displayed step (the default);
``"auto_all"``
    the extrema over every stored step (``post.plots.field_range``; computed once per
    field and results file, so an animation keeps one color scale);
``"manual"``
    ``vmin`` / ``vmax`` in display units; the minimum must be below the maximum.

Changing the field of an object in manual mode returns it to ``"auto_step"`` (the old
numbers belong to another quantity).

Animation
---------
:meth:`ResultController.play` advances the displayed object one stored step per timer tick
(``interval_ms``, default 200 ms). With ``loop`` off (the default) it stops by itself on the
last step; starting it while on the last step restarts from step 0. With ``loop`` on it
wraps around until paused. It also stops when the results change, when the displayed object
changes or is deleted, and when the controller is destroyed (the timer is its child).

Probe
-----
While the probe is on, a viewport click evaluates the displayed field at that point of the
displayed step with :func:`thermalfea.post.path.value_at` and reports x, y and the value in
display units (status bar, :attr:`ResultController.probes`, :attr:`probe_changed`). A click
outside the mesh reports "outside the model". Each click inside the mesh also leaves a
marker with its value on the viewport overlay layer ``"probe"``; the markers are evaluated
again when the step, the field or the display units change, and cleared when the probe is
turned off or the results are replaced. A vector object is probed for the heat-flux
magnitude.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from datetime import UTC, datetime
from typing import Any, ClassVar

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction

from thermalfea.core.errors import ModelError, ThermalFEAError
from thermalfea.core.forms import copy_name, unique_name, unit_label
from thermalfea.core.units import from_si
from thermalfea.gui.document import Document
from thermalfea.gui.field_display import field_display_from_contour, field_display_from_vectors
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.property_panels.results import RESULT_ADDRESS
from thermalfea.gui.scene import FieldDisplay, OverlayMarker, SceneView
from thermalfea.gui.tree_summary import analysis_summary
from thermalfea.model.compare import model_changes
from thermalfea.post.path import value_at
from thermalfea.post.plots import (
    FIELDS,
    contour_data,
    contour_fields,
    display_value,
    field_display_values,
    field_range,
    field_si_values,
    vector_data,
)
from thermalfea.post.results import Results

_log = logging.getLogger(__name__)

#: Range modes of a contour object.
RANGE_MODES: tuple[str, ...] = ("auto_step", "auto_all", "manual")
#: Field a vector object is probed for.
VECTOR_PROBE_FIELD = "qmag"
#: Largest number of color bands.
MAX_LEVELS = 256
#: Longest list of probe readings kept.
MAX_PROBES = 50
#: Limits of the animation frame interval [ms].
MIN_INTERVAL_MS = 10
MAX_INTERVAL_MS = 10000

ADD_CONTOUR_ID = "results.add_contour"
ADD_VECTORS_ID = "results.add_vectors"
PROBE_ID = "results.probe"
PLAY_ID = "results.play"

OUT_OF_DATE_SUFFIX = " · out of date"


@dataclass(frozen=True)
class ResultStatus:
    """What the results file says about itself and whether the model still matches it.

    Attributes
    ----------
    available : bool
        There is a readable results file.
    current : bool or None
        ``True`` when the model equals the one solved, ``False`` when it differs, ``None``
        when the comparison is impossible (no model stored in the file).
    changes : list of str
        Readable differences (``model.compare.model_changes``); empty unless out of date.
    lines : list of str
        Header lines: analysis, mesh, "results written ...", and the state.
    """

    available: bool
    current: bool | None
    changes: list[str]
    lines: list[str]

    @property
    def state(self) -> str:
        """``current``, ``out of date (N changes)``, ``comparison unavailable`` or ``""``."""
        if not self.available:
            return ""
        if self.current is None:
            return "comparison unavailable"
        if self.current:
            return "current"
        n = len(self.changes)
        return f"out of date ({n} change{'' if n == 1 else 's'})"

    @property
    def short(self) -> str:
        """The state without the count: ``current``, ``out of date``, ..."""
        return self.state.split(" (")[0]

    @property
    def out_of_date(self) -> bool:
        return self.available and self.current is False


@dataclass(frozen=True)
class _Stored:
    model: Any
    analysis: str
    mesh: str
    created: str


_STORED_CACHE: dict[tuple, _Stored | None] = {}


def _file_key(path: Any) -> tuple | None:
    try:
        return (str(path), os.stat(path).st_mtime_ns)
    except OSError:
        return None


def _written(created: str) -> str:
    try:
        stamp = datetime.fromisoformat(created)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=UTC)
        return stamp.astimezone().strftime("%d %b %Y %H:%M")
    except ValueError:
        return created


def _stored(path: Any) -> _Stored | None:
    """The header facts of a results file, read once per (path, modification time)."""
    key = _file_key(path)
    if key is None:
        return None
    if key in _STORED_CACHE:
        return _STORED_CACHE[key]
    try:
        results = Results(path)
        model = results.model
        mesh = results.mesh
        meta = results.meta
        etypes = "/".join(dict.fromkeys(b.etype for b in mesh.blocks))
        mesh_text = f"{etypes} · {mesh.n_nodes:,} nodes · {mesh.n_elements:,} elements"
        stored: _Stored | None = _Stored(
            model,
            str(meta.get("analysis", "")),
            mesh_text.replace(",", " "),
            _written(str(meta.get("created", ""))),
        )
    except (ThermalFEAError, OSError, KeyError, ValueError, TypeError) as exc:
        _log.warning("results %s cannot be read: %s", path, exc)
        stored = None
    if len(_STORED_CACHE) > 8:
        _STORED_CACHE.clear()
    _STORED_CACHE[key] = stored
    return stored


def result_status(document: Document) -> ResultStatus:
    """Compare the document's model with the model stored in its results (Plan §6).

    The one definition of "current": ``model_changes(stored, document.model)`` is empty.
    A results file without a stored model gives ``current=None``.
    """
    path = document.results_path
    stored = _stored(path) if path is not None else None
    if stored is None:
        return ResultStatus(False, None, [], [])
    model = document.model
    changes: list[str] = []
    current: bool | None = None
    if stored.model is not None:
        try:
            changes = model_changes(stored.model, model, model.display_units)
            current = not changes
        except (ThermalFEAError, KeyError, ValueError, TypeError) as exc:
            _log.warning("cannot compare the model with its results: %s", exc)
            changes, current = [], None
    analysis = stored.analysis
    if stored.model is not None:
        analysis = analysis_summary(stored.model)
    status = ResultStatus(True, current, changes, [])
    lines = [
        f"Analysis: {analysis}",
        f"Mesh: {stored.mesh}",
        f"Results written {stored.created}",
        f"Status: {status.state}",
    ]
    return ResultStatus(True, current, changes, lines)


@dataclass
class ContourObject:
    """A filled contour of a scalar field.

    Attributes
    ----------
    name : str
        Unique among the result objects.
    field : str
        A key of :data:`thermalfea.post.plots.FIELDS` (``T``, ``qx``, ``qmag``, ...).
    step : int
        Stored step shown (0-based).
    range_mode : {"auto_step", "auto_all", "manual"}
    vmin, vmax : float or None
        Manual color range in display units (used when ``range_mode == "manual"``).
    banded : bool
        Color bands (``True``) or smooth shading.
    levels : int
        Number of bands when ``banded``.
    show_mesh : bool
        Element edges over the field.
    markers : bool
        Mark and annotate the minimum and the maximum.
    """

    kind: ClassVar[str] = "contour"
    name: str
    field: str = "T"
    step: int = 0
    range_mode: str = "auto_step"
    vmin: float | None = None
    vmax: float | None = None
    banded: bool = True
    levels: int = 12
    show_mesh: bool = False
    markers: bool = True


@dataclass
class VectorObject:
    """Heat-flux arrows.

    Attributes
    ----------
    name : str
    step : int
        Stored step shown (0-based).
    density : int
        About this many arrows across the larger model dimension.
    show_mesh : bool
        Element edges under the arrows.
    """

    kind: ClassVar[str] = "vector"
    name: str
    step: int = 0
    density: int = 30
    show_mesh: bool = False


ResultObject = ContourObject | VectorObject


@dataclass(frozen=True)
class ProbeReading:
    """One probe evaluation.

    Attributes
    ----------
    x, y : float
        Clicked position [m].
    value : float
        Field value in display units; NaN outside the model.
    unit, label : str
        Display unit and field name.
    inside : bool
        Whether the point lies in the mesh.
    step : int
        Step evaluated.
    text : str
        The readout shown to the user.
    """

    x: float
    y: float
    value: float
    unit: str
    label: str
    inside: bool
    step: int
    text: str


class ResultController(QObject):
    """Owns the result objects and drives the viewport's field display.

    Parameters
    ----------
    window : MainWindow
        Its Results menu receives the actions ``results.add_contour``,
        ``results.add_vectors``, ``results.probe`` and ``results.play``.
    document : Document
        ``results_path`` / ``results_changed`` say which results exist.
    view : SceneView
        Receives ``set_field`` and sends ``point_picked``.

    Signals
    -------
    objects_changed
        Objects were added, removed or renamed.
    display_changed
        The displayed object, its settings or its arrays changed (or the results did).
    probe_changed(str)
        A probe reading was taken (its text).
    playing_changed(bool)
        The animation started or stopped.

    Attributes
    ----------
    objects : list of ContourObject or VectorObject
    shown : str or None
        Name of the displayed object.
    display : FieldDisplay or None
        What was last handed to ``view.set_field``.
    probes : list of ProbeReading
        The last readings (newest last).
    interval_ms : int
        Animation frame interval.
    loop : bool
        Wrap around at the last step instead of stopping.
    tree : QWidget or None
        The model tree, if installed (selects new objects, starts inline rename).
    """

    objects_changed = Signal()
    display_changed = Signal()
    probe_changed = Signal(str)
    playing_changed = Signal(bool)
    status_changed = Signal()

    def __init__(self, window: MainWindow, document: Document, view: SceneView) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.view = view
        self.tree: Any = None
        self.objects: list[ResultObject] = []
        self.shown: str | None = None
        self.display: FieldDisplay | None = None
        self.probes: list[ProbeReading] = []
        self._markers: list[tuple[float, float]] = []
        self._items: list[OverlayMarker] = []
        self.loop = False
        self._interval_ms = 200
        self._results: Results | None = None
        self._times: np.ndarray = np.zeros(0)
        self._ranges: dict[str, tuple[float, float]] = {}
        self._units = document.model.display_units
        self._generation = document.generation
        self._status_cache: tuple[Any, tuple, ResultStatus] | None = None
        self._suffixed = False
        #: Results show the units of the model stored in their file until the user
        #: changes the units of the document; from then on they follow the document.
        self._follow_document_units = False
        self.timer = QTimer(self)
        self.timer.setInterval(self._interval_ms)
        self.timer.timeout.connect(self.tick)
        self._build_actions()
        document.results_changed.connect(self._on_results_changed)
        document.model_changed.connect(self._on_model_changed)
        view.point_picked.connect(self._on_point_picked)
        self._on_results_changed()

    # ---------------------------------------------------------------- actions
    def _build_actions(self) -> None:
        window = self.window
        specs: tuple[tuple[str, str, bool, Callable[..., object]], ...] = (
            (ADD_CONTOUR_ID, "Add &contour", False, lambda _c=False: self.add_contour()),
            (ADD_VECTORS_ID, "Add &vector plot", False, lambda _c=False: self.add_vectors()),
            (PROBE_ID, "&Probe", True, lambda checked: self.set_probe(bool(checked))),
            (PLAY_ID, "P&lay animation", True, lambda checked: self._play_toggled(bool(checked))),
        )
        for key, text, checkable, slot in specs:
            action = QAction(text, window)
            action.setCheckable(checkable)
            action.setEnabled(False)
            if checkable:
                action.toggled.connect(slot)
            else:
                action.triggered.connect(slot)
            window.actions[key] = action
            window.menus["results"].addAction(action)
        window.actions[PROBE_ID].setToolTip("Click the viewport to read the displayed field")
        window.actions[PLAY_ID].setToolTip("Step through the stored steps")

    def _update_actions(self) -> None:
        has = self._results is not None
        actions = self.window.actions
        actions[ADD_CONTOUR_ID].setEnabled(has)
        actions[ADD_VECTORS_ID].setEnabled(has)
        actions[PROBE_ID].setEnabled(has)
        actions[PLAY_ID].setEnabled(self.can_play)
        playing = actions[PLAY_ID]
        if playing.isChecked() != self.playing:
            playing.blockSignals(True)
            playing.setChecked(self.playing)
            playing.blockSignals(False)

    # ------------------------------------------------------------ the results
    @property
    def results(self) -> Results | None:
        """The results of the document (one object per results file), or ``None``."""
        return self._results

    @property
    def n_steps(self) -> int:
        """Number of stored steps (0 without results)."""
        return int(self._times.size)

    @property
    def times(self) -> np.ndarray:
        """Time of every stored step [s]."""
        return self._times

    def time_of(self, step: int) -> float:
        """Time [s] of a stored step (clamped to the stored range)."""
        if not self._times.size:
            return 0.0
        return float(self._times[min(max(int(step), 0), self._times.size - 1)])

    def step_for_time(self, time: float) -> int:
        """The stored step whose time is nearest ``time`` [s] (the earlier one on a tie)."""
        if not self._times.size:
            return 0
        return int(np.argmin(np.abs(self._times - float(time))))

    def fields(self) -> list[str]:
        """The contour fields the results can show (``post.plots.contour_fields``)."""
        return contour_fields(self._results) if self._results is not None else []

    def _forget_previous_model(self) -> None:
        """The document was replaced (New, Open, Example): drop the old model's results state."""
        self.objects = []
        self.shown = None
        self.display = None
        self.probes = []
        self._clear_markers()  # before set_probe(False), which only clears kept markers
        self._follow_document_units = False
        self._units = self.document.model.display_units
        self.set_probe(False)

    def _on_results_changed(self) -> None:
        self.pause()
        if self.document.generation != self._generation:
            self._generation = self.document.generation
            self._forget_previous_model()
        self._ranges.clear()
        self._results = None
        self._times = np.zeros(0)
        self._clear_markers()
        path = self.document.results_path
        if path is not None:
            try:
                results = Results(path)
                if self._follow_document_units:
                    results.display_units = self.document.model.display_units
                self._units = self.document.model.display_units
                self._times = np.asarray(results.times, dtype=float)
                self._results = results
            except (ThermalFEAError, OSError, KeyError) as exc:
                _log.warning("results %s cannot be read: %s", path, exc)
                self._status(f"Results cannot be read: {exc}")
        if self._results is not None:
            if not self.objects:
                name = unique_name("Temperature", [])
                self.objects.append(ContourObject(name, step=self.n_steps - 1))
            self.objects = [self._clamped(obj) for obj in self.objects]
            if self.get(self.shown) is None:
                self.shown = self.objects[0].name
        self.objects_changed.emit()
        self._refresh()
        self.status_changed.emit()

    def status(self) -> ResultStatus:
        """Freshness of the displayed results (cached per model object and file)."""
        document = self.document
        rest = (
            document.results_path, _file_key(document.results_path) if document.results_path
            else None, document.generation, document.undo_stack.index(),
        )
        cache = self._status_cache
        if cache is not None and cache[0] is document.model and cache[1] == rest:
            return cache[2]
        status = result_status(document)
        self._status_cache = (document.model, rest, status)
        return status

    def _on_model_changed(self) -> None:
        self._apply_units()
        status = self.status()
        if self._results is not None and self._suffixed != status.out_of_date:
            self._refresh()  # the viewport title gains or loses " · out of date"
        self.status_changed.emit()

    def _apply_units(self) -> None:
        """Show the results again when the display units changed.

        Manual color ranges are typed in display units, so they are converted to the new
        units (the same SI values); the cached ranges over all steps are dropped.
        """
        new = self.document.model.display_units
        old = self._units
        if new == old:
            return
        self._units = new
        self._follow_document_units = True
        if self._results is None:
            return
        self._results.display_units = new
        self._ranges.clear()
        converted: list[ResultObject] = []
        for obj in self.objects:
            if isinstance(obj, ContourObject) and obj.vmin is not None and obj.vmax is not None:
                lo, hi = (
                    float(field_display_values(
                        obj.field, field_si_values(obj.field, v, old), new)[0])
                    for v in (obj.vmin, obj.vmax)
                )
                obj = replace(obj, vmin=lo, vmax=hi)
            converted.append(obj)
        self.objects = converted
        self.objects_changed.emit()
        self._refresh()

    def _clamped(self, obj: ResultObject) -> ResultObject:
        step = min(max(obj.step, 0), max(self.n_steps - 1, 0))
        out = replace(obj, step=step) if step != obj.step else obj
        if isinstance(out, ContourObject) and out.field not in self.fields():
            out = replace(out, field="T", range_mode="auto_step", vmin=None, vmax=None)
        return out

    def _status(self, text: str, timeout_ms: int = 8000) -> None:
        self.window.statusBar().showMessage(text, timeout_ms)

    # ---------------------------------------------------------------- objects
    def get(self, name: str | None) -> ResultObject | None:
        """The object called ``name``, or ``None``."""
        return next((o for o in self.objects if o.name == name), None)

    def _require(self, name: str) -> ResultObject:
        obj = self.get(name)
        if obj is None:
            raise ModelError(f"there is no result object {name!r}")
        return obj

    def _names(self) -> list[str]:
        return [o.name for o in self.objects]

    def _added(self, obj: ResultObject) -> str:
        self.objects.append(obj)
        self.show(obj.name)
        self.objects_changed.emit()
        if self.tree is not None:
            self.tree.select_address((RESULT_ADDRESS, obj.name))
        return obj.name

    def add_contour(self, field: str = "T") -> str:
        """Add a contour object, show it and return its name.

        Parameters
        ----------
        field : str
            A key of :data:`thermalfea.post.plots.FIELDS`.
        """
        if field not in FIELDS:
            raise ModelError(f"unknown contour field {field!r}")
        title = FIELDS[field][3]
        obj = ContourObject(
            unique_name(title, self._names()), field=field, step=max(self.n_steps - 1, 0)
        )
        return self._added(obj)

    def add_vectors(self) -> str:
        """Add a vector object (heat-flux arrows), show it and return its name."""
        obj = VectorObject(
            unique_name("Heat flux vectors", self._names()), step=max(self.n_steps - 1, 0)
        )
        return self._added(obj)

    def rename_object(self, name: str, new_name: str) -> bool:
        """Rename an object; ``False`` if the name is unchanged.

        Raises
        ------
        ModelError
            If the name is empty or used by another object.
        """
        new_name = new_name.strip()
        obj = self._require(name)
        if not new_name:
            raise ModelError("a name cannot be empty")
        if new_name == name:
            return False
        if new_name in self._names():
            raise ModelError(f"the name {new_name!r} is already used")
        self.objects[self.objects.index(obj)] = replace(obj, name=new_name)
        if self.shown == name:
            self.shown = new_name
        self.objects_changed.emit()
        return True

    def duplicate(self, name: str) -> str:
        """Copy an object under a new unique name, show the copy and return its name."""
        obj = self._require(name)
        copy = replace(obj, name=copy_name(name, self._names()))
        position = self.objects.index(obj) + 1
        self.objects.insert(position, copy)
        self.show(copy.name)
        self.objects_changed.emit()
        if self.tree is not None:
            self.tree.select_address((RESULT_ADDRESS, copy.name))
        return copy.name

    def delete(self, name: str) -> bool:
        """Delete an object; another one (or none) is displayed afterwards."""
        obj = self._require(name)
        index = self.objects.index(obj)
        del self.objects[index]
        if self.shown == name:
            self.pause()
            following = self.objects[min(index, len(self.objects) - 1)] if self.objects else None
            self.shown = following.name if following is not None else None
        self.objects_changed.emit()
        self._refresh()
        return True

    def show(self, name: str) -> None:
        """Make the object the displayed one."""
        self._require(name)
        if self.shown != name:
            self.pause()
        self.shown = name
        self._refresh()

    # ----------------------------------------------------------------- editing
    def update(self, name: str, **changes: Any) -> ResultObject:
        """Change settings of an object and refresh the display if it is the shown one.

        Parameters
        ----------
        name : str
        **changes
            Attributes of the object (``field``, ``step``, ``range_mode``, ``vmin``,
            ``vmax``, ``banded``, ``levels``, ``show_mesh``, ``markers``, ``density``).
            A ``step`` is clamped to the stored steps.

        Returns
        -------
        ContourObject or VectorObject
            The updated object.

        Raises
        ------
        ModelError
            For an unknown setting or an invalid value; nothing is changed.
        """
        obj = self._require(name)
        valid = {f.name for f in fields(obj)} - {"name"}
        for key in changes:
            if key not in valid:
                raise ModelError(f"a {obj.kind} object has no setting {key!r}")
        new = self._validated(obj, changes)
        if new != obj:
            self.objects[self.objects.index(obj)] = new
            if self.shown == name:
                self._refresh()
            else:
                self.display_changed.emit()
        return new

    def _validated(self, obj: ResultObject, changes: dict[str, Any]) -> ResultObject:
        values = dict(changes)
        for key, value in values.items():
            if key == "step":
                values[key] = min(max(int(value), 0), max(self.n_steps - 1, 0))
            elif key in ("levels", "density"):
                number = int(value)
                if not 1 <= number <= (MAX_LEVELS if key == "levels" else 10**6):
                    raise ModelError(f"{key} must be at least 1 (levels at most {MAX_LEVELS})")
                values[key] = number
            elif key in ("banded", "show_mesh", "markers"):
                values[key] = bool(value)
            elif key == "field":
                if value not in (self.fields() or list(FIELDS)):
                    raise ModelError(f"the results cannot show the field {value!r}")
            elif key == "range_mode":
                if value not in RANGE_MODES:
                    raise ModelError(f"unknown range mode {value!r}")
            elif key in ("vmin", "vmax"):
                if value is not None:
                    number_f = float(value)
                    if not np.isfinite(number_f):
                        raise ModelError(f"the range {key} must be a finite number")
                    values[key] = number_f
        if (
            isinstance(obj, ContourObject)
            and "field" in values
            and values["field"] != obj.field
            and "range_mode" not in values
            and obj.range_mode == "manual"
        ):
            values.update(range_mode="auto_step", vmin=None, vmax=None)
        new = replace(obj, **values)
        if isinstance(new, ContourObject) and new.range_mode == "manual":
            mode = obj.range_mode if obj.range_mode != "manual" else "auto_step"
            both_typed = values.get("vmin") is not None and values.get("vmax") is not None
            if new.vmin is None or new.vmax is None:
                lo, hi = self._auto_range(replace(new, range_mode=mode))
                new = replace(
                    new,
                    vmin=lo if new.vmin is None else new.vmin,
                    vmax=hi if new.vmax is None else new.vmax,
                )
            if new.vmin > new.vmax:  # type: ignore[operator]
                raise ModelError("the range minimum must be below the maximum")
            if new.vmin == new.vmax:  # type: ignore[operator]
                # equal limits are only allowed where they come from a uniform field, whose
                # automatic range is empty; limits the user typed must be strictly ordered
                lo, hi = self._auto_range(replace(new, range_mode=mode))
                if both_typed or lo < hi:
                    raise ModelError("the range minimum must be below the maximum")
        return new

    # ----------------------------------------------------------------- display
    def _all_range(self, field: str) -> tuple[float, float]:
        if field not in self._ranges:
            assert self._results is not None
            self._ranges[field] = field_range(self._results, field)
        return self._ranges[field]

    def _auto_range(self, obj: ContourObject) -> tuple[float, float]:
        """The automatic range an object would have now (for filling in a manual one)."""
        if self._results is None:
            return 0.0, 1.0
        if obj.range_mode == "auto_all":
            return self._all_range(obj.field)
        data = contour_data(self._results, obj.step, obj.field)
        return data.vmin, data.vmax

    def build_display(self, obj: ResultObject) -> FieldDisplay:
        """The :class:`FieldDisplay` of an object for the current results."""
        results = self._results
        if results is None:
            raise ModelError("there are no results")
        if isinstance(obj, VectorObject):
            data = vector_data(results, obj.step, obj.density)
            display = field_display_from_vectors(data, show_mesh=obj.show_mesh)
        else:
            lo = hi = None
            if obj.range_mode == "manual":
                lo, hi = obj.vmin, obj.vmax
            elif obj.range_mode == "auto_all":
                lo, hi = self._all_range(obj.field)
            display = field_display_from_contour(
                contour_data(results, obj.step, obj.field),
                levels=obj.levels if obj.banded else None,
                vmin=lo,
                vmax=hi,
                show_mesh=obj.show_mesh,
                markers=obj.markers,
            )
        self._suffixed = self.status().out_of_date
        if self._suffixed:
            display.title = f"{display.title}{OUT_OF_DATE_SUFFIX}"
        return display

    def _refresh(self) -> None:
        obj = self.get(self.shown)
        spec: FieldDisplay | None = None
        if obj is not None and self._results is not None:
            try:
                spec = self.build_display(obj)
            except (ThermalFEAError, OSError, KeyError) as exc:
                _log.warning("cannot display %s: %s", obj.name, exc)
                self._status(f"Cannot display {obj.name}: {exc}")
                self.pause()
        self.display = spec
        self.view.set_field(spec)
        self._reevaluate_markers()
        self._update_actions()
        self.display_changed.emit()

    @property
    def displayed_range(self) -> tuple[float, float] | None:
        """The color range of the display (display units), or ``None`` if nothing is shown."""
        if self.display is None:
            return None
        return float(self.display.vmin), float(self.display.vmax)

    # ---------------------------------------------------------------- animation
    @property
    def can_play(self) -> bool:
        """Whether there is a displayed object and more than one stored step."""
        return self._results is not None and self.n_steps > 1 and self.get(self.shown) is not None

    @property
    def playing(self) -> bool:
        """Whether the animation timer runs."""
        return self.timer.isActive()

    @property
    def interval_ms(self) -> int:
        """Animation frame interval [ms]."""
        return self._interval_ms

    def set_interval(self, milliseconds: int) -> None:
        """Set the frame interval (limited to 10 .. 10000 ms)."""
        self._interval_ms = min(max(int(milliseconds), MIN_INTERVAL_MS), MAX_INTERVAL_MS)
        self.timer.setInterval(self._interval_ms)

    def play(self) -> bool:
        """Start the animation (from step 0 if the object is on its last step).

        Returns
        -------
        bool
            ``False`` if there is nothing to animate.
        """
        obj = self.get(self.shown)
        if not self.can_play or obj is None:
            return False
        if obj.step >= self.n_steps - 1:
            self.update(obj.name, step=0)
        self.timer.start()
        self._announce_playing()
        return True

    def pause(self) -> None:
        """Stop the animation (no effect when it is not running)."""
        was = self.timer.isActive()
        self.timer.stop()
        if was:
            self._announce_playing()

    def _announce_playing(self) -> None:
        self._update_actions()
        self.playing_changed.emit(self.playing)

    def _play_toggled(self, checked: bool) -> None:
        if checked:
            if not self.play():
                self._update_actions()
        else:
            self.pause()

    def tick(self) -> None:
        """One animation frame: advance the displayed object by one step.

        Stops on the last step unless :attr:`loop` is set, then wraps to step 0.
        """
        obj = self.get(self.shown)
        if obj is None or self._results is None or self.n_steps < 2:
            self.pause()
            return
        last = self.n_steps - 1
        step = obj.step + 1
        if step > last:
            if not self.loop:
                self.pause()
                return
            step = 0
        self.update(obj.name, step=step)
        if step >= last and not self.loop:
            self.pause()

    # ------------------------------------------------------------------- probe
    @property
    def probe_active(self) -> bool:
        """Whether viewport clicks are probed."""
        return self.window.actions[PROBE_ID].isChecked()

    def set_probe(self, on: bool) -> None:
        """Turn the probe on or off (keeps the Results-menu action in step)."""
        action = self.window.actions[PROBE_ID]
        if action.isChecked() != on:
            action.blockSignals(True)
            action.setChecked(on)
            action.blockSignals(False)
        if not on:
            self._clear_markers()
        if on:
            self._status("Probe: click in the viewport to read the displayed field", 5000)

    @property
    def probe_text(self) -> str:
        """Text of the latest probe reading (empty if none)."""
        return self.probes[-1].text if self.probes else ""

    def _marker_text(self, x: float, y: float) -> str | None:
        """Value and unit at a point for the displayed object and step (``None`` if outside)."""
        obj = self.get(self.shown)
        results = self._results
        if obj is None or results is None:
            return None
        field = obj.field if isinstance(obj, ContourObject) else VECTOR_PROBE_FIELD
        try:
            si = value_at(results, obj.step, [x, y][: results.mesh.dim], field)
            value, unit = display_value(results, field, si)
        except (ThermalFEAError, OSError, KeyError):
            return None
        return f"{value:.4g} {unit}" if np.isfinite(value) else None

    def _show_markers(self, items: list[OverlayMarker]) -> None:
        self._items = list(items)
        self._markers = [(m.x, m.y) for m in items]
        self.view.set_overlay("probe", list(items))

    def _clear_markers(self) -> None:
        if self._markers:
            self._markers = []
            self._items = []
            self.view.set_overlay("probe", [])

    def _reevaluate_markers(self) -> None:
        """Evaluate the kept markers again for the displayed object and step."""
        if not self._markers:
            return
        items: list[OverlayMarker] = []
        for x, y in self._markers:
            text = self._marker_text(x, y)
            if text is not None:
                items.append(OverlayMarker(x, y, text))
        self._show_markers(items)

    def probe_at(self, x: float, y: float) -> ProbeReading | None:
        """Evaluate the displayed field at ``(x, y)`` [m] for the displayed step.

        The reading is appended to :attr:`probes` and announced (status bar and
        :attr:`probe_changed`).

        Returns
        -------
        ProbeReading or None
            ``None`` when nothing is displayed.
        """
        obj = self.get(self.shown)
        results = self._results
        if obj is None or results is None:
            self._status("Probe: no result is displayed", 5000)
            return None
        field = obj.field if isinstance(obj, ContourObject) else VECTOR_PROBE_FIELD
        point = [x, y][: results.mesh.dim]
        try:
            si = value_at(results, obj.step, point, field)
            value, unit = display_value(results, field, si)
        except (ThermalFEAError, OSError, KeyError) as exc:
            self._status(f"Probe failed: {exc}")
            return None
        label = FIELDS[field][3]
        inside = bool(np.isfinite(value))
        units = self.document.model.display_units
        length = unit_label("length", units)
        x_shown, y_shown = (float(from_si(v, "length", units)) for v in (x, y))
        where = f"x = {x_shown:.6g} {length}, y = {y_shown:.6g} {length}"
        text = f"{where}: {label} = {value:.6g} {unit}" if inside else f"{where}: outside the model"
        reading = ProbeReading(x, y, value, unit, label, inside, obj.step, text)
        self.probes.append(reading)
        del self.probes[:-MAX_PROBES]
        if inside:
            items = [*self._items, OverlayMarker(x, y, f"{value:.4g} {unit}")]
            self._show_markers(items[-MAX_PROBES:])
        self._status(text, 15000)
        self.probe_changed.emit(text)
        return reading

    def _on_point_picked(self, x: float, y: float, _z: float) -> None:
        if self.probe_active:
            self.probe_at(float(x), float(y))

    # ------------------------------------------------------- tree provider API
    def tree_items(self) -> list[tuple[str, tuple, bool]]:
        """The children of the Solution node: ``(text, address, renameable)``."""
        return [(o.name, (RESULT_ADDRESS, o.name), True) for o in self.objects]

    def tree_summary(self, address: tuple) -> str:
        """``contour · current``: the plot kind and the freshness of the results."""
        obj = self.get(address[1]) if len(address) > 1 else None
        if obj is None:
            return ""
        state = self.status().short
        return f"{obj.kind} · {state}" if state else obj.kind

    def owns(self, address: tuple) -> bool:
        """Whether an address is a result object's."""
        return bool(address) and address[0] == RESULT_ADDRESS

    def tree_actions(self, address: tuple | None) -> list[tuple[str, Callable[[], object], Any]]:
        """Context-menu actions of the Solution node (``None``) or of one object."""
        if address is None:
            return [
                ("Add contour", self.add_contour, ("add_result", "contour")),
                ("Add vector plot", self.add_vectors, ("add_result", "vector")),
            ]
        name = address[1]
        out: list[tuple[str, Callable[[], object], Any]] = [
            ("Show", lambda: self._select(name), ("show_result", address)),
        ]
        if self.tree is not None:
            out.append(("Rename", lambda: self.tree.begin_rename(address), ("rename", address)))
        out.append(("Duplicate", lambda: self.duplicate(name), ("duplicate", address)))
        out.append(("Delete", lambda: self.delete(name), ("delete", address)))
        return out

    def _select(self, name: str) -> None:
        self.show(name)
        if self.tree is not None:
            self.tree.select_address((RESULT_ADDRESS, name))

    def rename(self, address: tuple, new_name: str) -> bool:
        """Rename the object of a tree address (inline rename)."""
        return self.rename_object(address[1], new_name)


def attach_results(window: MainWindow, document: Document, view: SceneView) -> ResultController:
    """Install the result displays in a main window.

    Creates the controller, adds the Results-menu actions, makes the model tree show the
    result objects under the Solution node and the property controller show their panel.
    Call it after :func:`~thermalfea.gui.panels.attach_tree`.

    Parameters
    ----------
    window : MainWindow
    document : Document
    view : SceneView
        The viewport (from :func:`~thermalfea.gui.viewport_mpl.attach_viewport`).

    Returns
    -------
    ResultController
    """
    controller = ResultController(window, document, view)
    tree = window.tree_widget
    if hasattr(tree, "add_provider"):
        controller.tree = tree
        tree.add_provider(controller)
    props = getattr(tree, "property_controller", None)
    if props is not None:
        props.results_controller = controller

        def objects_changed() -> None:
            # the object of the open panel was renamed or deleted: follow the displayed one
            panel = props.result_panel
            if panel is None or controller.get(panel.name) is not None:
                return
            if controller.shown is None:
                props.show_object(("section", "solution"))
            elif controller.tree is not None:
                controller.tree.select_address((RESULT_ADDRESS, controller.shown))
            else:
                props.show_object((RESULT_ADDRESS, controller.shown))

        controller.objects_changed.connect(objects_changed)
    return controller
