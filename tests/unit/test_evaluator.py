"""M6.3 - convection coefficient from correlations (Theory §8)."""

from __future__ import annotations

import logging

import numpy as np
import pytest
from handmade import TYPES, assemble, make_problem, make_state
from scipy.optimize import brentq

from thermalfea.convection import correlations as c
from thermalfea.convection.evaluator import (
    CorrelationConvectionTerm,
    film_coefficient,
)
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Table
from thermalfea.materials import library
from thermalfea.model.bcs import CorrelationConvection, FixedTemperature
from thermalfea.physics.evaluate import interpolate
from thermalfea.physics.surface_loads import ConvectionTerm
from thermalfea.solver.compile import attach
from thermalfea.solver.steady import steady_solution

AIR = library.fluid("Air")
LOGGER = "thermalfea.convection.evaluator"


def nat(name="nat", side="right", **kw):
    kw.setdefault("correlation", "vplate_natural")
    kw.setdefault("fluid", "Air")
    kw.setdefault("T_inf", 300.0)
    return CorrelationConvection(name, side, **kw)


def build(bc, etype="Q4", **kw):
    problem = make_problem(etype, bcs=(bc,), **kw)
    return problem, problem.terms[-1]


def vplate_h(T_s, T_inf, L, g=c.G):
    p = AIR.props(0.5 * (T_s + T_inf))
    Ra = c.rayleigh(p.beta, T_s - T_inf, L, p.Pr, p.rho, p.mu, g)
    return c.nu_vplate_natural(Ra, p.Pr) * p.k / L


def points(term, problem, s):
    return [(b, term.coefficient(s, b)) for b in term._batches]


# ------------------------------------------------------------------------------ 1, 2


@pytest.mark.parametrize("etype", TYPES)
def test_vertical_plate_uniform_wall(etype: str) -> None:
    problem, term = build(nat(char_length=0.5), etype)
    assert isinstance(term, CorrelationConvectionTerm) and isinstance(term, ConvectionTerm)
    assert not term.is_linear and not term.is_time_dependent and not problem.is_linear
    s = make_state(problem, 400.0)
    h = vplate_h(400.0, 300.0, 0.5)
    for _, values in points(term, problem, s):
        np.testing.assert_allclose(values, h, rtol=1e-12)
    area = 1.0  # right edge: length 1, thickness 1
    asm = assemble(problem, s, [term])
    assert asm.matrix().sum() == pytest.approx(h * area, rel=1e-12)
    assert asm.vector().sum() == pytest.approx(h * 300.0 * area, rel=1e-12)
    assert term.boundary_heat(s) == pytest.approx(-h * area * 100.0, rel=1e-12)


def test_film_temperature_is_used() -> None:
    problem, term = build(nat(char_length=0.5))
    s = make_state(problem, 500.0)
    (_, got), *_ = points(term, problem, s)
    film = AIR.props(400.0)
    Ra = c.rayleigh(film.beta, 200.0, 0.5, film.Pr, film.rho, film.mu)
    expected = c.nu_vplate_natural(Ra, film.Pr) * film.k / 0.5
    np.testing.assert_allclose(got, expected, rtol=1e-12)
    for wrong in (500.0, 300.0):
        p = AIR.props(wrong)
        Ra = c.rayleigh(p.beta, 200.0, 0.5, p.Pr, p.rho, p.mu)
        other = c.nu_vplate_natural(Ra, p.Pr) * p.k / 0.5
        assert abs(other - expected) > 1e-3 * expected


# ---------------------------------------------------------------------------------- 3


def test_local_and_average_wall_temperature() -> None:
    field_ = lambda problem: 350.0 + 40.0 * problem.mesh.nodes[:, 1]  # noqa: E731
    problem, term = build(nat(char_length=0.5))
    s = make_state(problem, field_(problem))
    for b, values in points(term, problem, s):
        T_s = interpolate(b.geom.N, s.u[b.dofs])
        np.testing.assert_allclose(values, vplate_h(T_s, 300.0, 0.5), rtol=1e-12)
        assert np.ptp(values) > 0.0
    problem, term = build(nat(char_length=0.5, wall_T_mode="average"))
    s = make_state(problem, field_(problem))
    expected = vplate_h(370.0, 300.0, 0.5)
    for _, values in points(term, problem, s):
        np.testing.assert_allclose(values, expected, rtol=1e-12)


# ---------------------------------------------------------------------------------- 4


