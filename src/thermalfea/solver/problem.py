"""The compiled problem handed to the drivers (Data §13).

A :class:`CompiledProblem` is a list of terms, a DOF map, the prescribed-DOF provider and
the settings. It can be produced from a model by :func:`thermalfea.solver.compile.compile`
or assembled by hand (tests, future physics) — the drivers do not care which.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy import ndarray

from ..core.mesh import Mesh
from ..materials.material import Material
from ..model.settings import SolutionSettings
from .dofs import DofMap
from .terms import Constraint, Term

if TYPE_CHECKING:
    from ..model.model import Model

log = logging.getLogger(__name__)

TEMPERATURE = "T"


@dataclass
class RegionData:
    """Properties of one mesh region (the elements of one geometry surface).

    Attributes
    ----------
    material : Material
    thickness : float
        Planar thickness [m]; ignored for axisymmetric and 3D models.
    material_angle : float
        Angle of the material axis [rad], counter-clockwise from x.
    name : str
        Name of the region selection, for messages.
    """

    material: Material
    thickness: float = 1.0
    material_angle: float = 0.0
    name: str = ""


@dataclass
class CompiledProblem:
    """Everything a driver needs.

    Attributes
    ----------
    mesh : Mesh
    dofs : DofMap
    regions : dict of int to RegionData
        Region id (``ElementBlock.region``) -> properties.
    terms : list of Term
        Every contribution to the equations.
    constraints : list of Constraint
        Sources of prescribed DOF values, in model order (later ones win).
    settings : SolutionSettings
    model : Model or None
        The model this was compiled from, if any.
    built : object or None
        The built geometry used to resolve selections, if any.
    """

    mesh: Mesh
    dofs: DofMap
    regions: dict[int, RegionData] = field(default_factory=dict)
    terms: list[Term] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    settings: SolutionSettings = field(default_factory=SolutionSettings)
    model: Model | None = None
    built: Any = None
    #: Data shared between terms (element batches, ...), filled on demand.
    cache: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_linear(self) -> bool:
        """True when no term depends on the solution (Theory §5)."""
        return all(term.is_linear for term in self.terms)

    @property
    def is_time_dependent(self) -> bool:
        """True when any term or prescribed value depends on time."""
        return any(term.is_time_dependent for term in self.terms) or any(
            c.is_time_dependent for c in self.constraints
        )

    @property
    def symmetric(self) -> bool:
        """True when every term contributes symmetric matrices."""
        return all(term.symmetric for term in self.terms)

    def breakpoints(self) -> list[float]:
        """Sorted, distinct times [s] the time stepper must land on."""
        times = {float(t) for term in self.terms for t in term.breakpoints()}
        times |= {float(t) for c in self.constraints for t in c.breakpoints()}
        return sorted(times)

    def prescribed(self, t: float) -> tuple[ndarray, ndarray]:
        """Prescribed DOFs and their values at time ``t``.

        When several constraints prescribe the same DOF the later one in the list wins,
        and a warning is logged.

        Parameters
        ----------
        t : float
            Time [s].

        Returns
        -------
        idx : ndarray of int64
            Distinct DOF numbers, ascending.
        values : ndarray
            Their prescribed values.
        """
        values = np.full(self.dofs.n_dofs, np.nan)
        owner = np.full(self.dofs.n_dofs, -1, dtype=np.int64)
        for k, constraint in enumerate(self.constraints):
            idx, vals = constraint.values(t)
            idx = np.asarray(idx, dtype=np.int64)
            vals = np.broadcast_to(np.asarray(vals, dtype=float), idx.shape)
            clash = (owner[idx] >= 0) & (values[idx] != vals)
            if clash.any():
                earlier = sorted({self.constraints[j].name for j in np.unique(owner[idx[clash]])})
                log.warning(
                    "%r and %s prescribe different values at %d shared DOF(s); %r wins",
                    constraint.name, ", ".join(map(repr, earlier)), int(clash.sum()),
                    constraint.name,
                )
            values[idx] = vals
            owner[idx] = k
        idx = np.flatnonzero(owner >= 0)
        return idx, values[idx]
