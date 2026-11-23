"""M7.2 — through-plane stream (Theory §9.1, last paragraph, and §8.1)."""

from __future__ import annotations

import numpy as np
import pytest
from handmade import TYPES, assemble, make_problem, make_state

from thermalfea import api
from thermalfea.convection import correlations as c
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Expression, Table
from thermalfea.flow.stream import (
    InletConstraint,
    StreamTerm,
    ThroughPlaneStreamTerm,
    stream_items,
)
from thermalfea.materials import library
from thermalfea.model.bcs import Convection, FixedTemperature, HeatFlux, Stream
from thermalfea.post.energy import energy_balance
from thermalfea.solver.compile import attach_stream
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.steady import steady_solution

LENGTH, T_BULK = 1.0, 300.0
AREA, PERIMETER = 1e-4, 0.04
D_H = 4 * AREA / PERIMETER
WATER = library.fluid("Water")


def stream(**changes) -> Stream:
    base = dict(
        name="hole", fluid="Water", mode="through_plane", walls=["bottom"], flow_area=AREA,
        wetted_perimeter=PERIMETER, cross_section="circular", T_inlet=T_BULK, mass_flow=0.3,
    )
    return Stream(**{**base, **changes})


def problem_with(st: Stream, etype: str = "Q4", bcs=(), cells=(8, 2), **kw):
    problem = make_problem(etype, size=(LENGTH, 0.1), cells=cells, bcs=bcs, **kw)
    attach_stream(problem, st)
    return problem, problem.terms[-1]


def expected_h(m: float, T_bulk: float, heating: bool = True, option: str = "auto",
               section: str = "circular") -> float:
    p = WATER.props(T_bulk)
    re = m * D_H / (AREA * p.mu)
    nu = c.nu_duct(re, p.Pr, section, "constant_T", option, heating)
    return float(nu * p.k / D_H)


# ----------------------------------------------------------------------- equivalence


@pytest.mark.parametrize("etype", TYPES)
def test_with_h_override_it_is_an_ordinary_convection(etype: str) -> None:
    h, T_inf = 700.0, 310.0
    problem, term = problem_with(stream(h_override=h, T_inlet=T_inf), etype)
    reference = make_problem(
        etype, size=(LENGTH, 0.1), cells=(8, 2),
        bcs=(Convection("ref", "bottom", h=h, T_inf=T_inf),),
    )
    assert isinstance(term, ThroughPlaneStreamTerm)
    a = assemble(problem, make_state(problem, 305.0))
    b = assemble(reference, make_state(reference, 305.0))
    diff = (a.matrix() - b.matrix()).toarray()
    assert np.abs(diff).max() <= 1e-12
    assert np.abs(a.vector() - b.vector()).max() <= 1e-12
    assert problem.is_linear and problem.symmetric
    assert problem.dofs.extras == [] and problem.constraints == []
    assert problem.dofs.n_dofs == problem.mesh.n_nodes


def test_h_override_needs_no_mass_flow_and_ignores_it() -> None:
    problem, term = problem_with(stream(h_override=400.0, mass_flow=None))
    s = make_state(problem, 320.0)
    assert term.mean_coefficient(s) == 400.0
    _, mult = problem_with(stream(h_override=400.0, mass_flow=None, h_multiplier=1.25))
    assert mult.mean_coefficient(s) == pytest.approx(500.0, rel=1e-14)


# ---------------------------------------------------------------------- correlations


