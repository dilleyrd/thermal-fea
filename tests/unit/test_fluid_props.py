"""M6.1 — fluid properties: interpolation, beta rule, clamping and warnings (Data §6)."""

from __future__ import annotations

import logging

import numpy as np
import pytest

from thermalfea.convection.fluid_props import FluidProps, fluid_props, reset_clamp_warning
from thermalfea.core.errors import ModelError
from thermalfea.materials import library
from thermalfea.materials.material import Fluid

LOGGER = "thermalfea.convection.fluid_props"
FIELDS = ("rho", "cp", "mu", "k")


def table_row(fluid: Fluid, i: int) -> dict[str, float]:
    return {name: getattr(fluid, name)[i] for name in FIELDS}


# ------------------------------------------------------------------ table rows and midpoints


def test_table_rows_are_returned_exactly_for_air() -> None:
    air = library.fluid("Air")
    for i, T in enumerate(air.T):
        p = air.props(T)
        assert isinstance(p, FluidProps)
        for name in FIELDS:
            assert float(getattr(p, name)) == table_row(air, i)[name]
        assert not bool(p.clamped)


def test_table_rows_are_returned_exactly_for_water() -> None:
    water = library.fluid("Water")
    for i, T in enumerate(water.T):
        p = fluid_props(water, T)
        for name in FIELDS:
            assert float(getattr(p, name)) == table_row(water, i)[name]
        assert float(p.beta) == water.beta[i]


def test_linear_interpolation_at_midpoint_air() -> None:
    air = library.fluid("Air")
    lo, hi = table_row(air, 1), table_row(air, 2)  # 300 K and 350 K
    p = air.props(325.0)
    for name in FIELDS:
        assert float(getattr(p, name)) == pytest.approx((lo[name] + hi[name]) / 2, rel=1e-12)


def test_linear_interpolation_at_midpoint_water() -> None:
    water = library.fluid("Water")
    lo, hi = table_row(water, 1), table_row(water, 2)  # 300 K and 320 K
    p = water.props(310.0)
    for name in FIELDS:
        assert float(getattr(p, name)) == pytest.approx((lo[name] + hi[name]) / 2, rel=1e-12)


# ---------------------------------------------------------------------------- beta rule


def test_ideal_gas_beta_is_one_over_T_inside_and_outside_the_table() -> None:
    air = library.fluid("Air")
    for T in (200.0, 250.0, 325.0, 1000.0, 1500.0):
        assert float(air.props(T).beta) == pytest.approx(1.0 / T, rel=1e-15)
    temps = np.array([[200.0, 1500.0], [300.0, 900.0]])
    assert np.allclose(fluid_props(air, temps).beta, 1.0 / temps, rtol=1e-15, atol=0.0)


def test_liquid_beta_comes_from_the_table() -> None:
    water = library.fluid("Water")
    expected = (water.beta[1] + water.beta[2]) / 2
    assert float(water.props(310.0).beta) == pytest.approx(expected, rel=1e-12)


# ------------------------------------------------------------------------- derived values


def test_derived_numbers_match_their_definitions() -> None:
    air = library.fluid("Air")
    p = air.props(np.array([300.0, 400.0, 600.0]))
    assert np.allclose(p.Pr, p.mu * p.cp / p.k, rtol=1e-14, atol=0.0)
    assert np.allclose(p.nu, p.mu / p.rho, rtol=1e-14, atol=0.0)
    assert np.allclose(p.alpha, p.k / (p.rho * p.cp), rtol=1e-14, atol=0.0)
    row = table_row(air, 1)  # 300 K
    assert float(p.Pr[0]) == pytest.approx(row["mu"] * row["cp"] / row["k"], rel=1e-12)
    assert float(p.Pr[0]) == pytest.approx(0.707, abs=0.002)


# ---------------------------------------------------------------------------------- shapes


