"""M11.65: the counterflow double-pipe oil cooler example (``examples/oil_cooler``).

The three checks of the example's page: constant film coefficients against the counterflow
effectiveness-NTU method, the duct-correlation run (regimes, equal duties, LMTD), and the
copper energy storage in the start-up (shortened here to keep the suite fast).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[2] / "examples" / "oil_cooler"
sys.path.insert(0, str(EXAMPLE))

import oil_cooler as oc  # noqa: E402


def test_geometry_of_the_two_ducts() -> None:
    assert oc.D_I == pytest.approx(0.010211, abs=1e-6)  # ASTM B88 Type K 3/8 in
    assert 4 * oc.water_area() / oc.water_perimeter() == pytest.approx(oc.D_S - oc.D_O)
    assert 4 * oc.oil_area() / oc.oil_perimeter() == pytest.approx(oc.D_I)
    assert oc.diameter_ratio() == pytest.approx(0.635)


def test_constant_coefficients_match_effectiveness_ntu() -> None:
    h = oc.correlation_h()
    prediction = oc.ntu_prediction(*h)
    assert prediction.NTU == pytest.approx(0.6878, abs=1e-3)
    model, built = oc.build("reference", n_axial=50, h_override=h)
    result = oc.compare(oc.solve(model, built), prediction)
    assert abs(result["dT_oil_out"]) < 0.01 and abs(result["dT_water_out"]) < 0.01  # K
    assert abs(result["dQ_oil_pct"]) < 0.05 and abs(result["dQ_water_pct"]) < 0.05
    assert result["Q_oil"] == pytest.approx(result["Q_water"], rel=1e-8)


def test_correlation_run_regimes_and_lmtd() -> None:
    model, built = oc.build("correlation", n_axial=50)
    results = oc.solve(model, built)
    rows = oc.streams(results)
    oil, water = rows[oc.OIL_STREAM], rows[oc.WATER_STREAM]
    assert oil.regime == "laminar" and water.regime == "laminar"
    assert water.Re < 2300  # the annulus diameter-ratio table is exercised
    assert -oil.heat == pytest.approx(water.heat, rel=1e-8)
    d1, d2 = oil.T_in - water.T_out, oil.T_out - water.T_in
    lmtd = (d1 - d2) / math.log(d1 / d2)
    ua = 1.0 / (
        1.0 / (oil.h_mean * math.pi * oc.D_I * oc.LENGTH)
        + math.log(oc.D_O / oc.D_I) / (2.0 * math.pi * 401.0 * oc.LENGTH)
        + 1.0 / (water.h_mean * math.pi * oc.D_O * oc.LENGTH)
    )
    assert water.heat / lmtd == pytest.approx(ua, rel=2e-3)


def test_startup_stores_the_duty_difference_in_the_copper(tmp_path, monkeypatch) -> None:
    model, built = oc.build("correlation")  # the start-up model uses the same mesh
    steady_path = tmp_path / "steady.tfea.h5"
    oc.solve(model, built, steady_path)
    monkeypatch.setattr(oc, "END_TIME", 20.0)
    start = oc.startup_study(steady_path)
    assert start["T_oil_in"][-1] == pytest.approx(oc.T_OIL_STEP)
    assert start["stored"] == pytest.approx(start["delta_u"], rel=5e-3)
    assert start["q_oil"][-1] > start["q_water"][-1] > start["q_water"][0]