@pytest.mark.parametrize("m", [0.005, 0.025, 0.3])  # laminar, transitional, turbulent
def test_h_from_the_duct_correlation_at_the_bulk_temperature(m: float) -> None:
    T_bulk = 305.0
    problem, term = problem_with(stream(mass_flow=m, T_inlet=T_bulk))
    p = WATER.props(T_bulk)
    re = m * D_H / (AREA * p.mu)
    assert (m == 0.005 and re < 2300) or (m == 0.3 and re > 4000) or m == 0.025
    expected = expected_h(m, T_bulk)
    for wall in (290.0, 320.0, 380.0):  # the wall temperature does not matter for "auto"
        s = make_state(problem, wall)
        assert term.mean_coefficient(s) == pytest.approx(expected, rel=1e-13)
    b = term._batches[0]
    s = make_state(problem, 320.0)
    np.testing.assert_allclose(term.coefficient(s, b), expected, rtol=1e-13)
    assert term.coefficient(s, b).shape == b.g.shape
    np.testing.assert_array_equal(term.ambient(s, b), np.full(b.g.shape, T_bulk))
    assert term.is_linear
    assert term.results(s)["h_mean:hole"] == pytest.approx([expected], rel=1e-13)


def test_square_section_and_multiplier() -> None:
    problem, term = problem_with(stream(cross_section="square", h_multiplier=1.4, mass_flow=0.2))
    s = make_state(problem, 330.0)
    expected = 1.4 * expected_h(0.2, T_BULK, section="square")
    assert term.mean_coefficient(s) == pytest.approx(expected, rel=1e-13)


def test_properties_are_taken_at_the_bulk_temperature_only() -> None:
    _, cold = problem_with(stream(T_inlet=290.0))
    _, warm = problem_with(stream(T_inlet=350.0))
    p1, p2 = WATER.props(290.0), WATER.props(350.0)
    assert not np.isclose(p1.k, p2.k)
    s = make_state(make_problem(), 300.0)
    assert cold.mean_coefficient(s) == pytest.approx(expected_h(0.3, 290.0), rel=1e-13)
    assert warm.mean_coefficient(s) == pytest.approx(expected_h(0.3, 350.0), rel=1e-13)


def test_dittus_boelter_exponent_follows_the_wall_to_fluid_difference() -> None:
    problem, term = problem_with(stream(nu_option="dittus_boelter"))
    assert not term.is_linear and not problem.is_linear
    hot = term.mean_coefficient(make_state(problem, 340.0))  # wall hotter: exponent 0.4
    cold = term.mean_coefficient(make_state(problem, 260.0))  # wall colder: exponent 0.3
    assert hot == pytest.approx(expected_h(0.3, T_BULK, True, "dittus_boelter"), rel=1e-13)
    assert cold == pytest.approx(expected_h(0.3, T_BULK, False, "dittus_boelter"), rel=1e-13)
    assert hot / cold == pytest.approx(WATER.props(T_BULK).Pr ** 0.1, rel=1e-12)
    # an override makes it linear whatever the option
    _, fixed = problem_with(stream(nu_option="dittus_boelter", h_override=100.0))
    assert fixed.is_linear


# ------------------------------------------------------------------------- walls


def test_several_walls_and_total_heat() -> None:
    problem, term = problem_with(stream(walls=["bottom", "top"], mass_flow=0.1))
    s = make_state(problem, 340.0)
    h = expected_h(0.1, T_BULK)
    area = 2 * LENGTH * 1.0
    assert term.area() == pytest.approx(area)
    assert term.boundary_heat(s) == pytest.approx(-h * area * (340.0 - T_BULK), rel=1e-12)
    # both edges carry the load: the global vector sums to h * T_bulk * area
    asm = assemble(problem, s, terms=[term])
    assert asm.vector().sum() == pytest.approx(h * T_BULK * area, rel=1e-12)
    only_bottom, _ = problem_with(stream(walls=["bottom"], mass_flow=0.1))
    assert only_bottom.terms[-1].area() == pytest.approx(LENGTH)


