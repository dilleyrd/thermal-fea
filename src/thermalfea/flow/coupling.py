"""Streams and a pipe network coupled to the solid (Theory §9, Data §13).

:class:`StreamNetworkProvider` is the :class:`~thermalfea.flow.provider.FlowProvider` of
the one-dimensional flow solver. It owns the stream terms and, when the model has a
network, keeps the mass flow of every stream on a branch up to date:

    "Fluid properties in the network use each branch's mean stream temperature; the
    hydraulic and thermal solutions are alternated inside the nonlinear loop (hydraulics
    updated at most once per nonlinear iteration, and only when a branch's mean
    temperature has changed by more than 1 K)."

The heat-transfer coefficients of the streams are evaluated by their terms at each
assembly, with properties of the current iterate (lagged).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray

from ..convection import correlations as c
from ..convection.fluid_props import fluid_props
from ..core.errors import ModelError
from ..model.bcs import FlowNetwork, Stream
from ..solver.results_writer import FLUID_FIELD
from ..solver.terms import State, Term
from .network import NetworkSolution, solve_network_full
from .stream import StreamTerm, ThroughPlaneStreamTerm, stream_items

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem

log = logging.getLogger(__name__)

#: Hydraulics are re-solved when a branch's mean temperature has moved by more than this.
HYDRAULICS_DT = 1.0  # K

#: Per-step scalars written for every stream (Data §9, ``/fluid/<stream>``).
STREAM_SCALARS = ("mass_flow", "h_mean", "Re", "dp", "T_in", "T_out", "heat")


class StreamNetworkProvider:
    """The one-dimensional stream and network solver as a flow provider.

    Parameters
    ----------
    streams : list of Stream
        In-plane and through-plane streams.
    network : FlowNetwork, optional
        Pipe network that distributes the flow among the streams on its branches.
    """

    def __init__(self, streams: list[Stream] | None = None, network: FlowNetwork | None = None):
        self.streams: dict[str, Stream] = {}
        self.network = network
        self._terms: dict[str, Term] = {}
        self._pending = list(streams or [])
        self._branch_of: dict[str, str] = {}  # stream name -> id of the branch that feeds it
        self._last_T: dict[str, float] | None = None
        self._problem: CompiledProblem | None = None
        self.solution: NetworkSolution | None = None
        self.hydraulic_solves = 0

    # ------------------------------------------------------------------------ setup

    def _feeding_branches(self) -> dict[str, str]:
        """For every stream named by the network, the branch whose flow it takes.

        A stream may lend its area to several branches (a duct and its entry loss, say);
        its flow is that of its one duct branch, or of its one branch when it has no duct.
        """
        named: dict[str, list] = {}
        for branch in self.network.branches if self.network is not None else []:
            if branch.stream is not None:
                named.setdefault(branch.stream, []).append(branch)
        feeds = {}
        for name, branches in named.items():
            ducts = [b for b in branches if b.kind == "duct"]
            candidates = ducts or branches
            if len(candidates) > 1:
                raise ModelError(
                    f"stream {name!r} is on {len(candidates)} network branches "
                    f"({', '.join(repr(b.id) for b in candidates)}); it can take its flow "
                    "from one duct branch only"
                )
            feeds[name] = candidates[0].id
        return feeds

    def setup(self, problem: CompiledProblem) -> None:
        """Create the terms and constraints of every stream and attach them to the problem."""
        self._problem = problem
        self._branch_of = self._feeding_branches()
        for stream in self._pending:
            self.add_stream(problem, stream)
        self._pending = []
        missing = sorted(set(self._branch_of) - set(self.streams))
        if missing:
            raise ModelError(f"the flow network refers to unknown stream(s) {missing}")

    def add_stream(self, problem: CompiledProblem, stream: Stream) -> Term:
        """Add one stream: build its term (and inlet constraint) and set them up."""
        self._problem = problem
        if stream.name in self.streams:
            raise ModelError(f"two streams are called {stream.name!r}")
        terms, constraints = stream_items(stream)
        (term,) = terms
        if stream.name in self._branch_of:
            # its flow follows the hydraulics, which depend on the temperatures
            term.is_linear = False
        for target, items in ((problem.terms, terms), (problem.constraints, constraints)):
            for item in items:
                try:
                    item.setup(problem)
                except ModelError as exc:
                    raise ModelError(f"{item.name}: {exc}") from None
                target.append(item)
        self.streams[stream.name] = stream
        self._terms[stream.name] = term
        return term

    def terms(self) -> list[Term]:
        """The coupling terms of all streams."""
        return list(self._terms.values())

    def term(self, name: str) -> Term:
        """The term of one stream."""
        try:
            return self._terms[name]
        except KeyError:
            raise ModelError(f"unknown stream {name!r}") from None

    def initialize(self, u: ndarray, t: float) -> None:
        """Give the fluid nodes of every in-plane stream their starting temperature.

        The fluid is quasi-steady (Theory §9.1), so it has no initial condition of its
        own: the nodes are set to the inlet temperature and then, cell by cell from the
        inlet, to the temperature that satisfies the fluid energy equation for the
        initial wall temperatures.

        Parameters
        ----------
        u : ndarray, shape (n_dofs,)
            Initial solution [K]; its fluid entries are overwritten.
        t : float
            Start time [s].
        """
        in_plane = [term for term in self._terms.values() if isinstance(term, StreamTerm)]
        for term in in_plane:
            u[term.fluid_dofs] = float(term.stream.T_inlet(t=t))
        if self._problem is None:
            return
        state = State(u=u, u_prev=u, t=t, dt=None, dofs=self._problem.dofs)
        self.update(state)
        for term in in_plane:
            m_cp = term.capacity_rate(t)
            for cell in range(term.n_cells):
                up, down = term.fluid_dofs[cell], term.fluid_dofs[cell + 1]
                u[down] = u[up] + term.heat_to_fluid(state)[cell] / m_cp

    # -------------------------------------------------------------------- hydraulics

    def _mean_temperature(self, term: Term, s: State) -> float:
        """Mean temperature of a stream's fluid [K]."""
        if isinstance(term, StreamTerm):
            return float(np.mean(s.u[term.fluid_dofs]))
        return float(term.stream.T_inlet(t=s.t))  # type: ignore[attr-defined]

    def update(self, s: State) -> None:
        """Re-solve the network hydraulics when a branch temperature has moved enough.

        Hydraulics are solved on the first call and thereafter only when the mean stream
        temperature of some branch differs by more than :data:`HYDRAULICS_DT` from the
        value used for the last solve. Each branch's mass flow then feeds its stream.
        """
        if self.network is None or not self._branch_of:
            return
        # mean temperature of every stream on the network; a branch has its stream's
        temperatures = {
            name: self._mean_temperature(self._terms[name], s) for name in self._branch_of
        }
        usable = all(np.isfinite(v) and v > 0.0 for v in temperatures.values())
        if not usable and self._last_T is not None:
            return  # an unusable trial state: keep the flows of the last solve
        if self._last_T is not None and all(
            abs(temperatures[n] - self._last_T[n]) <= HYDRAULICS_DT for n in temperatures
        ):
            return
        fluid_T = {
            branch.id: temperatures[branch.stream]
            for branch in self.network.branches
            if branch.stream in temperatures
        }
        self.solution = solve_network_full(self.network, self.streams, fluid_T)
        self._last_T = temperatures
        self.hydraulic_solves += 1
        for name, branch in self._branch_of.items():
            flow = self.solution.mass_flow[branch]
            if not flow > 0.0:
                raise ModelError(
                    f"the network gives stream {name!r} a mass flow of {flow:g} kg/s; flow "
                    "against the direction of a stream's path is not supported — reverse "
                    "the branch or the path"
                )
            self._terms[name].mass_flow_override = flow  # type: ignore[attr-defined]
        log.debug("hydraulics solved (%d): %s", self.hydraulic_solves, self.solution.mass_flow)

    # ----------------------------------------------------------------------- results

    def static(self) -> dict[str, dict[str, ndarray | str]]:
        """Step-independent data of every stream.

        ``mode`` for all; for an in-plane stream also ``s`` (path coordinate of its fluid
        nodes [m]) and ``dofs`` (their DOF numbers).
        """
        out: dict[str, dict[str, ndarray | str]] = {}
        for name, term in self._terms.items():
            out[name] = {"mode": self.streams[name].mode}
            if isinstance(term, StreamTerm):
                out[name].update(s=term.node_s, dofs=term.fluid_dofs)
        return out

    def _numbers(self, name: str, term: Term, s: State) -> dict[str, float]:
        """The per-step scalars of one stream (NaN where a quantity does not apply)."""
        stream = self.streams[name]
        out = dict.fromkeys(STREAM_SCALARS, float("nan"))
        in_plane = isinstance(term, StreamTerm)
        T_in = float(stream.T_inlet(t=s.t))
        out["T_in"] = T_in
        if in_plane:
            fluid = s.u[term.fluid_dofs]
            reference = fluid[:-1]
            out["T_out"] = float(fluid[-1])
            h, _ = term.coefficients(s)
            _, A, _, _ = term._operators(s.dofs.n_dofs)
            cell_area = A.T @ term.edge_area
            out["h_mean"] = float((h * cell_area).sum() / cell_area.sum())
            out["heat"] = float(term.heat_to_fluid(s).sum())
        else:
            reference = np.array([T_in])
            out["T_out"] = T_in
            out["h_mean"] = float(term.mean_coefficient(s))  # type: ignore[attr-defined]
            out["heat"] = -float(term.boundary_heat(s))
        try:
            flow = float(term.mass_flow(s.t))  # type: ignore[attr-defined]
        except ModelError:
            return out  # a given h without a mass flow: nothing more to report
        out["mass_flow"] = flow
        p = fluid_props(term.fluid, reference)  # type: ignore[attr-defined]
        D_h = term.D_h  # type: ignore[attr-defined]
        reynolds = flow * D_h / (stream.flow_area * p.mu)
        out["Re"] = float(np.mean(reynolds))
        branch = self._branch_of.get(name)
        if branch is not None and self.solution is not None:
            out["dp"] = float(self.solution.pressure_drop[branch])
        elif in_plane:
            rho = float(np.mean(p.rho))
            f = float(c.friction_churchill(out["Re"], stream.roughness / D_h))
            velocity = flow / (rho * stream.flow_area)
            out["dp"] = float(c.pressure_drop(f, term.length, D_h, 0.0, rho, velocity))
        return out

    def results(self, s: State) -> dict[str, ndarray]:
        """Per-step output of every stream.

        Keys are ``"<quantity>:<stream name>"``: ``T_fluid`` (temperature of the fluid
        nodes of an in-plane stream [K]) and the scalars ``mass_flow`` [kg/s], ``h_mean``
        [W/(m^2 K)], ``Re``, ``dp`` [Pa], ``T_in``, ``T_out`` [K] and ``heat`` (heat
        picked up from the walls [W]).
        """
        out: dict[str, ndarray] = {}
        for name, term in self._terms.items():
            if isinstance(term, StreamTerm):
                out[f"{FLUID_FIELD}:{name}"] = np.array(s.u[term.fluid_dofs], dtype=float)
            for key, value in self._numbers(name, term, s).items():
                out[f"{key}:{name}"] = np.array([value])
        return out


def provider_of(problem: CompiledProblem) -> StreamNetworkProvider:
    """The stream provider of a problem, created (and registered) on first use."""
    for provider in problem.providers:
        if isinstance(provider, StreamNetworkProvider):
            return provider
    provider = StreamNetworkProvider()
    problem.providers.append(provider)
    return provider


__all__ = [
    "FLUID_FIELD",
    "HYDRAULICS_DT",
    "STREAM_SCALARS",
    "StreamNetworkProvider",
    "ThroughPlaneStreamTerm",
    "provider_of",
]
