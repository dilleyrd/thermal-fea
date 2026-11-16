"""Result displays: contour and vector objects, probe and animation (Plan M8.10).

Result objects are *view state*, not model data
-----------------------------------------------
A :class:`ContourObject` or :class:`VectorObject` says how some results are shown (which
field, which step, the colour range, ...). The model file format has no place for them and
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
    field and results file, so an animation keeps one colour scale);
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
outside the mesh reports "outside the model". A vector object is probed for the heat-flux
magnitude.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, fields, replace
from typing import Any, ClassVar

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QAction

from thermalfea.core.errors import ModelError, ThermalFEAError
from thermalfea.core.forms import copy_name, unique_name
from thermalfea.gui.document import Document
from thermalfea.gui.field_display import field_display_from_contour, field_display_from_vectors
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.property_panels.results import RESULT_ADDRESS
from thermalfea.gui.scene import FieldDisplay, SceneView
from thermalfea.post.path import value_at
from thermalfea.post.plots import (
    FIELDS,
    contour_data,
    contour_fields,
    display_value,
    field_range,
    vector_data,
)
from thermalfea.post.results import Results

_log = logging.getLogger(__name__)

#: Range modes of a contour object.
RANGE_MODES: tuple[str, ...] = ("auto_step", "auto_all", "manual")
#: Field a vector object is probed for.
VECTOR_PROBE_FIELD = "qmag"
#: Largest number of colour bands.
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
        Manual colour range in display units (used when ``range_mode == "manual"``).
    banded : bool
        Colour bands (``True``) or smooth shading.
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
        self.loop = False
        self._interval_ms = 200
        self._results: Results | None = None
        self._times: np.ndarray = np.zeros(0)
        self._ranges: dict[str, tuple[float, float]] = {}
        self.timer = QTimer(self)
        self.timer.setInterval(self._interval_ms)
        self.timer.timeout.connect(self.tick)
        self._build_actions()
        document.results_changed.connect(self._on_results_changed)
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

    def _on_results_changed(self) -> None:
        self.pause()
        self._ranges.clear()
        self._results = None
        self._times = np.zeros(0)
        path = self.document.results_path
        if path is not None:
            try:
                results = Results(path)
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
            if new.vmin is None or new.vmax is None:
                mode = obj.range_mode if obj.range_mode != "manual" else "auto_step"
                lo, hi = self._auto_range(replace(new, range_mode=mode))
                new = replace(
                    new,
                    vmin=lo if new.vmin is None else new.vmin,
                    vmax=hi if new.vmax is None else new.vmax,
                )
            if not new.vmin < new.vmax:  # type: ignore[operator]
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
            return field_display_from_vectors(data, show_mesh=obj.show_mesh)
        lo = hi = None
        if obj.range_mode == "manual":
            lo, hi = obj.vmin, obj.vmax
        elif obj.range_mode == "auto_all":
            lo, hi = self._all_range(obj.field)
        return field_display_from_contour(
            contour_data(results, obj.step, obj.field),
            levels=obj.levels if obj.banded else None,
            vmin=lo,
            vmax=hi,
            show_mesh=obj.show_mesh,
            markers=obj.markers,
        )

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
        self._update_actions()
        self.display_changed.emit()

    @property
    def displayed_range(self) -> tuple[float, float] | None:
        """The colour range of the display (display units), or ``None`` if nothing is shown."""
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
        if on:
            self._status("Probe: click in the viewport to read the displayed field", 5000)

    @property
    def probe_text(self) -> str:
        """Text of the latest probe reading (empty if none)."""
        return self.probes[-1].text if self.probes else ""

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
        where = f"x = {x:.6g} m, y = {y:.6g} m"
        text = f"{where}: {label} = {value:.6g} {unit}" if inside else f"{where}: outside the model"
        reading = ProbeReading(x, y, value, unit, label, inside, obj.step, text)
        self.probes.append(reading)
        del self.probes[:-MAX_PROBES]
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
