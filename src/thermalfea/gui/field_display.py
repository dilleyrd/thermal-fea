"""Build :class:`~thermalfea.gui.scene.FieldDisplay` from the display data prepared by ``post/``."""

from __future__ import annotations

import numpy as np

from thermalfea.gui.scene import FieldDisplay
from thermalfea.post.plots import ContourData, VectorData

_MARKER_FORMAT = "{text} {value:.4g}"


def field_display_from_contour(
    data: ContourData,
    levels: int | None = 12,
    vmin: float | None = None,
    vmax: float | None = None,
    show_mesh: bool = False,
    vectors: VectorData | None = None,
    markers: bool = True,
) -> FieldDisplay:
    """Merge the parts of a contour data set into one plain :class:`FieldDisplay`.

    Parameters
    ----------
    data : ContourData
        From :func:`thermalfea.post.plots.contour_data` (values in display units).
    levels : int or None
        Colour bands; ``None`` for smooth shading.
    vmin, vmax : float, optional
        Colour range; default the field's extrema.
    show_mesh : bool
        Draw element edges over the field.
    vectors : VectorData, optional
        Heat-flux arrows to draw on top.
    markers : bool
        Annotate the minimum and maximum.

    Returns
    -------
    FieldDisplay
    """
    offsets = np.cumsum([0] + [p.xy.shape[0] for p in data.parts])
    xy = np.concatenate([p.xy for p in data.parts])
    tri = np.concatenate([p.triangles + off for p, off in zip(data.parts, offsets, strict=False)])
    values = np.concatenate([p.values for p in data.parts])
    lo = data.vmin if vmin is None else float(vmin)
    hi = data.vmax if vmax is None else float(vmax)
    notes: list[tuple[float, float, str]] = []
    if markers:
        for point, value, text in (
            (data.xy_min, data.vmin, "min"),
            (data.xy_max, data.vmax, "max"),
        ):
            notes.append(
                (float(point[0]), float(point[1]),
                 _MARKER_FORMAT.format(text=text, value=value))
            )
    spec = FieldDisplay(
        xy=xy, triangles=tri, values=values, vmin=lo, vmax=hi, levels=levels,
        label=data.label, title=data.title, markers=notes, show_mesh=show_mesh,
    )
    if vectors is not None:
        spec.vector_xy = vectors.xy
        spec.vector_uv = vectors.q
        spec.vector_values = vectors.magnitude
        spec.vector_label = "Heat flux [W/m²]"
    return spec
