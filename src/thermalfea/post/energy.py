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
from ..solver.steady import STEADY_TIME
from .reactions import heat_flows


@dataclass
class EnergyBalance:
    """Heat entering the body by source, the stored energy rate, and what is left over.

    Attributes
    ----------
    flows : dict of str to float
        Name of each load or boundary condition -> heat entering the body [W].
    stored_rate : float
        Rate of change of the stored energy ``dE/dt = sum(C dT/dt)`` [W]; 0 when steady.
    """

    flows: dict[str, float] = field(default_factory=dict)
    stored_rate: float = 0.0

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
        return max([abs(v) for v in self.flows.values()] + [abs(self.stored_rate)], default=0.0)

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
    flows = heat_flows(problem, u, t, system, capacitance_rate, u_prev, dt)
    stored = float(capacitance_rate.sum()) if capacitance_rate is not None else 0.0
    return EnergyBalance(flows, stored)
