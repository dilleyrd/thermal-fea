"""Geometry operations (Data §4).

Geometry is stored as a history of operations, not as shapes. Each operation has a unique
``id`` and refers to the results of earlier operations by their ids. The builder replays
the list in order. All coordinates and lengths are in metres, angles in radians.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.errors import ModelError


def _choice(value: str, allowed: tuple[str, ...], what: str) -> None:
    if value not in allowed:
        raise ModelError(f"{what} must be one of {', '.join(allowed)}; got {value!r}")


@dataclass
class GeometryOp:
    """Base class of all geometry operations.

    Parameters
    ----------
    id : str
        Unique identifier of the operation within the model.
    """

    id: str

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ModelError("geometry operation id must be a non-empty string")


@dataclass
class Point(GeometryOp):
    """A point at ``(x, y)`` [m]."""

    x: float
    y: float


@dataclass
class Line(GeometryOp):
    """A straight line between two point operations."""

    p1: str
    p2: str


@dataclass
class Arc(GeometryOp):
    """A circular arc from ``p_start`` to ``p_end`` about ``p_center`` (point op ids)."""

    p_start: str
    p_center: str
    p_end: str


@dataclass
class Spline(GeometryOp):
    """A spline through the listed point operations."""

    points: list[str]


@dataclass
class Rectangle(GeometryOp):
    """A rectangular surface with lower-left corner ``(x, y)`` [m]."""

    x: float
    y: float
    width: float
    height: float
    corner_radius: float = 0.0


@dataclass
class Circle(GeometryOp):
    """A disc of the given ``radius`` [m] centred at ``(xc, yc)`` [m]."""

    xc: float
    yc: float
    radius: float


@dataclass
class Polygon(GeometryOp):
    """A polygonal surface through ``vertices`` [m], closed automatically."""

    vertices: list[tuple[float, float]]

    def __post_init__(self) -> None:
        super().__post_init__()
        self.vertices = [(float(v[0]), float(v[1])) for v in self.vertices]


@dataclass
class SurfaceFromCurves(GeometryOp):
    """A surface bounded by a closed loop of curve operations, with optional hole loops."""

    curves: list[str]
    holes: list[list[str]] = field(default_factory=list)


@dataclass
class Boolean(GeometryOp):
    """Boolean operation between the results of earlier operations."""

    kind: Literal["union", "cut", "intersect"]
    objects: list[str]
    tools: list[str]

    def __post_init__(self) -> None:
        super().__post_init__()
        _choice(self.kind, ("union", "cut", "intersect"), "boolean kind")


@dataclass
class Transform(GeometryOp):
    """Move or copy the results of earlier operations.

    ``params`` by kind: translate ``dx, dy`` [m]; rotate ``angle`` [rad] about
    ``cx, cy`` [m]; mirror about the line through ``x0, y0`` and ``x1, y1`` [m];
    scale by ``factor`` about ``cx, cy`` [m].
    """

    kind: Literal["translate", "rotate", "mirror", "scale"]
    targets: list[str]
    params: dict[str, float]
    copy: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        _choice(self.kind, ("translate", "rotate", "mirror", "scale"), "transform kind")


@dataclass
class ImportFile(GeometryOp):
    """Geometry read from a file; ``scale`` multiplies its coordinates."""

    path: str
    format: Literal["step", "brep", "dxf"]
    scale: float = 1.0

    def __post_init__(self) -> None:
        super().__post_init__()
        _choice(self.format, ("step", "brep", "dxf"), "import format")


@dataclass
class Delete(GeometryOp):
    """Remove the results of earlier operations."""

    targets: list[str]
