"""Definitions of the geometry tools (Plan M8.5): which operation each tool adds and how.

No widgets here. A :class:`ToolDef` names the operation class, the fields its dialog
shows, the fields fixed by the tool (``kind="union"``), how clicks place it and which
method of :class:`thermalfea.api.Geometry` adds it, so the GUI adds operations exactly
like a script does.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec, form_for
from thermalfea.model import geometry_ops as g
from thermalfea.model.geometry_edit import TRANSFORM_PARAMS

#: Numeric fields that start with a value; every other number must be typed or clicked.
DEFAULTS: dict[str, float] = {"corner_radius": 0.0, "scale": 1.0, "factor": 1.0}

Adder = Callable[[api.Geometry, dict[str, Any], "str | None"], str]


@dataclass(frozen=True)
class ToolDef:
    """One geometry tool.

    Attributes
    ----------
    key : str
        Stable id; the action is ``"geometry.<key>"``.
    title : str
        Menu and dialog title.
    cls : type
        The operation class it creates.
    show : tuple of str
        Form fields of ``cls`` the dialog edits (transform parameters are added
        according to the kind).
    fixed : dict
        Field values the tool fixes (``{"kind": "cut"}``).
    placement : str or None
        :class:`~thermalfea.model.geometry_edit.Placement` kind for click-to-place.
    selection : str or None
        ``"boolean"`` (objects/tools from the viewport selection), ``"targets"`` or
        ``None``; tools with a selection rule are only enabled with a selection.
    add : callable
        ``add(geometry, values, id)`` appends the operation and returns its id.
    """

    key: str
    title: str
    cls: type
    show: tuple[str, ...]
    add: Adder
    fixed: dict[str, Any] = field(default_factory=dict)
    placement: str | None = None
    selection: str | None = None

    def specs(self) -> list[FieldSpec]:
        """The :class:`FieldSpec` of every field the dialog shows, in order."""
        form = form_for(self.cls)
        out: list[FieldSpec] = []
        for name in self.show:
            if name == "params":
                out.extend(self._params())
            else:
                out.append(form.field(name))
        return out

    def _params(self) -> list[FieldSpec]:
        kind = self.fixed["kind"]
        specs = []
        for name, label in TRANSFORM_PARAMS[kind]:
            quantity = None if name in ("angle", "factor") else "length"
            specs.append(FieldSpec(name, label, "float", quantity=quantity))
        return specs


def _ids(values: dict[str, Any], name: str) -> list[str]:
    value = values[name]
    return [value] if isinstance(value, str) else list(value)


_COPY = ("copy",)


def _transform(method: str, names: tuple[str, ...]) -> Adder:
    def add(geo: api.Geometry, v: dict[str, Any], op_id: str | None) -> str:
        args = [v[n] for n in names]
        return getattr(geo, method)(
            _ids(v, "targets"), *args, copy=bool(v.get("copy", False)), id=op_id
        )

    return add


def _boolean(method: str) -> Adder:
    def add(geo: api.Geometry, v: dict[str, Any], op_id: str | None) -> str:
        return getattr(geo, method)(_ids(v, "objects"), _ids(v, "tools"), id=op_id)

    return add


_TOOL_LIST: tuple[ToolDef, ...] = (
    ToolDef("point", "Point", g.Point, ("x", "y"),
            lambda geo, v, i: geo.point(v["x"], v["y"], id=i), placement="point"),
    ToolDef("line", "Line", g.Line, ("p1", "p2"),
            lambda geo, v, i: geo.line(v["p1"], v["p2"], id=i)),
    ToolDef("arc", "Arc", g.Arc, ("p_start", "p_center", "p_end"),
            lambda geo, v, i: geo.arc(v["p_start"], v["p_center"], v["p_end"], id=i)),
    ToolDef("spline", "Spline", g.Spline, ("points",),
            lambda geo, v, i: geo.spline(_ids(v, "points"), id=i)),
    ToolDef("rectangle", "Rectangle", g.Rectangle,
            ("x", "y", "width", "height", "corner_radius"),
            lambda geo, v, i: geo.rectangle(
                v["x"], v["y"], v["width"], v["height"], v["corner_radius"], id=i),
            placement="rectangle"),
    ToolDef("circle", "Circle", g.Circle, ("xc", "yc", "radius"),
            lambda geo, v, i: geo.circle(v["xc"], v["yc"], v["radius"], id=i),
            placement="circle"),
    ToolDef("polygon", "Polygon", g.Polygon, ("vertices",),
            lambda geo, v, i: geo.polygon(v["vertices"], id=i), placement="polygon"),
    ToolDef("surface", "Surface from curves", g.SurfaceFromCurves, ("curves", "holes"),
            lambda geo, v, i: geo.surface(_ids(v, "curves"), v.get("holes", []), id=i)),
    ToolDef("union", "Union", g.Boolean, ("objects", "tools"), _boolean("union"),
            fixed={"kind": "union"}, selection="boolean"),
    ToolDef("cut", "Cut", g.Boolean, ("objects", "tools"), _boolean("cut"),
            fixed={"kind": "cut"}, selection="boolean"),
    ToolDef("intersect", "Intersect", g.Boolean, ("objects", "tools"), _boolean("intersect"),
            fixed={"kind": "intersect"}, selection="boolean"),
    ToolDef("translate", "Translate", g.Transform, ("targets", "params", "copy"),
            _transform("translate", ("dx", "dy")), fixed={"kind": "translate"},
            placement="translate", selection="targets"),
    ToolDef("rotate", "Rotate", g.Transform, ("targets", "params", "copy"),
            _transform("rotate", ("angle", "cx", "cy")), fixed={"kind": "rotate"},
            placement="rotate", selection="targets"),
    ToolDef("mirror", "Mirror", g.Transform, ("targets", "params", "copy"),
            _transform("mirror", ("x0", "y0", "x1", "y1")), fixed={"kind": "mirror"},
            placement="mirror", selection="targets"),
    ToolDef("scale", "Scale", g.Transform, ("targets", "params", "copy"),
            _transform("scale", ("factor", "cx", "cy")), fixed={"kind": "scale"},
            placement="scale", selection="targets"),
    ToolDef("delete", "Delete", g.Delete, ("targets",),
            lambda geo, v, i: geo.delete(_ids(v, "targets"), id=i), selection="targets"),
    ToolDef("import", "Import STEP/BREP", g.ImportFile, ("path", "format", "scale"),
            lambda geo, v, i: geo.import_file(v["path"], v["format"], v["scale"], id=i)),
)  # fmt: skip

#: Every geometry tool by key, in menu order.
TOOLS: dict[str, ToolDef] = {t.key: t for t in _TOOL_LIST}


def make_op(tool: ToolDef, values: dict[str, Any], op_id: str = "new") -> g.GeometryOp:
    """Build the operation a tool would add, for validation.

    Parameters
    ----------
    tool : ToolDef
    values : dict
        Field values in SI (transform parameters flat, like ``dx``).
    op_id : str
        Placeholder id.

    Raises
    ------
    ModelError
        If the operation class rejects the values.
    """
    names = {f.name for f in form_for(tool.cls).fields}
    merged = {**tool.fixed, **values}
    kwargs = {k: v for k, v in merged.items() if k in names}
    if tool.cls is g.Transform:
        kind = merged["kind"]
        kwargs["params"] = {k: float(merged[k]) for k, _ in TRANSFORM_PARAMS[kind] if k in merged}
        kwargs["targets"] = _targets(merged)
    for name in ("points", "curves", "objects", "tools", "targets"):
        if name in kwargs:
            kwargs[name] = _targets({name: kwargs[name]}, name)
    try:
        return tool.cls(op_id, **kwargs)
    except TypeError as exc:
        raise ModelError(f"incomplete {tool.title.lower()}: {exc}") from None


def _targets(values: dict[str, Any], name: str = "targets") -> list[str]:
    value = values.get(name, [])
    return [value] if isinstance(value, str) else list(value)
