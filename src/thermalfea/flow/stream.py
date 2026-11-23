"""In-plane stream: fluid temperature along a wall, coupled to the solid (Theory §9.1).

A stream is a one-dimensional fluid path with mass flow ``m`` [kg/s], inlet temperature,
flow area and wetted perimeter, and wall boundary sets that it cools or heats. It is
divided into N cells along its path coordinate ``s``. Fluid node 0 is the inlet
(prescribed); fluid node j is the outlet of cell j-1. Fluid nodes are extra DOFs.

Per wall edge element i, in the cell containing the path coordinate of its midpoint:

* conductance ``G_i = h_i * integral of g ds`` over the edge;
* wall temperature ``T_w,i = sum_j w_j T_j`` with ``w_j = int N_j g ds / int g ds``.

Per cell with upstream fluid node u and downstream node d:

* ``G = sum G_i``, ``Tw = sum G_i T_w,i / G``, ``NTU = G / (m c_p)``;
* ``phi = (1 - exp(-NTU)) / NTU`` (``phi = 1`` when ``NTU < 1e-8``);
* effective fluid temperature seen by the wall: ``T_f* = (1 - phi) Tw + phi T_u``;
* heat from wall edge i to the fluid: ``Q_i = G_i (T_w,i - T_f*)``;
* fluid energy equation: ``m c_p (T_d - T_u) - sum_i Q_i = 0``.

``Q_i`` is removed from the wall nodes of edge i with the same weights ``w_j``. The scheme
is exact for a constant wall temperature per cell, cannot oscillate for any NTU, and
conserves energy exactly. The rows are linear in the temperatures (for frozen ``h`` and
``c_p``) and **unsymmetric**. Fluid thermal storage is neglected (quasi-steady fluid).

As a conductance-type matrix ``K_s`` (heat *leaving* each DOF is ``K_s T``): the row of
wall DOF a gets ``sum_i w_a,i G_i (T_w,i - (1 - phi) Tw - phi T_u)`` and the row of d gets
``m c_p (T_d - T_u) - sum_i G_i (T_w,i - (1 - phi) Tw - phi T_u)``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np
from numpy import ndarray
from scipy.sparse import coo_matrix, csr_matrix, diags

from ..convection import correlations as c
from ..convection.fluid_props import fluid_props
from ..core.errors import ModelError
from ..materials import library
from ..materials.material import Fluid
from ..model.bcs import Stream, diameter_ratio_problem
from ..physics.batches import FacetBatch, facet_batches
from ..physics.surface_loads import ConvectionTerm, FacetTerm
from ..solver.assembler import Assembler
from ..solver.terms import BaseTerm, State

if TYPE_CHECKING:
    from ..solver.problem import CompiledProblem

log = logging.getLogger(__name__)

NTU_SMALL = 1e-8  # below this, phi = 1
_S_TOL = 1e-9  # relative tolerance when comparing path coordinates
_MIN_PATH_POINTS = 2  # a path runs from an inlet point to an outlet point


# ----------------------------------------------------------------------------- geometry


def path_coordinate(points: ndarray, polyline: ndarray) -> ndarray:
    """Path coordinate of the projection of points onto a polyline.

    Parameters
    ----------
    points : ndarray, shape (n, dim)
        Positions [m].
    polyline : ndarray, shape (m, dim)
        Vertices of the path from inlet to outlet [m], ``m >= 2``.

    Returns
    -------
    ndarray, shape (n,)
        Arc length ``s`` [m] from the first vertex to the nearest point of the polyline.
    """
    a, b = polyline[:-1], polyline[1:]
    d = b - a
    length = np.linalg.norm(d, axis=1)
    if np.any(length <= 0.0):
        raise ModelError("a stream path has two coincident consecutive points")
    start = np.concatenate([[0.0], np.cumsum(length)[:-1]])
    rel = points[:, None, :] - a[None, :, :]  # (n, segments, dim)
    u = np.clip(np.einsum("nsi,si->ns", rel, d) / length**2, 0.0, 1.0)
    nearest = a[None] + u[..., None] * d[None]
    distance = np.linalg.norm(points[:, None, :] - nearest, axis=-1)
    best = np.argmin(distance, axis=1)
    rows = np.arange(points.shape[0])
    return start[best] + u[rows, best] * length[best]


def cell_edges(s_mid: ndarray, total: float, n_cells: int | None) -> ndarray:
    """Path coordinates of the cell boundaries.

    Parameters
    ----------
    s_mid : ndarray
        Path coordinates of the wall-edge midpoints [m].
    total : float
        Length of the path [m].
    n_cells : int or None
        Number of equal cells; ``None`` gives one cell per wall edge along the path
        (edges at the same path coordinate, such as the two sides of a channel, share a
        cell), with boundaries half-way between neighbouring edge midpoints.

    Returns
    -------
    ndarray, shape (N + 1,)
        Ascending boundaries from 0 to ``total``.
    """
    if n_cells is not None:
        if n_cells < 1:
            raise ModelError("a stream needs at least one cell")
        return np.linspace(0.0, total, n_cells + 1)
    distinct = np.unique(np.round(s_mid / (_S_TOL * max(total, 1.0)))) * _S_TOL * max(total, 1.0)
    if distinct.size == 0:
        return np.array([0.0, total])
    inner = 0.5 * (distinct[:-1] + distinct[1:])
    return np.concatenate([[0.0], inner, [total]])


def cell_matrix(G: ndarray, weights: ndarray, m_cp: float) -> ndarray:
    """Dense matrix of one stream cell (Theory §9.1), for reference and testing.

    DOF order: the wall DOFs (columns of ``weights``), then the upstream fluid node u,
    then the downstream fluid node d. The heat leaving each DOF is ``K @ T``; the row of
    u is empty (its equation belongs to the cell upstream, or to the inlet).

    Parameters
    ----------
    G : ndarray, shape (n_edges,)
        Conductance of each wall edge [W/K].
    weights : ndarray, shape (n_edges, n_wall)
        ``weights[i, a]`` is the weight of wall DOF a in the wall temperature of edge i;
        each row sums to 1.
    m_cp : float
        Capacity rate ``m c_p`` [W/K].

    Returns
    -------
    ndarray, shape (n_wall + 2, n_wall + 2)
    """
    n_wall = weights.shape[1]
    e = np.hstack([weights, np.zeros((weights.shape[0], 2))])  # T_w,i = e_i . T
    e_u = np.zeros(n_wall + 2)
    e_u[n_wall] = 1.0
    e_d = np.zeros(n_wall + 2)
    e_d[n_wall + 1] = 1.0
    total = float(G.sum())
    mean = (G[:, None] * e).sum(axis=0) / total if total > 0.0 else np.zeros(n_wall + 2)
    ntu = total / m_cp
    phi = 1.0 if ntu < NTU_SMALL else -np.expm1(-ntu) / ntu
    drive = e - (1.0 - phi) * mean - phi * e_u  # (T_w,i - T_f*) as a row per edge
    K = np.einsum("i,ia,ib->ab", G, e, drive)
    K[n_wall + 1] = m_cp * (e_d - e_u) - (G[:, None] * drive).sum(axis=0)
    return K


# --------------------------------------------------------------------------------- term


class InletConstraint:
    """Prescribes the temperature of the inlet fluid node of a stream."""

    #: The inlet node has no equation of its own, so no reaction heat flow is reported.
    exchanges_heat = False

    def __init__(self, term: StreamTerm) -> None:
        self.name = f"{term.name}: inlet"
        self._term = term
        self.is_time_dependent = term.stream.T_inlet.depends_on_time

    def setup(self, problem: CompiledProblem) -> None:
        """Nothing to resolve: the stream term owns the fluid DOFs."""

    def values(self, t: float) -> tuple[ndarray, ndarray]:
        """Return the inlet DOF and the inlet temperature [K] at time ``t`` [s]."""
        return self._term.fluid_dofs[:1], np.array([float(self._term.stream.T_inlet(t=t))])

    def breakpoints(self) -> list[float]:
        """Breakpoints of the inlet-temperature function."""
        return self._term.stream.T_inlet.breakpoints()


class _StreamCommon:
    """Parts shared by the in-plane and the through-plane stream terms.

    Holds the stream, its fluid and hydraulic diameter, the construction checks, the
    mass flow (own or imposed by a network branch) and the time breakpoints.
    """

    name: str
    stream: Stream
    fluid: Fluid
    D_h: float
    mass_flow_override: float | None

    def _init_stream(self, stream: Stream) -> None:
        """Check the stream's data and set ``stream``, ``fluid``, ``D_h`` and flags."""
        if stream.flow_area <= 0.0 or stream.wetted_perimeter <= 0.0:
            raise ModelError(f"stream {stream.name!r}: flow area and perimeter must be positive")
        if stream.h_multiplier <= 0.0:
            raise ModelError(f"stream {stream.name!r}: h_multiplier must be positive")
        message = diameter_ratio_problem(stream)
        if message:
            raise ModelError(f"stream {stream.name!r}: {message}")
        if stream.T_inlet.depends_on_T:
            raise ModelError(f"stream {stream.name!r}: the inlet temperature cannot depend on T")
        if stream.mass_flow is not None and stream.mass_flow.depends_on_T:
            raise ModelError(f"stream {stream.name!r}: the mass flow may depend on time only")
        self.stream = stream
        self.fluid = library.fluid(stream.fluid)
        self.D_h = float(c.hydraulic_diameter(stream.flow_area, stream.wetted_perimeter))
        override = stream.h_override
        if override is not None and override.depends_on_T:
            raise ModelError(f"stream {stream.name!r}: h_override may depend on time only")
        functions = [stream.T_inlet, stream.mass_flow, override]
        self.is_time_dependent = any(f is not None and f.depends_on_time for f in functions)
        #: mass flow [kg/s] imposed from outside (a network branch); overrides the model's
        self.mass_flow_override = None

    def mass_flow(self, t: float) -> float:
        """Mass flow of the stream [kg/s] at time ``t`` [s]."""
        if self.mass_flow_override is not None:
            value = self.mass_flow_override
        elif self.stream.mass_flow is not None:
            value = float(self.stream.mass_flow(t=t))
        else:
            raise ModelError(
                f"stream {self.name!r} has no mass flow: give one, or attach it to a "
                "network branch"
            )
        if not value > 0.0:
            raise ModelError(
                f"stream {self.name!r}: the mass flow must be positive (got {value:g} kg/s); "
                "reverse the path for flow in the other direction"
            )
        return value

    def breakpoints(self) -> list[float]:
        """Breakpoints of the stream's functions of time."""
        stream = self.stream
        functions = [stream.T_inlet, stream.mass_flow, stream.h_override]
        return sorted({t for f in functions if f is not None for t in f.breakpoints()})


