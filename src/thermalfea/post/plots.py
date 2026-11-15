"""Plots of results (M5). Every function takes a :class:`Results` and returns a ``Figure``.

Figures are built with ``matplotlib.figure.Figure`` and the Agg canvas, never ``pyplot``, so
nothing here opens a window and the GUI can pass its own ``ax`` to draw into.

The contour plot is split in two: :func:`contour_data` is a pure function that gathers the
arrays to be drawn (triangulation, values in display units, extrema, labels), and
:func:`contour` draws them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.cm import ScalarMappable
from matplotlib.collections import LineCollection
from matplotlib.colors import Normalize
from matplotlib.figure import Figure
from matplotlib.tri import Triangulation
from numpy import ndarray

from ..core.errors import ModelError
from ..core.mesh import Mesh
from ..core.registry import element
from ..core.units import UnitSettings, from_si
from .results import Results

log = logging.getLogger(__name__)

#: Contour fields: name -> (source, component or None for the magnitude, SI unit, title).
#: ``source`` is ``"T"`` (nodal temperature), ``"flux"`` or ``"grad"`` (per-region nodal).
FIELDS: dict[str, tuple[str, int | None, str, str]] = {
    "T": ("T", None, "K", "Temperature"),
    "qx": ("flux", 0, "W/m^2", "Heat flux qx"),
    "qy": ("flux", 1, "W/m^2", "Heat flux qy"),
    "qmag": ("flux", None, "W/m^2", "Heat flux magnitude"),
    "gradx": ("grad", 0, "K/m", "Temperature gradient x"),
    "grady": ("grad", 1, "K/m", "Temperature gradient y"),
    "gradmag": ("grad", None, "K/m", "Temperature gradient magnitude"),
}

_TEMPERATURE_LABEL = {"K": "K", "degC": "°C", "degF": "°F"}


# -------------------------------------------------------------------- display triangulation


@dataclass
class DisplayMesh:
    """Linear triangles that tile a mesh, for drawing.

    Attributes
    ----------
    triangles : ndarray of int, shape (n_tri, 3)
        Node indices (into ``mesh.nodes``), counter-clockwise.
    region : ndarray of int, shape (n_tri,)
        Region id of the parent element of every triangle.
    element : ndarray of int, shape (n_tri,)
        Position of the parent element in the concatenation of the mesh's blocks.
    outlines : list of ndarray of int
        One ``(n_facets, k)`` array per element block: the node indices along every facet
        of every element, in drawing order.
    """

    triangles: ndarray
    region: ndarray
    element: ndarray
    outlines: list[ndarray] = field(default_factory=list)


_CACHE: dict[int, tuple[Mesh, DisplayMesh]] = {}
_CACHE_SIZE = 8


def _facet_order(local: ndarray) -> ndarray:
    """Order a facet's local nodes along the curve: end, mid-side nodes..., other end."""
    if local.shape[1] <= 2:
        return local
    return np.concatenate([local[:, :1], local[:, 2:], local[:, 1:2]], axis=1)


def display_triangulation(mesh: Mesh) -> DisplayMesh:
    """The display triangulation of a mesh, built once per mesh object and cached.

    Each element is split by its type's registered ``display_simplices``; the loop is over
    element blocks only.

    Parameters
    ----------
    mesh : Mesh
        A 2D mesh.

    Returns
    -------
    DisplayMesh
    """
    cached = _CACHE.get(id(mesh))
    if cached is not None and cached[0] is mesh:
        return cached[1]
    tris: list[ndarray] = []
    regions: list[ndarray] = []
    parents: list[ndarray] = []
    outlines: list[ndarray] = []
    offset = 0
    for block in mesh.blocks:
        et = element(block.etype)
        simplices = np.asarray(et.display_simplices)
        n_el = block.conn.shape[0]
        if simplices.shape[1] != 3:
            raise ModelError(f"element type {et.name!r} cannot be drawn as triangles")
        t = block.conn[:, simplices].reshape(-1, 3)  # element-major
        # make every triangle counter-clockwise (vectorised signed area)
        p = mesh.nodes[t]
        area2 = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (
            p[:, 2, 0] - p[:, 0, 0]
        ) * (p[:, 1, 1] - p[:, 0, 1])
        t = np.where((area2 < 0.0)[:, None], t[:, ::-1], t)
        tris.append(t)
        regions.append(np.repeat(np.asarray(block.region, dtype=int), simplices.shape[0]))
        parents.append(np.repeat(offset + np.arange(n_el), simplices.shape[0]))
        offset += n_el
        if et.facets is not None:
            order = _facet_order(np.asarray(et.facets))
            outlines.append(block.conn[:, order].reshape(-1, order.shape[1]))
    if tris:
        display = DisplayMesh(
            np.concatenate(tris), np.concatenate(regions), np.concatenate(parents), outlines
        )
    else:
        display = DisplayMesh(np.zeros((0, 3), int), np.zeros(0, int), np.zeros(0, int), outlines)
    if len(_CACHE) >= _CACHE_SIZE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[id(mesh)] = (mesh, display)
    return display


