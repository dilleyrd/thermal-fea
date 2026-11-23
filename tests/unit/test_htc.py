"""M6.4 - stand-alone heat-transfer calculator (Theory §8 and §8.1)."""

from __future__ import annotations

import numpy as np
import pytest

from thermalfea import api
from thermalfea.convection import calculator
from thermalfea.convection import correlations as c
from thermalfea.core.errors import ModelError
from thermalfea.materials import library
from thermalfea.materials.material import Fluid

AIR = library.fluid("Air")
WATER = library.fluid("Water")


def htc(correlation, fluid, T_s, T_inf, **kw):
    return calculator.htc(correlation, fluid, T_s, T_inf, **kw)


# ------------------------------------------------------------------------------ 1


def test_vertical_plate_natural() -> None:
    res = htc("vplate_natural", "Air", 350.0, 300.0, length=0.5)
    p = AIR.props(325.0)
    Ra = c.rayleigh(p.beta, 50.0, 0.5, p.Pr, p.rho, p.mu)
    Nu = c.nu_vplate_natural(Ra, p.Pr)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.Ra == pytest.approx(Ra, rel=1e-12)
    assert res.Pr == pytest.approx(p.Pr, rel=1e-12)
    assert res.h == pytest.approx(Nu * p.k / 0.5, rel=1e-12)
    assert res.T_film == 325.0
    assert res.Re is None
    assert res.regime == "single correlation"
    assert res.warnings == []
    assert res.length == 0.5
    for value in (res.h, res.Nu, res.Ra, res.Pr, res.T_film, res.length):
        assert type(value) is float


# ------------------------------------------------------------------------------ 2


