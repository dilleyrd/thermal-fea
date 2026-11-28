"""Named selections of geometry entities (Data §5).

Loads never store raw gmsh tags alone, because tags can change when the geometry is
edited. A selection also stores a fingerprint of every entity so it can be found again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.errors import ModelError

if TYPE_CHECKING:  # the builder imports gmsh; this module must not (Plan §3)
    from ..geometry.builder import BuiltGeometry
    from .model import Model

#: Matching tolerance of :func:`resolve`: centre within ``TOL * L``, measure within ``TOL``.
RESOLVE_TOL = 1e-6


@dataclass
class Fingerprint:
    """Geometric signature of one entity.

    Parameters
    ----------
    dim : int
        0 point, 1 curve, 2 surface (3 volume in future).
    center : tuple of 3 float
        Centre of mass [m] (z = 0 in a 2D model).
    measure : float
        0 for a point, length [m], area [m^2] (or volume [m^3]).
    bbox : tuple of 6 float
        ``xmin, ymin, zmin, xmax, ymax, zmax`` [m].
    """

    dim: int
    center: tuple[float, float, float]
    measure: float
    bbox: tuple[float, float, float, float, float, float]

    def __post_init__(self) -> None:
        self.center = tuple(float(v) for v in self.center)  # type: ignore[assignment]
        self.bbox = tuple(float(v) for v in self.bbox)  # type: ignore[assignment]
        self.measure = float(self.measure)
        if len(self.center) != len(self.bbox) // 2 or len(self.bbox) % 2:
            raise ModelError("fingerprint: center needs 3 and bbox 6 components")


@dataclass
class Selection:
    """A named set of geometry entities of one dimension.

    Parameters
    ----------
    name : str
        Selection name, unique in the model.
    dim : int
        Dimension of the selected entities.
    tags : list of int
        Entity tags at the time of selection.
    fingerprints : list of Fingerprint
        One per tag, used to find the entities again after a rebuild.
    """

    name: str
    dim: int
    tags: list[int] = field(default_factory=list)
    fingerprints: list[Fingerprint] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ModelError("selection name must be a non-empty string")
        self.tags = [int(t) for t in self.tags]
        if len(self.tags) != len(self.fingerprints):
            raise ModelError(f"selection {self.name!r}: one fingerprint per tag is required")
        if any(fp.dim != self.dim for fp in self.fingerprints):
            raise ModelError(f"selection {self.name!r}: fingerprint dimension mismatch")


class StaleSelectionError(ModelError):
    """A selection refers to an entity that no longer exists in the built geometry."""


def fingerprint_matches(fp: Fingerprint, other: Fingerprint, length: float) -> bool:
    """True when two fingerprints describe the same entity (Data §5).

    Parameters
    ----------
    fp, other : Fingerprint
    length : float
        Bounding-box diagonal of the model [m].
    """
    if fp.dim != other.dim:
        return False
    if math.dist(fp.center, other.center) > RESOLVE_TOL * length:
        return False
    return abs(fp.measure - other.measure) <= RESOLVE_TOL * max(abs(fp.measure), abs(other.measure))


def resolve(selection: Selection, built: BuiltGeometry) -> list[int]:
    """Find the current tags of a selection's entities in a built geometry.

    For each fingerprint the entity of the same dimension is found whose centre is within
    ``1e-6 L`` and whose measure is within ``1e-6`` relative, ``L`` being the bounding-box
    diagonal of the geometry.

    Parameters
    ----------
    selection : Selection
    built : BuiltGeometry

    Returns
    -------
    list of int
        One tag per fingerprint, in order.

    Raises
    ------
    StaleSelectionError
        If a fingerprint matches no entity; the message names the selection.
    """
    candidates = built.entities(selection.dim)
    length = built.diagonal
    tags: list[int] = []
    for i, fp in enumerate(selection.fingerprints):
        matches = [
            (math.dist(fp.center, other.center), tag)
            for tag, other in candidates.items()
            if fingerprint_matches(fp, other, length)
        ]
        if not matches:
            # the roles of a 2-D domain (see model.vocabulary), named as the window does
            kind = {0: "point", 1: "boundary", 2: "part"}.get(selection.dim, "entity")
            raise StaleSelectionError(
                f"selection {selection.name!r} is stale: its {kind} #{i + 1} (centre "
                f"({fp.center[0]:.6g}, {fp.center[1]:.6g}), size {fp.measure:.6g}) no longer "
                "exists in the geometry; select it again"
            )
        tags.append(min(matches)[1])
    return tags


def refresh(selections: dict[str, Selection], built: BuiltGeometry) -> dict[str, str]:
    """Resolve every selection against a new build and update its tags.

    Parameters
    ----------
    selections : dict of str to Selection
        Updated in place: the tags of every selection that resolves.
    built : BuiltGeometry

    Returns
    -------
    dict of str to str
        Name -> message for every stale selection (empty when all resolve).
    """
    stale: dict[str, str] = {}
    for name, selection in selections.items():
        try:
            selection.tags = resolve(selection, built)
        except StaleSelectionError as exc:
            stale[name] = str(exc)
    return stale


# ------------------------------------------------------------------ selection editing
#
# One traversal (``selection_refs``) finds every place a selection name is stored. The
# list of users, renaming and the delete protection all go through it, so a holder added
# later is either found through its registered form (loads) or listed once in
# ``_explicit_refs`` below.

#: The selection that every build rewrites (all surfaces). It may be used but never
#: renamed, deleted, edited or created by hand.
ALL_SELECTION = "all"


@dataclass
class SelectionRef:
    """One stored reference to a selection name.

    Attributes
    ----------
    address : tuple
        Address of the object holding the reference, e.g. ``("bcs", 2)``,
        ``("regions", 0)``, ``("mesh_settings",)`` (see ``gui/addressing``).
    label : str
        What uses the selection, for messages and the users list ("load cooling").
    container : object
        The dataclass, list or dict that stores the name.
    key : str or int
        Attribute name (dataclass), index (list) or the name itself (dict key).
    kind : {"attr", "item", "key"}
        How the name is stored: as an attribute value, as a list item, or as a dict key.
    """

    address: tuple
    label: str
    container: object
    key: str | int
    kind: str


@dataclass
class SelectionUse:
    """One user of a selection: the address of the object and a readable label."""

    address: tuple
    label: str


def _value_refs(obj: object, attr: str, name: str, address: tuple, label: str):
    """References to ``name`` in ``obj.attr``, which holds a name or a list of names."""
    value = getattr(obj, attr, None)
    if value == name:
        yield SelectionRef(address, label, obj, attr, "attr")
    elif isinstance(value, list):
        for i, item in enumerate(value):
            if item == name:
                yield SelectionRef(address, label, value, i, "item")


def _form_selection_fields(obj: object) -> list[str]:
    """Names of the fields of ``obj`` whose registered form kind is a selection."""
    from ..core.forms import form_for  # the forms import the registry; keep this lazy

    return [
        f.name
        for f in form_for(type(obj)).fields
        if f.kind in ("selection", "selection_list")
    ]


def _title(obj: object) -> str:
    from ..core.forms import form_for

    return form_for(type(obj)).title


def _part_label(region: object) -> str:
    return getattr(region, "name", "") or getattr(region, "selection", "")


def selection_refs(model: Model, name: str) -> list[SelectionRef]:
    """Every stored reference to the selection ``name`` in ``model``.

    Covers regions, every boundary condition (suppressed ones too; their selection
    fields come from the registered forms), contacts, enclosure surfaces, stream walls
    (one reference per repeated entry), the mesh settings (``curve_sizes``,
    ``point_sizes`` and ``curve_divisions`` keys, ``structured_surfaces``, refinements)
    and the keys of ``InitialCondition.per_region``.
    """
    refs: list[SelectionRef] = []
    for i, region in enumerate(model.regions):
        refs += _value_refs(region, "selection", name, ("regions", i),
                            f"part {_part_label(region)}")  # fmt: skip
    for i, bc in enumerate(model.bcs):
        label = f"{_title(bc).lower()} {bc.name}"
        for attr in _form_selection_fields(bc):
            refs += _value_refs(bc, attr, name, ("bcs", i), label)
    for i, contact in enumerate(model.contacts):
        refs += _value_refs(contact, "selection", name, ("contacts", i),
                            f"contact {contact.name}")  # fmt: skip
    for i, enclosure in enumerate(model.enclosures):
        for j, surface in enumerate(enclosure.surfaces):
            refs += _value_refs(surface, "selection", name, ("enclosures", i),
                                f"enclosure {enclosure.name} surface {j + 1}")  # fmt: skip
    for i, stream in enumerate(model.streams):
        refs += _value_refs(stream, "walls", name, ("streams", i), f"stream {stream.name} walls")
    refs += _explicit_refs(model, name)
    return refs


def _explicit_refs(model: Model, name: str) -> list[SelectionRef]:
    """The references stored as dict keys or nested values outside any form field."""
    refs: list[SelectionRef] = []
    mesh = model.mesh_settings
    where = ("mesh_settings",)
    for attr, label in (
        ("curve_sizes", "mesh: boundary size"),
        ("point_sizes", "mesh: point size"),
        ("curve_divisions", "mesh: divisions"),
    ):
        table = getattr(mesh, attr)
        if name in table:
            refs.append(SelectionRef(where, label, table, name, "key"))
    refs += _value_refs(mesh, "structured_surfaces", name, where, "mesh: structured parts")
    for i, refinement in enumerate(mesh.refinements):
        refs += _value_refs(refinement, "selection", name, where, f"mesh: refinement {i + 1}")
    per_region = model.initial_condition.per_region
    if per_region and name in per_region:
        refs.append(SelectionRef(("initial_condition",), "initial condition (per part)",
                                 per_region, name, "key"))  # fmt: skip
    # a path plot along boundaries (Data §3a, M11.77)
    for item in getattr(model, "result_items", []):
        if getattr(item, "kind", None) == "boundaries" and hasattr(item, "selection"):
            refs += _value_refs(item, "selection", name, ("path", item.name),
                                f"path plot {item.name}")  # fmt: skip
    return refs


def selection_users(model: Model, name: str) -> list[SelectionUse]:
    """The objects that use the selection ``name``, one entry per object and label."""
    seen: list[SelectionUse] = []
    for ref in selection_refs(model, name):
        use = SelectionUse(ref.address, ref.label)
        if use not in seen:
            seen.append(use)
    return seen


def _key_tables(model: Model) -> list[dict]:
    """Every dict keyed by selection names (mesh sizes, divisions, per-region values)."""
    mesh = model.mesh_settings
    tables: list[dict] = [mesh.curve_sizes, mesh.point_sizes, mesh.curve_divisions]
    if model.initial_condition.per_region:
        tables.append(model.initial_condition.per_region)
    return tables


def check_new_selection_name(model: Model, name: str) -> str:
    """Return the stripped ``name`` if a new selection may take it.

    Raises
    ------
    ModelError
        If the name is empty, reserved (``"all"``), already a selection, or already a key
        of a table keyed by selection names (a dangling mesh size, say, which the new
        selection would silently pick up).
    """
    name = name.strip()
    if not name:
        raise ModelError("a selection name cannot be empty")
    if name == ALL_SELECTION:
        raise ModelError(f"the name {ALL_SELECTION!r} is reserved for all parts")
    if name in model.selections:
        raise ModelError(f"the selection name {name!r} is already used")
    if any(name in table for table in _key_tables(model)):
        raise ModelError(
            f"the name {name!r} is still used in the mesh settings or the initial "
            "condition; remove that entry first"
        )
    return name


def _replace_key(table: dict, old: str, new: str) -> None:
    """Rename a dict key in place, keeping the order of the keys."""
    items = [(new if k == old else k, v) for k, v in table.items()]
    table.clear()
    table.update(items)


def rename_selection(model: Model, old: str, new: str) -> bool:
    """Rename a selection and every reference to it.

    Every check runs before anything changes, so a refusal leaves the model untouched
    (and :meth:`Document.edit` records no undo step).

    Returns
    -------
    bool
        ``False`` when ``new`` equals ``old`` (nothing to do).

    Raises
    ------
    ModelError
        If ``old`` is not a selection or is ``"all"``, or ``new`` cannot be taken (see
        :func:`check_new_selection_name`).
    """
    if old == ALL_SELECTION:
        raise ModelError(f"the selection {ALL_SELECTION!r} cannot be renamed")
    if old not in model.selections:
        raise ModelError(f"there is no selection {old!r}")
    if new.strip() == old:
        return False
    new = check_new_selection_name(model, new)
    refs = selection_refs(model, old)
    for region in model.regions:  # an unnamed part keeps the name it was shown with
        if region.selection == old and hasattr(region, "name") and not region.name:
            region.name = old
    for ref in refs:
        if ref.kind == "attr":
            setattr(ref.container, str(ref.key), new)
        elif ref.kind == "item":
            ref.container[ref.key] = new  # type: ignore[index]
        else:
            _replace_key(ref.container, old, new)  # type: ignore[arg-type]
    model.selections[old].name = new
    _replace_key(model.selections, old, new)
    return True


def delete_selection(model: Model, name: str) -> None:
    """Delete a selection that nothing uses.

    Raises
    ------
    ModelError
        If it is ``"all"``, does not exist, or is still used (the message names the
        users).
    """
    if name == ALL_SELECTION:
        raise ModelError(f"the selection {ALL_SELECTION!r} cannot be deleted")
    if name not in model.selections:
        raise ModelError(f"there is no selection {name!r}")
    users = selection_users(model, name)
    if users:
        names = ", ".join(u.label for u in users)
        raise ModelError(f"the selection {name!r} is used by {names}")
    del model.selections[name]