def test_automatic_characteristic_length() -> None:
    s_args = 400.0
    auto, t_auto = build(nat())
    fixed, t_fixed = build(nat(char_length=1.0))  # the right edge is 1 m long
    a = points(t_auto, auto, make_state(auto, s_args))
    f = points(t_fixed, fixed, make_state(fixed, s_args))
    for (_, x), (_, y) in zip(a, f, strict=True):
        np.testing.assert_allclose(x, y, rtol=1e-13)
    # two curves: bottom (2 m) + right (1 m)
    problem = make_problem("Q4")
    problem.named_entities["both"] = (1, [1, 2])
    attach(problem, nat("both", "both"))
    explicit = make_problem("Q4")
    explicit.named_entities["both"] = (1, [1, 2])
    attach(explicit, nat("both", "both", char_length=3.0))
    a = points(problem.terms[-1], problem, make_state(problem, 400.0))
    f = points(explicit.terms[-1], explicit, make_state(explicit, 400.0))
    for (_, x), (_, y) in zip(a, f, strict=True):
        np.testing.assert_allclose(x, y, rtol=1e-13)
    with pytest.raises(ModelError, match="char_length"):
        build(nat(correlation="hcyl_natural"))
    with pytest.raises(ModelError, match="char_length"):
        build(CorrelationConvection("x", "right", "cylinder_crossflow", "Air", 300.0,
                                    velocity=2.0))
    problem, term = build(nat(correlation="hcyl_natural", char_length=0.05))
    assert term.coefficient(make_state(problem, 400.0), term._batches[0]).min() > 0.0


# ---------------------------------------------------------------------------------- 5


def forced_h(V, L, T_s=400.0, T_inf=300.0):
    p = AIR.props(0.5 * (T_s + T_inf))
    Re = c.reynolds(p.rho, V, L, p.mu)
    return c.nu_plate_forced_avg(Re, p.Pr) * p.k / L


def test_forced_convection_with_velocity() -> None:
    bc = CorrelationConvection("f", "right", "plate_forced_avg", "Air", 300.0, velocity=5.0,
                               char_length=0.5)
    problem, term = build(bc)
    assert not term.is_time_dependent and term.breakpoints() == []
    for _, values in points(term, problem, make_state(problem, 400.0)):
        np.testing.assert_allclose(values, forced_h(5.0, 0.5), rtol=1e-12)
    bc = CorrelationConvection("f", "right", "plate_forced_avg", "Air", 300.0,
                               velocity=Table([0.0, 10.0], [1.0, 5.0], "t"), char_length=0.5)
    problem, term = build(bc)
    assert term.is_time_dependent and term.breakpoints() == [0.0, 10.0]
    for _, values in points(term, problem, make_state(problem, 400.0, t=10.0)):
        np.testing.assert_allclose(values, forced_h(5.0, 0.5), rtol=1e-12)
    for _, values in points(term, problem, make_state(problem, 400.0, t=0.0)):
        np.testing.assert_allclose(values, forced_h(1.0, 0.5), rtol=1e-12)
    with pytest.raises(ModelError, match="velocity"):
        build(CorrelationConvection("f", "right", "plate_forced_avg", "Air", 300.0))


# ---------------------------------------------------------------------------------- 6


def test_plate_forced_local() -> None:
    params = {"x0": 0.8, "y0": 0.0, "dir_x": 3.0, "dir_y": 0.0}
    bc = CorrelationConvection("loc", "bottom", "plate_forced_local", "Air", 300.0,
                               velocity=4.0, params=params)
    problem, term = build(bc)
    s = make_state(problem, 400.0)
    p = AIR.props(350.0)
    clamped = 0
    seen = []
    for b, values in points(term, problem, s):
        raw = b.geom.xgp[..., 0] - 0.8
        clamped += int((raw < 1e-6).sum())
        x = np.maximum(raw, 1e-6)
        Re_x = c.reynolds(p.rho, 4.0, x, p.mu)
        expected = c.nu_plate_forced_local(Re_x, p.Pr) * p.k / x
        np.testing.assert_allclose(values, expected, rtol=1e-12)
        seen.append((x, values))
    assert clamped > 0
    x = np.concatenate([a.ravel() for a, _ in seen])
    h = np.concatenate([v.ravel() for _, v in seen])
    order = np.argsort(x)
    inside = x[order] > 1e-6
    assert np.all(np.diff(h[order][inside]) < 0.0)  # h falls with distance from the edge
    for bad in ({"x0": 0.0}, {**params, "dir_x": 0.0, "dir_y": 0.0}):
        with pytest.raises(ModelError):
            build(CorrelationConvection("loc", "bottom", "plate_forced_local", "Air", 300.0,
                                        velocity=4.0, params=bad))


# ---------------------------------------------------------------------------------- 7


