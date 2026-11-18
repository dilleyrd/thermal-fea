"""The pump-closure demonstration (``examples/pump_closure``) builds, solves and balances.

The example has no analytic answer, so this checks properties that hold whatever the
numbers: every boundary curve has exactly one condition, the energy balance closes (V-34),
the heat across the joint is consistent with what the films take in and out, the nut is a
dead end at steady state, and a better-conducting main seat carries more heat.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from thermalfea import api

FOLDER = Path(__file__).resolve().parents[2] / "examples" / "pump_closure"
BALANCE_STEADY = 1e-8  # V-34, linear steady


@pytest.fixture(scope="module")
def cm():
    if str(FOLDER) not in sys.path:
        sys.path.insert(0, str(FOLDER))
    import closure_model

    return closure_model


def steady(cm, seat_factor: float = 1.0) -> dict[str, float]:
    p = cm.load_params()
    model, built = cm.build_model(p, kind="steady", seat_factor=seat_factor, mesh_factor=2.0)
    mesh = api.mesh(model, built)
    results = api.solve(model, mesh, built=built)
    return cm.metrics(p, results, -1, cm.ContactHeats(model, built, mesh))


def test_every_boundary_curve_has_one_condition(cm) -> None:
    model, built = cm.build_model(kind="transient")
    sets = ("H", "M", "Cw", "J", "A", "X", "insulated", *cm.CONTACT_SIDES)
    used = [t for name in sets for t in model.selections[name].tags]
    assert len(used) == len(set(used)), "a curve is in two sets"
    # the curves in no set are the bonded interfaces: stud foot, two band partitions,
    # liner and shell tops, liner/shell
    assert len(built.entities(1)) - len(used) == 6
    assert model.axisymmetric


def test_band_mix_follows_sheet_4(cm) -> None:
    lay = cm.layout(cm.load_params())
    assert lay.stud_w == pytest.approx(6.486e-3, abs=1e-6)  # sheet 4: 6.486 mm
    assert lay.nut_w == pytest.approx(18.746e-3, abs=1e-6)  # sheet 4: 18.746 mm
    assert lay.band_fraction == pytest.approx(0.162, abs=5e-4)  # sheet 4: f = 0.162


def test_steady_hot_case_balances_and_partitions(cm) -> None:
    row = steady(cm)
    assert abs(row["relative_imbalance"]) < BALANCE_STEADY
    assert row["Q_film_H_W"] > 0.0
    for name in ("M", "Cw", "J", "A"):
        assert row[f"Q_film_{name}_W"] < 0.0
    # the nut only touches the flange: at steady state no heat crosses its bearing face
    assert abs(row["Q_nut_bearing_W"]) < 1e-6 * row["Q_film_H_W"]
    for name in ("main_seat", "seal_land", "barrier_foot", "stud_anchor"):
        assert row[f"Q_{name}_W"] > 0.0, name


def test_better_seat_carries_more_heat_and_unloads_the_studs(cm) -> None:
    poor, good = steady(cm, 0.1), steady(cm, 10.0)
    assert good["Q_main_seat_W"] > poor["Q_main_seat_W"]
    assert good["Q_stud_anchor_W"] < poor["Q_stud_anchor_W"]
