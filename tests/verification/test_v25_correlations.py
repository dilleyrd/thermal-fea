"""V-25 — correlation spot checks (Theory §8, §8.1).

Each correlation is evaluated by the module and compared with the same formula written out
here in plain Python arithmetic, independently of the module, to relative tolerance 1e-12.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from thermalfea.convection import correlations as c

REL = 1e-12
PR = 0.7
G = 9.80665


def rel_eq(got: float, want: float) -> None:
    assert got == pytest.approx(want, rel=REL, abs=0.0)


# ------------------------------------------------------------------ external forced


@pytest.mark.parametrize("Re", [1e4, 5e5, 5e5 + 1, 1e6, 1e7])
def test_plate_forced_avg(Re: float) -> None:
    if Re <= 5e5:
        want = 0.664 * Re**0.5 * PR ** (1 / 3)
    else:
        want = (0.037 * Re**0.8 - 871) * PR ** (1 / 3)
    rel_eq(c.nu_plate_forced_avg(Re, PR), want)


@pytest.mark.parametrize("Rx", [1e4, 5e5, 5e5 + 1, 1e6, 1e7])
def test_plate_forced_local(Rx: float) -> None:
    if Rx <= 5e5:
        want = 0.332 * Rx**0.5 * PR ** (1 / 3)
    else:
        want = 0.0296 * Rx**0.8 * PR ** (1 / 3)
    rel_eq(c.nu_plate_forced_local(Rx, PR), want)


@pytest.mark.parametrize("Re", [0.5, 1e2, 1e4, 1e5, 1e6])
def test_cylinder_crossflow(Re: float) -> None:
    want = (
        0.3
        + 0.62
        * Re**0.5
        * PR ** (1 / 3)
        * (1 + (0.4 / PR) ** (2 / 3)) ** (-1 / 4)
        * (1 + (Re / 282000) ** (5 / 8)) ** (4 / 5)
    )
    rel_eq(c.nu_cylinder_crossflow(Re, PR), want)


# ------------------------------------------------------------------ natural


@pytest.mark.parametrize("Ra", [1e3, 1e6, 1e9, 1e11])
def test_vplate_natural(Ra: float) -> None:
    want = (0.825 + 0.387 * Ra ** (1 / 6) / (1 + (0.492 / PR) ** (9 / 16)) ** (8 / 27)) ** 2
    rel_eq(c.nu_vplate_natural(Ra, PR), want)


@pytest.mark.parametrize("Ra", [1e3, 1e9])
def test_inclined_natural_same_formula_as_vertical(Ra: float) -> None:
    want = (0.825 + 0.387 * Ra ** (1 / 6) / (1 + (0.492 / PR) ** (9 / 16)) ** (8 / 27)) ** 2
    rel_eq(c.nu_inclined_natural(Ra, PR), want)


@pytest.mark.parametrize("Ra", [1e5, 1e7, 1e7 + 1, 1e9])
def test_hplate_up_natural(Ra: float) -> None:
    if Ra <= 1e7:
        want = 0.54 * Ra**0.25
    else:
        want = 0.15 * Ra ** (1 / 3)
    rel_eq(c.nu_hplate_up_natural(Ra), want)


@pytest.mark.parametrize("Ra", [1e4, 1e5, 1e7, 1e9])
def test_hplate_down_natural(Ra: float) -> None:
    rel_eq(c.nu_hplate_down_natural(Ra), 0.52 * Ra ** (1 / 5))


@pytest.mark.parametrize("Ra", [1e4, 1e8, 1e11])
def test_hcyl_natural(Ra: float) -> None:
    want = (0.60 + 0.387 * Ra ** (1 / 6) / (1 + (0.559 / PR) ** (9 / 16)) ** (8 / 27)) ** 2
    rel_eq(c.nu_hcyl_natural(Ra, PR), want)


@pytest.mark.parametrize(("C", "n", "dT"), [(1.3, 0.25, 40.0), (5.0, 1.33, -12.5)])
def test_h_power_law(C: float, n: float, dT: float) -> None:
    rel_eq(c.h_power_law(C, n, dT), C * abs(dT) ** n)


# ------------------------------------------------------------------ internal duct


@pytest.mark.parametrize("Re", [1e4, 5e4, 1e5])
def test_friction_smooth(Re: float) -> None:
    rel_eq(c.friction_smooth(Re), (0.790 * math.log(Re) - 1.64) ** -2)


@pytest.mark.parametrize("Re", [4000.0, 1e4, 1e5, 1e6])
def test_nu_gnielinski(Re: float) -> None:
    f = (0.790 * math.log(Re) - 1.64) ** -2
    want = (f / 8) * (Re - 1000) * PR / (1 + 12.7 * (f / 8) ** 0.5 * (PR ** (2 / 3) - 1))
    rel_eq(c.nu_gnielinski(Re, PR), want)


@pytest.mark.parametrize(("heating", "n"), [(True, 0.4), (False, 0.3)])
@pytest.mark.parametrize("Re", [1e4, 5e4])
def test_nu_dittus_boelter(heating: bool, n: float, Re: float) -> None:
    rel_eq(c.nu_dittus_boelter(Re, PR, heating=heating), 0.023 * Re**0.8 * PR**n)


def test_nu_dittus_boelter_default_is_heating() -> None:
    rel_eq(c.nu_dittus_boelter(1e4, PR), 0.023 * 1e4**0.8 * PR**0.4)


@pytest.mark.parametrize(
    ("section", "wall", "want"),
    [
        ("circular", "constant_T", 3.66),
        ("circular", "constant_flux", 4.36),
        ("parallel_plates", "constant_T", 7.54),
        ("parallel_plates", "constant_flux", 8.23),
        ("parallel_plates_one_side", "constant_T", 4.86),
        ("parallel_plates_one_side", "constant_flux", 5.39),
        ("square", "constant_T", 2.98),
        ("square", "constant_flux", 3.61),
    ],
)
def test_nu_laminar_table(section: str, wall: str, want: float) -> None:
    assert c.nu_laminar(section, wall) == want


def test_nu_duct_laminar() -> None:
    rel_eq(c.nu_duct(500.0, PR), 3.66)
    rel_eq(c.nu_duct(1000.0, PR, cross_section="square", wall="constant_flux"), 3.61)


def _gnielinski(Re: float) -> float:
    f = (0.790 * math.log(Re) - 1.64) ** -2
    return (f / 8) * (Re - 1000) * PR / (1 + 12.7 * (f / 8) ** 0.5 * (PR ** (2 / 3) - 1))


def _dittus(Re: float) -> float:
    return 0.023 * Re**0.8 * PR**0.4


def test_nu_duct_transition_end_points() -> None:
    rel_eq(c.nu_duct(2300.0, PR), 3.66)
    rel_eq(c.nu_duct(4000.0, PR), _gnielinski(4000.0))


def test_nu_duct_transition_interpolates() -> None:
    Re = 3000.0
    nu_lam = 3.66
    nu_end = _gnielinski(4000.0)
    want = nu_lam + (Re - 2300.0) / (4000.0 - 2300.0) * (nu_end - nu_lam)
    rel_eq(c.nu_duct(Re, PR), want)


def test_nu_duct_turbulent() -> None:
    rel_eq(c.nu_duct(1e5, PR), _gnielinski(1e5))


def test_nu_duct_dittus_boelter_option() -> None:
    rel_eq(c.nu_duct(1e5, PR, option="dittus_boelter"), _dittus(1e5))
    Re = 3000.0
    nu_lam = 3.66
    want = nu_lam + (Re - 2300.0) / 1700.0 * (_dittus(4000.0) - nu_lam)
    rel_eq(c.nu_duct(Re, PR, option="dittus_boelter"), want)


def test_nu_duct_dittus_boelter_cooling_exponent() -> None:
    rel_eq(c.nu_duct(1e5, PR, option="dittus_boelter", heating=False), 0.023 * 1e5**0.8 * PR**0.3)


def _churchill(Re: float, rr: float) -> float:
    A = (2.457 * math.log(1 / ((7 / Re) ** 0.9 + 0.27 * rr))) ** 16
    B = (37530 / Re) ** 16
    return 8 * ((8 / Re) ** 12 + (A + B) ** (-1.5)) ** (1 / 12)


@pytest.mark.parametrize("Re", [500.0, 2e3, 1e4, 1e5, 1e6])
def test_friction_churchill_smooth_formula(Re: float) -> None:
    rel_eq(c.friction_churchill(Re), _churchill(Re, 0.0))


@pytest.mark.parametrize(("Re", "rr"), [(1e4, 1e-3), (1e5, 0.01), (5e5, 0.05)])
def test_friction_churchill_rough_formula(Re: float, rr: float) -> None:
    rel_eq(c.friction_churchill(Re, rr), _churchill(Re, rr))


def test_pressure_drop() -> None:
    f, L, Dh, K, rho, V = 0.02, 3.0, 0.05, 1.5, 998.0, 1.2
    want = (f * L / Dh + K) * rho * V**2 / 2
    rel_eq(c.pressure_drop(f, L, Dh, K, rho, V), want)


def test_reynolds_prandtl_rayleigh_hydraulic_nusselt() -> None:
    rho, V, L, mu = 1.2, 3.5, 0.4, 1.8e-5
    rel_eq(c.reynolds(rho, V, L, mu), rho * V * L / mu)

    cp, k = 1006.0, 0.026
    rel_eq(c.prandtl(mu, cp, k), mu * cp / k)

    beta, dT = 1 / 300.0, 25.0
    Pr = mu * cp / k
    want_ra = G * beta * abs(dT) * L**3 * Pr * rho**2 / mu**2
    rel_eq(c.rayleigh(beta, dT, L, Pr, rho, mu), want_ra)
    rel_eq(c.rayleigh(beta, -dT, L, Pr, rho, mu), want_ra)

    rel_eq(c.hydraulic_diameter(0.02, 0.6), 4 * 0.02 / 0.6)
    rel_eq(c.nusselt_to_h(120.0, 0.6, 0.25), 120.0 * 0.6 / 0.25)


# ------------------------------------------------------------------ array inputs


def test_array_inputs_match_scalar_calls() -> None:
    Re = np.array([1e3, 4e3, 1e5, 6e5])
    got = c.nu_plate_forced_avg(Re, PR)
    assert got.shape == Re.shape
    for i, r in enumerate(Re):
        rel_eq(float(got[i]), c.nu_plate_forced_avg(float(r), PR))

    Ra = np.array([1e5, 1e7, 1e7 + 1, 1e9])
    got_h = c.nu_hplate_up_natural(Ra)
    for i, r in enumerate(Ra):
        rel_eq(float(got_h[i]), c.nu_hplate_up_natural(float(r)))

    Re_d = np.array([1000.0, 2300.0, 3000.0, 4000.0, 1e5])
    got_d = c.nu_duct(Re_d, PR)
    for i, r in enumerate(Re_d):
        rel_eq(float(got_d[i]), c.nu_duct(float(r), PR))

    got_f = c.friction_churchill(Re_d, 0.001)
    for i, r in enumerate(Re_d):
        rel_eq(float(got_f[i]), c.friction_churchill(float(r), 0.001))


# ------------------------------------------------------------------ M11.39: non-circular, spheres


@pytest.mark.parametrize("Re", [6000.0, 2e4, 6e4])
def test_square_corner_crossflow(Re: float) -> None:
    rel_eq(c.nu_square_corner_crossflow(Re, PR), 0.304 * Re**0.59 * PR ** (1 / 3))


@pytest.mark.parametrize("Re", [5000.0, 2e4, 6e4])
def test_square_face_crossflow(Re: float) -> None:
    rel_eq(c.nu_square_face_crossflow(Re, PR), 0.158 * Re**0.66 * PR ** (1 / 3))


@pytest.mark.parametrize("Re", [5200.0, 20400.0, 20400.0 + 1, 5e4, 105000.0])
def test_hexagon_face_crossflow_both_branches(Re: float) -> None:
    if Re <= 20400:
        want = 0.164 * Re**0.638 * PR ** (1 / 3)
    else:
        want = 0.039 * Re**0.78 * PR ** (1 / 3)
    rel_eq(c.nu_hexagon_face_crossflow(Re, PR), want)


def test_hexagon_face_crossflow_array_mixes_branches() -> None:
    Re = np.array([1e4, 20400.0, 3e4])
    got = c.nu_hexagon_face_crossflow(Re, PR)
    for i, r in enumerate(Re):
        rel_eq(float(got[i]), c.nu_hexagon_face_crossflow(float(r), PR))


@pytest.mark.parametrize("Re", [4500.0, 3e4, 90700.0])
def test_hexagon_corner_crossflow(Re: float) -> None:
    rel_eq(c.nu_hexagon_corner_crossflow(Re, PR), 0.150 * Re**0.638 * PR ** (1 / 3))


@pytest.mark.parametrize("Re", [1e4, 3e4, 5e4])
def test_plate_front_crossflow(Re: float) -> None:
    rel_eq(c.nu_plate_front_crossflow(Re, PR), 0.667 * Re**0.500 * PR ** (1 / 3))


@pytest.mark.parametrize("Re", [7000.0, 4e4, 8e4])
def test_plate_back_crossflow(Re: float) -> None:
    rel_eq(c.nu_plate_back_crossflow(Re, PR), 0.191 * Re**0.667 * PR ** (1 / 3))


@pytest.mark.parametrize(("Re", "ratio"), [(3.5, 1.0), (1e3, 1.3), (7.6e4, 3.2)])
def test_sphere_forced(Re: float, ratio: float) -> None:
    want = 2 + (0.4 * Re**0.5 + 0.06 * Re ** (2 / 3)) * PR**0.4 * ratio**0.25
    rel_eq(c.nu_sphere_forced(Re, PR, ratio), want)


@pytest.mark.parametrize("Ra", [1e3, 1e6, 1e9])
def test_vplate_natural_laminar(Ra: float) -> None:
    want = 0.68 + 0.670 * Ra**0.25 / (1 + (0.492 / PR) ** (9 / 16)) ** (4 / 9)
    rel_eq(c.nu_vplate_natural_laminar(Ra, PR), want)


@pytest.mark.parametrize("Ra", [1e3, 1e7, 1e11])
def test_sphere_natural(Ra: float) -> None:
    want = 2 + 0.589 * Ra**0.25 / (1 + (0.469 / PR) ** (9 / 16)) ** (4 / 9)
    rel_eq(c.nu_sphere_natural(Ra, PR), want)


# ------------------------------------------------------------------ M11.40: vertical channels


@pytest.mark.parametrize("x", [1e-2, 1.0, 50.0, 1e3, 1e6])
def test_vchannel_natural(x: float) -> None:
    # x = Ra_S S/L, split into Ra_S and S/L
    want = (576.0 / x**2 + 2.87 / x**0.5) ** -0.5
    rel_eq(c.nu_vchannel_natural(x * 10.0, 0.1), want)
    rel_eq(c.nu_vchannel_natural(x, 1.0), want)


@pytest.mark.parametrize("x", [1e-2, 1.0, 50.0, 1e3, 1e6])
def test_vchannel_one_side_natural(x: float) -> None:
    want = (144.0 / x**2 + 2.87 / x**0.5) ** -0.5
    rel_eq(c.nu_vchannel_one_side_natural(x * 10.0, 0.1), want)
    rel_eq(c.nu_vchannel_one_side_natural(x, 1.0), want)


def test_vchannel_array_inputs() -> None:
    x = np.array([1.0, 1e3])
    got = c.nu_vchannel_natural(x, 1.0)
    for i, v in enumerate(x):
        rel_eq(float(got[i]), c.nu_vchannel_natural(float(v), 1.0))