# ---------------------------------------------------------------------------- contour data


@dataclass
class ContourPart:
    """One separately drawn piece of a contour plot (the whole mesh, or one region).

    Attributes
    ----------
    region : int or None
        Region id, or ``None`` for a field drawn over the whole mesh.
    nodes : ndarray of int, shape (n,)
        Global node indices of the part.
    xy : ndarray, shape (n, 2)
        Node coordinates [m].
    triangles : ndarray of int, shape (m, 3)
        Triangles as indices into ``nodes`` / ``xy`` / ``values``.
    values : ndarray, shape (n,)
        Field values in display units.
    """

    region: int | None
    nodes: ndarray
    xy: ndarray
    triangles: ndarray
    values: ndarray


@dataclass
class ContourData:
    """Everything a contour plot draws, in display units.

    Attributes
    ----------
    parts : list of ContourPart
    vmin, vmax : float
        Smallest and largest value over all parts.
    xy_min, xy_max : ndarray, shape (2,)
        Coordinates [m] of the node holding the smallest and largest value.
    unit : str
        Display-unit label, e.g. ``"degC"`` is shown as ``"°C"``.
    label : str
        Colour-bar label: name and unit.
    title : str
        Plot title, including the time of the step.
    time : float
        Time of the step [s].
    """

    parts: list[ContourPart]
    vmin: float
    vmax: float
    xy_min: ndarray
    xy_max: ndarray
    unit: str
    label: str
    title: str
    time: float


def _unit_settings(results: Results) -> UnitSettings:
    model = results.model
    return model.display_units if model is not None else UnitSettings()


def contour_data(results: Results, step: int = -1, field: str = "T") -> ContourData:
    """Gather the arrays of a contour plot.

    Parameters
    ----------
    results : Results
    step : int
        Stored step; negative counts from the end.
    field : str
        One of :data:`FIELDS`: ``T``, ``qx``, ``qy``, ``qmag``, ``gradx``, ``grady``,
        ``gradmag``. Flux and gradient parts are separate per region, because those
        fields are discontinuous at material interfaces.

    Returns
    -------
    ContourData
        Values are in display units (temperature in the model's unit; flux in W/m^2;
        gradient in K/m, or degF/m when the model displays degF).

    Raises
    ------
    ModelError
        For an unknown field or step, or a component the mesh does not have.
    """
    if field not in FIELDS:
        raise ModelError(f"unknown contour field {field!r}; choose from {', '.join(FIELDS)}")
    source, component, si_unit, name = FIELDS[field]
    mesh = results.mesh
    if component is not None and component >= mesh.dim:
        raise ModelError(f"field {field!r} needs a {component + 1}D mesh")
    display = display_triangulation(mesh)
    units = _unit_settings(results)
    times = results.times
    if not -times.size <= step < times.size:
        raise ModelError(f"step {step} is out of range; the file has {times.size} step(s)")
    time = float(times[step])

    if source == "T":
        T = from_si(np.asarray(results.temperature(step), dtype=float), "temperature", units)
        groups: list[tuple[int | None, ndarray, ndarray]] = [
            (None, np.arange(mesh.n_nodes), np.asarray(T))
        ]
        unit = _TEMPERATURE_LABEL[units.temperature]
    else:
        raw = results.flux(step) if source == "flux" else results.gradient(step)
        groups = []
        for region_id in sorted(raw):
            nodes, vec = raw[region_id]
            vals = np.linalg.norm(vec, axis=1) if component is None else vec[:, component]
            if source == "grad":
                vals = np.asarray(from_si(vals, "temperature_difference", units))
            groups.append((region_id, np.asarray(nodes), vals))
        if source == "flux":
            unit = si_unit
        else:
            unit = f"{_TEMPERATURE_LABEL[units.temperature]}/m"

    parts: list[ContourPart] = []
    lookup = np.full(mesh.n_nodes, -1, dtype=int)
    for region_id, nodes, vals in groups:
        tri = display.triangles
        if region_id is not None:
            tri = tri[display.region == region_id]
        if tri.shape[0] == 0:
            continue
        used = np.unique(tri)
        lookup[:] = -1
        lookup[used] = np.arange(used.size)
        full = np.full(mesh.n_nodes, np.nan)
        full[nodes] = vals
        parts.append(
            ContourPart(region_id, used, mesh.nodes[used][:, :2], lookup[tri], full[used])
        )
    if not parts:
        raise ModelError("the mesh has nothing to draw")

    lo = min(float(np.nanmin(p.values)) for p in parts)
    hi = max(float(np.nanmax(p.values)) for p in parts)
    xy_min = xy_max = np.zeros(2)
    for p in parts:
        if np.nanmin(p.values) == lo:
            xy_min = p.xy[int(np.nanargmin(p.values))]
            break
    for p in parts:
        if np.nanmax(p.values) == hi:
            xy_max = p.xy[int(np.nanargmax(p.values))]
            break
    return ContourData(
        parts=parts,
        vmin=lo,
        vmax=hi,
        xy_min=np.asarray(xy_min),
        xy_max=np.asarray(xy_max),
        unit=unit,
        label=f"{name} [{unit}]",
        title=f"{name}, t = {time:.6g} s",
        time=time,
    )


