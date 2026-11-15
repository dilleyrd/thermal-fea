"""Public scripting facade (Data §11). Everything the GUI does is available from here."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

from .core.errors import ModelError
from .core.mesh import Mesh
from .geometry import builder
from .geometry.builder import BuiltGeometry
from .materials import library
from .meshing import mesher
from .model import geometry_ops as ops
from .model.model import Model, RegionAssignment
from .model.selections import Fingerprint, Selection, refresh
from .model.serialize import from_json, to_json

log = logging.getLogger(__name__)

#: Name of the selection holding every surface; :func:`build` keeps it up to date.
ALL_SURFACES = "all"
_SURFACE_DIM = 2


def new_model(
    analysis: Literal["planar", "axisymmetric"] = "planar", name: str = "Untitled"
) -> Model:
    """Create an empty model.

    Parameters
    ----------
    analysis : {"planar", "axisymmetric"}
        Axisymmetric models use x as the radius and y as the axis.
    name : str
        Model name.
    """
    return Model(name=name, analysis=analysis)


def save(model: Model, path: str | Path) -> None:
    """Write a model to a ``.tfea`` file (JSON, sorted keys, 2-space indent, SI units).

    Parameters
    ----------
    model : Model
    path : str or Path
        File to write.
    """
    text = json.dumps(to_json(model), sort_keys=True, indent=2, allow_nan=False)
    Path(path).write_text(text + "\n", encoding="utf-8")


def load(path: str | Path) -> Model:
    """Read a model from a ``.tfea`` file, migrating older schema versions.

    Parameters
    ----------
    path : str or Path
        File to read.

    Raises
    ------
    ModelError
        If the file cannot be read or understood.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ModelError(f"cannot read model file {path}: {exc}") from None
    return from_json(data)


# -------------------------------------------------------------------------- selections


def _select(
    model: Model,
    built: BuiltGeometry,
    dim: int,
    name: str,
    where: Callable[[Fingerprint], bool] | None,
    tags: Sequence[int] | None,
) -> Selection:
    entities = built.entities(dim)
    if (where is None) == (tags is None):
        raise ModelError(f"selection {name!r}: give exactly one of where= and tags=")
    if tags is not None:
        chosen = [int(t) for t in tags]
        missing = [t for t in chosen if t not in entities]
        if missing:
            raise ModelError(f"selection {name!r}: no entity with tag(s) {missing}")
    else:
        chosen = [tag for tag, fp in entities.items() if where(fp)]
    if not chosen:
        raise ModelError(f"selection {name!r} matches nothing")
    selection = Selection(name, dim, chosen, [entities[t] for t in chosen])
    model.selections[name] = selection
    return selection


def select_points(
    model: Model,
    built: BuiltGeometry,
    name: str,
    where: Callable[[Fingerprint], bool] | None = None,
    tags: Sequence[int] | None = None,
) -> Selection:
    """Create (or replace) a named selection of geometry points.

    Parameters
    ----------
    model : Model
        The selection is stored in ``model.selections[name]``.
    built : BuiltGeometry
        The current build of the model.
    name : str
        Selection name.
    where : callable, optional
        Predicate on each point's :class:`Fingerprint` (``center`` in metres).
    tags : sequence of int, optional
        Explicit tags. Give exactly one of ``where`` and ``tags``.

    Returns
    -------
    Selection
    """
    return _select(model, built, 0, name, where, tags)


def select_curves(
    model: Model,
    built: BuiltGeometry,
    name: str,
    where: Callable[[Fingerprint], bool] | None = None,
    tags: Sequence[int] | None = None,
) -> Selection:
    """Create (or replace) a named selection of curves; see :func:`select_points`."""
    return _select(model, built, 1, name, where, tags)


def select_surfaces(
    model: Model,
    built: BuiltGeometry,
    name: str,
    where: Callable[[Fingerprint], bool] | None = None,
    tags: Sequence[int] | None = None,
) -> Selection:
    """Create (or replace) a named selection of surfaces; see :func:`select_points`."""
    return _select(model, built, 2, name, where, tags)


# ---------------------------------------------------------------------------- geometry


