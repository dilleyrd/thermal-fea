"""Matplotlib implementation of the viewport (:class:`~thermalfea.gui.scene.SceneView`).

This is the only GUI module that draws the model view with Matplotlib artists (Plan §7
rule 8). One axes with equal aspect carries separate layers, each a few artists with a fixed
``zorder``:

========  ==========================================  =====================
layer     contents                                    zorder
========  ==========================================  =====================
geometry  surface fills, curves, points               1.0 .. 1.3
mesh      per-element colors, element outlines       1.9, 2.0
results   field, arrows, extrema markers              3.0 .. 3.3
symbols   load / boundary-condition symbols, legend   4.0
overlay   named layers of text, markers, polylines    4.5
highlight selection and hover overlays, rubber band   5.0, 5.5
========  ==========================================  =====================

The overlay layers (:meth:`MplSceneView.set_overlay`) are replaced one named layer at a
time and survive ``set_field``, ``set_mesh``, ``set_symbols`` and ``fit``; they are not part of
the fit bounds, and ``set_geometry(None)`` (a new model) clears them all.

Element outlines are lifted above the results (``Z_MESH_OVER_FIELD``) when a field is shown
with ``show_mesh``; without ``show_mesh`` the mesh layer is hidden while a field is shown.

Hover and selection overlays are *animated* artists drawn with blitting: after every full
draw (``draw_event``) the canvas background is cached with ``copy_from_bbox``; a hover or
rubber-band update restores the cached region, draws only the overlay artists and blits.
Every change of the static layers, a zoom or pan, and every resize triggers a full draw
(``draw_idle``) which refreshes the cache; until it has happened the next overlay update
performs one synchronous draw.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.artist import Artist
from matplotlib.backend_bases import MouseEvent
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.collections import LineCollection, PathCollection, PolyCollection
from matplotlib.figure import Figure
from matplotlib.legend import Legend
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.path import Path
from matplotlib.tri import Triangulation
from numpy import ndarray
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget
from scipy.spatial import cKDTree

from thermalfea.core.forms import unit_label
from thermalfea.core.mesh import Mesh
from thermalfea.core.units import from_si
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.gui import picking
from thermalfea.gui.scene import (
    ELEMENT_DIM,
    MODE_DIM,
    NODE_DIM,
    FieldDisplay,
    LoadSymbol,
    OverlayItem,
    OverlayMarker,
    OverlayPolyline,
    OverlayText,
    kind_color,
)
from thermalfea.post.plots import DisplayMesh, display_triangulation

if TYPE_CHECKING:
    from thermalfea.gui.document import Document
    from thermalfea.gui.main_window import MainWindow

log = logging.getLogger(__name__)


class _QuietAspect(logging.Filter):
    """Drop Matplotlib's "Ignoring fixed ... limits" notice.

    The viewport uses an equal aspect with ``adjustable="datalim"`` and fixed limits on
    purpose: the data limits follow the window shape, which is the intended behaviour.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return not record.getMessage().startswith("Ignoring fixed")


logging.getLogger("matplotlib.axes._base").addFilter(_QuietAspect())

#: Layer z-orders (see the module docstring).
Z_GEOMETRY = 1.0
Z_MESH = 2.0
Z_RESULTS = 3.0
Z_SYMBOLS = 4.0
Z_AXIS = 4.2
Z_OVERLAY = 4.5
Z_HIGHLIGHT = 5.0
Z_MESH_OVER_FIELD = Z_RESULTS + 0.5
#: Color-by-part fills: above the plain surface fill, below curves and mesh lines.
Z_ENTITY_COLORS = Z_GEOMETRY + 0.1
_ENTITY_ALPHA = 0.35

#: Picking tolerance [screen pixels].
PICK_TOL_PX = 8.0
#: Mouse travel [pixels] after which a left press becomes a rubber-band drag.
DRAG_PX = 4.0
#: Zoom factor per wheel step.
ZOOM_STEP = 1.2
#: Margin around the content when fitting, as a fraction of its larger extent.
FIT_MARGIN = 0.05
#: Axes rectangle in figure coordinates (left, bottom, width, height).
AXES_RECT = (0.01, 0.01, 0.98, 0.93)

#: Selection and hover overlays use colors that no load kind uses (scene.KIND_COLORS):
#: an orange selection on a convection edge looked like an adiabatic one (2026-11-23).
_SELECT_COLOR = "#fcc419"
_HOVER_COLOR = "#000000"
_BAND_COLOR = "#1c7ed6"
#: The axis of symmetry of an axisymmetric model; not one of scene.KIND_COLORS.
_AXIS_COLOR = "#087f5b"
#: Default color of overlay markers and polylines.
_OVERLAY_COLOR = "#c2255c"
_SURFACE_FILL = "#adb5bd"
_CURVE_COLOR = "#343a40"
_POINT_COLOR = "#212529"
_MESH_COLOR = "#495057"
#: A field whose range is below this fraction of its magnitude is drawn as uniform (a range
#: at round-off level would give contour levels that are not increasing).
_UNIFORM_RTOL = 1e-9
_LEFT, _MIDDLE = 1, 2
_GEOMETRIC_MODES = ("point", "curve", "surface")
_FEW_ELEMENTS = 32  # up to this many selected elements are looked up one by one
_PLANE = 2  # coordinates of the viewport plane (x, y)


def _is_ctrl(event: MouseEvent) -> bool:
    """``True`` if Ctrl (Cmd on macOS) was held for ``event``."""
    mods = getattr(event, "modifiers", None) or ()
    return "ctrl" in mods or "control" in str(event.key or "") or "cmd" in mods


def _surface_path(loops: list[ndarray]) -> Path:
    """One compound path for a surface: the largest loop counter-clockwise, holes clockwise."""
    areas = [picking.loop_area(lp) for lp in loops]
    outer = int(np.argmax(np.abs(areas))) if areas else 0
    verts: list[ndarray] = []
    codes: list[int] = []
    for k, loop in enumerate(loops):
        ccw = (areas[k] > 0.0) == (k == outer)
        pts = loop if ccw else loop[::-1]
        verts.append(np.vstack([pts, pts[:1]]))
        codes += [Path.MOVETO, *([Path.LINETO] * (pts.shape[0] - 1)), Path.CLOSEPOLY]
    if not verts:
        return Path(np.zeros((0, _PLANE)))
    return Path(np.vstack(verts), codes)


