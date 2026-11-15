"""Reaction heat flows and the heat flow of every boundary condition (Theory §4, §7).

**Sign convention used throughout the program: a heat flow is positive when heat enters
the body.** This is how Theory §4 defines the reaction at a prescribed node,

    R_p = (C dT/dt + K T - F)_p        (plus the radiation part of the residual)

and it is what the energy balance adds up. Theory §7 writes the boundary formulas as heat
*leaving* the body; the values reported here are those with the sign reversed.
"""

from __future__ import annotations

import numpy as np
from numpy import ndarray

from ..solver.nonlinear import Assembled
from ..solver.problem import CompiledProblem
from ..solver.steady import STEADY_TIME, assemble
from ..solver.terms import State


def reaction_vector(
    system: Assembled, u: ndarray, capacitance_rate: ndarray | None = None
) -> ndarray:
    """Reaction heat flow at every DOF (Theory §4).

    Parameters
    ----------
    system : Assembled
        The system assembled at ``u``.
    u : ndarray, shape (n_dofs,)
        Solution [K].
    capacitance_rate : ndarray, shape (n_dofs,), optional
        ``C dT/dt`` [W] in a transient analysis.

    Returns
    -------
    ndarray, shape (n_dofs,)
        ``R = C dT/dt + K T - F - r_extra`` [W]. At a prescribed DOF this is the heat
        entering the body through the constraint; at a free DOF it is the (negative)
        residual, zero at convergence.
    """
    reaction = -system.residual(u)
    if capacitance_rate is not None:
        reaction = reaction + capacitance_rate
    return reaction


def heat_flows(
    problem: CompiledProblem,
    u: ndarray,
    t: float = STEADY_TIME,
    system: Assembled | None = None,
    capacitance_rate: ndarray | None = None,
    u_prev: ndarray | None = None,
    dt: float | None = None,
) -> dict[str, float]:
    """Heat entering the body through every boundary condition and load [W].

    Loads report the integral of what they apply (flux, generation, convection,
    radiation); fixed temperatures report the sum of the reactions at their nodes. A node
    shared by two fixed-temperature conditions is counted for the one whose value is used.

    Parameters
    ----------
    problem : CompiledProblem
    u : ndarray, shape (n_dofs,)
        Solution [K].
    t : float
        Time [s].
    system : Assembled, optional
        The system assembled at ``u``; assembled here when not given.
    capacitance_rate : ndarray, optional
        ``C dT/dt`` [W] in a transient analysis.
    u_prev : ndarray, optional
        Solution of the previous step.
    dt : float, optional
        Time step [s].

    Returns
    -------
    dict of str to float
        Name of the condition -> heat entering the body [W] (negative when heat leaves),
        in the order of the problem's terms, then its constraints.
    """
    if system is None:
        system = assemble(problem, u, t, u_prev, dt)
    state = State(u=u, u_prev=u if u_prev is None else u_prev, t=t, dt=dt, dofs=problem.dofs)
    flows: dict[str, float] = {}
    for term in problem.terms:
        heat = term.boundary_heat(state)
        if heat is not None:
            flows[term.name] = flows.get(term.name, 0.0) + float(heat)
    if problem.constraints:
        reaction = reaction_vector(system, u, capacitance_rate)
        idx, owner = problem.prescribed_owners(t)
        totals = np.bincount(owner, weights=reaction[idx], minlength=len(problem.constraints))
        for constraint, total in zip(problem.constraints, totals, strict=True):
            flows[constraint.name] = flows.get(constraint.name, 0.0) + float(total)
    return flows
