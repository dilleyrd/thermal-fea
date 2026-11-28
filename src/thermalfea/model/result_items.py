"""Result items: the saved displays of the results (Data §3a; owner's approval 2026-11-28).

The displays the user builds in the window — contours, vector plots, nodal histories and
path plots — are plain records in ``Model.result_items``, saved in the model file. They are
display only: the solver ignores them, they never make results "out of date"
(:mod:`thermalfea.model.compare` and the GUI document skip them), and the results file is
unchanged.

* An item stores the *time* it shows (``None`` = the last stored step), not a step index:
  a new solve may store other steps, so the nearest stored step is shown.
* A manual color range is in SI, so a change of display units does not change it.
* ``visible`` is the item's eye toggle (convention C4).

The classes form the registered family ``"result_item"``, so a model file tags each item
with its kind (``"contour"``, ``"vector"``, ``"history"``, ``"path"``). Data §3a writes
the family as the union ``ResultItem = ContourItem | VectorItem | HistoryItem | PathItem``;
here :class:`ResultItem` is their common base class, which plays that role.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core import registry

RESULT_ITEM_FAMILY = "result_item"


@dataclass
class ResultItem:
    """Common base of the result items.

    Parameters
    ----------
    name : str
        Unique among the result items.
    """

    name: str


@dataclass
class ContourItem(ResultItem):
    """A filled contour of a scalar field (M11.75).

    Parameters
    ----------
    field : str
        A key of :data:`thermalfea.post.plots.FIELDS` (``T``, ``qx``, ``qmag``, ...).
    time : float or None
        Time shown [s]; ``None`` the last stored step (steady: the solution).
    range_mode : {"auto_step", "auto_all", "manual"}
    vmin, vmax : float or None
        Manual color range in SI (``range_mode == "manual"`` only).
    banded : bool
        Color bands, or smooth shading.
    levels : int
        Number of bands.
    show_mesh : bool
        Element edges over the field.
    markers : bool
        Mark the minimum and the maximum.
    visible : bool
        The eye toggle: ``False`` hides the field and keeps the settings.
    """

    field: str = "T"
    time: float | None = None
    range_mode: Literal["auto_step", "auto_all", "manual"] = "auto_step"
    vmin: float | None = None
    vmax: float | None = None
    banded: bool = True
    levels: int = 12
    show_mesh: bool = False
    markers: bool = True
    visible: bool = True


@dataclass
class VectorItem(ResultItem):
    """Heat-flux arrows (M11.75).

    Parameters
    ----------
    time : float or None
        Time shown [s]; ``None`` the last stored step.
    density : int
        About this many arrows across the larger model dimension.
    show_mesh : bool
        Element edges under the arrows.
    visible : bool
        The eye toggle.
    """

    time: float | None = None
    density: int = 30
    show_mesh: bool = False
    visible: bool = True


@dataclass
class HistoryItem(ResultItem):
    """The history of a field at chosen nodes (M11.76).

    Parameters
    ----------
    points : list of (float, float)
        Positions [m]; each is matched to the nearest mesh node when plotted (node
        numbers change when the mesh is regenerated).
    field : str
        A key of :data:`thermalfea.post.plots.FIELDS`.
    visible : bool
        Node markers and numbers in the view.
    """

    points: list[tuple[float, float]] = field(default_factory=list)
    field: str = "T"
    visible: bool = True


@dataclass
class PathItem(ResultItem):
    """A field along a path (M11.77).

    Parameters
    ----------
    kind : {"two_points", "boundaries", "points"}
    points : list of (float, float)
        Two points ``[A, B]`` or the polyline [m].
    selection : str
        For ``"boundaries"``: a boundary selection whose curves join end to end.
    samples : int
        Evenly spaced samples (``"two_points"`` and ``"points"``).
    snap : bool
        ``"two_points"``: snap A and B to the nearest nodes.
    reverse : bool
        Run from B to A.
    field : str
    times : list of float or None
        Times [s]; ``None`` the displayed step; several are overlaid.
    axis : {"distance", "x", "y"}
        Horizontal axis (r and z in an axisymmetric model).
    visible : bool
        The path drawing in the view.
    """

    kind: Literal["two_points", "boundaries", "points"] = "two_points"
    points: list[tuple[float, float]] = field(default_factory=list)
    selection: str = ""
    samples: int = 100
    snap: bool = False
    reverse: bool = False
    field: str = "T"
    times: list[float] | None = None
    axis: Literal["distance", "x", "y"] = "distance"
    visible: bool = True


registry.register_family(RESULT_ITEM_FAMILY, ResultItem)
registry.register_class(RESULT_ITEM_FAMILY, "contour", ContourItem)
registry.register_class(RESULT_ITEM_FAMILY, "vector", VectorItem)
registry.register_class(RESULT_ITEM_FAMILY, "history", HistoryItem)
registry.register_class(RESULT_ITEM_FAMILY, "path", PathItem)

__all__ = [
    "RESULT_ITEM_FAMILY",
    "ContourItem",
    "HistoryItem",
    "PathItem",
    "ResultItem",
    "VectorItem",
]