def test_slab_series_resistance() -> None:
    """T_surface = T_b + (T_hot - T_b) / (1 + h L / k), exact for a 1-D slab."""
    L, k, h, T_hot, T_b = 0.2, 50.0, 400.0, 400.0, 300.0
    problem = make_problem("Q4", size=(L, 0.1), cells=(10, 2), k=k,
                           bcs=(FixedTemperature("hot", "left", T=T_hot),))
    attach_stream(problem, stream(walls=["right"], h_override=h, T_inlet=T_b))
    result = steady_solution(problem)
    assert result.iterations == 1
    nodes = problem.mesh.nodes
    right = np.isclose(nodes[:, 0], L)
    expected = T_b + (T_hot - T_b) / (1.0 + h * L / k)
    np.testing.assert_allclose(result.T[right], expected, rtol=0, atol=1e-10)
    # the correlation version obeys the same law with its own h
    problem2 = make_problem("Q4", size=(L, 0.1), cells=(10, 2), k=k,
                            bcs=(FixedTemperature("hot", "left", T=T_hot),))
    attach_stream(problem2, stream(walls=["right"], T_inlet=T_b))
    h_c = expected_h(0.3, T_b)
    result2 = steady_solution(problem2)
    np.testing.assert_allclose(
        result2.T[right], T_b + (T_hot - T_b) / (1.0 + h_c * L / k), rtol=0, atol=1e-10)


# -------------------------------------------------------------------- time dependence


def test_time_dependence_and_breakpoints() -> None:
    ramp = Table([0.0, 10.0], [0.1, 0.3], "t")
    warm = Table([0.0, 5.0], [300.0, 320.0], "t")
    problem, term = problem_with(stream(mass_flow=ramp, T_inlet=warm))
    assert term.is_time_dependent and problem.is_time_dependent
    assert term.breakpoints() == [0.0, 5.0, 10.0]
    assert term.mass_flow(5.0) == pytest.approx(0.2)
    s = make_state(problem, 330.0, t=5.0)
    assert term.mean_coefficient(s) == pytest.approx(expected_h(0.2, 320.0), rel=1e-13)
    b = term._batches[0]
    np.testing.assert_allclose(term.ambient(s, b), 320.0)
    _, steady = problem_with(stream())
    assert not steady.is_time_dependent and steady.breakpoints() == []
    _, timed_h = problem_with(stream(h_override=Table([0.0, 2.0], [10.0, 20.0], "t")))
    assert timed_h.is_time_dependent and timed_h.breakpoints() == [0.0, 2.0]


# ------------------------------------------------------------------------- errors


def test_errors() -> None:
    for changes, message in (
        (dict(mode="in_plane", path=[(0.0, 0.0), (1.0, 0.0)]), "not a through-plane"),
        (dict(flow_area=0.0), "must be positive"),
        (dict(h_multiplier=0.0), "h_multiplier"),
        (dict(T_inlet=Expression("T")), "cannot depend on T"),
        (dict(h_override=Expression("T")), "time only"),
        (dict(fluid="Unobtainium"), "no fluid named"),
    ):
        with pytest.raises(ModelError, match=message):
            ThroughPlaneStreamTerm(stream(**changes))
    with pytest.raises(ModelError, match="hole: unknown selection"):
        problem_with(stream(walls=["nope"]))
    with pytest.raises(ModelError, match="planar model"):
        problem_with(stream(), axisymmetric=True)


def test_mass_flow_rules() -> None:
    problem, term = problem_with(stream(mass_flow=None))
    s = make_state(problem, 320.0)
    with pytest.raises(ModelError, match="has no mass flow"):
        term.mean_coefficient(s)
    term.mass_flow_override = 0.2  # as a network branch would set it
    assert term.mean_coefficient(s) == pytest.approx(expected_h(0.2, T_BULK), rel=1e-13)
    _, backwards = problem_with(stream(mass_flow=-0.1))
    with pytest.raises(ModelError, match="must be positive"):
        backwards.mean_coefficient(s)
    _, zero = problem_with(stream(mass_flow=0.3))
    zero.mass_flow_override = 0.0
    with pytest.raises(ModelError, match="must be positive"):
        zero.mean_coefficient(s)


# ---------------------------------------------------------------------- stream_items