@pytest.mark.parametrize(
    ("V", "regime"), [(5.0, "laminar"), (30.0, "turbulent")]
)
def test_plate_forced_average(V: float, regime: str) -> None:
    res = htc("plate_forced_avg", "Air", 400.0, 300.0, length=0.5, velocity=V)
    p = AIR.props(350.0)
    Re = c.reynolds(p.rho, V, 0.5, p.mu)
    Nu = c.nu_plate_forced_avg(Re, p.Pr)
    assert (Re <= 5e5) == (regime == "laminar")
    assert res.Re == pytest.approx(Re, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(Nu * p.k / 0.5, rel=1e-12)
    assert res.Ra is None
    assert res.regime == regime
    assert res.warnings == []


# ------------------------------------------------------------------------------ 3


@pytest.mark.parametrize("x", [0.3, 0.0])
def test_plate_forced_local(x: float) -> None:
    V = 5.0
    res = htc("plate_forced_local", "Air", 400.0, 300.0, x=x, velocity=V)
    x_used = max(x, 1e-6)
    p = AIR.props(350.0)
    Re_x = c.reynolds(p.rho, V, x_used, p.mu)
    Nu = c.nu_plate_forced_local(Re_x, p.Pr)
    assert res.length == pytest.approx(x_used, rel=1e-15)
    assert res.Re == pytest.approx(Re_x, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(Nu * p.k / x_used, rel=1e-12)
    assert np.isfinite(res.h) and res.h > 0.0
    assert res.regime == "laminar"


# ------------------------------------------------------------------------------ 4


def test_cylinder_crossflow_uses_diameter() -> None:
    D, V = 0.02, 3.0
    res = htc("cylinder_crossflow", "Air", 350.0, 300.0, length=D, velocity=V)
    p = AIR.props(325.0)
    Re = c.reynolds(p.rho, V, D, p.mu)
    Nu = c.nu_cylinder_crossflow(Re, p.Pr)
    assert res.length == D
    assert res.Re == pytest.approx(Re, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(Nu * p.k / D, rel=1e-12)
    assert res.regime == "single correlation"
    assert res.warnings == []


def test_horizontal_cylinder_natural() -> None:
    D = 0.02
    res = htc("hcyl_natural", "Air", 350.0, 300.0, length=D)
    p = AIR.props(325.0)
    Ra = c.rayleigh(p.beta, 50.0, D, p.Pr, p.rho, p.mu)
    Nu = c.nu_hcyl_natural(Ra, p.Pr)
    assert res.Ra == pytest.approx(Ra, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(Nu * p.k / D, rel=1e-12)
    assert res.regime == "single correlation"


# ------------------------------------------------------------------------------ 5


def _hplate_expected(T_s: float, up_nu: bool, L: float = 0.5):
    p = AIR.props(0.5 * (T_s + 300.0))
    Ra = c.rayleigh(p.beta, T_s - 300.0, L, p.Pr, p.rho, p.mu)
    Nu = c.nu_hplate_up_natural(Ra) if up_nu else c.nu_hplate_down_natural(Ra)
    return Ra, Nu, Nu * p.k / L


@pytest.mark.parametrize("name", ["hplate_up_natural", "hplate_down_natural"])
def test_horizontal_plate_named_without_direction(name: str) -> None:
    res = htc(name, "Air", 400.0, 300.0, length=0.5)
    Ra, Nu, h = _hplate_expected(400.0, name == "hplate_up_natural")
    assert res.Ra == pytest.approx(Ra, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(h, rel=1e-12)
    if name == "hplate_up_natural":
        assert res.regime == ("laminar" if Ra <= 1e7 else "turbulent")
    else:
        assert res.regime == "single correlation"


def test_horizontal_plate_face_up_hot_wall_uses_up() -> None:
    res = htc("hplate_up_natural", "Air", 400.0, 300.0, length=0.5, face_direction="up")
    Ra, Nu, h = _hplate_expected(400.0, up_nu=True)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(h, rel=1e-12)
    used = "laminar" if Ra <= 1e7 else "turbulent"
    assert res.regime == f"hplate_up_natural, {used}"
    assert res.warnings == []


def test_horizontal_plate_face_up_cold_wall_uses_down() -> None:
    res = htc("hplate_up_natural", "Air", 250.0, 300.0, length=0.5, face_direction="up")
    Ra, Nu, h = _hplate_expected(250.0, up_nu=False)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(h, rel=1e-12)
    assert res.regime == "hplate_down_natural, single correlation"


def test_horizontal_plate_face_down_hot_wall_uses_down() -> None:
    res = htc("hplate_down_natural", "Air", 400.0, 300.0, length=0.5, face_direction="down")
    _, _, h = _hplate_expected(400.0, up_nu=False)
    assert res.h == pytest.approx(h, rel=1e-12)
    assert res.regime == "hplate_down_natural, single correlation"


# ------------------------------------------------------------------------------ 6


def test_inclined_plate_uses_cos_theta_in_gravity() -> None:
    theta, L = 30.0, 0.5
    res = htc("inclined_natural", "Air", 400.0, 300.0, length=L, theta_deg=theta)
    p = AIR.props(350.0)
    g = c.G * np.cos(np.radians(theta))
    Ra = c.rayleigh(p.beta, 100.0, L, p.Pr, p.rho, p.mu, g)
    Nu = c.nu_vplate_natural(Ra, p.Pr)
    assert res.h == pytest.approx(Nu * p.k / L, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    vertical = htc("vplate_natural", "Air", 400.0, 300.0, length=L)
    assert res.h < vertical.h


def test_inclined_plate_at_zero_is_vertical_plate() -> None:
    res = htc("inclined_natural", "Air", 400.0, 300.0, length=0.5, theta_deg=0.0)
    vertical = htc("vplate_natural", "Air", 400.0, 300.0, length=0.5)
    assert res.h == pytest.approx(vertical.h, rel=1e-12)


# ------------------------------------------------------------------------------ 7


def test_power_law_needs_no_fluid() -> None:
    res = htc("power_law", None, 400.0, 300.0, C=2.0, n=0.25)
    assert res.h == pytest.approx(2.0 * 100.0**0.25, rel=1e-13)
    assert res.Nu is None and res.Re is None and res.Ra is None and res.Pr is None
    assert res.length is None
    assert res.T_film == 350.0
    assert res.regime == "single correlation"
    assert res.warnings == []
    other = htc("power_law", "anything", 200.0, 300.0, C=2.0, n=0.25)
    assert other.h == pytest.approx(2.0 * 100.0**0.25, rel=1e-13)


# ------------------------------------------------------------------------------ 8

D_PIPE = 0.02
AREA = np.pi * D_PIPE**2 / 4.0
PERIM = np.pi * D_PIPE
T_BULK = 330.0
T_WALL = 360.0


def _mass_flow(Re: float, area: float = AREA, perim: float = PERIM, T: float = T_BULK) -> float:
    mu = float(WATER.props(T).mu)
    return Re * area * mu / (4.0 * area / perim)


@pytest.mark.parametrize(
    ("Re_target", "regime"), [(1000.0, "laminar"), (3000.0, "transition"), (10000.0, "turbulent")]
)
def test_duct_internal_water(Re_target: float, regime: str) -> None:
    m_dot = _mass_flow(Re_target)
    res = htc("duct_internal", "Water", T_WALL, T_BULK, mass_flow=m_dot, area=AREA,
              wetted_perimeter=PERIM)
    p = WATER.props(T_BULK)  # bulk temperature, not the film temperature
    D_h = 4.0 * AREA / PERIM
    Nu = c.nu_duct(Re_target, p.Pr, "circular", "constant_T", "auto", heating=True)
    assert res.Re == pytest.approx(Re_target, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(Nu * p.k / D_h, rel=1e-12)
    assert res.length == pytest.approx(D_h, rel=1e-12)
    assert res.T_film == T_BULK
    assert res.Pr == pytest.approx(p.Pr, rel=1e-12)
    assert res.Ra is None
    assert res.regime == regime
    assert res.warnings == []
    film = WATER.props(0.5 * (T_WALL + T_BULK))
    film_Re = m_dot * D_h / (AREA * float(film.mu))
    assert abs(film_Re - Re_target) / Re_target > 1e-3  # the bulk choice is observable


def test_duct_internal_dittus_boelter_exponent_follows_heating() -> None:
    m_dot = _mass_flow(1e4)
    p = WATER.props(T_BULK)
    common = dict(mass_flow=m_dot, area=AREA, wetted_perimeter=PERIM,
                  option="dittus_boelter")
    hot = htc("duct_internal", "Water", T_WALL, T_BULK, **common)
    cold = htc("duct_internal", "Water", 300.0, T_BULK, **common)
    assert hot.Nu == pytest.approx(c.nu_dittus_boelter(1e4, p.Pr, heating=True), rel=1e-12)
    assert cold.Nu == pytest.approx(c.nu_dittus_boelter(1e4, p.Pr, heating=False), rel=1e-12)
    assert hot.Nu == pytest.approx(0.023 * 1e4**0.8 * float(p.Pr) ** 0.4, rel=1e-12)
    assert cold.Nu == pytest.approx(0.023 * 1e4**0.8 * float(p.Pr) ** 0.3, rel=1e-12)


def test_duct_internal_square_constant_flux() -> None:
    side = 0.02
    area, perim = side * side, 4.0 * side
    m_dot = _mass_flow(1000.0, area=area, perim=perim)
    res = htc("duct_internal", "Water", T_WALL, T_BULK, mass_flow=m_dot, area=area,
              wetted_perimeter=perim, cross_section="square", wall="constant_flux")
    assert res.length == pytest.approx(side, rel=1e-12)
    assert res.Nu == pytest.approx(c.nu_laminar("square", "constant_flux"), rel=1e-12)
    p = WATER.props(T_BULK)
    assert res.h == pytest.approx(res.Nu * float(p.k) / side, rel=1e-12)
    assert res.regime == "laminar"


# ------------------------------------------------------------------------------ 9


def test_multiplier_scales_h_and_fluid_object_is_accepted() -> None:
    base = htc("vplate_natural", "Air", 350.0, 300.0, length=0.5)
    scaled = htc("vplate_natural", "Air", 350.0, 300.0, length=0.5, multiplier=1.7)
    assert scaled.h == pytest.approx(1.7 * base.h, rel=1e-13)
    assert scaled.Nu == pytest.approx(base.Nu, rel=1e-13)
    by_object = htc("vplate_natural", library.fluid("Air"), 350.0, 300.0, length=0.5)
    assert by_object == base
    assert isinstance(library.fluid("Air"), Fluid)


# ------------------------------------------------------------------------------ 10


def test_validity_warning_is_returned() -> None:
    res = htc("hplate_up_natural", "Air", 300.5, 300.0, length=0.02, face_direction="up")
    assert res.Ra < 1e4
    assert len(res.warnings) == 1
    assert "hplate_up_natural" in res.warnings[0] and "Ra" in res.warnings[0]


def test_property_table_warning_is_returned() -> None:
    res = htc("vplate_natural", "Air", 8000.0, 300.0, length=0.5)
    assert res.warnings == [
        "fluid temperature outside the property table; end values are used"
    ]


def test_in_range_case_has_no_warnings() -> None:
    res = htc("vplate_natural", "Air", 400.0, 300.0, length=0.5)
    assert res.warnings == []


# ------------------------------------------------------------------------------ 11


@pytest.mark.parametrize(
    ("args", "kwargs", "match"),
    [
        (("nope", "Air", 350.0, 300.0), {"length": 0.5}, "vplate_natural"),
        (("vplate_natural", "Air", 350.0, 300.0), {"length": 0.5, "foo": 1}, "foo"),
        (("vplate_natural", "Air", 350.0, 300.0), {}, "length"),
        (("plate_forced_avg", "Air", 350.0, 300.0), {"length": 0.5}, "velocity"),
        (("inclined_natural", "Air", 350.0, 300.0), {"length": 0.5}, "theta_deg"),
        (("power_law", None, 350.0, 300.0), {"n": 0.3}, "C"),
        (("power_law", None, 350.0, 300.0), {"C": 2.0}, "n"),
        (("duct_internal", "Water", 360.0, 330.0),
         {"mass_flow": 0.01, "wetted_perimeter": PERIM}, "area"),
        (("vplate_natural", "Air", 0.0, 300.0), {"length": 0.5}, "T_surface"),
        (("vplate_natural", "Air", 350.0, -5.0), {"length": 0.5}, "T_inf"),
        (("vplate_natural", "Air", 350.0, 300.0), {"length": 0.5, "multiplier": 0.0},
         "multiplier"),
        (("vplate_natural", "Air", 350.0, 300.0), {"length": 0.5, "multiplier": -2.0},
         "multiplier"),
        (("vplate_natural", "Unobtainium", 350.0, 300.0), {"length": 0.5}, "Unobtainium"),
        (("vplate_natural", None, 350.0, 300.0), {"length": 0.5}, "fluid"),
    ],
)
def test_errors(args, kwargs, match: str) -> None:
    with pytest.raises(ModelError, match=match):
        calculator.htc(*args, **kwargs)


# ------------------------------------------------------------------------------ 12


def test_api_wrapper_matches_calculator() -> None:
    kwargs = dict(length=0.5, multiplier=1.2)
    via_api = api.htc("vplate_natural", "Air", 350.0, 300.0, **kwargs)
    direct = calculator.htc("vplate_natural", "Air", 350.0, 300.0, **kwargs)
    assert via_api == direct
    assert api.HtcResult is calculator.HtcResult
    assert isinstance(via_api, api.HtcResult)


# ------------------------------------------------------------------------------- M11.38


def test_inclined_face_warning_in_the_calculator() -> None:
    kw = dict(length=0.5, theta_deg=30.0)
    assert any("face" in w for w in htc("inclined_natural", "Air", 400.0, 300.0,
                                        face_direction="up", **kw).warnings)
    assert any("face" in w for w in htc("inclined_natural", "Air", 250.0, 300.0,
                                        face_direction="down", **kw).warnings)
    assert htc("inclined_natural", "Air", 400.0, 300.0, face_direction="down", **kw).warnings == []
    assert htc("inclined_natural", "Air", 250.0, 300.0, face_direction="up", **kw).warnings == []
    assert htc("inclined_natural", "Air", 400.0, 300.0, **kw).warnings == []


def test_duct_dittus_boelter_validity_only_when_selected() -> None:
    m_dot = _mass_flow(5000.0)
    common = dict(mass_flow=m_dot, area=AREA, wetted_perimeter=PERIM)
    plain = htc("duct_internal", "Water", T_WALL, T_BULK, **common)
    db = htc("duct_internal", "Water", T_WALL, T_BULK, option="dittus_boelter", **common)
    assert plain.warnings == []
    assert len(db.warnings) == 1 and "Re" in db.warnings[0]  # Re = 5000 < 1e4
    ok = htc("duct_internal", "Water", T_WALL, T_BULK, option="dittus_boelter",
             **dict(common, mass_flow=_mass_flow(2e4)))
    assert ok.warnings == []


# ------------------------------------------------------------------------------ M11.39

_NONCIRCULAR = {
    "square_corner_crossflow": c.nu_square_corner_crossflow,
    "square_face_crossflow": c.nu_square_face_crossflow,
    "hexagon_face_crossflow": c.nu_hexagon_face_crossflow,
    "hexagon_corner_crossflow": c.nu_hexagon_corner_crossflow,
    "plate_front_crossflow": c.nu_plate_front_crossflow,
    "plate_back_crossflow": c.nu_plate_back_crossflow,
}


@pytest.mark.parametrize("name", list(_NONCIRCULAR))
def test_noncircular_crossflow_at_film_temperature(name: str) -> None:
    D, V = 0.3, 2.0
    res = htc(name, "Air", 350.0, 300.0, length=D, velocity=V)
    p = AIR.props(325.0)
    Re = c.reynolds(p.rho, V, D, p.mu)
    Nu = _NONCIRCULAR[name](Re, p.Pr)
    assert res.T_film == 325.0 and res.length == D
    assert res.Re == pytest.approx(Re, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(Nu * p.k / D, rel=1e-12)
    with pytest.raises(ModelError, match="length"):
        htc(name, "Air", 350.0, 300.0, velocity=V)


def test_noncircular_out_of_range_warns() -> None:
    res = htc("plate_front_crossflow", "Air", 350.0, 300.0, length=0.001, velocity=1.0)
    assert any("Re outside validity range" in w for w in res.warnings)


def test_sphere_forced_properties_at_t_inf_and_mu_s_at_t_s() -> None:
    D, V, T_s, T_i = 0.02, 5.0, 400.0, 300.0
    res = htc("sphere_forced", "Air", T_s, T_i, length=D, velocity=V)
    p = AIR.props(T_i)
    mu_s = AIR.props(T_s).mu
    Re = c.reynolds(p.rho, V, D, p.mu)
    Nu = c.nu_sphere_forced(Re, p.Pr, p.mu / mu_s)
    assert res.T_film == T_i
    assert res.Re == pytest.approx(Re, rel=1e-12)
    assert res.Pr == pytest.approx(p.Pr, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(Nu * p.k / D, rel=1e-12)
    # the film-temperature value is different
    pf = AIR.props(0.5 * (T_s + T_i))
    other = c.nu_sphere_forced(c.reynolds(pf.rho, V, D, pf.mu), pf.Pr, 1.0) * pf.k / D
    assert abs(other - res.h) > 1e-3 * res.h
    # a hot wall in a gas has mu/mu_s < 1: outside 1.0 <= mu/mu_s
    assert any("mu_ratio" in w for w in res.warnings)


def test_sphere_forced_mu_ratio_in_range_for_a_cold_wall() -> None:
    res = htc("sphere_forced", "Air", 280.0, 300.0, length=0.02, velocity=5.0)
    assert not any("mu_ratio" in w for w in res.warnings)


def test_sphere_natural_and_vplate_laminar() -> None:
    D = 0.1
    res = htc("sphere_natural", "Air", 350.0, 300.0, length=D)
    p = AIR.props(325.0)
    Ra = c.rayleigh(p.beta, 50.0, D, p.Pr, p.rho, p.mu)
    assert res.Ra == pytest.approx(Ra, rel=1e-12)
    assert res.Nu == pytest.approx(c.nu_sphere_natural(Ra, p.Pr), rel=1e-12)
    assert res.h == pytest.approx(res.Nu * p.k / D, rel=1e-12)
    res = htc("vplate_natural_laminar", "Air", 350.0, 300.0, length=0.3)
    Ra = c.rayleigh(p.beta, 50.0, 0.3, p.Pr, p.rho, p.mu)
    assert res.Nu == pytest.approx(c.nu_vplate_natural_laminar(Ra, p.Pr), rel=1e-12)
    assert res.warnings == []
    res = htc("vplate_natural_laminar", "Air", 350.0, 300.0, length=10.0)
    assert any("Ra outside validity range" in w for w in res.warnings)


# ------------------------------------------------------------------------------ M11.40

_CHANNEL_FUNCTIONS = {
    "vchannel_natural": c.nu_vchannel_natural,
    "vchannel_one_side_natural": c.nu_vchannel_one_side_natural,
}


@pytest.mark.parametrize("name", list(_CHANNEL_FUNCTIONS))
def test_vchannel_uses_the_spacing_for_ra_and_h(name: str) -> None:
    L, S = 0.5, 0.02
    res = htc(name, "Air", 350.0, 300.0, length=L, S=S)
    p = AIR.props(325.0)
    Ra_S = c.rayleigh(p.beta, 50.0, S, p.Pr, p.rho, p.mu)
    Nu = _CHANNEL_FUNCTIONS[name](Ra_S, S / L)
    assert res.T_film == 325.0 and res.length == L
    assert res.Ra == pytest.approx(Ra_S, rel=1e-12)
    assert res.Nu == pytest.approx(Nu, rel=1e-12)
    assert res.h == pytest.approx(Nu * p.k / S, rel=1e-12)
    assert res.warnings == []
    with pytest.raises(ModelError, match="S"):
        htc(name, "Air", 350.0, 300.0, length=L)
    with pytest.raises(ModelError, match="length"):
        htc(name, "Air", 350.0, 300.0, S=S)
    with pytest.raises(ModelError):
        htc(name, "Air", 350.0, 300.0, length=L, S=0.0)
