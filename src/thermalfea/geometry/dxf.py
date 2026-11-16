"""Import of DXF drawings: closed outlines become surfaces, inner outlines become holes.

The module has two layers.

* The *pure* layer reads the drawing with ``ezdxf`` (imported lazily, an optional dependency)
  into simple immutable segment records (:class:`Line`, :class:`Arc`, :class:`Circle`,
  :class:`Spline`), joins their end points, chains them into closed :class:`Loop` objects
  and works out which loop lies inside which (:func:`nest_loops`). It does not use gmsh.
* The *OCC* layer (:func:`create_surfaces`) turns the loops into OpenCASCADE curves, curve
  loops and plane surfaces of the model being built.

Supported entities: LINE, ARC, CIRCLE, LWPOLYLINE (bulges become arcs) and SPLINE. All other
entity types are ignored with a warning. Everything must lie in the plane z = 0 once the
entity coordinate systems (for example mirrored arcs with extrusion (0, 0, -1)) are applied.
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

from ..core.errors import GeometryError

log = logging.getLogger(__name__)

Point = tuple[float, float]

SURFACE_DIM = 2  # dimension of the entities a drawing is turned into

#: End points closer than this fraction of the largest in-plane extent of the drawing are
#: the same point (relative tolerance, the same fraction as ``importers.PLANE_TOL``).
JOIN_TOL = 1e-6

_ARC_STEP = math.pi / 32.0  # angular step of the polygon used for the nesting test
_CIRCLE_SAMPLES = 128
_MIN_ARC_SAMPLES = 4
_MAX_ARC_PIECE = 2.0 * math.pi / 3.0  # OCC arcs must stay well below pi
_FULL_TURN = 2.0 * math.pi
_ARC_AS_CIRCLE = math.pi  # a closed arc at least this long is kept as a loop of its own
_BULGE_MIN = 1e-12
_EXTRUSION_TOL = 1e-9
_MIN_NEIGHBOURS = 2  # a point where more than two segment ends meet is a branch
_MIN_FIT_POINTS = 2


# ------------------------------------------------------------------------------ segments


@dataclass(frozen=True)
class Line:
    """Straight segment from ``p0`` to ``p1`` [m]."""

    p0: Point
    p1: Point

    @property
    def start(self) -> Point:
        return self.p0

    @property
    def end(self) -> Point:
        return self.p1

    def reversed(self) -> Line:
        return Line(self.p1, self.p0)

    def samples(self) -> list[Point]:
        return [self.p0, self.p1]


@dataclass(frozen=True)
class Arc:
    """Circular arc about ``center`` from ``p0`` to ``p1``, ``sweep`` radians long [m, rad].

    ``ccw`` is the direction of travel seen in the x-y plane (counter-clockwise if true).
    """

    center: Point
    radius: float
    p0: Point
    p1: Point
    ccw: bool
    sweep: float

    @property
    def start(self) -> Point:
        return self.p0

    @property
    def end(self) -> Point:
        return self.p1

    def reversed(self) -> Arc:
        return Arc(self.center, self.radius, self.p1, self.p0, not self.ccw, self.sweep)

    def point_at(self, fraction: float) -> Point:
        """Point at ``fraction`` (0 to 1) of the sweep from ``p0``."""
        a0 = math.atan2(self.p0[1] - self.center[1], self.p0[0] - self.center[0])
        a = a0 + (fraction * self.sweep if self.ccw else -fraction * self.sweep)
        return (
            self.center[0] + self.radius * math.cos(a),
            self.center[1] + self.radius * math.sin(a),
        )

    def samples(self) -> list[Point]:
        n = max(_MIN_ARC_SAMPLES, math.ceil(self.sweep / _ARC_STEP))
        return [self.p0, *(self.point_at(i / n) for i in range(1, n)), self.p1]


@dataclass(frozen=True)
class Circle:
    """Full circle [m]; a loop on its own."""

    center: Point
    radius: float

    def samples(self) -> list[Point]:
        return [
            (
                self.center[0] + self.radius * math.cos(_FULL_TURN * i / _CIRCLE_SAMPLES),
                self.center[1] + self.radius * math.sin(_FULL_TURN * i / _CIRCLE_SAMPLES),
            )
            for i in range(_CIRCLE_SAMPLES)
        ]


@dataclass(frozen=True)
class Spline:
    """A B-spline or a spline through fit points.

    ``kind == "bspline"``: ``points`` are the control points of a clamped B-spline of
    ``degree`` with the full ``knots`` vector (and ``weights`` if rational); the curve starts
    at the first and ends at the last control point. ``kind == "fit"``: ``points`` are
    interpolated. ``polyline`` is a sampled copy of the curve, used for the nesting test.
    """

    kind: Literal["bspline", "fit"]
    points: tuple[Point, ...]
    degree: int
    knots: tuple[float, ...]
    weights: tuple[float, ...] | None
    polyline: tuple[Point, ...]

    @property
    def start(self) -> Point:
        return self.points[0]

    @property
    def end(self) -> Point:
        return self.points[-1]

    def reversed(self) -> Spline:
        total = self.knots[0] + self.knots[-1] if self.knots else 0.0
        knots = tuple(total - k for k in reversed(self.knots))
        weights = None if self.weights is None else tuple(reversed(self.weights))
        return Spline(
            self.kind,
            tuple(reversed(self.points)),
            self.degree,
            knots,
            weights,
            tuple(reversed(self.polyline)),
        )

    def samples(self) -> list[Point]:
        return list(self.polyline)


Segment = Line | Arc | Spline


@dataclass(frozen=True)
class Loop:
    """A closed chain of segments, each oriented along the direction of travel.

    ``nodes[i]`` is the index (into :attr:`Drawing.points`) of the start of ``items[i]``;
    the item ends at ``nodes[i + 1]`` (cyclically). A lone :class:`Circle` has no nodes.
    """

    items: tuple[Segment | Circle, ...]
    nodes: tuple[int, ...]

    def polygon(self) -> list[Point]:
        """Sampled outline, for containment tests."""
        out: list[Point] = []
        for item in self.items:
            out.extend(item.samples()[:-1] if not isinstance(item, Circle) else item.samples())
        return out


@dataclass(frozen=True)
class Drawing:
    """Joined drawing: shared ``points`` [m] and closed ``loops``."""

    points: tuple[Point, ...]
    loops: tuple[Loop, ...]


@dataclass(frozen=True)
class Region:
    """One surface: index of its outer loop and the indices of its hole loops."""

    outer: int
    holes: tuple[int, ...]


# ---------------------------------------------------------------------------- reading


def _import_ezdxf() -> Any:
    try:
        import ezdxf
    except ImportError as exc:
        raise GeometryError(
            "DXF import needs the optional package 'ezdxf'. Install it with "
            "'pip install ezdxf' (or 'pip install thermalfea[dxf]') and try again"
        ) from exc
    return ezdxf


@dataclass
class _Reader:
    """Collects segments of one drawing; ``scale`` multiplies every length."""

    scale: float
    name: str
    segments: list[Segment | Circle]
    z_max: float = 0.0

    def xy(self, p: Any) -> Point:
        self.z_max = max(self.z_max, abs(float(p[2])) * self.scale)
        return (float(p[0]) * self.scale, float(p[1]) * self.scale)

    def plane_ocs(self, entity: Any, kind: str) -> tuple[Any, bool]:
        """OCS of an entity whose plane must be parallel to z = 0; second value: mirrored."""
        from ezdxf.math import OCS

        ex = entity.dxf.extrusion
        if abs(ex[0]) > _EXTRUSION_TOL or abs(ex[1]) > _EXTRUSION_TOL:
            raise GeometryError(
                f"{self.name}: a {kind} lies in a plane that is not parallel to z = 0 "
                f"(extrusion direction {tuple(round(float(c), 6) for c in ex)}). Only a "
                "drawing in the plane z = 0 can be imported"
            )
        return OCS(ex), float(ex[2]) < 0.0

    def add_line(self, e: Any) -> None:
        self.segments.append(Line(self.xy(e.dxf.start), self.xy(e.dxf.end)))

    def add_circle(self, e: Any) -> None:
        ocs, _ = self.plane_ocs(e, "CIRCLE")
        centre = self.xy(ocs.to_wcs(e.dxf.center))
        self.segments.append(Circle(centre, float(e.dxf.radius) * self.scale))

    def add_arc(self, e: Any) -> None:
        ocs, mirrored = self.plane_ocs(e, "ARC")
        radius = float(e.dxf.radius)
        a0, a1 = math.radians(float(e.dxf.start_angle)), math.radians(float(e.dxf.end_angle))
        sweep = (a1 - a0) % _FULL_TURN
        c = e.dxf.center
        centre = self.xy(ocs.to_wcs(c))

        def end_at(angle: float) -> Point:
            local = (c[0] + radius * math.cos(angle), c[1] + radius * math.sin(angle), c[2])
            return self.xy(ocs.to_wcs(local))

        if sweep == 0.0:
            self.segments.append(Circle(centre, radius * self.scale))
        else:
            self.segments.append(
                Arc(centre, radius * self.scale, end_at(a0), end_at(a1), not mirrored, sweep)
            )

    def add_lwpolyline(self, e: Any) -> None:
        from ezdxf.math import OCS

        ex = e.dxf.extrusion
        ocs = OCS(ex)
        elevation = float(e.dxf.elevation)
        vertices = [(float(x), float(y), float(b)) for x, y, b in e.get_points("xyb")]
        n = len(vertices)
        count = n if e.closed else n - 1
        for i in range(count):
            x0, y0, bulge = vertices[i]
            x1, y1, _ = vertices[(i + 1) % n]
            p0 = self.xy(ocs.to_wcs((x0, y0, elevation)))
            p1 = self.xy(ocs.to_wcs((x1, y1, elevation)))
            if abs(bulge) < _BULGE_MIN:
                self.segments.append(Line(p0, p1))
                continue
            _, mirrored = self.plane_ocs(e, "LWPOLYLINE with bulges")
            chord = math.hypot(x1 - x0, y1 - y0)
            if chord == 0.0:
                continue
            radius = chord * (1.0 + bulge * bulge) / (4.0 * abs(bulge))
            sagitta = abs(bulge) * chord / 2.0
            side = math.copysign(radius - sagitta, bulge)  # left of the chord for bulge > 0
            cx = (x0 + x1) / 2.0 - (y1 - y0) / chord * side
            cy = (y0 + y1) / 2.0 + (x1 - x0) / chord * side
            centre = self.xy(ocs.to_wcs((cx, cy, elevation)))
            sweep = 4.0 * math.atan(abs(bulge))
            self.segments.append(
                Arc(centre, radius * self.scale, p0, p1, (bulge > 0.0) != mirrored, sweep)
            )

    def add_spline(self, e: Any) -> None:
        if e.control_point_count():
            self.segments.extend(self.bspline(e))
        elif e.fit_point_count() >= _MIN_FIT_POINTS:
            pts = [self.xy(p) for p in e.fit_points]
            if e.closed and math.dist(pts[0], pts[-1]) > 0.0:
                pts.append(pts[0])
            self.segments.append(Spline("fit", tuple(pts), 3, (), None, tuple(pts)))
        else:
            raise GeometryError(f"{self.name}: a SPLINE has neither control nor fit points")

    def bspline(self, e: Any) -> list[Spline]:
        """Clamped B-spline(s) of a SPLINE entity (two halves if its ends coincide).

        A curve whose first and last control points are the same OCC point would be taken
        by gmsh for a periodic B-spline, so a self-closing spline is split in two.
        """
        from ezdxf.math import BSpline

        tool = e.construction_tool()
        try:
            order, count = tool.order, tool.count
            knots0 = [float(k) for k in tool.knots()]
            ctrl = list(tool.control_points)
            weights = [float(w) for w in tool.weights()] if tool.is_rational else None
            shifted = [k - knots0[0] for k in knots0]
            ctrl, knots, weights = _clamp(ctrl, shifted, weights, order, count)
            curve = BSpline(ctrl, order, knots, weights)
            parts = [curve]
            span = max(np.ptp(np.array([tuple(p)[:2] for p in ctrl]), axis=0))
            if (ctrl[0] - ctrl[-1]).magnitude <= JOIN_TOL * max(float(span), 1e-300):
                # ezdxf mishandles a split at an existing knot: cut inside the longest span
                spans = list(zip(knots, knots[1:], strict=False))
                span_a, span_b = max(spans, key=lambda ab: ab[1] - ab[0])
                parts = list(curve.split(0.5 * (span_a + span_b)))
            return [self.spline_record(c) for c in parts]
        except GeometryError:
            raise
        except Exception as exc:  # ezdxf raises assorted errors for malformed splines
            raise GeometryError(f"{self.name}: cannot use a SPLINE ({exc})") from exc

    def spline_record(self, curve: Any) -> Spline:
        knots = [float(k) for k in curve.knots()]
        ts = np.linspace(knots[0], knots[-1], max(32, 8 * curve.count))
        weights = [float(w) for w in curve.weights()] if curve.is_rational else None
        return Spline(
            "bspline",
            tuple(self.xy(p) for p in curve.control_points),
            curve.degree,
            tuple(knots),
            None if weights is None else tuple(weights),
            tuple(self.xy(p) for p in curve.points(ts)),
        )


def _clamp(
    ctrl: list[Any], knots: list[float], weights: list[float] | None, order: int, count: int
) -> tuple[list[Any], list[float], list[float] | None]:
    """Return the B-spline restricted to its valid domain, with clamped end knots.

    Periodic splines (uniform knots, control points repeated at the end) are cut at the
    ends of the parameter domain by inserting knots until the end knots have multiplicity
    ``order``; the control points and knots outside the domain are dropped.
    """
    from ezdxf.math import BSpline

    p = order - 1
    t0, t1 = knots[p], knots[count]
    eps = 1e-9 * max(t1 - t0, 1e-300)
    if t1 <= t0:
        raise GeometryError("a SPLINE has an empty parameter range")

    def mult(values: list[float], t: float) -> int:
        return sum(abs(k - t) <= eps for k in values)

    if mult(knots, t0) >= order and mult(knots, t1) >= order and len(knots) == count + order:
        first = [i for i, k in enumerate(knots) if abs(k - t0) <= eps][0]
        if first == 0:
            return ctrl, knots, weights
    curve = BSpline(ctrl, order, knots, weights)
    for t in (t0, t1):
        for _ in range(order - mult(list(curve.knots()), t)):
            curve = curve.insert_knot(t)
    knots = [float(k) for k in curve.knots()]
    i0 = next(i for i, k in enumerate(knots) if abs(k - t0) <= eps)
    i1 = max(i for i, k in enumerate(knots) if abs(k - t1) <= eps)
    n = i1 - i0 + 1 - order
    new_w = [float(w) for w in curve.weights()] if curve.is_rational else None
    return (
        list(curve.control_points)[i0 : i0 + n],
        [k - t0 for k in knots[i0 : i1 + 1]],
        None if new_w is None else new_w[i0 : i0 + n],
    )


def read_dxf(path: str, scale: float = 1.0) -> list[Segment | Circle]:
    """Read the supported entities of a DXF file into segment records.

    Parameters
    ----------
    path : str
        DXF file.
    scale : float
        Factor applied to all coordinates (for example 0.001 for a drawing in millimetres),
        giving metres.

    Returns
    -------
    list of Line, Arc, Circle or Spline
        The segments of the model space, in metres, in the plane z = 0.

    Raises
    ------
    GeometryError
        If ``ezdxf`` is not installed, the file cannot be read, or an entity does not lie
        in the plane z = 0.
    """
    ezdxf = _import_ezdxf()
    if not scale > 0.0:
        raise GeometryError("import scale must be positive")
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    try:
        doc = ezdxf.readfile(path)
    except (OSError, ezdxf.DXFError) as exc:
        raise GeometryError(f"could not read {name} as dxf: {exc}") from exc
    reader = _Reader(scale, name, [])
    handlers = {
        "LINE": reader.add_line,
        "ARC": reader.add_arc,
        "CIRCLE": reader.add_circle,
        "LWPOLYLINE": reader.add_lwpolyline,
        "SPLINE": reader.add_spline,
    }
    ignored: dict[str, int] = defaultdict(int)
    for entity in doc.modelspace():
        kind = entity.dxftype()
        if kind in handlers:
            handlers[kind](entity)
        else:
            ignored[kind] += 1
    if ignored:
        listing = ", ".join(f"{k} x{n}" for k, n in sorted(ignored.items()))
        log.warning("%s: ignored unsupported DXF entities: %s", name, listing)
    check_plane(reader.segments, reader.z_max, name)
    return reader.segments


def check_plane(segments: list[Segment | Circle], z_max: float, name: str) -> None:
    """Raise if ``z_max`` [m], the largest |z| found, is not negligible for the drawing."""
    box = bounding_box(segments)
    if box is None:
        raise GeometryError(
            f"{name} contains no supported geometry (LINE, ARC, CIRCLE, LWPOLYLINE, SPLINE)"
        )
    extent = max(box[2] - box[0], box[3] - box[1])
    if z_max > JOIN_TOL * max(extent, 1e-300):
        raise GeometryError(
            f"{name}: an entity does not lie in the plane z = 0 (z up to {z_max:.6g} m). "
            "Only a flat drawing in z = 0 can be imported; flatten or move it"
        )


def bounding_box(segments: list[Segment | Circle]) -> tuple[float, float, float, float] | None:
    """Return ``(xmin, ymin, xmax, ymax)`` of the sampled segments, or ``None`` if empty."""
    pts = [p for s in segments for p in s.samples()]
    if not pts:
        return None
    xs, ys = zip(*pts, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------------------- joining


def _merge_points(points: list[Point], tol: float) -> tuple[list[int], list[Point]]:
    """Merge points closer than ``tol``; return each point's cluster and the cluster points."""
    parent = list(range(len(points)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    cell = max(tol, 1e-300)
    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for i, (x, y) in enumerate(points):
        gx, gy = math.floor(x / cell), math.floor(y / cell)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    if math.dist(points[i], points[j]) <= tol:
                        parent[find(i)] = find(j)
        grid[(gx, gy)].append(i)
    ids: dict[int, int] = {}
    cluster: list[int] = []
    reps: list[Point] = []
    for i in range(len(points)):
        root = find(i)
        if root not in ids:
            ids[root] = len(reps)
            reps.append(points[root])
        cluster.append(ids[root])
    return cluster, reps


def _coord(p: Point) -> str:
    return f"({p[0]:.6g}, {p[1]:.6g})"


def join_segments(segments: list[Segment | Circle], tolerance: float | None = None) -> Drawing:
    """Join segment end points and chain the segments into closed loops.

    Parameters
    ----------
    segments : list
        Segments in metres.
    tolerance : float, optional
        End points closer than this [m] are the same point. Default: :data:`JOIN_TOL` times
        the largest in-plane extent of the drawing.

    Returns
    -------
    Drawing
        The shared points and the closed loops. Open chains are dropped with a warning.

    Raises
    ------
    GeometryError
        If more than two segment ends meet at a point, or no closed loop exists.
    """
    box = bounding_box(segments)
    if box is None:
        raise GeometryError("the drawing contains no geometry")
    if tolerance is None:
        tolerance = JOIN_TOL * max(box[2] - box[0], box[3] - box[1])
    circles = [s for s in segments if isinstance(s, Circle)]
    curves = [s for s in segments if not isinstance(s, Circle)]
    ends = [p for s in curves for p in (s.start, s.end)]
    cluster, points = _merge_points(ends, tolerance)
    segs: list[Segment] = []
    node_of: list[tuple[int, int]] = []
    for k, seg in enumerate(curves):
        a, b = cluster[2 * k], cluster[2 * k + 1]
        if a == b and (
            isinstance(seg, Line) or (isinstance(seg, Arc) and seg.sweep < _ARC_AS_CIRCLE)
        ):
            log.debug("dropped a degenerate segment at %s", _coord(points[a]))
            continue
        segs.append(seg)
        node_of.append((a, b))
    incident: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for k, (a, b) in enumerate(node_of):
        incident[a].append((k, 0))
        incident[b].append((k, 1))
    for node, inc in incident.items():
        if len(inc) > _MIN_NEIGHBOURS:
            raise GeometryError(
                f"the drawing branches at {_coord(points[node])}: {len(inc)} segment ends "
                "meet there but an outline needs exactly two. Remove the extra lines or "
                "split the drawing into separate outlines"
            )
    visited = [False] * len(segs)
    loops: list[Loop] = [Loop((c,), ()) for c in circles]
    open_chains: list[Point] = []

    def walk(start: int) -> tuple[list[Segment], list[int], int]:
        items: list[Segment] = []
        nodes: list[int] = []
        node = start
        while True:
            nxt = next(((k, e) for k, e in incident[node] if not visited[k]), None)
            if nxt is None:
                return items, nodes, node
            k, e = nxt
            visited[k] = True
            items.append(segs[k] if e == 0 else segs[k].reversed())
            nodes.append(node)
            node = node_of[k][1 - e]

    for node, inc in sorted(incident.items()):  # open chains start at a lone end
        if len(inc) == 1 and not visited[inc[0][0]]:
            items, nodes, last = walk(node)
            open_chains.append(points[node])
            log.debug("open chain of %d segment(s) ends at %s", len(items), _coord(points[last]))
    for k in range(len(segs)):
        if not visited[k]:
            items, nodes, last = walk(node_of[k][0])
            loops.append(Loop(tuple(items), tuple(nodes)))
    if open_chains:
        log.warning(
            "ignored %d open chain(s) of lines/arcs/splines that do not close (for example "
            "one starting at %s)",
            len(open_chains),
            _coord(open_chains[0]),
        )
    if not loops:
        raise GeometryError(
            "the drawing has no closed loop: the outline is open, or its end points differ by "
            f"more than the join tolerance of {tolerance:.3g} m. Close the outline in the "
            "drawing so that its segments meet"
        )
    return Drawing(tuple(points), tuple(loops))


# ---------------------------------------------------------------------------- nesting


def _inside(point: Point, polygon: np.ndarray) -> bool:
    """Even-odd test of ``point`` against the closed ``polygon`` (n x 2 array)."""
    x, y = point
    x0, y0 = polygon[:, 0], polygon[:, 1]
    x1, y1 = np.roll(x0, -1), np.roll(y0, -1)
    straddle = (y0 > y) != (y1 > y)
    with np.errstate(divide="ignore", invalid="ignore"):
        cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
    return bool(np.count_nonzero(straddle & (x < cross)) % 2)


def nest_loops(drawing: Drawing) -> list[Region]:
    """Group the loops of a drawing into surfaces with holes.

    A loop contained in an even number of other loops bounds a surface; the loops directly
    inside it (one level deeper) are its holes. An island inside a hole is a surface again.
    Loops are assumed not to cross each other.

    Parameters
    ----------
    drawing : Drawing
        Joined drawing.

    Returns
    -------
    list of Region
        One entry per surface, in the order of the outer loops.
    """
    loops = drawing.loops
    polygons = [np.array(lp.polygon()) for lp in loops]
    probes = [
        lp.items[0].samples()[0] if isinstance(lp.items[0], Circle) else drawing.points[lp.nodes[0]]
        for lp in loops
    ]
    n = len(loops)
    inside = [[i != j and _inside(probes[i], polygons[j]) for j in range(n)] for i in range(n)]
    depth = [sum(row) for row in inside]
    regions: list[Region] = []
    for j in range(n):
        if depth[j] % 2 == 0:
            holes = tuple(i for i in range(n) if inside[i][j] and depth[i] == depth[j] + 1)
            regions.append(Region(j, holes))
    return regions


# --------------------------------------------------------------------------- OCC part


def create_surfaces(
    occ: Any, drawing: Drawing, regions: list[Region]
) -> list[tuple[int, int]]:
    """Create the OpenCASCADE surfaces of the regions of a drawing.

    Parameters
    ----------
    occ : module
        ``gmsh.model.occ`` of the model being built.
    drawing : Drawing
        Joined drawing (shared end points are shared OCC points).
    regions : list of Region
        Surfaces to create.

    Returns
    -------
    list of (dim, tag)
        The created plane surfaces.
    """
    point_tags: dict[int, int] = {}

    def point(node: int) -> int:
        if node not in point_tags:
            x, y = drawing.points[node]
            point_tags[node] = occ.addPoint(x, y, 0.0)
        return point_tags[node]

    def loop_tag(loop: Loop) -> int:
        curves: list[int] = []
        n = len(loop.items)
        for i, item in enumerate(loop.items):
            if isinstance(item, Circle):
                curves.append(occ.addCircle(item.center[0], item.center[1], 0.0, item.radius))
                continue
            a, b = point(loop.nodes[i]), point(loop.nodes[(i + 1) % n])
            curves.extend(_curves(occ, item, a, b))
        return int(occ.addCurveLoop(curves))

    surfaces: list[tuple[int, int]] = []
    for region in regions:
        loops = [loop_tag(drawing.loops[i]) for i in (region.outer, *region.holes)]
        surfaces.append((SURFACE_DIM, int(occ.addPlaneSurface(loops))))
    return surfaces


def _curves(occ: Any, item: Segment, a: int, b: int) -> list[int]:
    """OCC curves for one oriented segment between the OCC points ``a`` and ``b``."""
    if isinstance(item, Line):
        return [int(occ.addLine(a, b))]
    if isinstance(item, Arc):
        pieces = max(1, math.ceil(item.sweep / _MAX_ARC_PIECE))
        centre = occ.addPoint(item.center[0], item.center[1], 0.0)
        tags = [a]
        for i in range(1, pieces):
            x, y = item.point_at(i / pieces)
            tags.append(occ.addPoint(x, y, 0.0))
        tags.append(b)
        return [int(occ.addCircleArc(tags[i], centre, tags[i + 1])) for i in range(pieces)]
    inner = [occ.addPoint(x, y, 0.0) for x, y in item.points[1:-1]]
    tags = [a, *inner, b]
    if item.kind == "fit":
        return [int(occ.addSpline(tags))]
    unique: list[float] = []
    mult: list[int] = []
    for k in item.knots:
        if unique and abs(k - unique[-1]) <= 1e-9 * (item.knots[-1] - item.knots[0]):
            mult[-1] += 1
        else:
            unique.append(k)
            mult.append(1)
    return [
        int(
            occ.addBSpline(
                tags,
                degree=item.degree,
                weights=list(item.weights or ()),
                knots=unique,
                multiplicities=mult,
            )
        )
    ]


def import_dxf(occ: Any, path: str, scale: float = 1.0) -> list[tuple[int, int]]:
    """Read a DXF file and create its surfaces with OpenCASCADE.

    Parameters
    ----------
    occ : module
        ``gmsh.model.occ`` of the model being built.
    path : str
        DXF file.
    scale : float
        Factor applied to the coordinates (for example 0.001 for millimetres), giving metres.

    Returns
    -------
    list of (dim, tag)
        The surfaces: closed outlines, with the outlines inside them as holes.

    Raises
    ------
    GeometryError
        If ``ezdxf`` is missing, the file cannot be read, an entity is out of the plane
        z = 0, the drawing branches, or there is no closed outline.
    """
    segments = read_dxf(path, scale)
    drawing = join_segments(segments)
    regions = nest_loops(drawing)
    surfaces = create_surfaces(occ, drawing, regions)
    log.info(
        "imported %d surface(s) from %d closed outline(s) in %s",
        len(surfaces),
        len(drawing.loops),
        path.replace("\\", "/").rsplit("/", 1)[-1],
    )
    return surfaces
