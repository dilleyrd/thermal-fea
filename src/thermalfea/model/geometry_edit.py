"""Pure helpers of the geometry tools (Plan M8.5): no Qt, no gmsh.

* :class:`GridSnap` rounds picked coordinates to a grid.
* :func:`ops_for_entities` maps viewport entities back to the operations that own them.
* :func:`validate_op` and :func:`dependents` check an operation against the history.
* :class:`Placement` turns successive clicks into the fields of an operation.

Entity ownership
----------------
``BuiltGeometry.op_entities`` lists, for every operation, the final entities it owns; one
entity can belong to several operations (a translated rectangle is owned by the rectangle
and the transform; the pieces of two overlapping rectangles by both). The *latest* owner
in the history is the one that describes the entity now, so that is the one reported.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..core.errors import ModelError
from . import geometry_ops as g

#: Operation classes that produce surfaces (or surface-like results).
SURFACE_OPS: tuple[type, ...] = (
    g.Rectangle, g.Circle, g.Polygon, g.SurfaceFromCurves, g.Boolean, g.Transform, g.ImportFile,
)  # fmt: skip
POINT_OPS: tuple[type, ...] = (g.Point,)
CURVE_OPS: tuple[type, ...] = (g.Line, g.Arc, g.Spline)
#: Every operation that owns entities (everything but :class:`Delete`).
ANY_OPS: tuple[type, ...] = (*POINT_OPS, *CURVE_OPS, *SURFACE_OPS)

#: ``(operation class, field)`` -> operation classes the referenced ids must belong to.
REF_RULES: dict[tuple[type, str], tuple[type, ...]] = {
    (g.Line, "p1"): POINT_OPS,
    (g.Line, "p2"): POINT_OPS,
    (g.Arc, "p_start"): POINT_OPS,
    (g.Arc, "p_center"): POINT_OPS,
    (g.Arc, "p_end"): POINT_OPS,
    (g.Spline, "points"): POINT_OPS,
    (g.SurfaceFromCurves, "curves"): CURVE_OPS,
    (g.SurfaceFromCurves, "holes"): CURVE_OPS,
    (g.Boolean, "objects"): SURFACE_OPS,
    (g.Boolean, "tools"): SURFACE_OPS,
    (g.Transform, "targets"): ANY_OPS,
    (g.Delete, "targets"): ANY_OPS,
}

#: Parameters (name, label) each transform kind needs; lengths in metres, angle in radians.
TRANSFORM_PARAMS: dict[str, tuple[tuple[str, str], ...]] = {
    "translate": (("dx", "Dx [m]"), ("dy", "Dy [m]")),
    "rotate": (("angle", "Angle [rad]"), ("cx", "Centre x [m]"), ("cy", "Centre y [m]")),
    "mirror": (("x0", "Line x0 [m]"), ("y0", "Line y0 [m]"), ("x1", "Line x1 [m]"),
               ("y1", "Line y1 [m]")),
    "scale": (("factor", "Factor"), ("cx", "Centre x [m]"), ("cy", "Centre y [m]")),
}  # fmt: skip


@dataclass
class GridSnap:
    """Rounds picked points to a square grid.

    Parameters
    ----------
    spacing : float
        Grid spacing [m]; must be positive.
    enabled : bool
        When ``False`` :meth:`snap` returns its input unchanged.
    """

    spacing: float = 0.01
    enabled: bool = False

    def __post_init__(self) -> None:
        if not self.spacing > 0.0:
            raise ModelError("the grid spacing must be positive")

    def snap(self, x: float, y: float) -> tuple[float, float]:
        """Return ``(x, y)`` moved to the nearest grid point (unchanged when disabled)."""
        if not self.enabled:
            return float(x), float(y)
        s = self.spacing
        return round(round(x / s) * s, 12) + 0.0, round(round(y / s) * s, 12) + 0.0


def ops_for_entities(
    order: Sequence[str],
    op_entities: Mapping[str, Sequence[tuple[int, int]]],
    dim: int,
    tags: Iterable[int],
    allowed: Iterable[str] | None = None,
) -> list[str]:
    """Operation ids that own the given entities, latest owner of each entity.

    Parameters
    ----------
    order : sequence of str
        Operation ids in history order.
    op_entities : mapping
        ``BuiltGeometry.op_entities``: operation id -> ``(dim, tag)`` entities.
    dim : int
        Dimension of the selected entities.
    tags : iterable of int
        Their gmsh tags.
    allowed : iterable of str, optional
        Only these operation ids may be reported.

    Returns
    -------
    list of str
        Distinct ids in history order. An entity owned by no allowed operation adds none.
    """
    wanted = {(int(dim), int(t)) for t in tags}
    ok = None if allowed is None else set(allowed)
    latest: dict[tuple[int, int], str] = {}
    for op_id in order:
        if ok is not None and op_id not in ok:
            continue
        for entity in op_entities.get(op_id, ()):
            if (int(entity[0]), int(entity[1])) in wanted:
                latest[(int(entity[0]), int(entity[1]))] = op_id
    found = set(latest.values())
    return [op_id for op_id in order if op_id in found]


def refs_of(op: g.GeometryOp) -> list[str]:
    """Ids of the operations ``op`` refers to (with repeats removed, in field order)."""
    out: list[str] = []
    for (cls, name), _allowed in REF_RULES.items():
        if not isinstance(op, cls):
            continue
        value = getattr(op, name)
        flat = [value] if isinstance(value, str) else _flatten(value)
        out.extend(i for i in flat if i not in out)
    return out


def _flatten(value: Any) -> list[str]:
    out: list[str] = []
    for item in value:
        out.extend([item] if isinstance(item, str) else _flatten(item))
    return out


def dependents(ops: Sequence[g.GeometryOp], op_id: str) -> list[str]:
    """Ids of the operations that refer to ``op_id``."""
    return [op.id for op in ops if op.id != op_id and op_id in refs_of(op)]


def _replace_ref(value: Any, old: str, new: str) -> Any:
    """``value`` (an id, a list of ids or a list of id lists) with ``old`` replaced."""
    if isinstance(value, str):
        return new if value == old else value
    return [_replace_ref(item, old, new) for item in value]


def rename_operation(model: Any, old_id: str, new_id: str) -> bool:
    """Rename a geometry operation and every reference to it (Data §4, M11.63).

    Every reference field of :data:`REF_RULES` is rewritten in place, keeping repeats,
    order and nested hole loops. Every check runs first, so a refusal changes nothing.

    Parameters
    ----------
    model : Model
    old_id, new_id : str

    Returns
    -------
    bool
        ``False`` when the new id equals the old one.

    Raises
    ------
    ModelError
        If ``old_id`` is not an operation, or ``new_id`` is blank or already used.
    """
    new_id = new_id.strip()
    ids = [op.id for op in model.geometry]
    if old_id not in ids:
        raise ModelError(f"there is no geometry operation {old_id!r}")
    if new_id == old_id:
        return False
    if not new_id:
        raise ModelError("a geometry operation id cannot be empty")
    if new_id in ids:
        raise ModelError(f"the geometry operation id {new_id!r} is already used")
    for op in model.geometry:
        for (cls, name), _allowed in REF_RULES.items():
            if isinstance(op, cls):
                setattr(op, name, _replace_ref(getattr(op, name), old_id, new_id))
        if op.id == old_id:
            op.id = new_id
    return True


#: A representative class of each kind, used to match a transform against ``allowed`` classes.
_KIND_CLASS: dict[str, type] = {"point": g.Point, "curve": g.Line, "surface": g.Rectangle}


def op_kind(op: g.GeometryOp, history: Sequence[g.GeometryOp]) -> str:
    """Kind of entity an operation yields: ``"point"``, ``"curve"`` or ``"surface"``.

    A :class:`~thermalfea.model.geometry_ops.Transform` has the kind of its targets: a point
    when all its targets are points, a curve when all are curves (looking through earlier
    transforms), otherwise a surface. Other operations have the kind of their class.

    Parameters
    ----------
    op : GeometryOp
    history : sequence of GeometryOp
        The operations before ``op`` (the targets of a transform are looked up here).
    """
    return _kind(op, {e.id: e for e in history}, set())


def _kind(op: g.GeometryOp, by_id: Mapping[str, g.GeometryOp], seen: set[str]) -> str:
    if isinstance(op, g.Transform) and op.targets and op.id not in seen:
        seen = seen | {op.id}
        kinds = {
            _kind(by_id[t], by_id, seen) if t in by_id else "surface" for t in op.targets
        }
        return kinds.pop() if len(kinds) == 1 else "surface"
    if isinstance(op, POINT_OPS):
        return "point"
    if isinstance(op, CURVE_OPS):
        return "curve"
    return "surface"


def _fits(op: g.GeometryOp, by_id: Mapping[str, g.GeometryOp], allowed: tuple[type, ...]) -> bool:
    """Whether ``op`` is of one of the ``allowed`` classes, a transform by its kind."""
    if isinstance(op, g.Transform):
        return issubclass(_KIND_CLASS[_kind(op, by_id, set())], allowed)
    return isinstance(op, allowed)


def candidate_ids(
    earlier: Sequence[g.GeometryOp], allowed: tuple[type, ...]
) -> list[str]:
    """Ids of the earlier operations whose class is in ``allowed``.

    A transform counts by the kind of its targets (see :func:`op_kind`).
    """
    out: list[str] = []
    by_id: dict[str, g.GeometryOp] = {}
    for op in earlier:
        by_id[op.id] = op
        if _fits(op, by_id, allowed):
            out.append(op.id)
    return out


def _positive(value: float, what: str) -> None:
    if not value > 0.0:
        raise ModelError(f"{what} must be positive")


def validate_op(
    op: g.GeometryOp, earlier: Sequence[g.GeometryOp], check_files: bool = True
) -> None:
    """Check an operation against the operations before it.

    Parameters
    ----------
    op : GeometryOp
        The new or edited operation.
    earlier : sequence of GeometryOp
        The operations that precede it in the history.
    check_files : bool
        Require an imported file to exist.

    Raises
    ------
    ModelError
        With a message for the user: duplicate id, unknown or wrong-kind reference,
        too few items, non-positive size, missing file.
    """
    if any(e.id == op.id for e in earlier):
        raise ModelError(f"the id {op.id!r} is already used")
    by_id = {e.id: e for e in earlier}
    for (cls, name), allowed in REF_RULES.items():
        if not isinstance(op, cls):
            continue
        value = getattr(op, name)
        for ref in [value] if isinstance(value, str) else _flatten(value):
            if ref not in by_id:
                raise ModelError(f"{name}: there is no earlier operation {ref!r}")
            if not _fits(by_id[ref], by_id, allowed):
                kinds = "/".join(c.__name__.lower() for c in allowed)
                raise ModelError(f"{name}: {ref!r} is a {type(by_id[ref]).__name__}, not a {kinds}")
    _check_sizes(op, check_files)


def _check_sizes(op: g.GeometryOp, check_files: bool) -> None:
    if isinstance(op, g.Rectangle):
        _positive(op.width, "the width")
        _positive(op.height, "the height")
        if op.corner_radius < 0.0:
            raise ModelError("the corner radius cannot be negative")
    elif isinstance(op, g.Circle):
        _positive(op.radius, "the radius")
    elif isinstance(op, g.Polygon) and len(op.vertices) < 3:  # noqa: PLR2004
        raise ModelError("a polygon needs at least three vertices")
    elif isinstance(op, g.Spline) and len(op.points) < 2:  # noqa: PLR2004
        raise ModelError("a spline needs at least two points")
    elif isinstance(op, g.SurfaceFromCurves) and not op.curves:
        raise ModelError("give the curves of the outer loop")
    elif isinstance(op, g.Boolean):
        if not op.objects:
            raise ModelError("a boolean needs at least one object")
        if not op.tools:
            raise ModelError("a boolean needs at least one tool")
        if set(op.objects) & set(op.tools):
            raise ModelError("an operation cannot be both object and tool")
    elif isinstance(op, (g.Transform, g.Delete)):
        if not op.targets:
            raise ModelError("give at least one target")
        if isinstance(op, g.Transform):
            _check_transform(op)
    elif isinstance(op, g.ImportFile):
        _positive(op.scale, "the scale")
        if not op.path:
            raise ModelError("give a file")
        if check_files and not os.path.isfile(op.path):
            raise ModelError(f"file not found: {op.path}")


def _check_transform(op: g.Transform) -> None:
    missing = [k for k, _ in TRANSFORM_PARAMS[op.kind] if k not in op.params]
    if missing:
        raise ModelError(f"{op.kind}: missing parameter(s) {', '.join(missing)}")
    if op.kind == "scale":
        _positive(op.params["factor"], "the scale factor")
    if op.kind == "mirror" and (op.params["x0"], op.params["y0"]) == (
        op.params["x1"],
        op.params["y1"],
    ):
        raise ModelError("the two points of the mirror line coincide")


def import_format(path: str | Path) -> str | None:
    """File format (``"step"``, ``"brep"``, ``"dxf"``) from a file name, or ``None``."""
    suffix = Path(path).suffix.lower().lstrip(".")
    return {"stp": "step", "step": "step", "brep": "brep", "dxf": "dxf"}.get(suffix)


class Placement:
    """Turns successive clicks into the fields of one kind of operation.

    Parameters
    ----------
    kind : {"point", "rectangle", "circle", "polygon", "translate", "rotate", "scale", \
"mirror"}
        What is being placed.

    Notes
    -----
    * point: the latest click gives ``x, y``.
    * rectangle: the first click is a corner, the second the opposite corner; the fields
      are the lower-left corner and the size. A third click starts again.
    * circle: first click the centre, second a point on the circle (radius = distance).
    * polygon: every click appends a vertex; :meth:`reset` starts again.
    * translate: from-click then to-click give ``dx, dy``.
    * rotate, scale: the latest click gives the centre ``cx, cy``.
    * mirror: two clicks give the mirror line ``x0, y0, x1, y1``.
    """

    KINDS = ("point", "rectangle", "circle", "polygon", "translate", "rotate", "scale", "mirror")
    _COUNT = {"rectangle": 2, "circle": 2, "translate": 2, "mirror": 2}

    def __init__(self, kind: str) -> None:
        if kind not in self.KINDS:
            raise ModelError(f"cannot place {kind!r} by clicking")
        self.kind = kind
        self.picks: list[tuple[float, float]] = []

    def reset(self) -> None:
        """Forget the clicks."""
        self.picks = []

    def pick(self, x: float, y: float) -> dict[str, Any]:
        """Register a click and return the fields it determines.

        Parameters
        ----------
        x, y : float
            The (already snapped) point [m].

        Returns
        -------
        dict
            Field name -> value, as far as the clicks so far determine them.
        """
        limit = self._COUNT.get(self.kind)
        if limit is not None and len(self.picks) >= limit:
            self.picks = []
        self.picks.append((float(x), float(y)))
        (x0, y0), (x1, y1) = self.picks[0], self.picks[-1]
        two = len(self.picks) == 2  # noqa: PLR2004
        k = self.kind
        if k == "point":
            return {"x": x1, "y": y1}  # the latest click
        if k == "rectangle":
            if not two:
                return {"x": x0, "y": y0}
            return {"x": min(x0, x1), "y": min(y0, y1), "width": abs(x1 - x0),
                    "height": abs(y1 - y0)}  # fmt: skip
        if k == "circle":
            out: dict[str, Any] = {"xc": x0, "yc": y0}
            if two:
                out["radius"] = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            return out
        if k == "polygon":
            return {"vertices": list(self.picks)}
        if k == "translate":
            return {"dx": x1 - x0, "dy": y1 - y0} if two else {}
        if k in ("rotate", "scale"):
            return {"cx": x1, "cy": y1}
        return {"x0": x0, "y0": y0, "x1": x1, "y1": y1} if two else {"x0": x0, "y0": y0}
