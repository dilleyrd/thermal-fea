"""Energy balance (Theory §7).

    (generation + heat in through all boundaries) - dE/dt = imbalance

reported relative to the largest term. Heat flows are positive into the body
(see :mod:`thermalfea.post.reactions`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from numpy import ndarray

from ..solver.nonlinear import Assembled
from ..solver.problem import CompiledProblem
from ..solver.steady import STEADY_TIME, assemble
from .reactions import constraint_heats, heat_flows, reaction_vector, term_heats


@dataclass
class EnergyBalance:
    """Heat entering the body by source, the stored energy rate, and what is left over.

    Attributes
    ----------
    flows : dict of str to float
        Name of each load or boundary condition -> heat entering the body [W].
    stored_rate : float
        Rate of change of the stored energy ``dE/dt = sum(C dT/dt)`` [W]; 0 when steady.
    gross : float
        Heat passing through the prescribed nodes [W]: the larger of the heat entering
        and the heat leaving, summed node by node. It gives the balance a scale when a
        single fixed-temperature condition both supplies and removes the heat, so that
        its net flow is zero.
    """

    flows: dict[str, float] = field(default_factory=dict)
    stored_rate: float = 0.0
    gross: float = 0.0

    @property
    def heat_in(self) -> float:
        """Sum of the positive flows [W]."""
        return sum(v for v in self.flows.values() if v > 0.0)

    @property
    def heat_out(self) -> float:
        """Sum of the negative flows, as a positive number [W]."""
        return -sum(v for v in self.flows.values() if v < 0.0)

    @property
    def net(self) -> float:
        """Net heat entering the body [W]."""
        return sum(self.flows.values())

    @property
    def throughput(self) -> float:
        """Largest magnitude among the terms of the balance [W]."""
        terms = [abs(v) for v in self.flows.values()] + [abs(self.stored_rate), self.gross]
        return max(terms)

    @property
    def imbalance(self) -> float:
        """``net - stored_rate`` [W]; zero for an exact solution."""
        return self.net - self.stored_rate

    @property
    def relative_imbalance(self) -> float:
        """``imbalance / max(|terms|)`` (dimensionless); 0 when every term is zero."""
        scale = self.throughput
        return self.imbalance / scale if scale > 0.0 else 0.0

    def table(self) -> list[tuple[str, float]]:
        """Rows of the balance table: every flow, then the totals."""
        return [
            *self.flows.items(),
            ("net heat in", self.net),
            ("stored energy rate", self.stored_rate),
            ("imbalance", self.imbalance),
        ]

    def format(self) -> str:
        """The balance as text, one row per line, values in watts."""
        width = max(len(name) for name, _ in self.table())
        lines = [f"{name:<{width}}  {value:>14.6g} W" for name, value in self.table()]
        lines.append(f"{'relative imbalance':<{width}}  {self.relative_imbalance:>14.3e}")
        return "\n".join(lines)


def energy_balance(
    problem: CompiledProblem,
    u: ndarray,
    t: float = STEADY_TIME,
    system: Assembled | None = None,
    capacitance_rate: ndarray | None = None,
    u_prev: ndarray | None = None,
    dt: float | None = None,
) -> EnergyBalance:
    """Compute the energy balance of a solution.

    Parameters
    ----------
    problem : CompiledProblem
    u : ndarray, shape (n_dofs,)
        Solution [K].
    t : float
        Time [s].
    system : Assembled, optional
        The system assembled at ``u``.
    capacitance_rate : ndarray, shape (n_dofs,), optional
        ``C dT/dt`` [W] in a transient analysis; its sum is the stored energy rate.
    u_prev, dt
        Previous solution and time step [s], passed on to the terms.

    Returns
    -------
    EnergyBalance
    """
    if system is None:
        system = assemble(problem, u, t, u_prev, dt)
    flows = heat_flows(problem, u, t, system, capacitance_rate, u_prev, dt)
    stored = float(capacitance_rate.sum()) if capacitance_rate is not None else 0.0
    gross = 0.0
    if problem.constraints:
        idx, _ = problem.prescribed_owners(t)
        at_nodes = reaction_vector(system, u, capacitance_rate)[idx]
        gross = float(max(at_nodes[at_nodes > 0.0].sum(), -at_nodes[at_nodes < 0.0].sum()))
    return EnergyBalance(flows, stored, gross)


def gross_through_constraints(problem: CompiledProblem, reaction: ndarray, t: float) -> float:
    """Heat passing through the prescribed nodes, summed node by node [W]."""
    if not problem.constraints:
        return 0.0
    idx, _ = problem.prescribed_owners(t)
    at_nodes = reaction[idx]
    return float(max(at_nodes[at_nodes > 0.0].sum(), -at_nodes[at_nodes < 0.0].sum()))


def step_energy_balance(
    problem: CompiledProblem,
    theta: float,
    t: float,
    dt: float,
    T: ndarray,
    T_prev: ndarray,
    g_new: ndarray,
    g_prev: ndarray,
    capacitance_rate: ndarray,
    heats_prev: dict[str, float],
    row_theta: float | ndarray | None = None,
) -> tuple[EnergyBalance, dict[str, float]]:
    """Energy balance of one time step of the theta-method.

    The scheme balances the stored-energy rate against the *theta-weighted* heat flows of
    the two ends of the step, ``C dT/dt = theta g_{n+1} + (1 - theta) g_n``. The balance
    reported for the step therefore uses the same weighting, so that it closes to the
    solver residual: each load contributes ``theta q_{n+1} + (1 - theta) q_n``, and a
    fixed temperature the reaction ``(C dT/dt - theta g_{n+1} - (1 - theta) g_n)_p``.

    Parameters
    ----------
    problem : CompiledProblem
    theta : float
        The theta used by the step.
    t, dt : float
        Time at the end of the step and its size [s].
    T, T_prev : ndarray
        Solution at the end and at the start of the step [K].
    g_new, g_prev : ndarray
        ``g(T, t)`` and ``g(T_prev, t - dt)`` [W].
    capacitance_rate : ndarray
        ``C (T - T_prev) / dt`` [W].
    heats_prev : dict of str to float
        Result of :func:`~thermalfea.post.reactions.term_heats` at the start of the step.
    row_theta : float or ndarray, optional
        The theta of every row as the solver used it (1 on the rows without capacitance,
        Theory §6); by default ``theta``. The reactions at prescribed DOFs use it. The
        loads keep the weighting by ``theta``: a row without capacitance is converged at
        both ends of the step (``g_r = 0``), so the balance still closes.

    Returns
    -------
    balance : EnergyBalance
    heats_new : dict of str to float
        Term heats at the end of the step, to pass as ``heats_prev`` of the next one.
    """
    heats_new = term_heats(problem, T, t, T_prev, dt)
    flows = {
        name: theta * heat + (1.0 - theta) * heats_prev.get(name, heat)
        for name, heat in heats_new.items()
    }
    weight = theta if row_theta is None else row_theta
    reaction = capacitance_rate - weight * g_new - (1.0 - weight) * g_prev
    for name, heat in constraint_heats(problem, reaction, t).items():
        flows[name] = flows.get(name, 0.0) + heat
    balance = EnergyBalance(
        flows, float(capacitance_rate.sum()), gross_through_constraints(problem, reaction, t)
    )
    return balance, heats_new