class _Overlay:
    """Four animated artists (polygons, compound paths, lines, markers) in one color."""

    def __init__(self, ax: object, color: str, zorder: float, alpha: float) -> None:
        self.polys = PolyCollection(
            [], facecolors=color, edgecolors="none", alpha=alpha, animated=True, zorder=zorder
        )
        self.paths = PathCollection(
            [], facecolors=color, edgecolors=color, alpha=alpha, linewidths=1.5,
            animated=True, zorder=zorder,
        )
        self.lines = LineCollection([], colors=color, linewidths=3.0, animated=True, zorder=zorder)
        self.points = Line2D(
            [], [], ls="none", marker="o", ms=9, mfc=color, mec="black", mew=0.8,
            animated=True, zorder=zorder + 0.1,
        )
        ax.add_collection(self.polys, autolim=False)  # type: ignore[attr-defined]
        ax.add_collection(self.paths, autolim=False)  # type: ignore[attr-defined]
        ax.add_collection(self.lines, autolim=False)  # type: ignore[attr-defined]
        ax.add_artist(self.points)  # type: ignore[attr-defined]

    @property
    def artists(self) -> list[Artist]:
        return [self.polys, self.paths, self.lines, self.points]

    def set(
        self,
        polys: ndarray | list[ndarray] | None = None,
        paths: list[Path] | None = None,
        lines: list[ndarray] | None = None,
        points: ndarray | None = None,
    ) -> None:
        """Replace the contents; ``None`` clears that part."""
        self.polys.set_verts(polys if polys is not None else [])
        self.paths.set_paths(paths if paths is not None else [])
        self.lines.set_segments(lines if lines is not None else [])
        pts = np.zeros((0, _PLANE)) if points is None else np.asarray(points, float)
        self.points.set_data(pts[:, 0], pts[:, 1])

    def clear(self) -> None:
        self.set()

    def is_empty(self) -> bool:
        """``True`` if nothing is drawn."""
        return not (
            len(self.polys.get_paths()) or len(self.paths.get_paths())
            or len(self.lines.get_segments()) or len(self.points.get_xdata())
        )