def test_stream_items_by_mode() -> None:
    terms, constraints = stream_items(stream())
    assert len(terms) == 1 and isinstance(terms[0], ThroughPlaneStreamTerm) and constraints == []
    in_plane = stream(mode="in_plane", path=[(0.0, 0.0), (LENGTH, 0.0)])
    terms, constraints = stream_items(in_plane)
    assert isinstance(terms[0], StreamTerm) and isinstance(constraints[0], InletConstraint)
    problem = make_problem(cells=(4, 1), size=(LENGTH, 0.1))
    attach_stream(problem, in_plane)
    assert problem.dofs.extras == ["stream:hole"]
    assert problem.dofs.n_dofs > problem.mesh.n_nodes and len(problem.constraints) == 1
    assert not problem.symmetric


# ---------------------------------------------------------------- gmsh compile path


def test_cooling_hole_through_compile_on_a_gmsh_mesh() -> None:
    model = api.new_model(name="plate with a cooling hole")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 0.2, 0.1, id="plate")
    geo.circle(0.1, 0.05, 0.02, id="hole")
    geo.cut(["plate"], ["hole"], id="cut")
    model.mesh_settings.global_size = 0.01
    built = api.build(model)
    api.select_curves(model, built, "bore",
                      where=lambda cv: abs(cv.center[0] - 0.1) < 0.03
                      and abs(cv.center[1] - 0.05) < 0.03)
    api.select_curves(model, built, "hot", where=lambda cv: abs(cv.center[1] - 0.1) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    q = 5.0e4
    model.bcs.append(HeatFlux("load", "hot", q=q))
    model.streams.append(stream(name="bore_flow", walls=["bore"], flow_area=3e-4,
                                wetted_perimeter=0.12, mass_flow=0.05))
    mesh = api.mesh(model, built)
    problem = compile_problem(model, built, mesh)
    term = problem.terms[-1]
    assert isinstance(term, ThroughPlaneStreamTerm) and problem.dofs.n_dofs == mesh.n_nodes
    assert problem.is_linear and problem.symmetric
    result = steady_solution(problem)
    balance = energy_balance(problem, result.T, system=result.system)
    assert balance.flows["load"] == pytest.approx(q * 0.2, rel=1e-9)
    assert balance.flows["bore_flow"] == pytest.approx(-q * 0.2, rel=1e-8)
    assert abs(balance.relative_imbalance) < 1e-8
    # the bore runs hotter than the bulk fluid, and the whole plate hotter still
    assert result.T.min() > T_BULK
    results = api.solve(model, mesh, built=built)
    into = results.heat_flow("load")[-1]
    out = results.heat_flow("bore_flow")[-1]
    assert into == pytest.approx(q * 0.2, rel=1e-9)
    assert abs(into + out) / into < 1e-8


# ------------------------------------------------------------------------------ M11.42


def test_sieder_tate_uses_the_mean_wall_temperature() -> None:
    problem, term = problem_with(stream(nu_option="sieder_tate"))
    assert not term.is_linear
    T_w = 340.0
    h = term.mean_coefficient(make_state(problem, T_w))
    p, ps = WATER.props(T_BULK), WATER.props(T_w)
    re = 0.3 * D_H / (AREA * p.mu)
    nu = 0.027 * re**0.8 * p.Pr ** (1 / 3) * (p.mu / ps.mu) ** 0.14
    assert h == pytest.approx(nu * p.k / D_H, rel=1e-13)
    cold = term.mean_coefficient(make_state(problem, 270.0))
    assert cold != pytest.approx(h, rel=1e-3)


def test_through_plane_annulus() -> None:
    problem, term = problem_with(stream(mass_flow=0.001, cross_section="annulus_outer",
                                        diameter_ratio=0.25))
    h = term.mean_coefficient(make_state(problem, 320.0))
    assert h == pytest.approx(4.23 * WATER.props(T_BULK).k / D_H, rel=1e-13)