class StreamTerm(_StreamCommon, BaseTerm):
    """An in-plane stream coupled to the wall edges it wets (Theory §9.1).

    Parameters
    ----------
    stream : Stream
        ``mode`` must be ``"in_plane"``; ``path`` and ``mass_flow`` are required.
    """

    symmetric = False

    def __init__(self, stream: Stream) -> None:
        BaseTerm.__init__(self, stream.name)
        if stream.mode != "in_plane":
            raise ModelError(f"stream {stream.name!r} is not an in-plane stream")
        if not stream.path or len(stream.path) < _MIN_PATH_POINTS:
            raise ModelError(f"stream {stream.name!r}: an in-plane stream needs a path")
        self._init_stream(stream)
        self.group = f"stream:{stream.name}"
        # with a given h, a single c_p and no temperature-dependent property the rows are
        # linear in the temperatures
        self.is_linear = stream.h_override is not None
        self.fluid_dofs: ndarray = np.empty(0, dtype=np.int64)
        self._cache: dict[int, tuple] = {}

    # ------------------------------------------------------------------------ setup

    def setup(self, problem: CompiledProblem) -> None:
        """Resolve the wall edges, build the cells and create the fluid DOFs."""
        mesh = problem.mesh
        tags: list[int] = []
        for wall in self.stream.walls:
            tags += problem.selection_tags(wall, (mesh.dim - 1,))[1]
        batches = facet_batches(problem, tags)
        if not batches:
            raise ModelError(f"stream {self.name!r}: its walls contain no element edges")
        polyline = np.asarray(self.stream.path, dtype=float)
        self.length = float(np.linalg.norm(np.diff(polyline, axis=0), axis=1).sum())

        rows, cols, vals, area, mid = [], [], [], [], []
        offset = 0
        for b in batches:
            weighted = np.einsum("fp,pn->fn", b.g * b.geom.dS, b.geom.N)  # int N_j g ds
            a = weighted.sum(axis=1)  # int g ds
            if not bool(np.all(a > 0.0)):
                raise ModelError(
                    f"stream {self.name!r}: a wall lies on the axis r = 0, where a surface "
                    "has zero area; move the stream's walls off the axis"
                )
            n_f, n_n = b.dofs.shape
            rows.append(np.repeat(offset + np.arange(n_f), n_n))
            cols.append(b.dofs.ravel())
            vals.append((weighted / a[:, None]).ravel())
            area.append(a)
            # geometric midpoint of the edge (length-weighted mean of its points)
            mid.append(
                np.einsum("fp,fpi->fi", b.geom.dS, b.geom.xgp) / b.geom.dS.sum(axis=1)[:, None]
            )
            offset += n_f
        self._e = (np.concatenate(rows), np.concatenate(cols), np.concatenate(vals))
        self.edge_area = np.concatenate(area)  # (F,) int g ds of each wall edge [m^2]
        self.edge_s = path_coordinate(np.concatenate(mid), polyline)  # (F,) [m]

        self.edges = cell_edges(self.edge_s, self.length, self.stream.n_cells)
        self.n_cells = self.edges.size - 1
        self.edge_cell = np.clip(
            np.searchsorted(self.edges, self.edge_s, side="right") - 1, 0, self.n_cells - 1
        )
        problem.dofs.add_extra(self.group, self.n_cells + 1)
        self.fluid_dofs = problem.dofs.extra_dofs(self.group)
        self.node_s = self.edges.copy()  # path coordinate of every fluid node [m]
        self._cache.clear()
        if self.stream.mass_flow is None and self.mass_flow_override is None:
            log.debug("stream %r takes its mass flow from a network branch", self.name)

    def _operators(self, n_dofs: int) -> tuple[csr_matrix, csr_matrix, csr_matrix, csr_matrix]:
        """Sparse operators E (edge <- DOFs), A (edge <- cell), U and D (cell <- DOFs)."""
        if n_dofs not in self._cache:
            n_edges, n_cells = self.edge_area.size, self.n_cells
            rows, cols, vals = self._e
            E = coo_matrix((vals, (rows, cols)), shape=(n_edges, n_dofs)).tocsr()
            ones = np.ones(n_edges)
            A = coo_matrix(
                (ones, (np.arange(n_edges), self.edge_cell)), shape=(n_edges, n_cells)
            ).tocsr()
            cells = np.arange(n_cells)
            unit = np.ones(n_cells)
            U = coo_matrix((unit, (cells, self.fluid_dofs[:-1])), shape=(n_cells, n_dofs)).tocsr()
            D = coo_matrix((unit, (cells, self.fluid_dofs[1:])), shape=(n_cells, n_dofs)).tocsr()
            self._cache = {n_dofs: (E, A, U, D)}
        return self._cache[n_dofs]

    # ---------------------------------------------------------------------- physics

    def capacity_rate(self, t: float) -> float:
        """``m c_p`` [W/K], with ``c_p`` at the inlet temperature (one value per stream)."""
        cp = float(fluid_props(self.fluid, float(self.stream.T_inlet(t=t))).cp)
        return self.mass_flow(t) * cp

    def coefficients(self, s: State) -> tuple[ndarray, dict[str, ndarray]]:
        """Heat-transfer coefficient of every cell [W/(m^2 K)] and the numbers behind it.

        ``h`` comes from the duct correlation of Theory §8.1 with properties at the
        cell's upstream fluid-node temperature of the current iterate, or from the
        stream's ``h_override``. The multiplier is applied.
        """
        stream = self.stream
        if stream.h_override is not None:  # no property is needed: independent of s.u
            h = np.full(self.n_cells, float(stream.h_override(t=s.t)))
            return h * stream.h_multiplier, {}
        m = self.mass_flow(s.t)
        T_up = s.u[self.fluid_dofs[:-1]]
        p = fluid_props(self.fluid, T_up)
        Re = m * self.D_h / (stream.flow_area * p.mu)
        numbers = {"Re": np.asarray(Re), "Pr": np.asarray(p.Pr)}
        E, A, _, _ = self._operators(s.dofs.n_dofs)
        # wall hotter than the fluid? (only the Dittus-Boelter exponent depends on it)
        weight = A.T @ self.edge_area
        wall = (A.T @ (self.edge_area * (E @ s.u))) / np.where(weight > 0.0, weight, 1.0)
        # one flag per stream, decided over the cells that have a wall only (a cell without
        # a wall edge has no wall temperature); with no walled cell at all: cooling exponent
        walled = weight > 0.0
        heating = bool(walled.any() and np.mean(wall[walled]) > np.mean(T_up[walled]))
        mu_ratio = 1.0
        if stream.nu_option == "sieder_tate":
            # Theory §8.1: mu_s at the cell's mean wall temperature (a cell without a wall
            # edge has none: mu_s = mu)
            mu_ratio = p.mu / fluid_props(self.fluid, np.where(walled, wall, T_up)).mu
        Nu = c.nu_duct(
            Re, p.Pr, stream.cross_section, "constant_T", stream.nu_option, heating,
            stream.diameter_ratio, mu_ratio,
        )
        numbers["Nu"] = np.asarray(Nu)
        h = np.asarray(c.nusselt_to_h(Nu, p.k, self.D_h), dtype=float)
        return h * stream.h_multiplier, numbers

    def _cell_state(self, s: State) -> tuple:
        """Edge conductances, cell conductances, phi and the capacity rate."""
        _, A, _, _ = self._operators(s.dofs.n_dofs)
        h, _ = self.coefficients(s)
        G_edge = (A @ h) * self.edge_area
        G_cell = A.T @ G_edge
        m_cp = self.capacity_rate(s.t)
        ntu = G_cell / m_cp
        with np.errstate(divide="ignore", invalid="ignore"):
            phi = np.where(ntu < NTU_SMALL, 1.0, -np.expm1(-ntu) / np.where(ntu > 0, ntu, 1.0))
        return G_edge, G_cell, phi, m_cp

    def matrix(self, s: State) -> csr_matrix:
        """The stream's conductance-type matrix ``K_s`` (heat leaving each DOF is ``K_s T``)."""
        E, A, U, D = self._operators(s.dofs.n_dofs)
        G_edge, G_cell, phi, m_cp = self._cell_state(s)
        safe = np.where(G_cell > 0.0, G_cell, 1.0)
        mean = diags(1.0 / safe) @ (A.T @ (diags(G_edge) @ E))  # cell <- DOFs: mean wall T
        # (T_w,i - T_f*) as a row per edge
        drive = E - diags(A @ (1.0 - phi)) @ (A @ mean) - diags(A @ phi) @ (A @ U)
        wall_rows = E.T @ (diags(G_edge) @ drive)
        fluid_rows = D.T @ (m_cp * (D - U) - diags(G_cell * phi) @ (mean - U))
        return (wall_rows + fluid_rows).tocsr()

    def conductance(self, s: State, asm: Assembler) -> None:
        """Add ``K_s`` to ``K``."""
        asm.add_sparse(self.matrix(s))

    def heat_to_fluid(self, s: State) -> ndarray:
        """Heat passing from the wall to the fluid in each cell [W], shape (N,)."""
        E, A, U, _ = self._operators(s.dofs.n_dofs)
        G_edge, G_cell, phi, _ = self._cell_state(s)
        safe = np.where(G_cell > 0.0, G_cell, 1.0)
        wall = (A.T @ (G_edge * (E @ s.u))) / safe
        return G_cell * phi * (wall - U @ s.u)

    def boundary_heat(self, s: State) -> float:
        """The stream's enthalpy term of the energy balance, ``m c_p (T_in - T_out)`` [W].

        This is the heat the stream brings into the system of solid and fluid: negative
        when the stream carries heat away. At a converged solution it equals minus the
        heat passed from the walls to the fluid (:meth:`heat_to_fluid`); using the
        enthalpy form makes the balance close to the residual of the whole system, fluid
        equations included.
        """
        fluid = s.u[self.fluid_dofs]
        return self.capacity_rate(s.t) * float(fluid[0] - fluid[-1])

    def fluid_temperature(self, u: ndarray) -> ndarray:
        """Temperature of the fluid nodes [K], inlet first, shape (N + 1,)."""
        return np.asarray(u)[self.fluid_dofs]


