"""Named selections of geometry entities (Data §5).

Loads never store raw gmsh tags alone, because tags can change when the geometry is
edited. A selection also stores a fingerprint of every entity so it can be found again.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..core.errors import ModelError

if TYPE_CHECKING:  # the builder imports gmsh; this module must not (Plan §3)
    from ..geometry.builder import BuiltGeometry

#: Matching tolerance of :func:`resolve`: centre within ``TOL * L``, measure within ``TOL``.
RESOLVE_TOL = 1e-6


@dataclass
class Fingerprint:
    """Geometric signature of one entity.

    Parameters
    ----------
    dim : int
        0 point, 1 curve, 2 surface (3 volume in future).
    center : tuple of 3 float
        Centre of mass [m] (z = 0 in a 2D model).
    measure : float
        0 for a point, length [m], area [m^2] (or volume [m^3]).
    bbox : tuple of 6 float
        ``xmin, ymin, zmin, xmax, ymax, zmax`` [m].
    """

    dim: int
    center: tuple[float, float, float]
    measure: float
    bbox: tuple[float, float, float, float, float, float]

    def __post_init__(self) -> None:
        self.center = tuple(float(v) for v in self.center)  # type: ignore[assignment]
        self.bbox = tuple(float(v) for v in self.bbox)  # type: ignore[assignment]
        self.measure = float(self.measure)
        if len(self.center) != len(self.bbox) // 2 or len(self.bbox) % 2:
            raise ModelError("fingerprint: center needs 3 and bbox 6 components")


@dataclass
class Selection:
    """A named set of geometry entities of one dimension.

    Parameters
    ----------
    name : str
        Selection name, unique in the model.
    dim : int
        Dimension of the selected entities.
    tags : list of int
        Entity tags at the time of selection.
    fingerprints : list of Fingerprint
        One per tag, used to find the entities again after a rebuild.
    """

    name: str
    dim: int
    tags: list[int] = field(default_factory=list)
    fingerprints: list[Fingerprint] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ModelError("selection name must be a non-empty string")
        self.tags = [int(t) for t in self.tags]
        if len(self.tags) != len(self.fingerprints):
            raise ModelError(f"selection {self.name!r}: one fingerprint per tag is required")
        if any(fp.dim != self.dim for fp in self.fingerprints):
            raise ModelError(f"selection {self.name!r}: fingerprint dimension mismatch")


class StaleSelectionError(ModelError):
    """A selection refers to an entity that no longer exists in the built geometry."""


def fingerprint_matches(fp: Fingerprint, other: Fingerprint, length: float) -> bool:
    """True when two fingerprints describe the same entity (Data §5).

    Parameters
    ----------
    fp, other : Fingerprint
    length : float
        Bounding-box diagonal of the model [m].
    """
    if fp.dim != other.dim:
        return False
    if math.dist(fp.center, other.center) > RESOLVE_TOL * length:
        return False
    return abs(fp.measure - other.measure) <= RESOLVE_TOL * max(abs(fp.measure), abs(other.measure))


def resolve(selection: Selection, built: BuiltGeometry) -> list[int]:
    """Find the current tags of a selection's entities in a built geometry.

    For each fingerprint the entity of the same dimension is found whose centre is within
    ``1e-6 L`` and whose measure is within ``1e-6`` relative, ``L`` being the bounding-box
    diagonal of the geometry.

    Parameters
    ----------
    selection : Selection
    built : BuiltGeometry

    Returns
    -------
    list of int
        One tag per fingerprint, in order.

    Raises
    ------
    StaleSelectionError
        If a fingerprint matches no entity; the message names the selection.
    """
    candidates = built.entities(selection.dim)
    length = built.diagonal
    tags: list[int] = []
    for i, fp in enumerate(selection.fingerprints):
        matches = [
            (math.dist(fp.center, other.center), tag)
            for tag, other in candidates.items()
            if fingerprint_matches(fp, other, length)
        ]
        if not matches:
            kind = {0: "point", 1: "curve", 2: "surface"}.get(selection.dim, "entity")
            raise StaleSelectionError(
                f"selection {selection.name!r} is stale: its {kind} #{i + 1} (centre "
                f"({fp.center[0]:.6g}, {fp.center[1]:.6g}), size {fp.measure:.6g}) no longer "
                "exists in the geometry; select it again"
            )
        tags.append(min(matches)[1])
    return tags


def refresh(selections: dict[str, Selection], built: BuiltGeometry) -> dict[str, str]:
    """Resolve every selection against a new build and update its tags.

    Parameters
    ----------
    selections : dict of str to Selection
        Updated in place: the tags of every selection that resolves.
    built : BuiltGeometry

    Returns
    -------
    dict of str to str
        Name -> message for every stale selection (empty when all resolve).
    """
    stale: dict[str, str] = {}
    for name, selection in selections.items():
        try:
            selection.tags = resolve(selection, built)
        except StaleSelectionError as exc:
            stale[name] = str(exc)
    return stale
