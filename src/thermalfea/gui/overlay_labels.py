"""Region names and load values as viewport labels (Plan M11.45).

:class:`OverlayLabelController` keeps two overlay layers of the viewport
(:meth:`~thermalfea.gui.scene.SceneView.set_overlay`) equal to the model:

* ``region_names`` -- one label per region at the area-weighted centroid of its surfaces,
  with the text the model tree shows (``"<selection> -> <material>"``);
* ``load_values`` -- one label per active condition (and per contact) at its entities, with
  the name and the values of the form fields of kind ``function`` and ``float`` in the
  display units, e.g. ``cooling: h = 750 W/(m²·K), T_inf = 0 °C``.

The label text comes from the forms of the registry (``form_for``), so a condition
registered later is labelled without a change here. Two checkable View-menu actions,
``view.region_names`` (default off) and ``view.load_values`` (default on), show the layers.
Both layers are empty without a built geometry.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from thermalfea.core.forms import form_for
from thermalfea.core.forms import format_value as format_value  # re-exported (M11.58 moved it)
from thermalfea.core.units import UnitSettings
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.gui.document import Document
from thermalfea.gui.load_symbols import contact_entities, entities_of
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.scene import OverlayItem, OverlayText, SceneView
from thermalfea.model.bcs import BoundaryCondition, Contact
from thermalfea.model.model import RegionAssignment, part_name

REGION_ACTION_ID = "view.region_names"
LOAD_ACTION_ID = "view.load_values"
REGION_LAYER = "region_names"
LOAD_LAYER = "load_values"
_VALUE_KINDS = ("function", "float")
_POINT_DIM, _CURVE_DIM, _SURFACE_DIM = 0, 1, 2
_XY = 2


def region_title(region: RegionAssignment) -> str:
    """The label of a part: its name, as the model tree shows it (M11.56)."""
    return part_name(region)


def label_text(obj: Any, units: UnitSettings) -> str:
    """``"<name>: <field> = <value>, ..."`` over the function and float fields of a form."""
    parts: list[str] = []
    for spec in form_for(type(obj)).fields:
        if spec.kind not in _VALUE_KINDS:
            continue
        text = format_value(spec, getattr(obj, spec.name, None), units)
        if text is not None:
            parts.append(f"{spec.name} = {text}")
    name = str(getattr(obj, "name", ""))
    return f"{name}: {', '.join(parts)}" if parts else name


def _surface_centroid(built: BuiltGeometry, tags: list[int]) -> tuple[float, float] | None:
    """Area-weighted centre of the surfaces; the mean of their centres if the areas vanish."""
    prints = [built.surfaces[t] for t in tags if t in built.surfaces]
    if not prints:
        return None
    centres = np.array([p.center[:_XY] for p in prints], dtype=float)
    areas = np.array([abs(p.measure) for p in prints], dtype=float)
    weights = areas if float(areas.sum()) > 0.0 else np.ones(len(prints))
    c = (centres * weights[:, None]).sum(axis=0) / weights.sum()
    return float(c[0]), float(c[1])


def _midpoint(line: np.ndarray) -> tuple[float, float]:
    """The point at half the arc length of a polyline."""
    pts = np.asarray(line, dtype=float)[:, :_XY]
    seg = np.hypot(*np.diff(pts, axis=0).T) if len(pts) > 1 else np.zeros(0)
    total = float(seg.sum())
    if total <= 0.0:
        return float(pts[0, 0]), float(pts[0, 1])
    s = np.concatenate([[0.0], np.cumsum(seg)])
    return float(np.interp(0.5 * total, s, pts[:, 0])), float(np.interp(0.5 * total, s, pts[:, 1]))


def _anchor(
    built: BuiltGeometry, groups: list[tuple[int, list[int]]]
) -> tuple[float, float] | None:
    """Where to put a load label: the highest dimension of the entities decides."""
    for dim, tags in reversed(groups):
        if dim == _SURFACE_DIM:
            found = _surface_centroid(built, tags)
            if found is not None:
                return found
        elif dim == _CURVE_DIM:
            known = [t for t in tags if t in built.curves]
            if known:
                longest = max(known, key=lambda t: built.curves[t].measure)
                line = built.curve_polylines.get(longest)
                if line is not None and len(line):
                    return _midpoint(line)
                return built.curves[longest].center[0], built.curves[longest].center[1]
        elif dim == _POINT_DIM:
            known = [t for t in tags if t in built.points]
            if known:
                c = built.points[known[0]].center
                return float(c[0]), float(c[1])
    return None


def region_labels(document: Document) -> list[OverlayItem]:
    """One name label per region whose surfaces resolve; empty without a built geometry."""
    built = document.built
    if built is None:
        return []
    out: list[OverlayItem] = []
    for region in document.model.regions:
        sel = document.model.selections.get(region.selection)
        if sel is None or sel.dim != _SURFACE_DIM or not sel.tags:
            continue
        at = _surface_centroid(built, [int(t) for t in sel.tags])
        if at is None:
            continue
        out.append(OverlayText(at[0], at[1], region_title(region)))
    return out


def load_labels(document: Document) -> list[OverlayItem]:
    """One value label per active condition and per contact; empty without a geometry."""
    built = document.built
    if built is None:
        return []
    units = document.model.display_units
    out: list[OverlayItem] = []
    items: list[tuple[BoundaryCondition | Contact, list[tuple[int, list[int]]]]] = [
        (bc, entities_of(document, bc)) for bc in document.model.bcs if bc.active
    ]
    items += [(c, contact_entities(document, c)) for c in document.model.contacts]
    for obj, groups in items:
        at = _anchor(built, groups)
        if at is not None:
            out.append(OverlayText(at[0], at[1], label_text(obj, units)))
    return out


class OverlayLabelController(QObject):
    """Keeps the ``region_names`` and ``load_values`` overlay layers current.

    Parameters
    ----------
    window : MainWindow
        Its View menu receives the checkable actions ``view.region_names`` and
        ``view.load_values``.
    document : Document
    view : SceneView
        Receives ``set_overlay`` for both layers.

    Attributes
    ----------
    region_action, load_action : QAction
        The View-menu entries (region names default unchecked, load values checked).
    """

    def __init__(self, window: MainWindow, document: Document, view: SceneView) -> None:
        super().__init__(window)
        self.document = document
        self.view = view
        self.region_action = QAction("Region &names", window)
        self.region_action.setCheckable(True)
        self.region_action.setChecked(False)
        self.load_action = QAction("Load &values", window)
        self.load_action.setCheckable(True)
        self.load_action.setChecked(True)
        actions = ((self.region_action, REGION_ACTION_ID), (self.load_action, LOAD_ACTION_ID))
        for action, key in actions:
            action.toggled.connect(lambda _checked: self.update())
            window.actions[key] = action
            window.menus["view"].addAction(action)
        document.model_changed.connect(self.update)
        document.geometry_built.connect(self.update)
        self.update()

    def update(self) -> None:
        """Send both layers (empty while hidden or without a built geometry)."""
        regions = region_labels(self.document) if self.region_action.isChecked() else []
        loads = load_labels(self.document) if self.load_action.isChecked() else []
        self.view.set_overlay(REGION_LAYER, regions)
        self.view.set_overlay(LOAD_LAYER, loads)


def attach_labels(
    window: MainWindow, document: Document, view: SceneView
) -> OverlayLabelController:
    """Install the region-name and load-value labels and their View-menu toggles."""
    return OverlayLabelController(window, document, view)
