"""Plots of results (M5). Every function takes a :class:`Results` and returns a ``Figure``.

Figures are built with ``matplotlib.figure.Figure`` and the Agg canvas, never ``pyplot``, so
nothing here opens a window and the GUI can pass its own ``ax`` to draw into.

The contour plot is split in two: :func:`contour_data` is a pure function that gathers the
arrays to be drawn (triangulation, values in display units, extrema, labels), and
:func:`contour` draws them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
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
from scipy.spatial import cKDTree

from ..core.errors import ModelError
from ..core.mesh import Mesh
from ..core.registry import element
from ..core.units import UnitSettings, from_si
from .path import sample as sample_path
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


def _display_temperature(results: Results, kelvin: ndarray) -> tuple[ndarray, str]:
    """Temperatures [K] converted to the model's display unit, and that unit's label."""
    units = _unit_settings(results)
    values = np.asarray(from_si(np.asarray(kelvin, dtype=float), "temperature", units), float)
    return values, _TEMPERATURE_LABEL[units.temperature]


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
        T, unit = _display_temperature(results, results.temperature(step))
        groups: list[tuple[int | None, ndarray, ndarray]] = [(None, np.arange(mesh.n_nodes), T)]
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


def contour_fields(results: Results) -> list[str]:
    """The contour fields these results can show, in the order of :data:`FIELDS`.

    A component field (``qx``, ``gradx``, ...) needs a mesh with that many dimensions.

    Parameters
    ----------
    results : Results

    Returns
    -------
    list of str
        Keys of :data:`FIELDS`.
    """
    dim = results.mesh.dim
    return [name for name, (_s, comp, _u, _t) in FIELDS.items() if comp is None or comp < dim]


def field_range(results: Results, field: str = "T") -> tuple[float, float]:
    """Smallest and largest value of a contour field over every stored step.

    Parameters
    ----------
    results : Results
    field : str
        One of :data:`FIELDS`.

    Returns
    -------
    vmin, vmax : float
        In display units (those of :func:`contour_data`).
    """
    lows: list[float] = []
    highs: list[float] = []
    for step in range(results.n_steps):
        data = contour_data(results, step, field)
        lows.append(data.vmin)
        highs.append(data.vmax)
    if not lows:
        raise ModelError("the results have no stored steps")
    return min(lows), max(highs)


def display_value(results: Results, field: str, value: float) -> tuple[float, str]:
    """Convert an SI field value (as returned by ``path.value_at``) to display units.

    Parameters
    ----------
    results : Results
    field : str
        One of :data:`FIELDS`.
    value : float
        SI value (K, W/m^2 or K/m); NaN stays NaN.

    Returns
    -------
    value : float
        In the display unit of the field (the unit :func:`contour_data` uses).
    unit : str
        Label of that unit.

    Raises
    ------
    ModelError
        For an unknown field.
    """
    if field not in FIELDS:
        raise ModelError(f"unknown contour field {field!r}; choose from {', '.join(FIELDS)}")
    source, component, si_unit, _name = FIELDS[field]
    units = _unit_settings(results)
    label = _TEMPERATURE_LABEL[units.temperature]
    if source == "T":
        return float(from_si(float(value), "temperature", units)), label
    if source == "flux":
        return float(value), si_unit
    # a gradient component or magnitude is a temperature difference per metre
    return float(from_si(float(value), "temperature_difference", units)), f"{label}/m"


# ------------------------------------------------------------------------------- helpers


#: A model whose height is below this fraction of its width gets a horizontal colour bar.
_WIDE_MODEL = 0.4
#: Margin around the model in a model view, as a fraction of its larger dimension.
_VIEW_MARGIN = 0.04
_CHART_SIZE = (7.5, 5.5)  # inches, for line charts
_VIEW_LONG_SIDE = 7.0  # inches, drawn length of the larger model dimension


def _bounds(mesh: Mesh) -> tuple[float, float, float, float]:
    """Bounding box ``(xmin, ymin, xmax, ymax)`` of a mesh [m]."""
    lo, hi = mesh.nodes.min(axis=0), mesh.nodes.max(axis=0)
    return float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])


def _ratio(bounds: tuple[float, float, float, float]) -> float:
    """Height over width of a bounding box (1 for a degenerate box)."""
    width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
    return height / width if width > 0.0 and height > 0.0 else 1.0


def _figure(
    ax: Axes | None, bounds: tuple[float, float, float, float] | None = None
) -> tuple[Figure, Axes]:
    """The figure and axes to draw into: ``ax`` if given, otherwise a new Agg figure.

    With the model's ``bounds`` a new figure is shaped to the model, so that a model view
    fills it instead of leaving large empty margins; without them it has the size of a
    line chart.
    """
    if ax is not None:
        return ax.figure, ax
    size = _CHART_SIZE
    if bounds is not None:
        ratio = _ratio(bounds)
        if ratio >= 1.0:  # tall model: colour bar at the side
            size = (float(np.clip(_VIEW_LONG_SIDE / ratio + 2.4, 4.5, 9.0)), _VIEW_LONG_SIDE)
        elif ratio >= _WIDE_MODEL:
            size = (_VIEW_LONG_SIDE + 2.0, float(np.clip(_VIEW_LONG_SIDE * ratio + 1.2, 3.5, 7.0)))
        else:  # wide, flat model: colour bar underneath
            size = (_VIEW_LONG_SIDE + 1.5, float(np.clip(_VIEW_LONG_SIDE * ratio + 2.6, 3.0, 6.0)))
    fig = Figure(figsize=size, layout="constrained")
    FigureCanvasAgg(fig)
    return fig, fig.add_subplot(1, 1, 1)


def _frame(
    fig: Figure,
    ax: Axes,
    mappable: ScalarMappable,
    label: str,
    title: str,
    bounds: tuple[float, float, float, float] | None = None,
) -> None:
    """Colour bar, equal aspect, view limits, axis labels and title of a model view."""
    wide = bounds is not None and _ratio(bounds) < _WIDE_MODEL
    fig.colorbar(
        mappable, ax=ax, label=label, orientation="horizontal" if wide else "vertical",
        shrink=0.9, pad=0.03,
    )
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("y [m]")
    ax.set_title(title)
    if bounds is None:
        ax.autoscale_view()
    else:  # show the whole model with a small margin, so nothing at its edge is clipped
        margin = _VIEW_MARGIN * max(bounds[2] - bounds[0], bounds[3] - bounds[1])
        ax.set_xlim(bounds[0] - margin, bounds[2] + margin)
        ax.set_ylim(bounds[1] - margin, bounds[3] + margin)


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
    bounds = _bounds(results.mesh)
    fig, ax = _figure(ax, bounds)
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
        ax.plot([xy[0]], [xy[1]], marker, color="white", mec="black", ms=7, clip_on=False)
        # put the label on the side of the marker that faces the middle of the model
        right = xy[0] <= 0.5 * (bounds[0] + bounds[2])
        up = xy[1] <= 0.5 * (bounds[1] + bounds[3])
        ax.annotate(
            f"{text} {value:.4g}", xy=(xy[0], xy[1]),
            xytext=(7 if right else -7, 7 if up else -7), textcoords="offset points",
            ha="left" if right else "right", va="bottom" if up else "top", fontsize=8,
            bbox={"boxstyle": "round,pad=0.2", "fc": "white", "alpha": 0.8, "lw": 0.3},
        )
    _frame(fig, ax, mappable, data.label, data.title, bounds)
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
    bounds = _bounds(results.mesh)
    fig, ax = _figure(ax, bounds)
    # arrows are centred on their element centroid, so they stay inside the model outline
    arrows = ax.quiver(
        data.xy[:, 0], data.xy[:, 1], data.q[:, 0], data.q[:, 1], data.magnitude,
        cmap="viridis", scale=scale, angles="xy", pivot="mid",
    )
    # the outline of the model and of its regions: the mesh facets (end nodes of each)
    nodes = results.mesh.nodes
    for facets in results.mesh.facets:
        ax.add_collection(
            LineCollection(nodes[facets.conn[:, :2]], colors="0.6", linewidths=0.6, zorder=0)
        )
    _frame(fig, ax, arrows, "Heat flux [W/m²]", data.title, bounds)
    _save(fig, path, "vector plot")
    return fig


# ------------------------------------------------------------------------------- history

#: Statistics of the temperature over a node set, by name.
STATS: dict[str, Callable[..., ndarray]] = {"min": np.min, "max": np.max, "mean": np.mean}

#: Histories with fewer steps than this are drawn with a marker at every step.
_MARKER_LIMIT = 50


@dataclass
class HistoryData:
    """Line-chart data of a history plot.

    Attributes
    ----------
    times : ndarray, shape (n_steps,)
        Time of every stored step [s].
    series : dict of str to ndarray
        Label -> values, each of shape (n_steps,), in the units of ``ylabel``.
    ylabel : str
        Vertical axis label, e.g. ``"Temperature [K]"``.
    title : str
        Plot title.
    """

    times: ndarray
    series: dict[str, ndarray]
    ylabel: str
    title: str


def _points_array(points: Sequence[tuple[float, float]]) -> ndarray:
    """Points as an ``(n, 2)`` float array; anything else is a :class:`ModelError`."""
    try:
        xy = np.asarray(points, dtype=float)
    except (TypeError, ValueError):
        raise ModelError("points must be (x, y) pairs") from None
    if xy.ndim != 2 or xy.shape[1] != 2 or xy.shape[0] == 0:
        raise ModelError("points must be a non-empty sequence of (x, y) pairs")
    return xy


def nearest_nodes(mesh: Mesh, points: Sequence[tuple[float, float]]) -> ndarray:
    """Index of the mesh node nearest to each point.

    Parameters
    ----------
    mesh : Mesh
    points : sequence of (x, y)
        Positions [m].

    Returns
    -------
    ndarray of int, shape (n,)
    """
    _, index = cKDTree(mesh.nodes[:, :2]).query(_points_array(points))
    return np.asarray(index, dtype=int)


def _selected_temperatures(results: Results, nodes: ndarray) -> ndarray:
    """Temperatures [K] of some nodes at every stored step, shape (n_steps, len(nodes))."""
    rows = [results.temperature(step)[nodes] for step in range(results.n_steps)]
    return np.asarray(rows, dtype=float).reshape(len(rows), nodes.size)


def history_data(
    results: Results,
    points: Sequence[tuple[float, float]] | None = None,
    nodes: Sequence[int] | None = None,
) -> HistoryData:
    """Gather the temperature history of some nodes.

    Parameters
    ----------
    results : Results
    points : sequence of (x, y), optional
        Positions [m]; each is replaced by its nearest mesh node.
    nodes : sequence of int, optional
        Node indices.

    Returns
    -------
    HistoryData
        One series per node, labelled with the node's coordinates, in the model's display
        unit (K when the results have no model).

    Raises
    ------
    ModelError
        If exactly one of ``points`` and ``nodes`` is not given, or a node index is out of
        range.
    """
    if (points is None) == (nodes is None):
        raise ModelError("history: give exactly one of points= and nodes=")
    mesh = results.mesh
    if points is not None:
        index = nearest_nodes(mesh, points)
    else:
        raw = np.asarray(nodes)
        if raw.size == 0 or not np.issubdtype(raw.dtype, np.integer):
            raise ModelError("nodes must be a non-empty sequence of node indices")
        index = raw.reshape(-1).astype(int)
    if index.min() < 0 or index.max() >= mesh.n_nodes:
        raise ModelError(f"node index out of range; the mesh has {mesh.n_nodes} nodes")
    values, unit = _display_temperature(results, _selected_temperatures(results, index))
    xy = mesh.nodes[index, :2]
    series = {
        f"node {int(node)} ({x:g}, {y:g})": values[:, k].copy()
        for k, (node, (x, y)) in enumerate(zip(index, xy.tolist(), strict=True))
    }
    return HistoryData(
        times=np.asarray(results.times, dtype=float),
        series=series,
        ylabel=f"Temperature [{unit}]",
        title="Temperature history",
    )


def history_stat_data(results: Results, selection: str, stat: str = "mean") -> HistoryData:
    """Gather the minimum, maximum or mean temperature over a node set, at every step.

    Parameters
    ----------
    results : Results
    selection : str
        Name of a node set in ``results.mesh.node_sets``.
    stat : {"min", "max", "mean"}

    Returns
    -------
    HistoryData
        One series, labelled e.g. ``"mean of corner"``, in the model's display unit.

    Raises
    ------
    ModelError
        For an unknown statistic, an unknown or empty node set.
    """
    if stat not in STATS:
        raise ModelError(f"unknown statistic {stat!r}; choose from {', '.join(STATS)}")
    node_sets = results.mesh.node_sets
    if selection not in node_sets:
        raise ModelError(
            f"unknown node set {selection!r} (available: {', '.join(node_sets) or 'none'})"
        )
    index = np.asarray(node_sets[selection], dtype=int).reshape(-1)
    if index.size == 0:
        raise ModelError(f"node set {selection!r} has no nodes")
    values, unit = _display_temperature(results, _selected_temperatures(results, index))
    return HistoryData(
        times=np.asarray(results.times, dtype=float),
        series={f"{stat} of {selection}": STATS[stat](values, axis=1)},
        ylabel=f"Temperature [{unit}]",
        title=f"{stat} temperature over {selection}",
    )


def heat_flow_history_data(results: Results, bc_names: Sequence[str] | None = None) -> HistoryData:
    """Gather the heat flow through boundary conditions, at every step.

    Parameters
    ----------
    results : Results
    bc_names : sequence of str, optional
        Boundary-condition names; default all of ``results.heat_flow_names``.

    Returns
    -------
    HistoryData
        One series per name, in watts, positive when heat enters the body.

    Raises
    ------
    ModelError
        For an unknown name (see :meth:`Results.heat_flow`) or when there is none to show.
    """
    names = results.heat_flow_names if bc_names is None else list(bc_names)
    if not names:
        raise ModelError("the results store no heat flow to plot")
    return HistoryData(
        times=np.asarray(results.times, dtype=float),
        series={name: np.asarray(results.heat_flow(name), dtype=float) for name in names},
        ylabel="Heat flow into the body [W]",
        title="Heat flow through boundary conditions",
    )


def _draw_history(data: HistoryData, ax: Axes | None, path: str | Path | None, what: str) -> Figure:
    """Draw one line per series, with a legend, grid and labelled axes."""
    fig, ax = _figure(ax)
    marker = "o" if data.times.size < _MARKER_LIMIT else None
    for label, values in data.series.items():
        ax.plot(data.times, values, marker=marker, ms=3.5, label=label)
    ax.set_xlabel("Time [s]")
    ax.set_ylabel(data.ylabel)
    ax.set_title(data.title)
    ax.grid(True)
    ax.legend()
    _save(fig, path, what)
    return fig


# --------------------------------------------------------------------------------- path


@dataclass
class PathData:
    """Line-chart data of a path plot.

    Attributes
    ----------
    s : ndarray, shape (n,)
        Arc length along the path [m].
    values : ndarray, shape (n,)
        Field in display units (``ylabel``); NaN where the path leaves the mesh.
    xlabel, ylabel, title : str
        Axis labels and plot title.
    """

    s: ndarray
    values: ndarray
    ylabel: str
    title: str
    xlabel: str = "Distance along path [m]"


def path_data(
    results: Results,
    step: int,
    polyline: Sequence[Sequence[float]],
    n: int = 200,
    field: str = "T",
) -> PathData:
    """Gather the values of a field along a polyline, in display units.

    Parameters
    ----------
    results : Results
    step : int
        Stored step; negative counts from the end.
    polyline : sequence of (x, y)
        Vertices [m].
    n : int
        Number of sample points.
    field : str
        One of :data:`FIELDS`. Temperature is in the model's display unit, flux in W/m^2,
        gradient in K/m (degF/m when the model displays degF).

    Raises
    ------
    ModelError
        For an unknown field or step, or an invalid polyline.
    """
    if field not in FIELDS:
        raise ModelError(f"unknown path field {field!r}; choose from {', '.join(FIELDS)}")
    source, _, si_unit, name = FIELDS[field]
    times = results.times
    if not -times.size <= step < times.size:
        raise ModelError(f"step {step} is out of range; the file has {times.size} step(s)")
    s, values = sample_path(results, step, polyline, n, field)
    if source == "T":
        values, unit = _display_temperature(results, values)
    elif source == "flux":
        unit = si_unit
    else:
        units = _unit_settings(results)
        values = np.asarray(from_si(values, "temperature_difference", units))
        unit = f"{_TEMPERATURE_LABEL[units.temperature]}/m"
    return PathData(
        s=s,
        values=np.asarray(values, dtype=float),
        ylabel=f"{name} [{unit}]",
        title=f"{name} along path, t = {float(times[step]):.6g} s",
    )


def path(
    results: Results,
    polyline: Sequence[Sequence[float]],
    step: int = -1,
    field: str = "T",
    n: int = 200,
    ax: Axes | None = None,
    path: str | Path | None = None,
) -> Figure:
    """A field against distance along a polyline.

    Parameters
    ----------
    results : Results
    polyline : sequence of (x, y)
        Path vertices [m]; the line breaks where the path leaves the mesh.
    step : int
        Stored step; negative counts from the end.
    field : str
        ``T``, ``qx``, ``qy``, ``qmag``, ``gradx``, ``grady`` or ``gradmag``.
    n : int
        Number of sample points.
    ax : Axes, optional
        Draw into these axes; otherwise a new figure is made.
    path : str or Path, optional
        Also save the figure here (PNG, 200 dpi).

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ModelError
        See :func:`path_data`.
    """
    data = path_data(results, step, polyline, n, field)
    fig, ax = _figure(ax)
    ax.plot(data.s, data.values)
    ax.set_xlabel(data.xlabel)
    ax.set_ylabel(data.ylabel)
    ax.set_title(data.title)
    ax.grid(True)
    _save(fig, path, "path plot")
    return fig


def history(
    results: Results,
    points: Sequence[tuple[float, float]] | None = None,
    nodes: Sequence[int] | None = None,
    ax: Axes | None = None,
    path: str | Path | None = None,
) -> Figure:
    """Temperature against time at some nodes.

    Parameters
    ----------
    results : Results
    points : sequence of (x, y), optional
        Positions [m]; each is plotted at its nearest mesh node.
    nodes : sequence of int, optional
        Node indices. Give exactly one of ``points`` and ``nodes``.
    ax : Axes, optional
        Draw into these axes; otherwise a new figure is made.
    path : str or Path, optional
        Also save the figure here (PNG, 200 dpi).

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ModelError
        See :func:`history_data`.
    """
    return _draw_history(history_data(results, points, nodes), ax, path, "history plot")


def history_stat(
    results: Results,
    selection: str,
    stat: str = "mean",
    ax: Axes | None = None,
    path: str | Path | None = None,
) -> Figure:
    """Minimum, maximum or mean temperature over a node set, against time.

    Parameters
    ----------
    results : Results
    selection : str
        Name of a node set of the mesh.
    stat : {"min", "max", "mean"}
    ax : Axes, optional
        Draw into these axes; otherwise a new figure is made.
    path : str or Path, optional
        Also save the figure here (PNG, 200 dpi).

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ModelError
        See :func:`history_stat_data`.
    """
    data = history_stat_data(results, selection, stat)
    return _draw_history(data, ax, path, "history statistic plot")


def heat_flow_history(
    results: Results,
    bc_names: Sequence[str] | None = None,
    ax: Axes | None = None,
    path: str | Path | None = None,
) -> Figure:
    """Heat flow into the body through boundary conditions, against time.

    Parameters
    ----------
    results : Results
    bc_names : sequence of str, optional
        Boundary conditions to plot; default all of them.
    ax : Axes, optional
        Draw into these axes; otherwise a new figure is made.
    path : str or Path, optional
        Also save the figure here (PNG, 200 dpi).

    Returns
    -------
    matplotlib.figure.Figure

    Raises
    ------
    ModelError
        See :func:`heat_flow_history_data`.
    """
    data = heat_flow_history_data(results, bc_names)
    return _draw_history(data, ax, path, "heat flow plot")