class Geometry:
    """Thin helpers that append geometry operations to a model (Data §4).

    Every method appends one operation and returns its id, which later operations use to
    refer to its result. Coordinates and lengths are in metres, angles in radians.

    Parameters
    ----------
    model : Model
        The model whose ``geometry`` list is extended.
    """

    def __init__(self, model: Model) -> None:
        self.model = model

    def _add(self, cls: type, id: str | None, *args: object) -> str:
        used = {op.id for op in self.model.geometry}
        if id is None:
            stem = cls.__name__.lower()
            n = 1
            while f"{stem}{n}" in used:
                n += 1
            id = f"{stem}{n}"
        elif id in used:
            raise ModelError(f"geometry operation id {id!r} is already used")
        self.model.geometry.append(cls(id, *args))
        return id

    def point(self, x: float, y: float, id: str | None = None) -> str:
        """Add a point."""
        return self._add(ops.Point, id, float(x), float(y))

    def line(self, p1: str, p2: str, id: str | None = None) -> str:
        """Add a straight line between two points (ids)."""
        return self._add(ops.Line, id, p1, p2)

    def arc(self, p_start: str, p_center: str, p_end: str, id: str | None = None) -> str:
        """Add a circular arc from ``p_start`` to ``p_end`` about ``p_center`` (ids)."""
        return self._add(ops.Arc, id, p_start, p_center, p_end)

    def spline(self, points: Sequence[str], id: str | None = None) -> str:
        """Add a spline through points (ids)."""
        return self._add(ops.Spline, id, list(points))

    def rectangle(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        corner_radius: float = 0.0,
        id: str | None = None,
    ) -> str:
        """Add a rectangular surface with lower-left corner ``(x, y)``."""
        return self._add(
            ops.Rectangle, id, float(x), float(y), float(width), float(height),
            float(corner_radius),
        )

    def circle(self, xc: float, yc: float, radius: float, id: str | None = None) -> str:
        """Add a disc."""
        return self._add(ops.Circle, id, float(xc), float(yc), float(radius))

    def polygon(self, vertices: Sequence[tuple[float, float]], id: str | None = None) -> str:
        """Add a polygonal surface."""
        return self._add(ops.Polygon, id, list(vertices))

    def surface(
        self,
        curves: Sequence[str],
        holes: Sequence[Sequence[str]] = (),
        id: str | None = None,
    ) -> str:
        """Add a surface bounded by a closed loop of curves (ids), with optional holes."""
        return self._add(ops.SurfaceFromCurves, id, list(curves), [list(h) for h in holes])

    def union(self, objects: Sequence[str], tools: Sequence[str], id: str | None = None) -> str:
        """Fuse ``objects`` and ``tools``."""
        return self._add(ops.Boolean, id, "union", list(objects), list(tools))

    def cut(self, objects: Sequence[str], tools: Sequence[str], id: str | None = None) -> str:
        """Remove ``tools`` from ``objects``."""
        return self._add(ops.Boolean, id, "cut", list(objects), list(tools))

    def intersect(
        self, objects: Sequence[str], tools: Sequence[str], id: str | None = None
    ) -> str:
        """Keep the common part of ``objects`` and ``tools``."""
        return self._add(ops.Boolean, id, "intersect", list(objects), list(tools))

    def translate(
        self,
        targets: Sequence[str],
        dx: float,
        dy: float,
        copy: bool = False,
        id: str | None = None,
    ) -> str:
        """Move (or copy) ``targets`` by ``(dx, dy)``."""
        params = {"dx": float(dx), "dy": float(dy)}
        return self._add(ops.Transform, id, "translate", list(targets), params, copy)

    def rotate(
        self,
        targets: Sequence[str],
        angle: float,
        cx: float = 0.0,
        cy: float = 0.0,
        copy: bool = False,
        id: str | None = None,
    ) -> str:
        """Rotate (or copy) ``targets`` by ``angle`` [rad] about ``(cx, cy)``."""
        params = {"angle": float(angle), "cx": float(cx), "cy": float(cy)}
        return self._add(ops.Transform, id, "rotate", list(targets), params, copy)

    def mirror(
        self,
        targets: Sequence[str],
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        copy: bool = False,
        id: str | None = None,
    ) -> str:
        """Mirror (or copy) ``targets`` about the line through two points."""
        params = {"x0": float(x0), "y0": float(y0), "x1": float(x1), "y1": float(y1)}
        return self._add(ops.Transform, id, "mirror", list(targets), params, copy)

    def scale(
        self,
        targets: Sequence[str],
        factor: float,
        cx: float = 0.0,
        cy: float = 0.0,
        copy: bool = False,
        id: str | None = None,
    ) -> str:
        """Scale (or copy) ``targets`` by ``factor`` about ``(cx, cy)``."""
        params = {"factor": float(factor), "cx": float(cx), "cy": float(cy)}
        return self._add(ops.Transform, id, "scale", list(targets), params, copy)

    def import_file(
        self,
        path: str | Path,
        format: str | None = None,
        scale: float = 1.0,
        id: str | None = None,
    ) -> str:
        """Import a STEP or BREP file; the format defaults to the file extension."""
        if format is None:
            suffix = Path(path).suffix.lower().lstrip(".")
            format = {"stp": "step", "step": "step", "brep": "brep", "dxf": "dxf"}.get(suffix)
            if format is None:
                raise ModelError(f"cannot tell the format of {path}; pass format=")
        return self._add(ops.ImportFile, id, str(path), format, float(scale))

    def delete(self, targets: Sequence[str], id: str | None = None) -> str:
        """Remove the results of earlier operations."""
        return self._add(ops.Delete, id, list(targets))


