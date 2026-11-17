"""Form specifications of the geometry operations (Plan M8.5).

They give the property panel and the geometry-tool dialogs their fields. Coordinates and
sizes are lengths (``quantity="length"``). The id of an operation is never editable: later
operations refer to it. The transform parameters mix lengths, angles and a factor in
one mapping, so they stay in SI (m, rad) whatever the display units are.
"""

from __future__ import annotations

from ..core.forms import FieldSpec, FormSpec, register_form
from . import geometry_ops as g

_CATEGORY = "geometry"


def _length(name: str, label: str, minimum: float | None = None, tooltip: str = "") -> FieldSpec:
    return FieldSpec(name, label, "float", quantity="length", minimum=minimum, tooltip=tooltip)


def _ref(name: str, label: str, tooltip: str) -> FieldSpec:
    return FieldSpec(name, label, "str", tooltip=tooltip)


def _refs(name: str, label: str, tooltip: str) -> FieldSpec:
    return FieldSpec(name, label, "str_list", tooltip=tooltip)


_POINT_ID = "Id of a point operation."
_IDS = "Comma-separated operation ids."

FORMS: dict[type, FormSpec] = {
    g.Point: FormSpec("Point", [_length("x", "x"), _length("y", "y")], _CATEGORY, "A point."),
    g.Line: FormSpec(
        "Line",
        [_ref("p1", "From point", _POINT_ID), _ref("p2", "To point", _POINT_ID)],
        _CATEGORY,
        "A straight line between two points.",
    ),
    g.Arc: FormSpec(
        "Arc",
        [
            _ref("p_start", "Start point", _POINT_ID),
            _ref("p_center", "Centre point", _POINT_ID),
            _ref("p_end", "End point", _POINT_ID),
        ],
        _CATEGORY,
        "A circular arc from the start to the end point about the centre point.",
    ),
    g.Spline: FormSpec(
        "Spline",
        [_refs("points", "Points", "Comma-separated ids of point operations, in order.")],
        _CATEGORY,
        "A spline through points.",
    ),
    g.Rectangle: FormSpec(
        "Rectangle",
        [
            _length("x", "x", tooltip="Lower-left corner."),
            _length("y", "y", tooltip="Lower-left corner."),
            _length("width", "Width", 0.0),
            _length("height", "Height", 0.0),
            _length("corner_radius", "Corner radius", 0.0),
        ],
        _CATEGORY,
        "A rectangular surface.",
    ),
    g.Circle: FormSpec(
        "Circle",
        [_length("xc", "Centre x"), _length("yc", "Centre y"), _length("radius", "Radius", 0.0)],
        _CATEGORY,
        "A disc.",
    ),
    g.Polygon: FormSpec(
        "Polygon",
        [
            FieldSpec(
                "vertices", "Vertices", "xy_list", quantity="length",
                tooltip="Vertices as 'x, y; x, y; ...'; the polygon closes itself.",
            )  # fmt: skip
        ],
        _CATEGORY,
        "A polygonal surface.",
    ),
    g.SurfaceFromCurves: FormSpec(
        "Surface From Curves",
        [
            _refs("curves", "Boundary curves", "Ids of the curves of the closed outer loop."),
            FieldSpec(
                "holes", "Holes", "str_lists",
                tooltip="Curve ids of each hole loop; loops are separated by ';'.",
            ),  # fmt: skip
        ],
        _CATEGORY,
        "A surface bounded by a closed loop of curves, with optional holes.",
    ),
    g.Boolean: FormSpec(
        "Boolean",
        [
            FieldSpec("kind", "Kind", "choice", choices=("union", "cut", "intersect")),
            _refs("objects", "Objects", _IDS),
            _refs("tools", "Tools", _IDS),
        ],
        _CATEGORY,
        "Union, cut or intersection of the results of earlier operations.",
    ),
    g.Transform: FormSpec(
        "Transform",
        [
            FieldSpec(
                "kind", "Kind", "choice", choices=("translate", "rotate", "mirror", "scale")
            ),
            _refs("targets", "Targets", _IDS),
            FieldSpec(
                "params", "Parameters [SI: m, rad]", "dict",
                tooltip="Always in SI. translate: dx, dy [m]; rotate: angle [rad], cx, cy [m]; "
                "mirror: x0, y0, x1, y1 [m]; scale: factor, cx, cy [m].",
            ),  # fmt: skip
            FieldSpec("copy", "Keep original (copy)", "bool"),
        ],
        _CATEGORY,
        "Move or copy the results of earlier operations.",
    ),
    g.ImportFile: FormSpec(
        "Import File",
        [
            FieldSpec("path", "File", "str"),
            FieldSpec("format", "Format", "choice", choices=("step", "brep", "dxf")),
            FieldSpec("scale", "Scale", "float", minimum=0.0, tooltip="Multiplies coordinates."),
        ],
        _CATEGORY,
        "Geometry read from a STEP or BREP file.",
    ),
    g.Delete: FormSpec(
        "Delete",
        [_refs("targets", "Targets", _IDS)],
        _CATEGORY,
        "Remove the results of earlier operations.",
    ),
}

for _cls, _spec in FORMS.items():
    register_form(_cls, _spec)
