"""Import of CAD files into the geometry being built (STEP and BREP).

Only flat surfaces lying in the plane z = 0 are accepted: ThermalFEA models are 2D. Solids,
surfaces out of that plane and files without surfaces are refused with an explanation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..core.errors import GeometryError

log = logging.getLogger(__name__)

SURFACE_DIM = 2
_Z = 2  # index of the z coordinate
_BBOX_MAX = 3  # offset of the maxima in a (xmin, ymin, zmin, xmax, ymax, zmax) box
#: A surface is "in z = 0" when its z extent is below this fraction of its in-plane size.
PLANE_TOL = 1e-6
_FORMATS = {"step": "step", "brep": "brep"}


def import_shapes(occ: Any, path: str, fmt: str, scale: float = 1.0) -> list[tuple[int, int]]:
    """Read a STEP or BREP file with OpenCASCADE and return its surfaces.

    Parameters
    ----------
    occ : module
        ``gmsh.model.occ`` of the model being built.
    path : str
        File to read.
    fmt : {"step", "brep"}
        File format.
    scale : float
        Factor applied to the coordinates about the origin (for example 0.001 for a file
        in millimetres), giving metres.

    Returns
    -------
    list of (dim, tag)
        The imported surfaces.

    Raises
    ------
    GeometryError
        If the file cannot be read, contains solids, has no surfaces, or has a surface
        that does not lie in the plane z = 0.
    """
    if fmt not in _FORMATS:
        raise GeometryError(f"import of {fmt!r} files is not supported (use step or brep)")
    if not scale > 0.0:
        raise GeometryError("import scale must be positive")
    file = Path(path)
    if not file.is_file():
        raise GeometryError(f"file not found: {path}")
    try:
        shapes = occ.importShapes(str(file), highestDimOnly=True, format=_FORMATS[fmt])
    except Exception as exc:  # gmsh raises plain Exception
        raise GeometryError(f"could not read {file.name} as {fmt}: {exc}") from exc
    shapes = [(int(d), int(t)) for d, t in shapes]
    if not shapes:
        raise GeometryError(f"{file.name} contains no geometry")
    top = max(d for d, _ in shapes)
    if top > SURFACE_DIM:
        raise GeometryError(
            f"{file.name} contains 3D solids. ThermalFEA is two-dimensional: export only the "
            "flat faces of the cross-section, lying in the plane z = 0"
        )
    if top < SURFACE_DIM:
        raise GeometryError(
            f"{file.name} contains only curves or points, no surfaces. Export the "
            "cross-section as flat faces lying in the plane z = 0"
        )
    if scale != 1.0:
        occ.dilate(shapes, 0.0, 0.0, 0.0, scale, scale, scale)
    for dim, tag in shapes:
        box = occ.getBoundingBox(dim, tag)
        size = max(box[i + _BBOX_MAX] - box[i] for i in range(_Z))
        limit = PLANE_TOL * max(size, abs(box[0]), abs(box[1]))
        if max(abs(box[_Z]), abs(box[_Z + _BBOX_MAX])) > limit + _OCC_BOX_PADDING:
            raise GeometryError(
                f"{file.name}: a surface does not lie in the plane z = 0 (its z range is "
                f"{box[_Z]:.6g} to {box[_Z + _BBOX_MAX]:.6g} m). Only flat surfaces in "
                "z = 0 can be imported; move or re-export the cross-section"
            )
    log.info("imported %d surface(s) from %s", len(shapes), file.name)
    return shapes


#: OpenCASCADE enlarges bounding boxes by about this much [m].
_OCC_BOX_PADDING = 1e-6