def hplate_h(up: bool, T_s, T_inf=300.0, L=0.5):
    p = AIR.props(0.5 * (T_s + T_inf))
    Ra = c.rayleigh(p.beta, T_s - T_inf, L, p.Pr, p.rho, p.mu)
    Nu = c.nu_hplate_up_natural(Ra) if up else c.nu_hplate_down_natural(Ra)
    return Nu * p.k / L


@pytest.mark.parametrize(
    ("face", "T_s", "up"),
    [("up", 400.0, True), ("up", 250.0, False), ("down", 400.0, False), ("down", 250.0, True)],
)
def test_horizontal_plate_automatic_choice(face: str, T_s: float, up: bool) -> None:
    bc = nat(side="top", correlation="hplate_up_natural", char_length=0.5, face_direction=face)
    problem, term = build(bc)
    for _, values in points(term, problem, make_state(problem, T_s)):
        np.testing.assert_allclose(values, hplate_h(up, T_s), rtol=1e-12)
    # the same answer when the other correlation of the pair is named
    bc = nat(side="top", correlation="hplate_down_natural", char_length=0.5, face_direction=face)
    problem, term = build(bc)
    for _, values in points(term, problem, make_state(problem, T_s)):
        np.testing.assert_allclose(values, hplate_h(up, T_s), rtol=1e-12)


@pytest.mark.parametrize("name", ["hplate_up_natural", "hplate_down_natural"])
def test_horizontal_plate_without_direction_uses_the_named_correlation(name: str) -> None:
    problem, term = build(nat(side="top", correlation=name, char_length=0.5))
    for T_s in (400.0, 250.0):
        for _, values in points(term, problem, make_state(problem, T_s)):
            np.testing.assert_allclose(values, hplate_h(name == "hplate_up_natural", T_s))


def test_face_direction_is_ignored_by_other_correlations() -> None:
    problem, term = build(nat(char_length=0.5, face_direction="up"))
    (_, values), *_ = points(term, problem, make_state(problem, 400.0))
    np.testing.assert_allclose(values, vplate_h(400.0, 300.0, 0.5), rtol=1e-12)


# ---------------------------------------------------------------------------------- 8


def test_inclined_plate() -> None:
    theta = 40.0
    bc = nat(correlation="inclined_natural", char_length=0.5, params={"theta_deg": theta})
    problem, term = build(bc)
    s = make_state(problem, 400.0)
    expected = vplate_h(400.0, 300.0, 0.5, g=c.G * np.cos(np.radians(theta)))
    (_, values), *_ = points(term, problem, s)
    np.testing.assert_allclose(values, expected, rtol=1e-12)
    assert expected < vplate_h(400.0, 300.0, 0.5)
    bc = nat(correlation="inclined_natural", char_length=0.5, params={"theta_deg": 0.0})
    problem, term = build(bc)
    (_, values), *_ = points(term, problem, make_state(problem, 400.0))
    np.testing.assert_allclose(values, vplate_h(400.0, 300.0, 0.5), rtol=1e-12)
    with pytest.raises(ModelError, match="theta_deg"):
        build(nat(correlation="inclined_natural", char_length=0.5))


# ------------------------------------------------------------------------------ 9, 10


def test_power_law() -> None:
    bc = nat(correlation="power_law", fluid="not a fluid", params={"C": 2.0, "n": 0.25})
    problem, term = build(bc)
    (_, values), *_ = points(term, problem, make_state(problem, 400.0))
    np.testing.assert_allclose(values, 2.0 * 100.0**0.25, rtol=1e-13)
    (_, values), *_ = points(term, problem, make_state(problem, 200.0))
    np.testing.assert_allclose(values, 2.0 * 100.0**0.25, rtol=1e-13)
    with pytest.raises(ModelError, match="params"):
        build(nat(correlation="power_law", params={"C": 2.0}))


def test_multiplier_scales_h() -> None:
    base, t1 = build(nat(char_length=0.5))
    scaled, t2 = build(nat(char_length=0.5, multiplier=1.7))
    (_, a), *_ = points(t1, base, make_state(base, 400.0))
    (_, b), *_ = points(t2, scaled, make_state(scaled, 400.0))
    np.testing.assert_allclose(b, 1.7 * a, rtol=1e-13)


# --------------------------------------------------------------------------------- 11


def warnings_of(caplog) -> list[str]:
    return [r.getMessage() for r in caplog.records
            if r.name == LOGGER and r.levelno == logging.WARNING]


