"""M7.1 — in-plane stream (Theory §9.1). Includes V-27 and V-28 on hand-built meshes."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, make_problem, make_state

from thermalfea import api
from thermalfea.convection import correlations as c
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Expression, Table
from thermalfea.flow.stream import (
    InletConstraint,
    StreamTerm,
    cell_edges,
    cell_matrix,
    path_coordinate,
)
from thermalfea.materials import library
from thermalfea.model.bcs import FixedTemperature, HeatFlux, Stream
from thermalfea.model.serialize import from_json, to_json
from thermalfea.post.energy import energy_balance
from thermalfea.solver.compile import attach_stream
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.steady import solve_steady, steady_solution

LENGTH, T_IN = 1.0, 300.0
CP_IN = float(library.fluid("Water").props(T_IN).cp)


def stream(**changes) -> Stream:
    base = dict(
        name="coolant", fluid="Water", mode="in_plane", walls=["bottom"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=T_IN, mass_flow=0.25,
        path=[(0.0, 0.0), (LENGTH, 0.0)],
    )
    return Stream(**{**base, **changes})


def problem_with(st: Stream, etype: str = "Q4", bcs=(), cells=(20, 2), height=0.1, **kw):
    problem = make_problem(etype, size=(LENGTH, height), cells=cells, bcs=bcs, **kw)
    attach_stream(problem, st)
    return problem, problem.terms[-1]


# ---------------------------------------------------------------------- pure pieces


def test_path_coordinate() -> None:
    line = np.array([[0.0, 0.0], [2.0, 0.0], [2.0, 3.0]])
    points = np.array([[0.5, 0.0], [0.5, 0.7], [2.0, 1.0], [2.4, 1.0], [-1.0, 0.0], [2.0, 9.0]])
    np.testing.assert_allclose(path_coordinate(points, line), [0.5, 0.5, 3.0, 3.0, 0.0, 5.0])
    with pytest.raises(ModelError, match="coincident"):
        path_coordinate(points, np.array([[0.0, 0.0], [0.0, 0.0]]))


def test_cell_edges() -> None:
    np.testing.assert_allclose(cell_edges(np.array([0.3]), 2.0, 4), [0.0, 0.5, 1.0, 1.5, 2.0])
    # default: one cell per wall edge along the path; equal path coordinates share a cell
    mids = np.array([0.25, 0.75, 0.25, 0.75, 1.5])
    np.testing.assert_allclose(cell_edges(mids, 2.0, None), [0.0, 0.5, 1.125, 2.0])
    np.testing.assert_allclose(cell_edges(np.array([]), 2.0, None), [0.0, 2.0])
    with pytest.raises(ModelError):
        cell_edges(mids, 2.0, 0)


def test_cell_matrix_times_a_uniform_temperature_is_zero() -> None:
    rng = np.random.default_rng(0)
    G = rng.uniform(1.0, 5.0, size=4)
    w = rng.random((4, 6))
    w /= w.sum(axis=1, keepdims=True)
    for m_cp in (0.01, 3.0, 1e6):
        K = cell_matrix(G, w, m_cp)
        np.testing.assert_allclose(K @ np.full(8, 321.0), 0.0, atol=1e-9 * np.abs(K).max())
        assert not np.any(K[6])  # the upstream node has no equation in this cell
        assert not np.allclose(K, K.T)  # unsymmetric


def test_cell_matrix_reproduces_the_exponential_and_conserves_energy() -> None:
    G, m_cp, t_wall, t_up = np.array([2.0, 3.0]), 4.0, 350.0, 300.0
    w = np.array([[0.5, 0.5, 0.0], [0.0, 0.5, 0.5]])
    K = cell_matrix(G, w, m_cp)
    ntu = G.sum() / m_cp
    t_down = t_wall - (t_wall - t_up) * np.exp(-ntu)  # exact for a constant wall temperature
    T = np.array([t_wall, t_wall, t_wall, t_up, t_down])
    leaving = K @ T
    assert leaving[4] == pytest.approx(0.0, abs=1e-10)  # the fluid energy equation holds
    assert leaving[:3].sum() == pytest.approx(m_cp * (t_down - t_up))  # wall heat = enthalpy rise
    # phi -> 1 for a tiny NTU: the wall sees the upstream temperature
    tiny = cell_matrix(np.array([1e-12]), np.array([[1.0]]), 1.0)
    np.testing.assert_allclose(tiny[0], [1e-12, -1e-12, 0.0], rtol=1e-6)


# ------------------------------------------------------------------------- the term


def test_setup_creates_fluid_dofs_and_cells() -> None:
    problem, term = problem_with(stream())
    n_nodes = problem.mesh.n_nodes
    assert isinstance(term, StreamTerm) and not term.symmetric
    assert term.n_cells == 20  # one per wall edge along the path
    assert problem.dofs.extras == ["stream:coolant"]
    np.testing.assert_array_equal(term.fluid_dofs, n_nodes + np.arange(21))
    assert problem.dofs.n_dofs == n_nodes + 21
    np.testing.assert_allclose(term.node_s, np.linspace(0.0, LENGTH, 21))
    np.testing.assert_array_equal(np.sort(term.edge_cell), np.arange(20))
    assert term.edge_area.sum() == pytest.approx(LENGTH * 1.0)
    assert term.D_h == pytest.approx(4 * 1e-4 / 0.04)
    (inlet,) = problem.constraints
    assert isinstance(inlet, InletConstraint)
    idx, values = inlet.values(0.0)
    np.testing.assert_array_equal(idx, [n_nodes])
    np.testing.assert_array_equal(values, [T_IN])
    coarse, cterm = problem_with(stream(n_cells=4))
    assert cterm.n_cells == 4 and np.bincount(cterm.edge_cell).tolist() == [5, 5, 5, 5]


@pytest.mark.parametrize("etype", TYPES)
def test_matrix_equals_the_scattered_dense_cell_matrices(etype: str) -> None:
    problem, term = problem_with(stream(n_cells=3, h_override=800.0), etype, cells=(6, 1))
    s = make_state(problem, 300.0)
    K = term.matrix(s).toarray()
    n = problem.dofs.n_dofs
    reference = np.zeros((n, n))
    rows, cols, vals = term._e
    m_cp = term.capacity_rate(0.0)
    for cell in range(term.n_cells):  # test only: assemble cell by cell
        edges = np.flatnonzero(term.edge_cell == cell)
        wall = np.unique(cols[np.isin(rows, edges)])
        w = np.zeros((edges.size, wall.size))
        for i, edge in enumerate(edges):
            sel = rows == edge
            w[i, np.searchsorted(wall, cols[sel])] = vals[sel]
        dofs = np.concatenate([wall, term.fluid_dofs[cell:cell + 2]])
        reference[np.ix_(dofs, dofs)] += cell_matrix(800.0 * term.edge_area[edges], w, m_cp)
    np.testing.assert_allclose(K, reference, atol=1e-9 * np.abs(reference).max())
    np.testing.assert_allclose(K @ np.full(n, 333.0), 0.0, atol=1e-8 * np.abs(K).max())
    assert np.abs(K - K.T).max() > 1.0


def test_flags_and_breakpoints() -> None:
    _, plain = problem_with(stream())
    assert not plain.is_linear and not plain.is_time_dependent  # h from the correlation
    _, fixed_h = problem_with(stream(h_override=500.0))
    assert fixed_h.is_linear
    ramp = Table([0.0, 10.0], [0.1, 0.3], "t")
    _, timed = problem_with(stream(mass_flow=ramp, T_inlet=Table([0.0, 5.0], [300.0, 320.0], "t")))
    assert timed.is_time_dependent and timed.breakpoints() == [0.0, 5.0, 10.0]
    assert timed.mass_flow(5.0) == pytest.approx(0.2)
    problem, _ = problem_with(stream(h_override=500.0))
    assert problem.is_linear and not problem.symmetric


def test_coefficient_from_the_duct_correlation() -> None:
    problem, term = problem_with(stream(mass_flow=0.3, h_multiplier=1.5))
    s = make_state(problem, 320.0)
    s.u[term.fluid_dofs] = np.linspace(300.0, 310.0, 21)
    h, numbers = term.coefficients(s)
    p = library.fluid("Water").props(s.u[term.fluid_dofs[:-1]])  # upstream node of each cell
    re = 0.3 * term.D_h / (1e-4 * p.mu)
    nu = c.nu_duct(re, p.Pr, "circular", "constant_T", "auto", True)
    np.testing.assert_allclose(numbers["Re"], re, rtol=1e-14)
    np.testing.assert_allclose(h, 1.5 * nu * p.k / term.D_h, rtol=1e-13)
    assert np.all(re > 4000) and np.all(np.diff(h) != 0.0)
    # square duct, Dittus-Boelter
    _, other = problem_with(stream(mass_flow=0.3, cross_section="square",
                                   nu_option="dittus_boelter"))
    h2, n2 = other.coefficients(s)
    np.testing.assert_allclose(
        h2, c.nu_dittus_boelter(n2["Re"], n2["Pr"], True) * p.k / other.D_h, rtol=1e-13)


def _heating_h(n_cells: int, t_wall: float, t_fluid: float):
    problem, term = problem_with(stream(mass_flow=0.3, nu_option="dittus_boelter",
                                        n_cells=n_cells))
    s = make_state(problem, t_wall)
    s.u[term.fluid_dofs] = t_fluid
    h, numbers = term.coefficients(s)
    p = library.fluid("Water").props(s.u[term.fluid_dofs[:-1]])
    k_over_d = p.k / term.D_h
    return term, h, numbers, k_over_d


def test_heating_flag_ignores_cells_without_a_wall() -> None:
    # 30 cells over 20 wall edges: some cells have no wall edge (their "wall" T must not count)
    term, h, numbers, k_over_d = _heating_h(30, 350.0, 300.0)
    assert np.bincount(term.edge_cell, minlength=term.n_cells).min() == 0
    np.testing.assert_allclose(
        h, c.nu_dittus_boelter(numbers["Re"], numbers["Pr"], True) * k_over_d, rtol=1e-13)


def test_heating_flag_cooling_and_fully_walled_unchanged() -> None:
    term, h, numbers, k_over_d = _heating_h(30, 280.0, 300.0)  # wall colder: n = 0.3
    np.testing.assert_allclose(
        h, c.nu_dittus_boelter(numbers["Re"], numbers["Pr"], False) * k_over_d, rtol=1e-13)
    term, h, numbers, k_over_d = _heating_h(20, 350.0, 300.0)  # every cell walled
    assert np.bincount(term.edge_cell, minlength=term.n_cells).min() > 0
    np.testing.assert_allclose(
        h, c.nu_dittus_boelter(numbers["Re"], numbers["Pr"], True) * k_over_d, rtol=1e-13)


def test_errors() -> None:
    for changes, message in (
        (dict(mode="through_plane"), "not an in-plane stream"),
        (dict(path=None), "needs a path"),
        (dict(flow_area=0.0), "must be positive"),
        (dict(h_multiplier=0.0), "h_multiplier"),
        (dict(T_inlet=Expression("T")), "cannot depend on T"),
        (dict(h_override=Expression("T")), "time only"),
        (dict(fluid="Unobtainium"), "no fluid named"),
    ):
        with pytest.raises(ModelError, match=message):
            StreamTerm(stream(**changes))
    with pytest.raises(ModelError, match="coolant: unknown selection"):
        problem_with(stream(walls=["nope"]))
    problem, term = problem_with(stream(mass_flow=None, h_override=10.0))
    with pytest.raises(ModelError, match="has no mass flow"):
        term.mass_flow(0.0)
    term.mass_flow_override = 0.2  # as a network branch would set it
    assert term.mass_flow(0.0) == 0.2
    _, backwards = problem_with(stream(mass_flow=-0.1, h_override=10.0))
    with pytest.raises(ModelError, match="must be positive"):
        backwards.mass_flow(0.0)


# -------------------------------------------------------------------------------- V-27


@pytest.mark.parametrize("n_cells", [1, 20])
@pytest.mark.parametrize("etype", TYPES)
def test_v27_constant_wall_temperature(etype: str, n_cells: int) -> None:
    """Wall fixed at 350 K, length 1 m, water, T_in = 300 K, NTU = 1, constant h.

    T_out = T_w - (T_w - T_in) exp(-h A / (m c_p)); tolerance 1e-6 (the scheme is exact
    here), for 1 cell and for 20 cells.
    """
    t_wall, h = 350.0, 1000.0
    m = h * LENGTH * 1.0 / CP_IN  # NTU = h A / (m c_p) = 1
    problem, term = problem_with(
        stream(mass_flow=m, h_override=h, n_cells=n_cells), etype,
        bcs=(FixedTemperature("wall", "bottom", T=t_wall),),
    )
    result = steady_solution(problem)
    assert result.iterations == 1  # linear: frozen h and c_p
    fluid = term.fluid_temperature(result.T)
    assert fluid[0] == T_IN
    exact_out = t_wall - (t_wall - T_IN) * np.exp(-1.0)
    assert abs(fluid[-1] - exact_out) / exact_out < 1e-6
    # every fluid node lies on the exponential, whatever the number of cells
    exact = t_wall - (t_wall - T_IN) * np.exp(-term.node_s / LENGTH)
    np.testing.assert_allclose(fluid, exact, rtol=1e-9)
    # energy: the heat the wall gives up is the enthalpy rise of the stream
    state = make_state(problem, result.T)
    gained = term.capacity_rate(0.0) * (fluid[-1] - fluid[0])
    assert term.heat_to_fluid(state).sum() == pytest.approx(gained, rel=1e-10)
    assert term.boundary_heat(state) == pytest.approx(-gained, rel=1e-10)


# -------------------------------------------------------------------------------- V-28


@pytest.mark.parametrize("etype", TYPES)
def test_v28_constant_heat_flux(etype: str) -> None:
    """Thin wall strip with flux q on the outside and the stream inside.

    T_out = T_in + q A / (m c_p) (1e-6); wall-to-fluid temperature difference = q / h far
    from the inlet (1e-2).
    """
    q, h, rise = 5000.0, 500.0, 20.0
    m = q * LENGTH / (rise * CP_IN)
    problem, term = problem_with(
        stream(mass_flow=m, h_override=h), etype, cells=(40, 1), height=0.002,
        bcs=(HeatFlux("heating", "top", q=q),),
    )
    result = steady_solution(problem)
    fluid = term.fluid_temperature(result.T)
    exact_out = T_IN + q * LENGTH / (m * CP_IN)
    assert abs(fluid[-1] - exact_out) / exact_out < 1e-6
    # far from the inlet the wall runs q / h above the local fluid temperature
    nodes = problem.mesh.nodes
    wall = np.flatnonzero(np.isclose(nodes[:, 1], 0.0) & (nodes[:, 0] > 0.6) & (nodes[:, 0] < 0.9))
    local_fluid = np.interp(nodes[wall, 0], term.node_s, fluid)
    difference = result.T[wall] - local_fluid
    np.testing.assert_allclose(difference, q / h, rtol=1e-2)
    # the fluid heats up linearly along the wall
    np.testing.assert_allclose(fluid, T_IN + rise * term.node_s / LENGTH, atol=0.05)
    # energy balance of the solid: flux in equals heat handed to the stream
    balance = energy_balance(problem, result.T, system=result.system)
    assert balance.flows["heating"] == pytest.approx(q * LENGTH)
    assert balance.flows["coolant"] == pytest.approx(-q * LENGTH, rel=1e-9)
    assert abs(balance.relative_imbalance) < 1e-8


# ------------------------------------------------------------------------ behaviour


def test_no_oscillation_for_a_very_large_ntu() -> None:
    problem, term = problem_with(
        stream(mass_flow=1e-4, h_override=5000.0), bcs=(FixedTemperature("w", "bottom", T=350.0),))
    fluid = term.fluid_temperature(solve_steady(problem))
    # bounded by the wall temperature and never overshooting (to round-off)
    assert np.all(np.diff(fluid) >= -1e-9) and fluid.max() <= 350.0 + 1e-9
    assert fluid[1] == pytest.approx(350.0, abs=1e-6)  # saturated within the first cell


def test_correlation_stream_is_nonlinear_and_conserves_energy() -> None:
    problem, term = problem_with(
        stream(mass_flow=0.3), "Q8", bcs=(FixedTemperature("w", "top", T=360.0),))
    result = steady_solution(problem)
    assert result.converged and result.iterations >= 2
    fluid = term.fluid_temperature(result.T)
    assert T_IN < fluid[-1] < 360.0 and np.all(np.diff(fluid) > 0.0)
    state = make_state(problem, result.T)
    gained = term.capacity_rate(0.0) * (fluid[-1] - fluid[0])
    assert term.heat_to_fluid(state).sum() == pytest.approx(gained, rel=1e-6)
    balance = energy_balance(problem, result.T, system=result.system)
    assert balance.flows["w"] == pytest.approx(gained, rel=1e-6)
    assert abs(balance.relative_imbalance) < 1e-6


def test_two_walls_of_a_channel_share_the_cells() -> None:
    """A stream between the bottom and top edges: edges at the same s are in the same cell."""
    problem, term = problem_with(
        stream(walls=["bottom", "top"], h_override=300.0, path=[(0.0, 0.05), (LENGTH, 0.05)]),
        cells=(10, 1),
    )
    assert term.n_cells == 10 and np.bincount(term.edge_cell).tolist() == [2] * 10
    assert term.edge_area.sum() == pytest.approx(2 * LENGTH)


def test_time_dependent_inlet_is_prescribed() -> None:
    problem, term = problem_with(
        stream(T_inlet=Expression("300 + 2*t"), h_override=100.0),
        bcs=(FixedTemperature("w", "top", T=350.0),))
    idx, values = problem.prescribed(5.0)
    inlet = term.fluid_dofs[0]
    assert values[np.flatnonzero(idx == inlet)[0]] == 310.0
    assert problem.is_time_dependent


def test_through_compile_on_a_gmsh_mesh() -> None:
    model = api.new_model(name="cold plate")
    api.Geometry(model).rectangle(0.0, 0.0, LENGTH, 0.05)
    model.mesh_settings.global_size = 0.05
    built = api.build(model)
    api.select_curves(model, built, "channel", where=lambda cv: abs(cv.center[1]) < 1e-9)
    api.select_curves(model, built, "hot", where=lambda cv: abs(cv.center[1] - 0.05) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs.append(HeatFlux("load", "hot", q=2000.0))
    model.streams.append(stream(walls=["channel"], h_override=800.0, mass_flow=0.05))
    mesh = api.mesh(model, built)
    problem = compile_problem(model, built, mesh)
    term = problem.terms[-1]
    assert isinstance(term, StreamTerm) and problem.dofs.n_dofs == mesh.n_nodes + term.n_cells + 1
    result = steady_solution(problem)
    fluid = term.fluid_temperature(result.T)
    assert fluid[-1] == pytest.approx(T_IN + 2000.0 * LENGTH / (0.05 * CP_IN), rel=1e-9)
    # the results file and the recovered fields still cover the mesh nodes only
    results = api.solve(model, mesh, built=built)
    assert results.temperature().shape == (mesh.n_nodes,)
    assert results.heat_flow("coolant")[-1] == pytest.approx(-2000.0 * LENGTH, rel=1e-9)
    # a model with a stream survives saving and loading
    assert from_json(to_json(model)) == model


# ------------------------------------------------------------------------------ M11.42


def test_new_sections_in_a_stream() -> None:
    problem, term = problem_with(stream(mass_flow=0.001, cross_section="rectangle_3"))
    h, numbers = term.coefficients(make_state(problem, 320.0))
    assert np.all(numbers["Re"] < 2300) and np.all(numbers["Nu"] == 3.96)
    problem, term = problem_with(stream(mass_flow=0.001, cross_section="annulus_inner",
                                        diameter_ratio=0.15))
    _, numbers = term.coefficients(make_state(problem, 320.0))
    expected = 11.56 + (0.05 / 0.15) * (7.37 - 11.56)
    np.testing.assert_allclose(numbers["Nu"], expected, rtol=1e-13)


def test_diameter_ratio_rules() -> None:
    with pytest.raises(ModelError, match="annulus cross-sections only"):
        stream(diameter_ratio=0.5)
    with pytest.raises(ModelError, match="needs diameter_ratio"):
        stream(cross_section="annulus_outer")
    with pytest.raises(ModelError, match="diameter_ratio"):
        stream(cross_section="annulus_inner", diameter_ratio=0.04)
    ok = stream(cross_section="annulus_outer", diameter_ratio=0.0)
    assert ok.diameter_ratio == 0.0 and stream().diameter_ratio is None
    # a later edit that bypasses the constructor is caught when the stream is built
    bad = stream()
    bad.diameter_ratio = 0.5
    with pytest.raises(ModelError, match="annulus cross-sections only"):
        problem_with(bad)


def test_sieder_tate_stream_uses_the_cell_wall_temperature() -> None:
    problem, term = problem_with(stream(mass_flow=0.3, nu_option="sieder_tate", n_cells=20))
    s = make_state(problem, 350.0)
    s.u[term.fluid_dofs] = np.linspace(300.0, 310.0, 21)
    assert np.bincount(term.edge_cell, minlength=term.n_cells).min() > 0  # every cell walled
    h, numbers = term.coefficients(s)
    water = library.fluid("Water")
    T_up = s.u[term.fluid_dofs[:-1]]
    p = water.props(T_up)
    ps = water.props(350.0)
    Re = 0.3 * term.D_h / (1e-4 * p.mu)
    assert np.all(Re >= 1e4)
    Nu = 0.027 * Re**0.8 * p.Pr ** (1 / 3) * (p.mu / ps.mu) ** 0.14
    np.testing.assert_allclose(numbers["Nu"], Nu, rtol=1e-13)
    np.testing.assert_allclose(h, Nu * p.k / term.D_h, rtol=1e-13)


# ------------------------------------------------------------------- guards (M11.23)


def test_mass_flow_may_not_depend_on_temperature() -> None:
    with pytest.raises(ModelError, match="mass flow may depend on time only"):
        StreamTerm(stream(mass_flow=Expression("0.1 + 0*T")))
    StreamTerm(stream(mass_flow=Expression("0.1 + 0*t")))


def test_a_wall_on_the_axis_has_no_area() -> None:
    # the bottom wall of an axisymmetric strip whose left edge is on r = 0 is fine, but a
    # wall that is the axis itself has zero area
    with pytest.raises(ModelError, match="on the axis r = 0"):
        problem_with(stream(walls=["left"], path=[(0.0, 0.0), (0.0, 0.1)]), axisymmetric=True)
