"""M1.8 — materials and libraries (Data §6).

The library values are compared with the tables in ``docs/data-model.md``: the test reads
both, so the JSON files cannot drift from the plan.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Constant, Expression, Table
from thermalfea.materials import library
from thermalfea.materials.material import Fluid, Material, PhaseChange

ROOT = Path(__file__).resolve().parents[2]
DOC = (ROOT / "docs" / "data-model.md").read_text(encoding="utf-8")
DATA = ROOT / "src" / "thermalfea" / "materials" / "data"


def doc_table(marker: str) -> list[list[str]]:
    """Rows (without header) of the first markdown table after ``marker``."""
    rows: list[list[str]] = []
    started = False
    for line in DOC[DOC.index(marker) :].splitlines():
        if line.startswith("|"):
            started = True
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif started:
            break
    return rows[2:]


def scaled(cell: str, scale: str = "1") -> float:
    return float(Decimal(cell) * Decimal(scale))


SOLID_ROWS = doc_table("### Built-in solids")
AIR_ROWS = doc_table("Air at 1 atm")
WATER_ROWS = doc_table("Water, saturated liquid")


def test_doc_tables_were_found() -> None:
    assert len(SOLID_ROWS) == 10
    assert len(AIR_ROWS) == 9
    assert len(WATER_ROWS) == 5


# ----------------------------------------------------------------------------- solids


def test_every_solid_loads_and_equals_the_doc_table() -> None:
    solids = library.solids()
    assert list(solids) == [row[0] for row in SOLID_ROWS]
    for name, k, rho, cp in SOLID_ROWS:
        m = solids[name]
        assert isinstance(m, Material)
        assert m.name == name
        assert m.k == Constant(scaled(k))
        assert m.rho == Constant(scaled(rho))
        assert m.cp == Constant(scaled(cp))
        assert m.k2 is None
        assert m.phase_change is None
        assert not m.orthotropic
        assert not m.depends_on_T
        assert m.k(T=300.0) == float(k)


def test_solids_json_file_has_exactly_the_doc_numbers() -> None:
    raw = json.loads((DATA / "solids.json").read_text(encoding="utf-8"))
    expected = [
        {"name": n, "k": scaled(k), "rho": scaled(r), "cp": scaled(c)} for n, k, r, c in SOLID_ROWS
    ]
    assert raw == expected


def test_solid_lookup() -> None:
    copper = library.solid("Copper (pure)")
    assert copper.k() == 401.0
    assert library.solid("copper (PURE)").name == "Copper (pure)"
    with pytest.raises(ModelError, match="no solid"):
        library.solid("Unobtainium")
    # the library hands out copies
    copper.k = Constant(1.0)
    assert library.solid("Copper (pure)").k() == 401.0
    library.solids()["Silicon"].name = "changed"
    assert "Silicon" in library.solids()


# ----------------------------------------------------------------------------- fluids


def test_every_fluid_loads_and_equals_the_doc_table() -> None:
    fluids = library.fluids()
    assert sorted(fluids) == ["Air", "Water"]

    air = fluids["Air"]
    assert isinstance(air, Fluid)
    assert air.ideal_gas is True
    assert air.beta is None
    assert air.T == [scaled(r[0]) for r in AIR_ROWS]
    assert air.rho == [scaled(r[1]) for r in AIR_ROWS]
    assert air.cp == [scaled(r[2]) for r in AIR_ROWS]
    assert air.mu == [scaled(r[3], "1e-7") for r in AIR_ROWS]
    assert air.k == [scaled(r[4], "1e-3") for r in AIR_ROWS]

    water = fluids["Water"]
    assert water.ideal_gas is False
    assert water.T == [scaled(r[0]) for r in WATER_ROWS]
    assert water.rho == [scaled(r[1]) for r in WATER_ROWS]
    assert water.cp == [scaled(r[2]) for r in WATER_ROWS]
    assert water.mu == [scaled(r[3], "1e-6") for r in WATER_ROWS]
    assert water.k == [scaled(r[4]) for r in WATER_ROWS]
    assert water.beta == [scaled(r[5], "1e-6") for r in WATER_ROWS]


def test_fluid_values_are_si() -> None:
    air = library.fluid("air")
    i = air.T.index(300.0)
    assert air.mu[i] == pytest.approx(184.6e-7, rel=1e-15)
    assert air.k[i] == pytest.approx(26.3e-3, rel=1e-15)
    assert air.rho[i] == 1.1614
    water = library.fluid("WATER")
    j = water.T.index(300.0)
    assert water.mu[j] == pytest.approx(855e-6, rel=1e-15)
    assert water.beta[j] == pytest.approx(276.1e-6, rel=1e-15)
    with pytest.raises(ModelError, match="no fluid"):
        library.fluid("Mercury")


# ------------------------------------------------------------------ classes and JSON


def test_material_accepts_numbers_and_functions() -> None:
    m = Material("m", 10, 2000.0, Table([300.0, 400.0], [900.0, 950.0], "T"))
    assert m.k == Constant(10.0)
    assert m.depends_on_T
    ortho = Material(name="o", k=5.0, rho=1.0, cp=1.0, k2=Expression("1 + T/100"))
    assert ortho.orthotropic
    assert ortho.k2(T=300.0) == 4.0
    with pytest.raises(ModelError):
        Material("", 1.0, 1.0, 1.0)
    with pytest.raises(ModelError):
        Material("bad", "x", 1.0, 1.0)  # type: ignore[arg-type]


def test_material_json_round_trip() -> None:
    m = Material(
        "alloy",
        Table([300.0, 400.0], [10.0, 12.0], "T", extrapolate="linear"),
        2700.0,
        Expression("900 + 0.1*T"),
        k2=3.0,
        phase_change=PhaseChange(T_sol=800.0, T_liq=850.0, latent_heat=4.0e5),
    )
    assert Material.from_json(m.to_json()) == m
    assert Material.from_json(json.loads(json.dumps(m.to_json()))) == m
    simple = Material("s", 1.0, 2.0, 3.0)
    assert set(simple.to_json()) == {"name", "k", "rho", "cp"}
    assert Material.from_json({"name": "n", "k": 1, "rho": 2, "cp": 3}) == Material("n", 1, 2, 3)
    with pytest.raises(ModelError):
        Material.from_json({"name": "n", "k": 1})


def test_phase_change_validation() -> None:
    with pytest.raises(ModelError):
        PhaseChange(T_sol=900.0, T_liq=850.0, latent_heat=1.0)
    with pytest.raises(ModelError):
        PhaseChange(T_sol=800.0, T_liq=850.0, latent_heat=0.0)


def test_fluid_validation_and_round_trip() -> None:
    good = dict(name="f", ideal_gas=True, T=[300.0, 400.0], rho=[1.0, 0.8], cp=[1000.0, 1010.0],
                mu=[1e-5, 2e-5], k=[0.02, 0.03])
    fluid = Fluid(**good)
    assert Fluid.from_json(fluid.to_json()) == fluid
    for change in (
        {"T": [400.0, 300.0]},
        {"T": [300.0, 300.0]},
        {"rho": [1.0]},
        {"mu": [1e-5, -1.0]},
        {"k": [0.02, float("nan")]},
        {"ideal_gas": False},  # liquid without beta
        {"name": ""},
        {"T": [], "rho": [], "cp": [], "mu": [], "k": []},
    ):
        with pytest.raises(ModelError):
            Fluid(**{**good, **change})
    liquid = Fluid(**{**good, "ideal_gas": False, "beta": [1e-4, -2e-4]})  # beta may be negative
    assert Fluid.from_json(liquid.to_json()) == liquid
    with pytest.raises(ModelError):
        Fluid.from_json({"name": "x"})


# ------------------------------------------------------------------------ user library


def test_user_library_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    path = library.user_library_path()
    assert path == tmp_path / "ThermalFEA" / "materials.json"
    assert library.load_user_library() == ({}, {})
    solids = {"mine": Material("mine", 1.0, 2.0, 3.0, k2=0.5)}
    fluids = {"Air": library.fluid("Air")}
    assert library.save_user_library(solids, fluids) == path
    assert library.load_user_library() == (solids, fluids)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ModelError, match="user material library"):
        library.load_user_library()
