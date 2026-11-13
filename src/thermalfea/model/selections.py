"""Named selections of geometry entities (Data §5).

Loads never store raw gmsh tags alone, because tags can change when the geometry is
edited. A selection also stores a fingerprint of every entity so it can be found again.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.errors import ModelError


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