class MplSceneView(QObject):
    """Matplotlib viewport implementing :class:`~thermalfea.gui.scene.SceneView`.

    Signals
    -------
    selection_changed(int, list)
        ``(dim, tags)`` after a click, Ctrl-click or box selection; the full current
        selection with sorted tags (see :mod:`thermalfea.gui.scene` for nodes/elements).
    point_picked(float, float, float)
        ``(x, y, z)`` [m] of a left click (z = 0).
    entity_hovered(int, int)
        ``(dim, tag)`` of the geometry entity under the pointer in a point / curve /
        surface pick mode; ``(-1, -1)`` for none (also in the none, node and element modes).
    entity_clicked(int, int)
        ``(dim, tag)`` of a plain single click (no Ctrl, no box drag) on a geometry entity
        in a point / curve / surface pick mode; ``(-1, -1)`` for a plain click on empty space.
        Box picks and Ctrl clicks do not emit it.
    coordinates_changed(float, float)
        Cursor position [m] while it moves over the axes.

    Parameters
    ----------
    parent : QObject, optional
        Parent object.
    """

    selection_changed = Signal(int, list)
    point_picked = Signal(float, float, float)
    entity_hovered = Signal(int, int)
    entity_clicked = Signal(int, int)
    coordinates_changed = Signal(float, float)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fig = Figure(figsize=(6.4, 4.8))
        self._canvas = FigureCanvasQTAgg(self._fig)
        self._ax = self._fig.add_axes(AXES_RECT)
        self._ax.set_aspect("equal", adjustable="datalim")
        self._ax.set_axis_off()
        self._ax.set_autoscale_on(False)
        self._ax.set_xlim(0.0, 1.0)
        self._ax.set_ylim(0.0, 1.0)
        #: view centre x, y [m] and data units [m] per pixel; the axes limits follow it
        self._view = (0.5, 0.5, 1.0 / 640.0)

        # model state
        self._built: BuiltGeometry | None = None
        self._mesh: Mesh | None = None
        self._display: DisplayMesh | None = None
        self._field: FieldDisplay | None = None
        self._layers: dict[str, list[Artist]] = {
            "geometry": [], "mesh": [], "results": [], "symbols": [], "entity_colors": [],
        }
        self._entity_colors: tuple[int, dict[int, str], list[tuple[str, str]]] = (
            _PLANE, {}, [],
        )
        self._overlays: dict[str, list[Artist]] = {}
        self._mesh_lines: list[LineCollection] = []
        self._mesh_fill: PolyCollection | None = None
        self._colorbar: object | None = None

        # picking structures (geometry)
        self._pt_tags: list[int] = []
        self._pt_xy = np.zeros((0, _PLANE))
        self._pt_index: dict[int, int] = {}
        self._curve_tags: list[int] = []
        self._curve_lines: list[ndarray] = []
        self._seg_a = self._seg_b = np.zeros((0, _PLANE))
        self._seg_owner = np.zeros(0, dtype=int)
        self._surf_tags: list[int] = []
        self._surf_loops: list[list[ndarray]] = []
        self._surf_area: list[float] = []
        self._surf_bbox = np.zeros((0, 4))
        # picking structures (mesh), built lazily
        self._node_tree: cKDTree | None = None
        self._trifinder: Callable[[float, float], int] | None = None
        self._elem_ids: ndarray | None = None
        self._elem_pos: ndarray | None = None
        self._elem_centroids: ndarray | None = None

        # interaction state
        self._mode = "none"
        self._sel_dim = 0
        self._sel_tags: set[int] = set()
        self._hover: tuple[int, int] | None = None
        self._hover_sent: tuple[int, int] = (-1, -1)  # last value of entity_hovered
        self._press: tuple[float, float, float, float, bool] | None = None
        self._banding = False
        self._pan: tuple[float, float, tuple[float, float], tuple[float, float]] | None = None

        # overlays and blitting
        self._selection = _Overlay(self._ax, _SELECT_COLOR, Z_HIGHLIGHT, 0.45)
        self._hover_overlay = _Overlay(self._ax, _HOVER_COLOR, Z_HIGHLIGHT, 0.25)
        self._band = Rectangle(
            (0.0, 0.0), 0.0, 0.0, fill=True, facecolor=_BAND_COLOR, edgecolor=_BAND_COLOR,
            alpha=0.2, animated=True, visible=False, zorder=Z_HIGHLIGHT + 0.5,
        )
        self._ax.add_artist(self._band)
        # the axis of symmetry x = 0: x in data, y in axes coordinates, so it spans the view
        self._axis_line = Line2D(
            [0.0, 0.0], [0.0, 1.0], color=_AXIS_COLOR, linestyle="-.", linewidth=1.4,
            transform=self._ax.get_xaxis_transform(), zorder=Z_AXIS, visible=False,
        )
        self._ax.add_artist(self._axis_line)
        self._background: object | None = None
        self._background_valid = False

        canvas = self._canvas
        canvas.mpl_connect("draw_event", self._on_draw)
        canvas.mpl_connect("resize_event", self._on_resize)
        canvas.mpl_connect("scroll_event", self._on_scroll)
        canvas.mpl_connect("button_press_event", self._on_press)
        canvas.mpl_connect("button_release_event", self._on_release)
        canvas.mpl_connect("motion_notify_event", self._on_motion)
        canvas.mpl_connect("figure_leave_event", self._on_leave)

    # ------------------------------------------------------------------ SceneView API

    def widget(self) -> QWidget:
        """The canvas widget to install in the main window."""
        return self._canvas

    @property
    def axes(self):  # noqa: ANN201 - Matplotlib Axes; kept for tests and tools
        """The model-view axes."""
        return self._ax

    @property
    def canvas(self) -> FigureCanvasQTAgg:
        """The Qt canvas."""
        return self._canvas

    def set_geometry(self, built: BuiltGeometry | None) -> None:
        """Show the built geometry (surface fills, curves, points); ``None`` clears it."""
        had_content = self._has_content()
        self._clear_layer("geometry")
        self._clear_layer("entity_colors")
        self._entity_colors = (_PLANE, {}, [])
        self._built = built
        self._index_geometry(built)
        if built is not None:
            self._draw_geometry(built)
        else:
            for name in list(self._overlays):
                self._remove_overlay(name)
        self._reset_overlays(geometry=True)
        self._after_content_change(had_content)

    def set_mesh(self, mesh: Mesh | None, color_by: ndarray | None = None) -> None:
        """Show a mesh; ``None`` clears it.

        Parameters
        ----------
        mesh : Mesh or None
        color_by : ndarray, shape (n_elements,), optional
            One value per element, in the order of the concatenated element blocks, drawn
            as a color map under the element outlines (e.g. the region id).
        """
        had_content = self._has_content()
        self._clear_layer("mesh")
        self._mesh_lines = []
        self._mesh_fill = None
        self._mesh = mesh
        self._display = None
        self._node_tree = self._trifinder = None
        self._elem_ids = self._elem_pos = self._elem_centroids = None
        if mesh is not None:
            self._display = display_triangulation(mesh)
            self._draw_mesh(mesh, self._display, color_by)
        self._apply_mesh_visibility()
        self._reset_overlays()
        self._after_content_change(had_content)

    def set_field(self, spec: FieldDisplay | None) -> None:
        """Show a contour and/or vector display; ``None`` clears it."""
        self._clear_layer("results")
        self._field = spec
        if spec is not None:
            self._draw_field(spec)
        self._apply_mesh_visibility()
        self._apply_entity_color_visibility()
        self._invalidate()

    def set_symbols(self, symbols: list[LoadSymbol]) -> None:
        """Show load symbols (colored by ``kind``, with a legend); an empty list clears."""
        self._clear_layer("symbols")
        if symbols and self._built is not None:
            self._draw_symbols(symbols, self._built)
        self._invalidate()

    def set_entity_colors(
        self, dim: int, colors: dict[int, str], legend: list[tuple[str, str]]
    ) -> None:
        """Fill geometry entities of dimension ``dim`` with colors and show a legend.

        Only surfaces can be filled; holes stay empty. The fills sit above the plain surface
        fill and below the curves, mesh, symbols and highlights; they and their legend are
        hidden while a field is shown. Empty ``colors`` and ``legend`` clear both.
        """
        self._clear_layer("entity_colors")
        self._entity_colors = (int(dim), dict(colors), list(legend))
        if self._built is not None and (colors or legend):
            self._draw_entity_colors()
        self._apply_entity_color_visibility()
        self._invalidate()

    def _draw_entity_colors(self) -> None:
        dim, colors, legend = self._entity_colors
        ax = self._ax
        if dim == _PLANE and colors:
            lookup = dict(zip(self._surf_tags, self._surf_loops, strict=True))
            tags = [t for t in colors if t in lookup]
            if tags:
                fills = PathCollection(
                    [_surface_path(lookup[t]) for t in tags],
                    facecolors=[colors[t] for t in tags], edgecolors="none",
                    alpha=_ENTITY_ALPHA, zorder=Z_ENTITY_COLORS,
                )
                ax.add_collection(fills, autolim=False)
                self._add("entity_colors", fills)
        if legend:
            handles = [Patch(facecolor=c, edgecolor="none", alpha=_ENTITY_ALPHA) for _, c in legend]
            box = Legend(ax, handles, [label for label, _ in legend], loc="upper left", fontsize=8)
            box.set_zorder(Z_SYMBOLS + 0.5)
            ax.add_artist(box)  # a second artist: ``ax.legend`` keeps the load-symbol legend
            self._add("entity_colors", box)

    def _apply_entity_color_visibility(self) -> None:
        for artist in self._layers["entity_colors"]:
            artist.set_visible(self._field is None)

    def set_overlay(self, layer: str, items: list[OverlayItem]) -> None:
        """Replace the named overlay layer as a whole; an empty list clears it.

        Items are :class:`~thermalfea.gui.scene.OverlayText`, ``OverlayMarker`` and
        ``OverlayPolyline`` in model coordinates [m]. Other layers are not touched.
        """
        self._remove_overlay(layer)
        artists: list[Artist] = []
        for item in items:
            artists.extend(self._draw_overlay_item(item))
        if artists:
            self._overlays[layer] = artists
        self._invalidate()

    def overlay_artists(self, layer: str) -> list[Artist]:
        """The artists of an overlay layer (empty when the layer is empty or unknown)."""
        return list(self._overlays.get(layer, []))

    def _remove_overlay(self, layer: str) -> None:
        for artist in self._overlays.pop(layer, []):
            try:
                artist.remove()
            except (ValueError, NotImplementedError):  # pragma: no cover - defensive
                log.debug("overlay artist already removed")

    def _draw_overlay_item(self, item: OverlayItem) -> list[Artist]:
        ax = self._ax
        out: list[Artist] = []
        bbox = {"boxstyle": "round,pad=0.2", "fc": "white", "alpha": 0.75, "lw": 0.3}
        if isinstance(item, OverlayPolyline):
            if len(item.points) >= _PLANE:
                pts = np.asarray(item.points, float).reshape(-1, _PLANE)
                line = Line2D(
                    pts[:, 0], pts[:, 1], color=item.color or _OVERLAY_COLOR, lw=1.8,
                    zorder=Z_OVERLAY,
                )
                ax.add_artist(line)
                out.append(line)
        elif isinstance(item, OverlayMarker):
            dot = Line2D(
                [item.x], [item.y], ls="none", marker="o", ms=7,
                mfc=item.color or _OVERLAY_COLOR, mec="black", mew=0.8, zorder=Z_OVERLAY,
            )
            ax.add_artist(dot)
            out.append(dot)
            if item.text:
                note = ax.annotate(
                    item.text, xy=(item.x, item.y), xytext=(7, 7), textcoords="offset points",
                    fontsize=8, zorder=Z_OVERLAY + 0.1, annotation_clip=False, bbox=bbox,
                )
                out.append(note)
        elif isinstance(item, OverlayText):
            note = ax.annotate(
                item.text, xy=(item.x, item.y), ha="center", va="center", fontsize=8,
                color=item.color or "black", zorder=Z_OVERLAY, annotation_clip=False,
                bbox=bbox,
            )
            out.append(note)
        return out

    def set_axis_visible(self, visible: bool) -> None:
        """Show or hide the axis of symmetry x = 0 (a dash-dot line, not pickable)."""
        if self._axis_line.get_visible() != bool(visible):
            self._axis_line.set_visible(bool(visible))
            self._invalidate()

    @property
    def axis_visible(self) -> bool:
        """``True`` while the axis of symmetry is shown."""
        return bool(self._axis_line.get_visible())

    def set_selection_mode(self, mode: str) -> None:
        """Choose what can be picked: ``none``, ``point``, ``curve``, ``surface``,
        ``node`` or ``element``. Clears the hover; a selection of another kind is cleared
        and announced with an empty ``selection_changed``.

        Raises
        ------
        ValueError
            For an unknown mode.
        """
        if mode != "none" and mode not in MODE_DIM:
            raise ValueError(f"unknown selection mode {mode!r}")
        if mode == self._mode:
            return
        self._mode = mode
        self._hover = None
        self._hover_overlay.clear()
        self._announce_hover()
        self._press, self._banding = None, False
        self._band.set_visible(False)
        had_selection = bool(self._sel_tags)
        old_dim = self._sel_dim
        self._sel_tags = set()
        self._selection.clear()
        if had_selection:
            self._sel_dim = MODE_DIM.get(mode, old_dim)
            self.selection_changed.emit(self._sel_dim, [])
        self._blit()

    def layer_artists(self, layer: str) -> list[Artist]:
        """The static artists of a layer: ``geometry``, ``mesh``, ``results`` or ``symbols``."""
        return list(self._layers[layer])

    @property
    def hover(self) -> tuple[int, int] | None:
        """``(dim, tag)`` of the entity under the cursor, or ``None``."""
        return self._hover

    @property
    def selection_mode(self) -> str:
        """The current selection mode."""
        return self._mode

    @property
    def selection(self) -> tuple[int, list[int]]:
        """The current ``(dim, sorted tags)``."""
        return self._sel_dim, sorted(self._sel_tags)

    def highlight(self, dim: int, tags: list[int]) -> None:
        """Mark entities as selected (for example from the model tree) without emitting
        ``selection_changed``. ``dim`` is a geometry dimension or ``NODE_DIM`` /
        ``ELEMENT_DIM``; unknown tags are ignored.
        """
        self._sel_dim = int(dim)
        self._sel_tags = {int(t) for t in tags}
        self._update_overlay(self._selection, self._sel_dim, sorted(self._sel_tags))
        self._blit()

    def fit(self) -> None:
        """Zoom to show the geometry and the mesh."""
        bounds = self._content_bounds()
        if bounds is None:
            bounds = (0.0, 0.0, 1.0, 1.0)
        x0, y0, x1, y1 = bounds
        span = max(x1 - x0, y1 - y0)
        if span <= 0.0:
            span = 1.0
        pad = FIT_MARGIN * span
        cx, cy = 0.5 * (x0 + x1), 0.5 * (y0 + y1)
        half_x, half_y = 0.5 * max(x1 - x0, 0.0) + pad, 0.5 * max(y1 - y0, 0.0) + pad
        self._set_limits((cx - half_x, cx + half_x), (cy - half_y, cy + half_y))

    def save_image(self, path: str, dpi: int = 200) -> None:
        """Write the current view (including the selection, not the hover) to ``path``."""
        self._hover_overlay.clear()
        self._hover = None
        shown = self._selection.artists
        for a in shown:
            a.set_animated(False)
        try:
            self._fig.savefig(path, dpi=dpi)
        finally:
            for a in shown:
                a.set_animated(True)
            self._invalidate()

    # -------------------------------------------------------------- layers: drawing

    def _has_content(self) -> bool:
        return self._built is not None or self._mesh is not None

    def _after_content_change(self, had_content: bool) -> None:
        if not had_content and self._has_content():
            self.fit()
        else:
            self._invalidate()

    def _clear_layer(self, name: str) -> None:
        if name == "results" and self._colorbar is not None:
            try:
                self._colorbar.remove()  # type: ignore[attr-defined]
            except (AttributeError, ValueError, KeyError):  # pragma: no cover - defensive
                log.debug("color bar already gone")
            self._colorbar = None
            self._ax.set_title("")
            # ``fig.colorbar(ax=...)`` shrinks the model axes and removing it does not give
            # the space back; restore the rectangle so the axes never drift
            self._ax.set_position(AXES_RECT)
        for artist in self._layers[name]:
            try:
                artist.remove()
            except (ValueError, NotImplementedError):  # pragma: no cover - defensive
                log.debug("artist already removed")
        self._layers[name] = []

    def _add(self, layer: str, artist: Artist) -> None:
        self._layers[layer].append(artist)

    def _index_geometry(self, built: BuiltGeometry | None) -> None:
        """Build the plain arrays used for picking and drawing."""
        self._pt_tags, self._curve_tags, self._surf_tags = [], [], []
        self._curve_lines, self._surf_loops, self._surf_area = [], [], []
        self._pt_xy = np.zeros((0, _PLANE))
        self._seg_a = self._seg_b = np.zeros((0, _PLANE))
        self._seg_owner = np.zeros(0, dtype=int)
        self._surf_bbox = np.zeros((0, 4))
        if built is None:
            self._pt_index = {}
            return
        self._pt_tags = sorted(built.points)
        self._pt_xy = np.array(
            [built.points[t].center[:_PLANE] for t in self._pt_tags], dtype=float
        ).reshape(-1, _PLANE)
        self._pt_index = {t: i for i, t in enumerate(self._pt_tags)}
        self._curve_tags = sorted(t for t in built.curves if t in built.curve_polylines)
        self._curve_lines = [
            np.asarray(built.curve_polylines[t], float)[:, :_PLANE] for t in self._curve_tags
        ]
        self._seg_a, self._seg_b, self._seg_owner = picking.polyline_segments(self._curve_lines)
        tol = 1e-6 * max(built.diagonal, 1e-12)
        by_tag = dict(zip(self._curve_tags, self._curve_lines, strict=True))
        members: dict[int, list[ndarray]] = {}
        for curve, surfaces in built.curve_surfaces.items():
            if curve in by_tag:
                for s in surfaces:
                    members.setdefault(s, []).append(by_tag[curve])
        self._surf_tags = sorted(t for t in built.surfaces if t in members)
        for t in self._surf_tags:
            self._surf_loops.append(picking.chain_loops(members[t], tol))
            self._surf_area.append(built.surfaces[t].measure)
        self._surf_bbox = np.array(
            [
                [built.surfaces[t].bbox[0], built.surfaces[t].bbox[1],
                 built.surfaces[t].bbox[3], built.surfaces[t].bbox[4]]
                for t in self._surf_tags
            ],
            dtype=float,
        ).reshape(-1, 4)

    def _draw_geometry(self, built: BuiltGeometry) -> None:
        ax = self._ax
        if self._surf_tags:
            fills = PathCollection(
                [_surface_path(loops) for loops in self._surf_loops],
                facecolors=_SURFACE_FILL, edgecolors="none", alpha=0.25, zorder=Z_GEOMETRY,
            )
            ax.add_collection(fills, autolim=False)
            self._add("geometry", fills)
        if self._curve_lines:
            curves = LineCollection(
                self._curve_lines, colors=_CURVE_COLOR, linewidths=1.6, zorder=Z_GEOMETRY + 0.2
            )
            ax.add_collection(curves, autolim=False)
            self._add("geometry", curves)
        if self._pt_tags:
            pts = Line2D(
                self._pt_xy[:, 0], self._pt_xy[:, 1], ls="none", marker="o", ms=5,
                mfc=_POINT_COLOR, mec="white", mew=0.6, zorder=Z_GEOMETRY + 0.3,
            )
            ax.add_artist(pts)
            self._add("geometry", pts)

    def _draw_mesh(self, mesh: Mesh, display: DisplayMesh, color_by: ndarray | None) -> None:
        ax = self._ax
        xy = mesh.nodes[:, :_PLANE]
        if color_by is not None and display.triangles.shape[0]:
            values = np.asarray(color_by, dtype=float).reshape(-1)
            fill = PolyCollection(
                xy[display.triangles], array=values[display.element], cmap="Pastel1",
                edgecolors="none", zorder=Z_MESH - 0.1,
            )
            ax.add_collection(fill, autolim=False)
            self._add("mesh", fill)
            self._mesh_fill = fill
        for outline in display.outlines:
            lines = LineCollection(xy[outline], colors=_MESH_COLOR, linewidths=0.4, zorder=Z_MESH)
            ax.add_collection(lines, autolim=False)
            self._add("mesh", lines)
            self._mesh_lines.append(lines)
        if not display.outlines and display.triangles.shape[0]:
            tri = xy[display.triangles]
            edges = np.concatenate([tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]])
            lines = LineCollection(edges, colors=_MESH_COLOR, linewidths=0.4, zorder=Z_MESH)
            ax.add_collection(lines, autolim=False)
            self._add("mesh", lines)
            self._mesh_lines.append(lines)

    def _apply_mesh_visibility(self) -> None:
        """Mesh lines show without a field, or over it when the field asks for the mesh."""
        field = self._field
        for lines in self._mesh_lines:
            lines.set_visible(field is None or field.show_mesh)
            lines.set_zorder(Z_MESH_OVER_FIELD if field is not None and field.show_mesh else Z_MESH)
        if self._mesh_fill is not None:
            self._mesh_fill.set_visible(field is None)

    def _draw_field(self, spec: FieldDisplay) -> None:
        ax = self._ax
        lo, hi = float(spec.vmin), float(spec.vmax)
        scale = max(abs(lo), abs(hi), 1.0)
        if not hi - lo > _UNIFORM_RTOL * scale:  # uniform, also up to round-off
            pad = scale * 1e-6
            mid = 0.5 * (lo + hi) if np.isfinite(hi) else lo
            lo, hi = mid - pad, mid + pad
        mappable = None
        if spec.triangles.shape[0]:
            tri = Triangulation(spec.xy[:, 0], spec.xy[:, 1], spec.triangles)
            values = np.where(np.isfinite(spec.values), spec.values, lo)
            if spec.levels is None:
                mappable = ax.tripcolor(
                    tri, values, shading="gouraud", cmap=spec.cmap, vmin=lo, vmax=hi,
                    zorder=Z_RESULTS,
                )
            else:
                edges = np.linspace(lo, hi, max(int(spec.levels), 1) + 1)
                mappable = ax.tricontourf(
                    tri, values, levels=edges, cmap=spec.cmap, vmin=lo, vmax=hi,
                    extend="both", zorder=Z_RESULTS,
                )
            self._add("results", mappable)
        if spec.vector_xy is not None and spec.vector_uv is not None and len(spec.vector_xy):
            vxy = np.asarray(spec.vector_xy, float)
            uv = np.asarray(spec.vector_uv, float)
            if spec.vector_values is not None and mappable is None:
                arrows = ax.quiver(
                    vxy[:, 0], vxy[:, 1], uv[:, 0], uv[:, 1],
                    np.asarray(spec.vector_values, float), cmap=spec.cmap,
                    angles="xy", pivot="mid", zorder=Z_RESULTS + 0.2,
                )
                mappable = arrows
            else:
                arrows = ax.quiver(
                    vxy[:, 0], vxy[:, 1], uv[:, 0], uv[:, 1], color="black",
                    angles="xy", pivot="mid", zorder=Z_RESULTS + 0.2,
                )
            self._add("results", arrows)
        for x, y, text in spec.markers:
            dot = Line2D(
                [x], [y], ls="none", marker="o", ms=6, mfc="white", mec="black",
                zorder=Z_RESULTS + 0.3,
            )
            ax.add_artist(dot)
            note = ax.annotate(
                text, xy=(x, y), xytext=(6, 6), textcoords="offset points", fontsize=8,
                zorder=Z_RESULTS + 0.3, annotation_clip=False,
                bbox={"boxstyle": "round,pad=0.2", "fc": "white", "alpha": 0.8, "lw": 0.3},
            )
            self._add("results", dot)
            self._add("results", note)
        if mappable is not None:
            label = spec.label or spec.vector_label
            self._colorbar = self._fig.colorbar(mappable, ax=ax, label=label, shrink=0.9)
        ax.set_title(spec.title, fontsize=10)

    def _draw_symbols(self, symbols: list[LoadSymbol], built: BuiltGeometry) -> None:
        ax = self._ax
        colors: dict[str, str] = {}
        for sym in symbols:
            color = sym.color or colors.setdefault(
                sym.kind, kind_color(len(colors))
            )
            colors.setdefault(sym.kind, color)
            tags = [int(t) for t in sym.tags]
            artist: Artist | None = None
            if sym.dim == 0:
                idx = [self._pt_index[t] for t in tags if t in self._pt_index]
                if idx:
                    xy = self._pt_xy[idx]
                    artist = Line2D(
                        xy[:, 0], xy[:, 1], ls="none", marker="s", ms=10, mfc=color,
                        mec="black", zorder=Z_SYMBOLS,
                    )
                    ax.add_artist(artist)
            elif sym.dim == 1:
                lookup = dict(zip(self._curve_tags, self._curve_lines, strict=True))
                lines = [lookup[t] for t in tags if t in lookup]
                if lines:
                    artist = LineCollection(lines, colors=color, linewidths=4.0, zorder=Z_SYMBOLS)
                    ax.add_collection(artist, autolim=False)
            elif sym.dim == _PLANE:
                lookup2 = dict(zip(self._surf_tags, self._surf_loops, strict=True))
                paths = [_surface_path(lookup2[t]) for t in tags if t in lookup2]
                if paths:
                    artist = PathCollection(
                        paths, facecolors=color, edgecolors="none", alpha=0.3, zorder=Z_SYMBOLS
                    )
                    ax.add_collection(artist, autolim=False)
            if artist is not None:
                self._add("symbols", artist)
        if colors:
            handles = [Line2D([], [], color=c, lw=4.0, label=k) for k, c in colors.items()]
            legend = ax.legend(handles=handles, loc="upper right", fontsize=8)
            legend.set_zorder(Z_SYMBOLS + 0.5)
            self._add("symbols", legend)

    # ----------------------------------------------------------- view and blitting

    def _content_bounds(self) -> tuple[float, float, float, float] | None:
        boxes: list[tuple[float, float, float, float]] = []
        if self._built is not None:
            b = self._built.bbox
            boxes.append((b[0], b[1], b[3], b[4]))
        if self._mesh is not None and self._mesh.n_nodes:
            lo = self._mesh.nodes[:, :_PLANE].min(axis=0)
            hi = self._mesh.nodes[:, :_PLANE].max(axis=0)
            boxes.append((float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1])))
        if not boxes:
            return None
        arr = np.array(boxes)
        return (
            float(arr[:, 0].min()), float(arr[:, 1].min()),
            float(arr[:, 2].max()), float(arr[:, 3].max()),
        )

    def _set_limits(self, xlim: tuple[float, float], ylim: tuple[float, float]) -> None:
        """Show at least the region ``xlim`` x ``ylim``.

        The limits are widened to the pixel aspect of the axes, so that Matplotlib's own
        equal-aspect adjustment (which also depends on the data limits) has nothing to do.
        """
        bbox = self._ax.bbox
        width, height = max(float(bbox.width), 1.0), max(float(bbox.height), 1.0)
        scale = max((xlim[1] - xlim[0]) / width, (ylim[1] - ylim[0]) / height)
        if scale <= 0.0:
            scale = 1.0 / width
        self._view = (0.5 * (xlim[0] + xlim[1]), 0.5 * (ylim[0] + ylim[1]), scale)
        self._renormalize()

    def _renormalize(self) -> None:
        """Apply the stored view (centre and data units per pixel) to the axes."""
        cx, cy, scale = self._view
        bbox = self._ax.bbox
        half_x = 0.5 * scale * max(float(bbox.width), 1.0)
        half_y = 0.5 * scale * max(float(bbox.height), 1.0)
        self._ax.set_xlim(cx - half_x, cx + half_x)
        self._ax.set_ylim(cy - half_y, cy + half_y)
        self._invalidate()

    def _invalidate(self) -> None:
        """Drop the cached background and schedule a full redraw."""
        self._background_valid = False
        self._canvas.draw_idle()

    def _on_resize(self, _event: object) -> None:
        self._background_valid = False
        self._renormalize()

    def _on_draw(self, _event: object) -> None:
        """After a full draw: cache the background, then draw the animated artists."""
        self._background = self._canvas.copy_from_bbox(self._fig.bbox)
        self._background_valid = True
        self._draw_animated()

    def _animated(self) -> list[Artist]:
        out: list[Artist] = [*self._selection.artists, *self._hover_overlay.artists, self._band]
        return out

    def _draw_animated(self) -> None:
        for artist in self._animated():
            if artist.get_visible():
                self._ax.draw_artist(artist)

    def _blit(self) -> None:
        """Redraw only the overlay artists over the cached background."""
        if not self._background_valid:
            self._canvas.draw()  # the draw event caches the background and draws overlays
            return
        self._canvas.restore_region(self._background)
        self._draw_animated()
        self._canvas.blit(self._fig.bbox)

    # ----------------------------------------------------------------- coordinates

    def _data_xy(self, event: MouseEvent) -> tuple[float, float] | None:
        """Data coordinates of an event, or ``None`` outside the axes."""
        if event.x is None or event.y is None or not self._ax.bbox.contains(event.x, event.y):
            return None
        x, y = self._ax.transData.inverted().transform((event.x, event.y))
        return float(x), float(y)

    def _tolerance(self) -> float:
        """The picking tolerance in data units."""
        inv = self._ax.transData.inverted()
        a = inv.transform((0.0, 0.0))
        b = inv.transform((PICK_TOL_PX, 0.0))
        return float(abs(b[0] - a[0]))

    # ---------------------------------------------------------------------- events

    def _on_scroll(self, event: MouseEvent) -> None:
        pos = self._data_xy(event)
        if pos is None:
            return
        steps = event.step if event.step else (1.0 if event.button == "up" else -1.0)
        factor = ZOOM_STEP ** float(steps)
        x0, x1 = self._ax.get_xlim()
        y0, y1 = self._ax.get_ylim()
        cx, cy = pos
        self._set_limits(
            (cx + (x0 - cx) / factor, cx + (x1 - cx) / factor),
            (cy + (y0 - cy) / factor, cy + (y1 - cy) / factor),
        )

    def _on_press(self, event: MouseEvent) -> None:
        button = getattr(event.button, "value", event.button)
        if button == _MIDDLE:
            self._pan = (event.x, event.y, self._ax.get_xlim(), self._ax.get_ylim())
        elif button == _LEFT:
            pos = self._data_xy(event)
            if pos is not None:
                self._press = (event.x, event.y, pos[0], pos[1], _is_ctrl(event))
                self._banding = False

    def _on_motion(self, event: MouseEvent) -> None:
        pos = self._data_xy(event)
        if pos is not None:
            self.coordinates_changed.emit(pos[0], pos[1])
        if self._pan is not None:
            self._do_pan(event)
        elif self._press is not None:
            self._do_drag(event, pos)
        elif pos is not None and self._mode != "none":
            self._do_hover(pos)

    def _on_leave(self, _event: object) -> None:
        if self._hover is not None:
            self._hover = None
            self._hover_overlay.clear()
            self._announce_hover()
            self._blit()

    def _on_release(self, event: MouseEvent) -> None:
        button = getattr(event.button, "value", event.button)
        if button == _MIDDLE:
            self._pan = None
            return
        if button != _LEFT or self._press is None:
            return
        _px, _py, x0, y0, ctrl = self._press
        banding = self._banding
        self._press, self._banding = None, False
        self._band.set_visible(False)
        pos = self._data_xy(event)
        if banding and pos is not None:
            self._select_box(picking.normalized_box((x0, y0), pos), ctrl)
            self._blit()
            return
        if banding:
            self._blit()
            return
        self.point_picked.emit(x0, y0, 0.0)
        if self._mode != "none":
            hit = self._pick(x0, y0)
            self._select_click(hit, ctrl)
            if not ctrl and self._mode in _GEOMETRIC_MODES:
                if hit is None:
                    self.entity_clicked.emit(-1, -1)
                else:
                    self.entity_clicked.emit(MODE_DIM[self._mode], int(hit))

    def _do_pan(self, event: MouseEvent) -> None:
        assert self._pan is not None
        sx, sy, xlim, ylim = self._pan
        bbox = self._ax.bbox
        dx = (event.x - sx) * (xlim[1] - xlim[0]) / bbox.width
        dy = (event.y - sy) * (ylim[1] - ylim[0]) / bbox.height
        self._set_limits((xlim[0] - dx, xlim[1] - dx), (ylim[0] - dy, ylim[1] - dy))

    def _do_drag(self, event: MouseEvent, pos: tuple[float, float] | None) -> None:
        assert self._press is not None
        px, py, x0, y0, _ctrl = self._press
        if self._mode == "none" or pos is None:
            return
        if not self._banding and np.hypot(event.x - px, event.y - py) < DRAG_PX:
            return
        self._banding = True
        self._hover = None
        self._hover_overlay.clear()
        self._announce_hover()
        xmin, ymin, xmax, ymax = picking.normalized_box((x0, y0), pos)
        self._band.set_xy((xmin, ymin))
        self._band.set_width(xmax - xmin)
        self._band.set_height(ymax - ymin)
        self._band.set_visible(True)
        self._blit()

    def _do_hover(self, pos: tuple[float, float]) -> None:
        hit = self._pick(pos[0], pos[1])
        new = None if hit is None else (MODE_DIM[self._mode], hit)
        if new == self._hover:
            return
        self._hover = new
        if new is None:
            self._hover_overlay.clear()
        else:
            self._update_overlay(self._hover_overlay, new[0], [new[1]])
        self._announce_hover()
        self._blit()

    def _announce_hover(self) -> None:
        """Emit ``entity_hovered`` if the geometric hover differs from the last one sent."""
        h = self._hover
        now = (-1, -1) if h is None or h[0] not in (0, 1, 2) else (int(h[0]), int(h[1]))
        if now != self._hover_sent:
            self._hover_sent = now
            self.entity_hovered.emit(*now)

    # -------------------------------------------------------------------- picking

    def _ensure_mesh_structures(self) -> None:
        mesh, display = self._mesh, self._display
        if mesh is None or display is None or self._elem_ids is not None:
            return
        ids = np.concatenate([b.elem_ids for b in mesh.blocks]) if mesh.blocks else np.zeros(0, int)
        pos = np.full(int(ids.max()) + 1 if ids.size else 0, -1, dtype=int)
        pos[ids] = np.arange(ids.size)
        self._elem_ids, self._elem_pos = ids.astype(int), pos
        parts = [mesh.nodes[b.conn][:, :, :_PLANE].mean(axis=1) for b in mesh.blocks]
        self._elem_centroids = np.concatenate(parts) if parts else np.zeros((0, _PLANE))

    def _node_kdtree(self) -> cKDTree | None:
        if self._mesh is None:
            return None
        if self._node_tree is None:
            self._node_tree = cKDTree(self._mesh.nodes[:, :_PLANE])
        return self._node_tree

    def _finder(self) -> Callable[[float, float], int] | None:
        if self._mesh is None or self._display is None or not self._display.triangles.shape[0]:
            return None
        if self._trifinder is None:
            xy = self._mesh.nodes[:, :_PLANE]
            tri = Triangulation(xy[:, 0], xy[:, 1], self._display.triangles)
            self._trifinder = tri.get_trifinder()
        return self._trifinder

    def _pick(self, x: float, y: float) -> int | None:
        """The tag of the entity under ``(x, y)`` in the current mode, or ``None``."""
        mode = self._mode
        p = (x, y)
        tol = self._tolerance()
        if mode == "point":
            k = picking.nearest_point(self._pt_xy, p, tol)
            return None if k is None else self._pt_tags[k]
        if mode == "curve":
            k = picking.nearest_segment_owner(self._seg_a, self._seg_b, self._seg_owner, p, tol)
            return None if k is None else self._curve_tags[k]
        if mode == "surface":
            return self._pick_surface(p)
        if mode == "node":
            tree = self._node_kdtree()
            if tree is None:
                return None
            dist, k = tree.query(p, distance_upper_bound=tol)
            return None if not np.isfinite(dist) else int(k)
        if mode == "element":
            finder, display = self._finder(), self._display
            if finder is None or display is None:
                return None
            self._ensure_mesh_structures()
            tri = int(finder(x, y))
            if tri < 0:
                return None
            assert self._elem_ids is not None
            return int(self._elem_ids[display.element[tri]])
        return None

    def _pick_surface(self, p: tuple[float, float]) -> int | None:
        if not self._surf_tags:
            return None
        bb = self._surf_bbox
        near = np.flatnonzero((bb[:, 0] <= p[0]) & (p[0] <= bb[:, 2]) & (bb[:, 1] <= p[1])
                              & (p[1] <= bb[:, 3]))
        cands = [(self._surf_tags[i], self._surf_loops[i], self._surf_area[i]) for i in near]
        return picking.smallest_containing(cands, p)

    def _box_tags(self, box: picking.Box) -> list[int]:
        """Tags of everything of the current mode inside ``box``.

        Points and nodes must lie in the box, curves must lie entirely in it, surfaces
        need their bounding box in it, elements their centroid.
        """
        mode = self._mode
        if mode == "point":
            mask = picking.points_in_box(self._pt_xy, box)
            return [self._pt_tags[i] for i in np.flatnonzero(mask)]
        if mode == "curve":
            return [
                t for t, line in zip(self._curve_tags, self._curve_lines, strict=True)
                if picking.all_in_box(line, box)
            ]
        if mode == "surface":
            bb = self._surf_bbox
            inside = (bb[:, 0] >= box[0]) & (bb[:, 1] >= box[1]) & (bb[:, 2] <= box[2]) & (
                bb[:, 3] <= box[3]
            )
            return [self._surf_tags[i] for i in np.flatnonzero(inside)]
        if mode == "node" and self._mesh is not None:
            mask = picking.points_in_box(self._mesh.nodes[:, :_PLANE], box)
            return [int(i) for i in np.flatnonzero(mask)]
        if mode == "element" and self._mesh is not None:
            self._ensure_mesh_structures()
            assert self._elem_centroids is not None and self._elem_ids is not None
            mask = picking.points_in_box(self._elem_centroids, box)
            return [int(i) for i in self._elem_ids[mask]]
        return []

    # ------------------------------------------------------------------- selection

    def _select_click(self, hit: int | None, ctrl: bool) -> None:
        dim = MODE_DIM[self._mode]
        current = self._sel_tags if self._sel_dim == dim else set()
        if ctrl:
            if hit is None:
                return
            new = set(current)
            new ^= {hit}
        else:
            new = set() if hit is None else {hit}
        self._set_selection(dim, new)

    def _select_box(self, box: picking.Box, ctrl: bool) -> None:
        dim = MODE_DIM[self._mode]
        found = set(self._box_tags(box))
        current = self._sel_tags if self._sel_dim == dim else set()
        self._set_selection(dim, (current | found) if ctrl else found)

    def _set_selection(self, dim: int, tags: set[int]) -> None:
        changed = dim != self._sel_dim or tags != self._sel_tags
        self._sel_dim, self._sel_tags = dim, tags
        self._update_overlay(self._selection, dim, sorted(tags))
        self._blit()
        if changed:
            self.selection_changed.emit(dim, sorted(tags))

    # -------------------------------------------------------------------- overlays

    def _reset_overlays(self, geometry: bool = False) -> None:
        """Drop hover and stale selection tags after the geometry or mesh was replaced.

        Node and element tags belong to one mesh and are dropped whenever the geometry or
        the mesh is replaced; geometry tags are kept only if the new geometry still has them.
        No ``selection_changed`` is emitted (this is not a user edit).
        """
        self._hover = None
        self._hover_overlay.clear()
        self._announce_hover()
        dim = self._sel_dim
        if dim in (NODE_DIM, ELEMENT_DIM) or (geometry and self._built is None):
            self._sel_tags = set()
        elif geometry:
            valid = set({
                0: self._pt_index.keys(),
                1: self._curve_tags,
                2: self._surf_tags,
            }.get(dim, ()))
            self._sel_tags = {t for t in self._sel_tags if t in valid}
        self._update_overlay(self._selection, self._sel_dim, sorted(self._sel_tags))

    def _update_overlay(self, overlay: _Overlay, dim: int, tags: list[int]) -> None:
        """Fill ``overlay`` with the drawing of the entities ``(dim, tags)``."""
        if not tags:
            overlay.clear()
            return
        if dim == 0:
            idx = [self._pt_index[t] for t in tags if t in self._pt_index]
            overlay.set(points=self._pt_xy[idx])
        elif dim == 1:
            lookup = dict(zip(self._curve_tags, self._curve_lines, strict=True))
            overlay.set(lines=[lookup[t] for t in tags if t in lookup])
        elif dim == _PLANE:
            lookup2 = dict(zip(self._surf_tags, self._surf_loops, strict=True))
            overlay.set(paths=[_surface_path(lookup2[t]) for t in tags if t in lookup2])
        elif dim == NODE_DIM and self._mesh is not None:
            n = self._mesh.n_nodes
            idx = [t for t in tags if 0 <= t < n]
            overlay.set(points=self._mesh.nodes[idx][:, :_PLANE])
        elif dim == ELEMENT_DIM and self._mesh is not None and self._display is not None:
            overlay.set(polys=self._element_triangles(tags))
        else:
            overlay.clear()

    def _element_triangles(self, ids: list[int]) -> ndarray:
        """Vertices ``(k, 3, 2)`` of the display triangles of the elements with these ids."""
        assert self._mesh is not None and self._display is not None
        self._ensure_mesh_structures()
        assert self._elem_pos is not None
        valid = [t for t in ids if 0 <= t < self._elem_pos.size and self._elem_pos[t] >= 0]
        positions = self._elem_pos[valid]
        parent = self._display.element
        if len(positions) <= _FEW_ELEMENTS:
            rows = [
                np.arange(np.searchsorted(parent, p, "left"), np.searchsorted(parent, p, "right"))
                for p in positions
            ]
            tri = self._display.triangles[np.concatenate(rows) if rows else np.zeros(0, int)]
        else:
            tri = self._display.triangles[np.isin(parent, positions)]
        return self._mesh.nodes[:, :_PLANE][tri]