def build(model: Model) -> BuiltGeometry:
    """Build the model's geometry in gmsh and refresh its selections.

    The selection named ``"all"`` is (re)created to hold every surface. Every other
    selection is resolved against the new geometry (Data §5); stale ones are logged as
    warnings and reported later by validation.

    Parameters
    ----------
    model : Model

    Returns
    -------
    BuiltGeometry
    """
    built = builder.build(model)
    if built.surfaces:
        tags = sorted(built.surfaces)
        model.selections[ALL_SURFACES] = Selection(
            ALL_SURFACES, _SURFACE_DIM, tags, [built.surfaces[t] for t in tags]
        )
    else:
        model.selections.pop(ALL_SURFACES, None)
    for message in refresh(model.selections, built).values():
        log.warning("%s", message)
    return built


def mesh(model: Model, built: BuiltGeometry) -> Mesh:
    """Mesh a built geometry with the model's mesh settings.

    Parameters
    ----------
    model : Model
    built : BuiltGeometry
        The result of the latest :func:`build` of this model.

    Returns
    -------
    Mesh
    """
    return mesher.generate(model, built)


def assign_region(
    model: Model,
    selection: str,
    material: str,
    thickness: float = 1.0,
    material_angle: float = 0.0,
) -> RegionAssignment:
    """Assign a material to the surfaces of a selection.

    If ``material`` is not yet in the model it is copied from the built-in library. An
    existing assignment of the same selection is replaced.

    Parameters
    ----------
    model : Model
    selection : str
        Name of a surface selection (``"all"`` exists after :func:`build`).
    material : str
        Name of a model material or of a library solid.
    thickness : float
        Thickness [m]; planar models only.
    material_angle : float
        Material axis angle [rad], counter-clockwise from x; orthotropic materials only.

    Returns
    -------
    RegionAssignment
    """
    sel = model.selections.get(selection)
    if sel is None:
        raise ModelError(f"unknown selection {selection!r}; build the model and select first")
    if sel.dim != _SURFACE_DIM:
        raise ModelError(f"selection {selection!r} does not contain surfaces")
    if not thickness > 0.0:
        raise ModelError("region thickness must be positive")
    if material not in model.materials:
        found = library.solid(material)  # raises ModelError when unknown
        model.materials.setdefault(found.name, found)
        material = found.name
    region = RegionAssignment(selection, material, float(thickness), float(material_angle))
    model.regions = [r for r in model.regions if r.selection != selection] + [region]
    return region
