"""The viewport interface of the GUI (Data §13): the only viewport API the rest of the GUI uses.

This module imports no Matplotlib and no widget code at run time (``Signal`` and ``QWidget``
appear only in annotations, under ``TYPE_CHECKING``). :class:`FieldDisplay` and
:class:`LoadSymbol` hold plain arrays and values, so another renderer needs no access to
solver objects.

Selection convention
--------------------
``selection_changed(dim, tags)`` and :meth:`SceneView.highlight` use the geometry dimensions
for geometry entities (``0`` point, ``1`` curve, ``2`` surface; ``tags`` are the gmsh entity
tags of the built geometry) and two reserved pseudo-dimensions for mesh entities:

* :data:`NODE_DIM` (``-1``): ``tags`` are node indices, 0-based rows of ``mesh.nodes``;
* :data:`ELEMENT_DIM` (``-2``): ``tags`` are global element ids (``ElementBlock.elem_ids``).

The pseudo-dimensions are negative so they can never collide with a geometry dimension.
``selection_changed`` always carries the full current selection, tags sorted ascending.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

import numpy as np
from numpy import ndarray

if TYPE_CHECKING:
    from PySide6.QtCore import Signal
    from PySide6.QtWidgets import QWidget

    from thermalfea.core.mesh import Mesh
    from thermalfea.geometry.builder import BuiltGeometry

#: Pseudo-dimension of a selection of mesh nodes (tags are node indices).
NODE_DIM = -1
#: Pseudo-dimension of a selection of mesh elements (tags are global element ids).
ELEMENT_DIM = -2

SelectionMode = Literal["none", "point", "curve", "surface", "node", "element"]

#: Selection mode -> dimension reported in ``selection_changed`` (``none`` has none).
MODE_DIM: dict[str, int] = {
    "point": 0,
    "curve": 1,
    "surface": 2,
    "node": NODE_DIM,
    "element": ELEMENT_DIM,
}


@dataclass
class FieldDisplay:
    """A scalar field (and optional vectors) ready to draw.

    Attributes
    ----------
    xy : ndarray, shape (n, 2)
        Vertex coordinates [m]. Vertices may be duplicated where the field is
        discontinuous (e.g. flux at a material interface).
    triangles : ndarray of int, shape (m, 3)
        Display triangles, indices into ``xy`` / ``values``.
    values : ndarray, shape (n,)
        Field values at the vertices, in display units.
    vmin, vmax : float
        Colour range in display units.
    levels : int or None
        Number of colour bands; ``None`` means smooth shading.
    label : str
        Colour-bar label (name and unit).
    title : str
        Title of the plot.
    vector_xy : ndarray, shape (k, 2), optional
        Arrow positions [m].
    vector_uv : ndarray, shape (k, 2), optional
        Arrow components (any consistent unit; only direction and relative length matter).
    vector_values : ndarray, shape (k,), optional
        Values that colour the arrows (e.g. magnitude), in the units of ``vector_label``.
    vector_label : str
        Colour-bar label of the arrows, used when there are no triangles.
    markers : list of (x, y, text)
        Annotated points, e.g. the minimum and maximum.
    show_mesh : bool
        Draw the element edges over the field.
    cmap : str
        Matplotlib colour-map name.
    """

    xy: ndarray
    triangles: ndarray
    values: ndarray
    vmin: float
    vmax: float
    levels: int | None = None
    label: str = ""
    title: str = ""
    vector_xy: ndarray | None = None
    vector_uv: ndarray | None = None
    vector_values: ndarray | None = None
    vector_label: str = ""
    markers: list[tuple[float, float, str]] = field(default_factory=list)
    show_mesh: bool = False
    cmap: str = "viridis"

    def __post_init__(self) -> None:
        self.xy = np.asarray(self.xy, dtype=float)
        self.triangles = np.asarray(self.triangles, dtype=int).reshape(-1, 3)
        self.values = np.asarray(self.values, dtype=float)


#: The colours of load-symbol kinds; the one table of the GUI. A kind takes the colour at
#: its position in the registry (modulo the length), the viewport falls back to the order of
#: first appearance for a symbol without a colour.
KIND_COLORS: tuple[str, ...] = (
    "#d6336c", "#1c7ed6", "#2f9e44", "#f08c00", "#7048e8", "#0c8599", "#e03131",
    "#868e96", "#74b816", "#e8590c", "#364fc7", "#a61e4d",
)  # fmt: skip


def kind_color(index: int) -> str:
    """Return the colour of the ``index``-th kind (cycles through :data:`KIND_COLORS`)."""
    return KIND_COLORS[index % len(KIND_COLORS)]


@dataclass
class LoadSymbol:
    """A boundary-condition or load marker attached to geometry entities.

    Attributes
    ----------
    kind : str
        Type of the condition (e.g. ``"temperature"``, ``"convection"``); symbols of the
        same kind share a colour and a legend entry.
    label : str
        Name of the condition, shown to the user.
    dim : int
        Geometry dimension of the entities (``0`` point, ``1`` curve, ``2`` surface).
    tags : list of int
        Entity tags in the built geometry.
    color : str or None
        Matplotlib-style colour; ``None`` lets the renderer choose by ``kind``.
    """

    kind: str
    label: str
    dim: int
    tags: list[int]
    color: str | None = None


@dataclass
class OverlayText:
    """A text label at model coordinates ``(x, y)`` [m]; ``color`` ``None`` = renderer default."""

    x: float
    y: float
    text: str
    color: str | None = None


@dataclass
class OverlayMarker:
    """A point marker at ``(x, y)`` [m] with optional ``text`` beside it."""

    x: float
    y: float
    text: str = ""
    color: str | None = None


@dataclass
class OverlayPolyline:
    """A polyline through ``points`` (``(x, y)`` pairs [m])."""

    points: list[tuple[float, float]]
    color: str | None = None


#: One record of an overlay layer (see :meth:`SceneView.set_overlay`).
OverlayItem = OverlayText | OverlayMarker | OverlayPolyline


@runtime_checkable
class SceneView(Protocol):
    """The viewport interface (Data §13).

    Signals
    -------
    selection_changed : Signal(int, list)
        ``(dim, tags)``: the full current selection after a user action; see the module
        docstring for ``dim`` and ``tags`` of nodes and elements.
    point_picked : Signal(float, float, float)
        ``(x, y, z)`` [m]: a click in the viewport (z is 0 in a planar view).
    entity_hovered : Signal(int, int)
        ``(dim, tag)`` under the pointer in a point / curve / surface pick mode;
        ``(-1, -1)`` for none.
    entity_clicked : Signal(int, int)
        ``(dim, tag)`` hit by a plain single click (not a box or Ctrl pick); ``(-1, -1)`` for
        empty space.

    ``entity_hovered`` / ``entity_clicked`` are not protocol attributes checked by
    ``isinstance`` (partial fakes lack them); consumers connect through ``getattr``.
    """

    selection_changed: Signal
    point_picked: Signal

    def widget(self) -> QWidget:
        """The widget to put into the main window."""
        ...

    def set_geometry(self, built: BuiltGeometry | None) -> None:
        """Show (or, with ``None``, clear) the built geometry."""
        ...

    def set_mesh(self, mesh: Mesh | None, color_by: ndarray | None = None) -> None:
        """Show (or clear) a mesh, optionally coloured by one value per element."""
        ...

    def set_field(self, spec: FieldDisplay | None) -> None:
        """Show (or clear) a contour / vector display."""
        ...

    def set_symbols(self, symbols: list[LoadSymbol]) -> None:
        """Show load symbols; an empty list clears them."""
        ...

    def set_overlay(self, layer: str, items: list[OverlayItem]) -> None:
        """Replace the named overlay layer as a whole; an empty list clears it."""
        ...

    def set_entity_colors(
        self, dim: int, colors: dict[int, str], legend: list[tuple[str, str]]
    ) -> None:
        """Fill the geometry entities ``colors`` (tag -> colour) of dimension ``dim`` and show
        ``legend`` as ``(label, colour)`` entries; empty arguments clear both. The fills are
        hidden while a result field is shown.
        """
        ...

    def set_axis_visible(self, visible: bool) -> None:
        """Show or hide the axis of symmetry x = 0 (shown for an axisymmetric model)."""
        ...

    def set_selection_mode(self, mode: SelectionMode) -> None:
        """Choose what can be picked; ``"none"`` disables picking."""
        ...

    def highlight(self, dim: int, tags: list[int]) -> None:
        """Mark entities as selected without emitting ``selection_changed``."""
        ...

    def fit(self) -> None:
        """Zoom to show everything."""
        ...

    def save_image(self, path: str, dpi: int = 200) -> None:
        """Write the current view to an image file."""
        ...
