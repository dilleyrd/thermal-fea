"""The summary column of the model tree, and the Model dock title (Plan M11.50).

Every function here is a pure function of the model and the document state; nothing is
stored in the model. :func:`summary_for` is what :class:`~thermalfea.gui.tree.ModelTree`
calls for each item (column 1). Load summaries come from the registered forms
(``form_for``), so a load registered later needs no change here.

A provider of the Solution node may offer ``tree_summary(address) -> str``; without it the
summary of its objects is empty.

:class:`TreeSummaryController` keeps the Model dock title current and owns the View-menu
action ``view.tree_summary`` that shows or hides the column.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec, form_for
from thermalfea.core.units import UnitSettings, from_si, unit_label
from thermalfea.gui.overlay_labels import format_value
from thermalfea.materials import library
from thermalfea.model import geometry_ops as ops
from thermalfea.model.model import Model
from thermalfea.model.selections import StaleSelectionError, resolve, selection_users
from thermalfea.model.vocabulary import entity_word, shape_word

if TYPE_CHECKING:
    from thermalfea.gui.document import Document
    from thermalfea.gui.main_window import MainWindow
    from thermalfea.gui.tree import ModelTree

ACTION_ID = "view.tree_summary"
_SEP = " · "
_VALUE_KINDS = ("function", "float")


def _length(value: float, units: UnitSettings) -> str:
    return f"{float(from_si(value, 'length', units)):.4g}"


def _spec(quantity: str | None) -> FieldSpec:
    return FieldSpec("value", "", "function", quantity=quantity)


def _count(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# ------------------------------------------------------------------------- geometry
def geometry_summary(op: Any, units: UnitSettings) -> str:
    """Kind and size of a geometry step, in display units."""
    lu = unit_label("length", units)
    if isinstance(op, ops.Rectangle):
        return f"rectangle {_length(op.width, units)} × {_length(op.height, units)} {lu}"
    if isinstance(op, ops.Circle):
        return f"circle r {_length(op.radius, units)} {lu}"
    if isinstance(op, ops.Polygon):
        return f"polygon {len(op.vertices)} vertices"
    if isinstance(op, ops.Boolean):
        return f"boolean {op.kind}"
    if isinstance(op, ops.Transform):
        return f"transform {op.kind}"
    if isinstance(op, ops.ImportFile):
        return f"import {os.path.basename(op.path)}"
    if isinstance(op, ops.Point):
        return f"point ({_length(op.x, units)}, {_length(op.y, units)}) {lu}"
    if isinstance(op, ops.Spline):
        return f"spline {len(op.points)} points"
    if isinstance(op, ops.SurfaceFromCurves):
        return f"surface from {len(op.curves)} curves"
    if isinstance(op, ops.Delete):
        return f"delete {len(op.targets)}"
    return type(op).__name__.lower()


# ---------------------------------------------------------------------------- loads
def load_summary(obj: Any, units: UnitSettings) -> str:
    """``"<form title> · <field> <value>, ... → <selection>"`` of a load or a contact.

    The object's own name is not included. Fields of kind ``function`` and ``float`` are
    listed, as in the viewport labels.
    """
    form = form_for(type(obj))
    parts: list[str] = []
    for spec in form.fields:
        if spec.kind not in _VALUE_KINDS:
            continue
        text = format_value(spec, getattr(obj, spec.name, None), units)
        if text is not None:
            parts.append(f"{spec.name} {text}")
    out = form.title
    if parts:
        out += _SEP + ", ".join(parts)
    selection = getattr(obj, "selection", "")
    if selection:
        out += f" → {selection}"
    if getattr(obj, "active", True) is False:
        out += _SEP + "suppressed"
    return out


# --------------------------------------------------------------------------- others
def mesh_summary(document: Document) -> str:
    """Element type, size, counts and whether the mesh is current."""
    settings = document.model.mesh_settings
    units = document.model.display_units
    kind = {("tri", 1): "T3", ("tri", 2): "T6", ("quad", 1): "Q4", ("quad", 2): "Q8"}
    parts = [
        kind.get((settings.element_shape, settings.order), settings.element_shape),
        f"{_length(settings.global_size, units)} {unit_label('length', units)}",
    ]
    mesh = document.mesh
    if mesh is None:
        parts.append("not meshed")
    else:
        parts.append(f"{_count(mesh.n_nodes)} nodes")
        parts.append(f"{_count(mesh.n_elements)} elements")
        parts.append("out of date" if document.mesh_stale else "current")
    return _SEP.join(parts)


def initial_summary(model: Model) -> str:
    """``uniform 20 °C`` / ``expression`` / ``per region`` / ``from results``."""
    ic = model.initial_condition
    if ic.kind == "uniform":
        text = format_value(_spec("temperature"), ic.value, model.display_units)
        return f"uniform {text}" if text else "uniform"
    return {"per_region": "per part", "from_results": "from results"}.get(ic.kind, ic.kind)


def analysis_summary(model: Model) -> str:
    """``steady`` or ``transient 0–195 s``."""
    s = model.solution
    if s.kind == "steady":
        return "steady"
    units = model.display_units
    end = float(from_si(s.end_time, "time", units))
    return f"transient 0–{end:.4g} {unit_label('time', units)}"


def material_summary(material: Any, units: UnitSettings) -> str:
    """The conductivity and library state of a material.

    ``k 52 W/(m·K) · custom``, ``Copper (pure) · library``, ``... · edited`` or
    ``... · library entry not found``.
    """
    state, _, _ = library.source_state(material)
    if state == "custom":
        text = format_value(_spec("conductivity"), material.k, units)
        return f"k {text}{_SEP}custom" if text else "custom"
    entry = material.source.entry
    label = {
        "library": "library",
        "edited": "edited",
        "missing": "library entry not found",
    }[state]
    return f"{entry}{_SEP}{label}"


def region_summary(region: Any, model: Model, built: Any = None) -> str:
    """Material, the number of surfaces (with a build) and the thickness of a planar part."""
    parts = [str(region.material) or "no material"]
    if not region.selection:
        parts.append("no selection")
    elif built is not None and region.selection in model.selections:
        try:
            selection = model.selections[region.selection]
            n = len(resolve(selection, built))
            parts.append(f"{n} {shape_word(selection.dim, n != 1)}")
        except (StaleSelectionError, ModelError):
            parts.append("stale selection")
    if model.analysis == "planar":
        t = _length(region.thickness, model.display_units)
        parts.append(f"t {t} {unit_label('length', model.display_units)}")
    return _SEP.join(parts)


def selection_summary(document: Document, name: str) -> str:
    """``"2 boundaries · convection cooling"``, ``"... · unused"`` or ``"stale"``.

    A selection that no longer resolves in the current build is ``stale``.
    """
    model = document.model
    selection = model.selections[name]
    built = document.built
    if built is not None:
        try:
            resolve(selection, built)
        except StaleSelectionError:
            return "stale"
    n = len(selection.tags)
    word = entity_word(selection.dim, model, plural=n != 1)
    users = ", ".join(use.label for use in selection_users(model, name)) or "unused"
    return f"{n} {word}{_SEP}{users}"


def summary_for(
    document: Document, section: str, address: tuple | None, providers: list[Any] | None = None
) -> str:
    """The summary text of the tree item of ``section`` at ``address`` (``None``: the node)."""
    for provider in providers or []:
        if address is not None and provider.owns(address):
            fn = getattr(provider, "tree_summary", None)
            return str(fn(address)) if fn is not None else ""
    try:
        if address is None or address[0] in ("mesh_settings", "initial_condition", "solution"):
            return _section_summary(document, section, address)
        return _object_summary(document, address)
    except (IndexError, KeyError, AttributeError):
        return ""


def _section_summary(document: Document, section: str, address: tuple | None) -> str:
    model = document.model
    if address == ("mesh_settings",):
        return mesh_summary(document)
    if address == ("initial_condition",):
        return initial_summary(model)
    if address == ("solution",):
        return analysis_summary(model)
    if section == "folded":  # Contacts · Flow · Enclosures, all empty (M11.51)
        return "none"
    if section == "geometry":
        return f"{len(model.geometry)} steps"
    sizes = {
        "materials": len(model.materials),
        "regions": len(model.regions),
        "selections": len(model.selections),
        "loads": len(model.bcs),
        "contacts": len(model.contacts),
        "streams": len(model.streams),
        "enclosures": len(model.enclosures),
    }
    return str(sizes[section]) if section in sizes else ""


def _object_summary(document: Document, address: tuple) -> str:
    model = document.model
    units = model.display_units
    kind, key = address[0], address[1] if len(address) > 1 else None
    if kind == "geometry":
        return geometry_summary(model.geometry[key], units)
    if kind == "materials":
        return material_summary(model.materials[key], units)
    if kind == "regions":
        built = None if document.geometry_stale else document.built
        return region_summary(model.regions[key], model, built)
    if kind == "selections":
        return selection_summary(document, key)
    if kind == "bcs":
        return load_summary(model.bcs[key], units)
    if kind == "contacts":
        return load_summary(model.contacts[key], units)
    if kind == "streams":
        return f"{len(model.streams[key].walls)} walls"
    if kind == "enclosures":
        return f"{len(model.enclosures[key].surfaces)} surfaces"
    if kind == "network":
        net = model.network
        return "none" if net is None else f"{len(net.branches)} branches"
    return ""


# -------------------------------------------------------------------------- dock title
def dock_title(model: Model) -> str:
    """``Model — <name> · <planar|axisymmetric> · t 1 m · <temperature unit>``.

    The thickness is shown for a planar model whose regions all share one.
    """
    units = model.display_units
    parts = [model.name, model.analysis]
    if model.analysis == "planar" and model.regions:
        thicknesses = {r.thickness for r in model.regions}
        if len(thicknesses) == 1:
            t = _length(thicknesses.pop(), units)
            parts.append(f"t {t} {unit_label('length', units)}")
    parts.append(unit_label("temperature", units))
    return "Model — " + _SEP.join(parts)


class TreeSummaryController(QObject):
    """Sets the Model dock title and provides the View > Summary column action.

    Parameters
    ----------
    window : MainWindow
        Its ``model_dock`` (if any) receives the title; ``window.menus["view"]`` the action.
    document : Document
    tree : ModelTree
    """

    def __init__(self, window: MainWindow, document: Document, tree: ModelTree) -> None:
        super().__init__(window if isinstance(window, QObject) else None)
        self.window = window
        self.document = document
        self.tree = tree
        self.action = QAction("&Summary column", self)
        self.action.setCheckable(True)
        self.action.setChecked(True)
        self.action.toggled.connect(tree.set_summary_visible)
        actions = getattr(window, "actions", None)
        if isinstance(actions, dict):
            actions[ACTION_ID] = self.action
        menus = getattr(window, "menus", None)
        if isinstance(menus, dict) and "view" in menus:
            menus["view"].addAction(self.action)
        document.model_changed.connect(self.update_title)
        self.update_title()

    def update_title(self) -> None:
        """Set the Model dock title from the model (skipped without a ``model_dock``)."""
        dock = getattr(self.window, "model_dock", None)
        if dock is not None:
            dock.setWindowTitle(dock_title(self.document.model))
            # the dock's View-menu entry follows its title; it must keep the short name
            dock.toggleViewAction().setText("Model")
