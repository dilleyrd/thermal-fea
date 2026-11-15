"""The interface between physics and the solution drivers (Data §13, Plan §7 rule 5).

Every contribution to the equations — conduction, capacitance, each load type, streams,
enclosure radiation, contact — is a :class:`Term`. The steady and transient drivers know
only about terms, never about heat transfer.

How a term's contributions enter the equations (Theory §5, §6):

* ``conductance`` adds to the matrix ``K`` (with ``asm.add_matrix``) and, for parts that
  belong only to the Newton tangent such as ``K_rad``, with ``asm.add_tangent``;
* ``load`` adds to the vector ``F`` (``asm.add_vector``) and, for parts that enter the
  residual directly such as ``r_rad``, with ``asm.add_residual``;
* ``capacitance`` adds to ``C`` (``asm.add_matrix``).

The drivers form the residual ``r = F - K u + residual`` and the tangent ``K + tangent``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from numpy import ndarray

from .assembler import Assembler
from .dofs import DofMap

if TYPE_CHECKING:
    from .problem import CompiledProblem


@dataclass
class State:
    """What a term may look at when it assembles.

    Attributes
    ----------
    u : ndarray, shape (n_dofs,)
        Current iterate, all DOFs (temperatures in kelvin).
    u_prev : ndarray, shape (n_dofs,)
        Converged solution of the previous step (transient); equal to ``u`` when steady.
    t : float
        Time [s] at which loads are evaluated.
    dt : float or None
        Time step [s]; ``None`` in a steady solve.
    dofs : DofMap
        DOF numbering.
    """

    u: ndarray
    u_prev: ndarray
    t: float
    dt: float | None
    dofs: DofMap


@runtime_checkable
class Term(Protocol):
    """One contribution to the equations."""

    name: str
    is_linear: bool  # contribution does not depend on u
    is_time_dependent: bool
    symmetric: bool

    def setup(self, problem: CompiledProblem) -> None:
        """Resolve selections and precompute geometry; called once by ``compile``."""
        ...

    def conductance(self, s: State, asm: Assembler) -> None:
        """Add to ``K`` and to the tangent."""
        ...

    def load(self, s: State, asm: Assembler) -> None:
        """Add to ``F`` and to the residual."""
        ...

    def capacitance(self, s: State, asm: Assembler) -> None:
        """Add to ``C`` (may do nothing)."""
        ...

    def breakpoints(self) -> list[float]:
        """Times [s] the time stepper must land on."""
        ...

    def boundary_heat(self, s: State) -> float | None:
        """Heat this term adds to the body [W], or ``None`` if it exchanges no heat."""
        ...

    def results(self, s: State) -> dict[str, ndarray]:
        """Extra per-step output of this term."""
        ...


class BaseTerm:
    """A term that contributes nothing; subclasses override what they need.

    Parameters
    ----------
    name : str
        Name shown in logs and in the energy balance.
    """

    is_linear: bool = True
    is_time_dependent: bool = False
    symmetric: bool = True

    def __init__(self, name: str) -> None:
        self.name = name

    def setup(self, problem: CompiledProblem) -> None:
        """Do nothing."""

    def conductance(self, s: State, asm: Assembler) -> None:
        """Do nothing."""

    def load(self, s: State, asm: Assembler) -> None:
        """Do nothing."""

    def capacitance(self, s: State, asm: Assembler) -> None:
        """Do nothing."""

    def breakpoints(self) -> list[float]:
        """Return no breakpoints."""
        return []

    def boundary_heat(self, s: State) -> float | None:
        """Exchange no heat."""
        return None

    def results(self, s: State) -> dict[str, ndarray]:
        """Return no extra output."""
        return {}


@runtime_checkable
class Constraint(Protocol):
    """A source of prescribed DOF values (for example fixed temperatures)."""

    name: str
    is_time_dependent: bool

    def setup(self, problem: CompiledProblem) -> None:
        """Resolve selections; called once by ``compile``."""
        ...

    def values(self, t: float) -> tuple[ndarray, ndarray]:
        """Return ``(dof_indices, values)`` prescribed at time ``t`` [s]."""
        ...

    def breakpoints(self) -> list[float]:
        """Times [s] the time stepper must land on."""
        ...