def test_shapes_follow_the_input() -> None:
    air = library.fluid("Air")
    scalar = air.props(300.0)
    assert scalar.rho.shape == () and scalar.beta.shape == () and scalar.clamped.shape == ()
    vec = air.props(np.array([260.0, 330.0, 700.0]))
    for name in ("T", "rho", "cp", "mu", "k", "beta", "clamped", "Pr", "nu", "alpha"):
        assert getattr(vec, name).shape == (3,)
    grid = np.array([[260.0, 330.0], [700.0, 900.0]])
    g = air.props(grid)
    for name in ("T", "rho", "cp", "mu", "k", "beta", "clamped"):
        assert getattr(g, name).shape == (2, 2)
    # vectorised values agree with one-at-a-time evaluation
    for idx, T in np.ndenumerate(grid):
        assert g.rho[idx] == pytest.approx(float(air.props(float(T)).rho), rel=1e-15)
        assert g.mu[idx] == pytest.approx(float(air.props(float(T)).mu), rel=1e-15)


# --------------------------------------------------------------------------------- clamping


def test_clamping_holds_the_end_values_and_flags_only_outside() -> None:
    water = library.fluid("Water")
    low, high = water.T[0], water.T[-1]
    below = water.props(low - 20.0)
    above = water.props(high + 20.0)
    assert float(below.rho) == water.rho[0]
    assert float(above.mu) == water.mu[-1]
    assert float(below.beta) == water.beta[0]
    assert float(above.beta) == water.beta[-1]
    assert bool(below.clamped) and bool(above.clamped)

    at_ends = water.props(np.array([low, high]))
    assert not at_ends.clamped.any()
    assert float(at_ends.rho[0]) == water.rho[0]
    assert float(at_ends.rho[1]) == water.rho[-1]
    inside = water.props(310.0)
    assert not bool(inside.clamped)


# -------------------------------------------------------------------------------- warnings


def test_first_out_of_range_call_warns_once_and_names_the_fluid(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    air = library.fluid("Air")
    fluid_props(air, 200.0)
    records = [r for r in caplog.records if r.name == LOGGER]
    assert len(records) == 1
    assert records[0].levelno == logging.WARNING
    assert "Air" in records[0].getMessage()

    caplog.clear()
    fluid_props(air, 150.0)
    fluid_props(air, np.array([1200.0, 1300.0]))
    assert [r for r in caplog.records if r.name == LOGGER] == []

    caplog.clear()
    fresh = library.fluid("Air")  # a different Fluid object warns once more
    fluid_props(fresh, 200.0)
    assert len([r for r in caplog.records if r.name == LOGGER]) == 1

    caplog.clear()
    reset_clamp_warning(fresh)
    fluid_props(fresh, 200.0)
    assert len([r for r in caplog.records if r.name == LOGGER]) == 1


def test_in_range_calls_never_warn(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger=LOGGER)
    water = library.fluid("Water")
    fluid_props(water, np.linspace(280.0, 360.0, 9))
    water.props(280.0)
    water.props(360.0)
    assert [r for r in caplog.records if r.name == LOGGER] == []


# ---------------------------------------------------------------------------------- errors


@pytest.mark.parametrize("bad", [0.0, -5.0, float("nan"), float("inf")])
def test_non_absolute_temperatures_raise(bad: float) -> None:
    with pytest.raises(ModelError, match="absolute"):
        library.fluid("Air").props(bad)
    with pytest.raises(ModelError, match="absolute"):
        fluid_props(library.fluid("Water"), np.array([300.0, bad]))


# ------------------------------------------------------------------- Fluid equality and JSON


def test_warning_does_not_change_fluid_equality_or_json() -> None:
    air = library.fluid("Air")
    before = air.to_json()
    air.props(200.0)  # clamped, sets the warned state
    assert air._clamp_warned is True
    assert "_clamp_warned" not in air.to_json()
    assert air.to_json() == before
    assert Fluid.from_json(air.to_json()) == air
    assert library.fluid("Air") == air