# ------------------------------------------------------------------------------- helpers


def _figure(ax: Axes | None) -> tuple[Figure, Axes]:
    """The figure and axes to draw into: ``ax`` if given, otherwise a new Agg figure."""
    if ax is not None:
        return ax.figure, ax
    fig = Figure(figsize=(7.5, 5.5), layout="constrained")
    FigureCanvasAgg(fig)
    return fig, fig.add_subplot(1, 1, 1)


def _frame(fig: Figure, ax: Axes, mappable: ScalarMappable, label: str, title: str) -> None:
    """Colour bar, equal aspect, axis labels and title of a plot."""
    fig.colorbar(mappable, ax=ax, label=label)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_title(title)
    ax.autoscale_view()


def _save(fig: Figure, path: str | Path | None, what: str) -> None:
    """Save the figure as a 200 dpi PNG (or whatever the suffix of ``path`` names)."""
    if path is not None:
        fig.savefig(path, dpi=200)
        log.info("saved %s to %s", what, path)


# ------------------------------------------------------------------------------- contour


def contour(
    results: Results,
    step: int = -1,
    field: str = "T",
    levels: int = 12,
    vmin: float | None = None,
    vmax: float | None = None,
    smooth: bool = False,
    show_mesh: bool = False,
    ax: Axes | None = None,
    path: str | Path | None = None,
) -> Figure:
    """Filled contour plot of a field on the deformed-free mesh.

    Parameters
    ----------
    results : Results
    step : int
        Stored step; negative counts from the end.
    field : str
        ``T``, ``qx``, ``qy``, ``qmag``, ``gradx``, ``grady`` or ``gradmag``. Temperature
        is shown in the model's display unit. Flux and gradient fields are drawn region by
        region so the jump at an interface is kept.
    levels : int
        Number of colour bands (ignored when ``smooth``).
    vmin, vmax : float, optional
        Colour range in display units; default is the field's minimum and maximum.
    smooth : bool
        Continuous shading instead of bands.
    show_mesh : bool
        Overlay the element edges.
    ax : Axes, optional
        Draw into these axes (the colour bar is added to their figure); otherwise a new
        figure is made.
    path : str or Path, optional
        Also save the figure here (PNG, 200 dpi).

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ModelError
        For an unknown field or step.
    """
    data = contour_data(results, step, field)
    fig, ax = _figure(ax)
    lo = data.vmin if vmin is None else float(vmin)
    hi = data.vmax if vmax is None else float(vmax)
    if not hi > lo:  # uniform field or inverted limits: keep the colour scale valid
        pad = max(abs(lo), 1.0) * 1e-6
        lo, hi = lo - pad, lo + pad
    norm = Normalize(vmin=lo, vmax=hi)
    n_bands = max(int(levels), 1)
    band_edges = np.linspace(lo, hi, n_bands + 1)
    extend = "neither" if vmin is None and vmax is None else "both"

    mappable = None
    for part in data.parts:
        tri = Triangulation(part.xy[:, 0], part.xy[:, 1], part.triangles)
        values = np.where(np.isfinite(part.values), part.values, lo)
        if smooth:
            mappable = ax.tripcolor(
                tri, values, shading="gouraud", cmap="viridis", norm=norm
            )
        else:
            mappable = ax.tricontourf(
                tri, values, levels=band_edges, cmap="viridis", norm=norm, extend=extend
            )
    if show_mesh:
        coords = results.mesh.nodes[:, :2]
        # one collection per element block; the (n_edges, n_points, 2) array is passed
        # as it is, so there is no Python loop over element edges
        for outline in display_triangulation(results.mesh).outlines:
            ax.add_collection(LineCollection(coords[outline], colors="k", linewidths=0.4))
    for xy, value, marker, text in (
        (data.xy_min, data.vmin, "v", "min"),
        (data.xy_max, data.vmax, "^", "max"),
    ):
        ax.plot([xy[0]], [xy[1]], marker, color="white", mec="black", ms=7)
        ax.annotate(
            f"{text} {value:.4g}", xy=(xy[0], xy[1]), xytext=(6, 6),
            textcoords="offset points", fontsize=8,
            bbox={"boxstyle": "round,pad=0.2", "fc": "white", "alpha": 0.8, "lw": 0.3},
        )
    _frame(fig, ax, mappable, data.label, data.title)
    _save(fig, path, "contour plot")
    return fig