def attach_viewport(window: MainWindow, document: Document) -> MplSceneView:
    """Install a viewport in the main window and connect it to the document.

    Connects the toolbar's selection mode to ``set_selection_mode``, the ``view.fit``
    action to ``fit`` (and enables it), the cursor read-out to the status bar, and the
    document's ``geometry_built`` / ``mesh_changed`` to ``set_geometry`` / ``set_mesh``.

    Parameters
    ----------
    window : MainWindow
    document : Document

    Returns
    -------
    MplSceneView
    """
    view = MplSceneView(window)
    window.set_viewport(view.widget())
    window.selection_mode_changed.connect(view.set_selection_mode)
    fit = window.actions["view.fit"]
    fit.setEnabled(True)
    fit.triggered.connect(lambda _checked=False: view.fit())

    def show_coordinates(x: float, y: float) -> None:
        units = document.model.display_units
        unit = unit_label("length", units)
        window.show_status(
            f"x = {float(from_si(x, 'length', units)):.6g} {unit}    "
            f"y = {float(from_si(y, 'length', units)):.6g} {unit}"
        )

    view.coordinates_changed.connect(show_coordinates)
    document.geometry_built.connect(lambda: view.set_geometry(document.built))
    document.mesh_changed.connect(lambda: view.set_mesh(document.mesh))
    document.model_changed.connect(lambda: view.set_axis_visible(document.model.axisymmetric))
    view.set_geometry(document.built)
    view.set_mesh(document.mesh)
    view.set_axis_visible(document.model.axisymmetric)
    return view
