"""The interface between the solid solver and a flow solver (Data §13, Plan §7 rule 7).

The solid solver talks to flow only through :class:`FlowProvider`. The one-dimensional
stream and network solver (:mod:`thermalfea.flow.coupling`) is the first implementation;
a CFD solver or a coupling to an external code can be another.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from numpy import ndarray

from ..solver.terms import State, Term

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem


@runtime_checkable
class FlowProvider(Protocol):
    """Supplies the coupling terms of a flow solution and keeps that solution up to date."""

    def setup(self, problem: CompiledProblem) -> None:
        """Prepare for a solve; may add extra DOF groups, terms and constraints."""
        ...

    def terms(self) -> list[Term]:
        """The coupling terms for the solid system."""
        ...

    def update(self, s: State) -> None:
        """Bring the flow solution up to date with the state (for example lagged hydraulics).

        Called by the drivers at most once per nonlinear iteration (at each accepted
        iterate, and when a linear system is assembled), never for line-search trials.
        """
        ...

    def results(self, s: State) -> dict[str, ndarray]:
        """Per-step output, keyed ``"<quantity>:<stream name>"``."""
        ...