# -------------------------------------------------------------------------------- vectors


@dataclass
class VectorData:
    """Arrows of a heat-flux vector plot, after thinning.

    Attributes
    ----------
    xy : ndarray, shape (n, 2)
        Arrow positions: element centroids [m].
    q : ndarray, shape (n, 2)
        Heat flux at the arrows [W/m^2].
    magnitude : ndarray, shape (n,)
        Heat-flux magnitude [W/m^2]; colours the arrows.
    elements : ndarray of int, shape (n,)
        Global element ids of the kept elements.
    time : float
        Time of the step [s].
    title : str
        Plot title, including the time of the step.
    """

    xy: ndarray
    q: ndarray
    magnitude: ndarray
    elements: ndarray
    time: float
    title: str


def _thin(xy: ndarray, density: int) -> ndarray:
    """Positions (into ``xy``) of the elements kept: one per occupied square grid cell.

    The grid spans the bounding box of ``xy`` from its lower-left corner with square cells of
    size ``extent / density``, where ``extent`` is the larger of the two ranges. In each
    occupied cell the element whose centroid is nearest the cell centre is kept.
    """
    lo = xy.min(axis=0)
    extent = float(np.max(xy.max(axis=0) - lo))
    h = extent / density if extent > 0.0 else 1.0
    ij = np.floor((xy - lo) / h).astype(int)
    n_i = int(ij[:, 0].max()) + 1
    key = ij[:, 0] + ij[:, 1] * (n_i + 1)
    centre = lo + (ij + 0.5) * h
    distance = np.sum((xy - centre) ** 2, axis=1)
    order = np.lexsort((distance, key))
    _, first = np.unique(key[order], return_index=True)
    return np.sort(order[first])


def vector_data(results: Results, step: int = -1, density: int = 30) -> VectorData:
    """Gather the arrows of a heat-flux vector plot.

    Parameters
    ----------
    results : Results
    step : int
        Stored step; negative counts from the end.
    density : int
        About this many arrows across the larger model dimension (at most
        ``(density + 1)`` arrows per row of grid cells).

    Returns
    -------
    VectorData
        Positions in metres, heat flux in W/m^2.

    Raises
    ------
    ModelError
        If ``density`` is less than 1, the step is out of range, or no element has a centroid.
    """
    if density < 1:
        raise ModelError(f"vector density must be at least 1, not {density}")
    flux = results.element_flux(step)
    time = float(results.times[step])
    centroids = results.mesh.element_centroids()
    ids = np.flatnonzero(np.all(np.isfinite(centroids), axis=1))
    if ids.size == 0:
        raise ModelError("the mesh has no elements to draw")
    xy = centroids[ids, :2]
    chosen = _thin(xy, density)
    ids = ids[chosen]
    q = flux[ids, :2]
    return VectorData(
        xy=xy[chosen],
        q=q,
        magnitude=np.linalg.norm(q, axis=1),
        elements=ids,
        time=time,
        title=f"Heat flux, t = {time:.6g} s",
    )


def vectors(
    results: Results,
    step: int = -1,
    density: int = 30,
    scale: float | None = None,
    ax: Axes | None = None,
    path: str | Path | None = None,
) -> Figure:
    """Heat-flux arrows at element centroids, coloured by magnitude.

    Parameters
    ----------
    results : Results
    step : int
        Stored step; negative counts from the end.
    density : int
        About this many arrows across the larger model dimension; see :func:`vector_data`.
    scale : float, optional
        Arrow length in units of the plotted flux [W/m^2] per axis unit, as Matplotlib's
        ``quiver``; ``None`` lets Matplotlib choose.
    ax : Axes, optional
        Draw into these axes (the colour bar is added to their figure); otherwise a new
        figure is made.
    path : str or Path, optional
        Also save the figure here (PNG, 200 dpi).

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ModelError
        For a density below 1 or an unknown step.
    """
    data = vector_data(results, step, density)
    fig, ax = _figure(ax)
    arrows = ax.quiver(
        data.xy[:, 0], data.xy[:, 1], data.q[:, 0], data.q[:, 1], data.magnitude,
        cmap="viridis", scale=scale, angles="xy",
    )
    _frame(fig, ax, arrows, "Heat flux [W/m²]", data.title)
    _save(fig, path, "vector plot")
    return fig
