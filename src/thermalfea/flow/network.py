"""Pipe-network hydraulics (Theory §9.2).

Nodes carry pressure; branches are ducts (§8.1 pressure drop) or minor-loss elements.
The branch law ``m = sign(dp) A sqrt(2 rho |dp| / (f L / D_h + K_minor))`` is linearised as
``m = c (p_from - p_to)`` and the nodal system is iterated with an under-relaxed ``c``.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np
from numpy import ndarray
from scipy.sparse import csr_matrix

from ..convection.correlations import friction_churchill, hydraulic_diameter
from ..convection.fluid_props import fluid_props
from ..core.errors import ConvergenceError, ModelError
from ..materials import library
from ..model.bcs import FlowNetwork, Stream
from ..solver.linear import default_solver

log = logging.getLogger(__name__)

#: Starting assumption: laminar flow, ``f = 64 / Re`` at this Reynolds number.
RE_START = 1000.0
#: Under-relaxation factor of the branch conductance ``c``.
RELAXATION = 0.5
#: Convergence limit on the largest relative change of any branch mass flow.
TOLERANCE = 1e-6
#: Iteration cap.
MAX_ITERATIONS = 200


@dataclass
class NetworkSolution:
    """Result of :func:`solve_network_full`.

    Attributes
    ----------
    mass_flow : dict
        Branch id -> mass flow [kg/s], positive from ``node_from`` to ``node_to``.
    pressure : dict
        Node id -> pressure [Pa].
    iterations : int
        Number of nodal solves.
    converged : bool
        Always True for a returned solution (non-convergence raises).
    friction : dict
        Branch id -> Churchill friction factor at the solution.
    reynolds : dict
        Branch id -> Reynolds number at the solution.
    pressure_drop : dict
        Branch id -> ``p_from - p_to`` [Pa].
    """

    mass_flow: dict[str, float]
    pressure: dict[str, float]
    iterations: int
    converged: bool
    friction: dict[str, float]
    reynolds: dict[str, float]
    pressure_drop: dict[str, float]


def _stream_map(streams: Mapping[str, Stream] | Sequence[Stream]) -> dict[str, Stream]:
    if isinstance(streams, Mapping):
        return dict(streams)
    return {s.name: s for s in streams}


def _friction(Re: ndarray, rel_rough: ndarray) -> ndarray:
    """Churchill ``f``; a zero Reynolds number (no flow yet) is replaced by ``RE_START``."""
    Re_safe = np.where(Re > 0.0, Re, RE_START)
    return np.asarray(friction_churchill(Re_safe, rel_rough), dtype=float)


def _rel_change(new: ndarray, old: ndarray) -> float:
    """Largest relative difference, relative to the larger magnitude (0 for two zeros)."""
    scale = np.maximum(np.abs(new), np.abs(old))
    safe = np.where(scale > 0.0, scale, 1.0)
    return float(np.max(np.abs(new - old) / safe))


def solve_network_full(
    network: FlowNetwork,
    streams: Mapping[str, Stream] | Sequence[Stream],
    fluid_T: Mapping[str, float] | float,
) -> NetworkSolution:
    """Solve a flow network for branch mass flows and nodal pressures (Theory §9.2).

    Parameters
    ----------
    network : FlowNetwork
        Nodes (prescribed ``pressure`` [Pa] or ``inflow`` [kg/s]) and branches.
    streams : mapping of str to Stream, or sequence of Stream
        Streams naming the flow area [m^2], wetted perimeter [m], roughness [m] and fluid.
    fluid_T : mapping of str to float, or float
        Fluid temperature [K] of each branch (by branch id), or one value for all.

    Returns
    -------
    NetworkSolution

    Raises
    ------
    ModelError
        Invalid network (empty, duplicates, unknown ids, no pressure reference, missing
        stream, non-positive length or loss coefficient).
    SolverError
        If the nodal system is singular (for example a disconnected node).
    ConvergenceError
        If the iteration cap is reached.
    """
    nodes, branches = network.nodes, network.branches
    if not nodes or not branches:
        raise ModelError("flow network needs at least one node and one branch")
    node_ids = [n.id for n in nodes]
    branch_ids = [b.id for b in branches]
    if len(set(node_ids)) != len(node_ids):
        raise ModelError("flow network has duplicate node ids")
    if len(set(branch_ids)) != len(branch_ids):
        raise ModelError("flow network has duplicate branch ids")
    index = {nid: i for i, nid in enumerate(node_ids)}
    for n in nodes:
        if n.pressure is not None and n.inflow is not None:
            raise ModelError(f"node {n.id!r} has both a pressure and an inflow")
    if not any(n.pressure is not None for n in nodes):
        raise ModelError("flow network needs at least one node with a prescribed pressure")

    smap = _stream_map(streams)
    nb = len(branches)
    ifrom = np.empty(nb, dtype=int)
    ito = np.empty(nb, dtype=int)
    A = np.empty(nb)
    Dh = np.empty(nb)
    rho = np.empty(nb)
    mu = np.empty(nb)
    rough = np.empty(nb)
    length = np.zeros(nb)
    K = np.zeros(nb)
    is_duct = np.zeros(nb, dtype=bool)
    for k, b in enumerate(branches):
        for nid in (b.node_from, b.node_to):
            if nid not in index:
                raise ModelError(f"branch {b.id!r}: unknown node {nid!r}")
        ifrom[k], ito[k] = index[b.node_from], index[b.node_to]
        if b.stream is None:
            raise ModelError(f"branch {b.id!r} names no stream (it would have no flow area)")
        if b.stream not in smap:
            raise ModelError(f"branch {b.id!r}: unknown stream {b.stream!r}")
        s = smap[b.stream]
        if isinstance(fluid_T, Mapping):
            if b.id not in fluid_T:
                raise ModelError(f"no fluid temperature for branch {b.id!r}")
            T = float(fluid_T[b.id])
        else:
            T = float(fluid_T)
        props = fluid_props(library.fluid(s.fluid), T)
        A[k] = s.flow_area
        Dh[k] = float(hydraulic_diameter(s.flow_area, s.wetted_perimeter))
        rho[k], mu[k] = float(props.rho), float(props.mu)
        rough[k] = s.roughness
        K[k] = b.K_minor
        if b.kind == "duct":
            is_duct[k] = True
            length[k] = b.length
            if not b.length > 0.0:
                raise ModelError(f"duct branch {b.id!r} needs a positive length")
        elif not b.K_minor > 0.0:
            raise ModelError(f"loss branch {b.id!r} needs a positive K_minor")
        if not (A[k] > 0.0 and Dh[k] > 0.0 and rho[k] > 0.0 and mu[k] > 0.0):
            raise ModelError(f"branch {b.id!r}: stream area, perimeter and fluid must be positive")
    rel_rough = rough / Dh
    L_over_D = np.where(is_duct, length / Dh, 0.0)

    def resistance(f: ndarray) -> ndarray:
        return f * L_over_D + K

    nn = len(nodes)
    fixed = np.array([n.pressure is not None for n in nodes])
    p_fixed = np.array([n.pressure if n.pressure is not None else 0.0 for n in nodes])
    inflow = np.array([n.inflow if n.inflow is not None else 0.0 for n in nodes], dtype=float)
    free = np.flatnonzero(~fixed)
    pos = -np.ones(nn, dtype=int)
    pos[free] = np.arange(free.size)
    solver = default_solver()

    # Start: laminar at Re = RE_START
    m_prev = RE_START * A * mu / Dh
    f0 = np.full(nb, 64.0 / RE_START)
    dp0 = resistance(f0) * m_prev**2 / (2.0 * rho * A**2)
    c = m_prev / dp0

    def solve_nodes(c: ndarray) -> ndarray:
        p = p_fixed.copy()
        if free.size:
            rows: list[int] = []
            cols: list[int] = []
            vals: list[float] = []
            rhs = inflow[free].copy()
            for k in range(nb):
                a, b = ifrom[k], ito[k]
                for i, j in ((a, b), (b, a)):
                    if fixed[i]:
                        continue
                    rows.append(pos[i])
                    cols.append(pos[i])
                    vals.append(c[k])
                    if fixed[j]:
                        rhs[pos[i]] += c[k] * p_fixed[j]
                    else:
                        rows.append(pos[i])
                        cols.append(pos[j])
                        vals.append(-c[k])
            M = csr_matrix((vals, (rows, cols)), shape=(free.size, free.size))
            p[free] = solver.factorize(M, True).solve(rhs)
        return p

    change = np.inf
    for it in range(1, MAX_ITERATIONS + 1):
        p = solve_nodes(c)
        dp = p[ifrom] - p[ito]
        m_lin = c * dp
        Re_prev = np.abs(m_prev) * Dh / (A * mu)
        f = _friction(Re_prev, rel_rough)
        m_new = np.sign(dp) * A * np.sqrt(2.0 * rho * np.abs(dp) / resistance(f))
        with np.errstate(divide="ignore", invalid="ignore"):
            c_new = np.where(dp != 0.0, m_new / dp, c)
        # The iterates are the linearised flows of successive solves (m_new does not depend
        # on c when the pressures are prescribed, so it alone could not show convergence).
        # Likewise m_lin alone cannot show convergence when the flow is prescribed, so the
        # branch law must also be met: the change is the larger of the two measures.
        change = max(_rel_change(m_lin, m_prev), _rel_change(m_new, m_lin))
        log.debug("network iteration %d: max relative change %.3e", it, change)
        c = RELAXATION * c_new + (1.0 - RELAXATION) * c
        m_prev = m_lin
        if change < TOLERANCE:
            Re = np.abs(m_lin) * Dh / (A * mu)
            return NetworkSolution(
                mass_flow={bid: float(v) for bid, v in zip(branch_ids, m_lin, strict=True)},
                pressure={nid: float(v) for nid, v in zip(node_ids, p, strict=True)},
                iterations=it,
                converged=True,
                friction={bid: float(v) for bid, v in zip(branch_ids, _friction(Re, rel_rough),
                                                          strict=True)},
                reynolds={bid: float(v) for bid, v in zip(branch_ids, Re, strict=True)},
                pressure_drop={bid: float(v) for bid, v in zip(branch_ids, dp, strict=True)},
            )
    raise ConvergenceError(
        f"flow network did not converge in {MAX_ITERATIONS} iterations "
        f"(last relative change {change:.3e})"
    )


def solve_network(
    network: FlowNetwork,
    streams: Mapping[str, Stream] | Sequence[Stream],
    fluid_T: Mapping[str, float] | float,
) -> tuple[dict[str, float], dict[str, float]]:
    """Solve a flow network (Theory §9.2); see :func:`solve_network_full`.

    Returns
    -------
    mass_flow : dict
        Branch id -> mass flow [kg/s], positive from ``node_from`` to ``node_to``.
    pressure : dict
        Node id -> pressure [Pa].
    """
    sol = solve_network_full(network, streams, fluid_T)
    return sol.mass_flow, sol.pressure