class ThroughPlaneStreamTerm(_StreamCommon, ConvectionTerm):
    """A through-plane stream: ordinary convection at the bulk temperature (Theory §9.1).

    The fluid temperature is uniform on the walls and equals ``stream.T_inlet(t)`` [K];
    ``h`` [W/(m^2 K)] comes from the duct correlation of Theory §8.1 with properties at
    that bulk temperature, or from ``h_override``, times ``h_multiplier``. No fluid DOFs
    are created.

    Parameters
    ----------
    stream : Stream
        ``mode`` must be ``"through_plane"``; ``mass_flow`` is needed unless ``h_override``
        is given.
    """

    symmetric = True

    def __init__(self, stream: Stream) -> None:
        if stream.mode != "through_plane":
            raise ModelError(f"stream {stream.name!r} is not a through-plane stream")
        FacetTerm.__init__(self, stream.name, ", ".join(stream.walls))
        self._init_stream(stream)
        # h does not depend on the solution when given, or with the "auto" Nusselt number;
        # only the Dittus-Boelter exponent and the Sieder-Tate mu_s depend on the wall
        self.is_linear = stream.h_override is not None or stream.nu_option == "auto"

    def setup(self, problem: CompiledProblem) -> None:
        """Resolve the wall edges of every wall selection."""
        if problem.mesh.axisymmetric:
            raise ModelError(
                f"stream {self.name!r}: a through-plane stream needs a planar model"
            )
        tags: list[int] = []
        for wall in self.stream.walls:
            tags += problem.selection_tags(wall, (problem.mesh.dim - 1,))[1]
        self._batches = facet_batches(problem, tags)
        if not self._batches:
            raise ModelError(f"stream {self.name!r}: its walls contain no element edges")

    def bulk_temperature(self, t: float) -> float:
        """Bulk fluid temperature [K] at time ``t`` [s]."""
        return float(self.stream.T_inlet(t=t))

    def _mean_wall_temperature(self, s: State) -> float:
        """Area-weighted mean wall temperature over all the stream's walls [K]."""
        total = weight = 0.0
        for b in self._batches:
            dA = b.g * b.geom.dS
            total += float((self.temperature(s, b) * dA).sum())
            weight += float(dA.sum())
        return total / weight

    def mean_coefficient(self, s: State) -> float:
        """Heat-transfer coefficient of the stream [W/(m^2 K)], the same on every wall."""
        stream = self.stream
        if stream.h_override is not None:
            return float(stream.h_override(t=s.t)) * stream.h_multiplier
        T_bulk = self.bulk_temperature(s.t)
        p = fluid_props(self.fluid, T_bulk)
        Re = self.mass_flow(s.t) * self.D_h / (stream.flow_area * p.mu)
        T_wall = self._mean_wall_temperature(s)
        heating = bool(T_wall > T_bulk)
        mu_ratio = 1.0
        if stream.nu_option == "sieder_tate":
            mu_ratio = float(p.mu / fluid_props(self.fluid, T_wall).mu)
        Nu = c.nu_duct(
            Re, p.Pr, stream.cross_section, "constant_T", stream.nu_option, heating,
            stream.diameter_ratio, mu_ratio,
        )
        h = float(c.nusselt_to_h(Nu, p.k, self.D_h))
        return h * stream.h_multiplier

    def coefficient(self, s: State, batch: FacetBatch) -> ndarray:
        """``h`` at every integration point [W/(m^2 K)], shape (f, gp)."""
        return np.full(batch.g.shape, self.mean_coefficient(s))

    def ambient(self, s: State, batch: FacetBatch) -> ndarray:
        """Bulk fluid temperature at every integration point [K], shape (f, gp)."""
        return np.full(batch.g.shape, self.bulk_temperature(s.t))

    def results(self, s: State) -> dict[str, ndarray]:
        """Named result values: ``h_mean:<name>`` [W/(m^2 K)]."""
        return {f"h_mean:{self.name}": np.array([self.mean_coefficient(s)])}


def stream_items(stream: Stream) -> tuple[list, list]:
    """The terms and constraints of one stream.

    An in-plane stream gives its term and its inlet constraint; a through-plane stream
    gives one convection term and no constraint.
    """
    if stream.mode == "through_plane":
        return [ThroughPlaneStreamTerm(stream)], []
    term = StreamTerm(stream)
    return [term], [InletConstraint(term)]