def test_validity_warning_once_per_bc(caplog: pytest.LogCaptureFixture) -> None:
    bc = nat("weak", "top", correlation="hplate_up_natural", char_length=0.02)
    problem, term = build(bc)
    s = make_state(problem, 300.5)  # Ra far below 1e4
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for _ in range(3):
            points(term, problem, s)
    found = warnings_of(caplog)
    assert len(found) == 1 and "weak" in found[0] and "Ra" in found[0]
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        points(term, problem, s)
    assert warnings_of(caplog) == []
    term.reset_warnings()
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        points(term, problem, s)
    assert len(warnings_of(caplog)) == 1


def test_no_warning_inside_the_range(caplog: pytest.LogCaptureFixture) -> None:
    bc = nat("fine", "top", correlation="hplate_up_natural", char_length=0.5)
    problem, term = build(bc)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        points(term, problem, make_state(problem, 400.0))
    assert warnings_of(caplog) == []


def test_property_table_warning(caplog: pytest.LogCaptureFixture) -> None:
    problem, term = build(nat("hot", char_length=0.5))
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for _ in range(2):
            points(term, problem, make_state(problem, 5000.0))
    found = warnings_of(caplog)
    assert len(found) == 1 and "hot" in found[0] and "table" in found[0]


# --------------------------------------------------------------------------------- 12


@pytest.mark.parametrize(
    ("bc", "match"),
    [
        (nat("bad", correlation="nope"), "bad: unknown correlation.*vplate_natural"),
        (nat("bad", fluid="Unobtainium"), "Unobtainium"),
        (nat("bad", multiplier=0.0), "bad: multiplier"),
        (nat("bad", multiplier=-1.0), "bad: multiplier"),
        (nat("bad", char_length=0.0), "bad: char_length"),
        (nat("bad", params={"theta": 1.0}), "bad: unknown params"),
        (nat("bad", correlation="duct_internal", char_length=0.1), "stream"),
        (nat("bad", correlation="plate_forced_local", velocity=1.0), "bad: .*params"),
    ],
)
def test_setup_errors(bc, match: str) -> None:
    with pytest.raises(ModelError, match=match):
        build(bc)


# --------------------------------------------------------------------------------- 13


@pytest.mark.parametrize("etype", TYPES)
def test_slab_matches_the_scalar_balance(etype: str) -> None:
    length, k = 0.1, 50.0
    bcs = (
        FixedTemperature("hot", "left", T=400.0),
        nat("natural", "right", char_length=0.5),
    )
    problem = make_problem(etype, size=(length, length / 10), cells=(10, 1), bcs=bcs)
    assert not problem.is_linear
    result = steady_solution(problem)
    assert result.converged
    nodes = problem.mesh.nodes
    T_s = float(result.T[np.isclose(nodes[:, 0], length)].mean())
    root = brentq(lambda t: k * (400.0 - t) / length - vplate_h(t, 300.0, 0.5) * (t - 300.0),
                  300.0, 400.0, xtol=1e-14)
    assert abs(T_s - root) / root < 1e-6


# --------------------------------------------------------------------------------- 14


def test_film_coefficient_helper_and_results() -> None:
    problem, term = build(nat(char_length=0.5, multiplier=2.0))
    s = make_state(problem, 400.0)
    (_, from_term), *_ = points(term, problem, s)
    h, numbers = film_coefficient(c.CORRELATIONS["vplate_natural"], AIR, 400.0, 300.0, 0.5)
    np.testing.assert_allclose(from_term, 2.0 * h, rtol=1e-13)
    p = AIR.props(350.0)
    assert numbers["T_film"] == 350.0 and numbers["k"] == p.k and numbers["Pr"] == p.Pr
    assert numbers["Nu"] == pytest.approx(h * 0.5 / p.k)
    assert "Ra" in numbers and "Re" not in numbers
    assert np.isscalar(h) or np.ndim(h) == 0
    # arrays
    arr, _ = film_coefficient(c.CORRELATIONS["vplate_natural"], AIR, np.array([350.0, 400.0]),
                              300.0, 0.5)
    assert arr.shape == (2,) and arr[1] == pytest.approx(h)
    forced, nf = film_coefficient(c.CORRELATIONS["plate_forced_avg"], AIR, 400.0, 300.0, 0.5,
                                  velocity=5.0)
    assert forced == pytest.approx(forced_h(5.0, 0.5)) and "Re" in nf
    assert term.mean_coefficient(s) == pytest.approx(2.0 * h, rel=1e-12)
    out = term.results(s)
    assert list(out) == ["h_mean:nat"] and out["h_mean:nat"][0] == pytest.approx(2.0 * h)
    with pytest.raises(ModelError, match="stream"):
        film_coefficient(c.CORRELATIONS["duct_internal"], AIR, 400.0, 300.0, 0.5)
