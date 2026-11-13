"""Replays a model's geometry operations in gmsh (Data §4).

``build(model)`` runs every :class:`~thermalfea.model.geometry_ops.GeometryOp` in order
with the OpenCASCADE kernel and returns a :class:`BuiltGeometry`. The gmsh model stays
alive in the :class:`~thermalfea.geometry.gmsh_session.GmshSession` for the mesher.

Each operation class has a handler registered with :func:`handler`, so a new operation
(for example a 3D extrusion) is a new handler, not a change to the build loop.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType

from numpy import ndarray

from ..core.errors import GeometryError
from ..model import geometry_ops as ops
from ..model.model import Model
from ..model.selections import Fingerprint
from .gmsh_session import GmshSession

log = logging.getLogger(__name__)

DimTag = tuple[int, int]

POINT_DIM, CURVE_DIM, SURFACE_DIM = 0, 1, 2
_MIN_SPLINE_POINTS = 2
_MIN_POLYGON_VERTICES = 3


@dataclass
class BuiltGeometry:
    """Result of building a model's geometry.

    Attributes
    ----------
    serial : int
        Identifies the gmsh model this object describes (``GmshSession.serial``).
    op_entities : dict of str to list of (dim, tag)
        The entities each geometry operation currently owns.
    surfaces, curves, points : dict of int to Fingerprint
        Final entities by tag, with their fingerprints.
    curve_surfaces : dict of int to list of int
        For each curve, the tags of the surfaces it bounds (two on an interface).
    curve_polylines : dict of int to ndarray, shape (n, 3)
        Sampled points along each curve [m], for display.
    bbox : tuple of 6 float
        ``xmin, ymin, zmin, xmax, ymax, zmax`` of the whole geometry [m].
    """

    serial: int
    op_entities: dict[str, list[DimTag]] = field(default_factory=dict)
    surfaces: dict[int, Fingerprint] = field(default_factory=dict)
    curves: dict[int, Fingerprint] = field(default_factory=dict)
    points: dict[int, Fingerprint] = field(default_factory=dict)
    curve_surfaces: dict[int, list[int]] = field(default_factory=dict)
    curve_polylines: dict[int, ndarray] = field(default_factory=dict)
    bbox: tuple[float, float, float, float, float, float] = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    @property
    def diagonal(self) -> float:
        """Length of the bounding-box diagonal [m]."""
        half = len(self.bbox) // 2
        return sum((self.bbox[half + i] - self.bbox[i]) ** 2 for i in range(half)) ** 0.5

    def entities(self, dim: int) -> dict[int, Fingerprint]:
        """Return the final entities of one dimension, by tag."""
        return {POINT_DIM: self.points, CURVE_DIM: self.curves, SURFACE_DIM: self.surfaces}[dim]


class BuildContext:
    """State shared by the operation handlers during one build."""

    def __init__(self, gmsh: ModuleType) -> None:
        self.gmsh = gmsh
        self.occ = gmsh.model.occ
        self.op_entities: dict[str, list[DimTag]] = {}
        #: end-point tags of the curves made by curve operations, for ordering loops
        self.curve_ends: dict[int, tuple[int, int]] = {}

    def entities(self, op_id: str) -> list[DimTag]:
        """Entities owned by an earlier operation."""
        try:
            return self.op_entities[op_id]
        except KeyError:
            raise GeometryError(f"refers to unknown or later operation {op_id!r}") from None

    def tags(self, op_ids: list[str], dim: int) -> list[int]:
        """Tags of the entities of dimension ``dim`` owned by the given operations."""
        out: list[int] = []
        for op_id in op_ids:
            found = [t for d, t in self.entities(op_id) if d == dim]
            if not found:
                raise GeometryError(f"operation {op_id!r} has no entity of dimension {dim}")
            out.extend(found)
        return out

    def single(self, op_id: str, dim: int) -> int:
        """Tag of the one entity of dimension ``dim`` owned by an operation."""
        found = self.tags([op_id], dim)
        if len(found) != 1:
            raise GeometryError(f"operation {op_id!r} has {len(found)} entities, expected one")
        return found[0]


    def ordered_loop(self, curve_tags: list[int]) -> list[int]:
        """Return the curves of a closed loop in chain order.

        gmsh needs the curves of a loop in the order they connect. Curves whose end
        points are known are chained by shared points; if any is unknown the given order
        is kept.
        """
        if not curve_tags or any(t not in self.curve_ends for t in curve_tags):
            return list(curve_tags)
        remaining = list(curve_tags)
        first = remaining.pop(0)
        chain = [first]
        start, end = self.curve_ends[first]
        while remaining:
            for tag in remaining:
                a, b = self.curve_ends[tag]
                if end in (a, b):
                    end = b if a == end else a
                    chain.append(tag)
                    remaining.remove(tag)
                    break
            else:
                raise GeometryError("the curves do not form a single closed loop")
        if end != start:
            raise GeometryError("the curves do not form a closed loop")
        return chain


Handler = Callable[[BuildContext, ops.GeometryOp], list[DimTag]]
_HANDLERS: dict[type, Handler] = {}


def handler(cls: type) -> Callable[[Handler], Handler]:
    """Register the function that builds operations of class ``cls``."""

    def register(fn: Handler) -> Handler:
        _HANDLERS[cls] = fn
        return fn

    return register


# ---------------------------------------------------------------------------- primitives


@handler(ops.Point)
def _point(ctx: BuildContext, op: ops.Point) -> list[DimTag]:
    return [(POINT_DIM, ctx.occ.addPoint(op.x, op.y, 0.0))]


@handler(ops.Line)
def _line(ctx: BuildContext, op: ops.Line) -> list[DimTag]:
    p1, p2 = ctx.single(op.p1, POINT_DIM), ctx.single(op.p2, POINT_DIM)
    tag = ctx.occ.addLine(p1, p2)
    ctx.curve_ends[tag] = (p1, p2)
    return [(CURVE_DIM, tag)]


@handler(ops.Arc)
def _arc(ctx: BuildContext, op: ops.Arc) -> list[DimTag]:
    start, end = ctx.single(op.p_start, POINT_DIM), ctx.single(op.p_end, POINT_DIM)
    tag = ctx.occ.addCircleArc(start, ctx.single(op.p_center, POINT_DIM), end)
    ctx.curve_ends[tag] = (start, end)
    return [(CURVE_DIM, tag)]


@handler(ops.Spline)
def _spline(ctx: BuildContext, op: ops.Spline) -> list[DimTag]:
    if len(op.points) < _MIN_SPLINE_POINTS:
        raise GeometryError("a spline needs at least two points")
    points = ctx.tags(op.points, POINT_DIM)
    tag = ctx.occ.addSpline(points)
    ctx.curve_ends[tag] = (points[0], points[-1])
    return [(CURVE_DIM, tag)]


@handler(ops.Rectangle)
def _rectangle(ctx: BuildContext, op: ops.Rectangle) -> list[DimTag]:
    if op.width <= 0.0 or op.height <= 0.0:
        raise GeometryError("rectangle width and height must be positive")
    tag = ctx.occ.addRectangle(
        op.x, op.y, 0.0, op.width, op.height, roundedRadius=op.corner_radius
    )
    return [(SURFACE_DIM, tag)]


@handler(ops.Circle)
def _circle(ctx: BuildContext, op: ops.Circle) -> list[DimTag]:
    if op.radius <= 0.0:
        raise GeometryError("circle radius must be positive")
    return [(SURFACE_DIM, ctx.occ.addDisk(op.xc, op.yc, 0.0, op.radius, op.radius))]


@handler(ops.Polygon)
def _polygon(ctx: BuildContext, op: ops.Polygon) -> list[DimTag]:
    n = len(op.vertices)
    if n < _MIN_POLYGON_VERTICES:
        raise GeometryError("a polygon needs at least three vertices")
    points = [ctx.occ.addPoint(x, y, 0.0) for x, y in op.vertices]
    lines = [ctx.occ.addLine(points[i], points[(i + 1) % n]) for i in range(n)]
    loop = ctx.occ.addCurveLoop(lines)
    return [(SURFACE_DIM, ctx.occ.addPlaneSurface([loop]))]


@handler(ops.SurfaceFromCurves)
def _surface_from_curves(ctx: BuildContext, op: ops.SurfaceFromCurves) -> list[DimTag]:
    loops = [
        ctx.occ.addCurveLoop(ctx.ordered_loop(ctx.tags(curves, CURVE_DIM)))
        for curves in (op.curves, *op.holes)
    ]
    return [(SURFACE_DIM, ctx.occ.addPlaneSurface(loops))]


# --------------------------------------------------------------------------------- build


def replay(ctx: BuildContext, model: Model) -> None:
    """Run every geometry operation of the model, filling ``ctx.op_entities``."""
    for op in model.geometry:
        if op.id in ctx.op_entities:
            raise GeometryError(f"duplicate geometry operation id {op.id!r}")
        fn = _HANDLERS.get(type(op))
        if fn is None:
            raise GeometryError(
                f"operation {op.id!r}: {type(op).__name__} is not supported by the builder"
            )
        try:
            ctx.op_entities[op.id] = fn(ctx, op)
        except GeometryError as exc:
            raise GeometryError(f"operation {op.id!r} ({type(op).__name__}): {exc}") from None
        except Exception as exc:  # gmsh raises plain Exception
            raise GeometryError(
                f"operation {op.id!r} ({type(op).__name__}) failed in gmsh: {exc}"
            ) from exc


def build(model: Model) -> BuiltGeometry:
    """Build the geometry of a model in gmsh.

    Parameters
    ----------
    model : Model
        Its ``geometry`` list is replayed in order.

    Returns
    -------
    BuiltGeometry
        Describes the gmsh model, which stays in the session for meshing.

    Raises
    ------
    GeometryError
        If an operation is invalid or gmsh fails; the message names the operation.
    """
    session = GmshSession.get()
    with session.fresh_model(model.name or "model") as gmsh:
        ctx = BuildContext(gmsh)
        replay(ctx, model)
        try:
            ctx.occ.synchronize()
        except Exception as exc:
            raise GeometryError(f"gmsh could not synchronise the geometry: {exc}") from exc
        return BuiltGeometry(serial=session.serial, op_entities=ctx.op_entities)
