"""M1.8 — materials and libraries (Data §6).

The library values are compared with the tables in ``docs/data-model.md``: the test reads
both, so the JSON files cannot drift from the plan.
"""

from __future__ import annotations

import json
import re
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


SOLID_ROWS = doc_table("values that tests check")
FLUID_ROWS = doc_table("### Built-in fluids")

REMOVED = ("6061", "Ti-6Al-4V", "FR-4")
ORTHOTROPIC = (
    "Boron fiber epoxy (30% vol) composite",
    "Graphite, pyrolytic",
    "Graphite fiber epoxy (25% vol) composite",
    "Silicon dioxide, crystalline (quartz)",
)
FLUID_NAMES = (
    "Air", "Water", "Ammonia", "Carbon Dioxide", "Carbon Monoxide", "Helium", "Hydrogen",
    "Nitrogen", "Oxygen", "Water Vapor (Steam)", "Engine Oil (Unused)", "Ethylene Glycol",
    "Glycerin", "Refrigerant-134a", "Refrigerant-22", "Mercury",
)


def raw_solids() -> list[dict]:
    return json.loads((DATA / "solids.json").read_text(encoding="utf-8"))


def raw_fluids() -> list[dict]:
    return json.loads((DATA / "fluids.json").read_text(encoding="utf-8"))


def test_doc_tables_were_found() -> None:
    assert len(SOLID_ROWS) == 6
    assert len(FLUID_ROWS) == 6


# ----------------------------------------------------------------------------- solids


def test_every_builtin_solid_loads() -> None:
    solids = library.solids()
    raw = raw_solids()
    assert len(raw) == 117  # 113 isotropic + 4 orthotropic (Data section 6)
    assert list(solids) == [item["name"] for item in raw]
    assert len(set(solids)) == len(solids)
    for item in raw:
        m = solids[item["name"]]
        assert isinstance(m, Material)
        assert m.k == Constant(item["k"])
        assert m.rho == Constant(item["rho"])
        assert m.cp == Constant(item["cp"])
        assert m.phase_change is None
        assert not m.depends_on_T
        assert re.search(r"Table A\.[123]\b", item["source"]), item["name"]


def test_solid_spot_rows_match_the_doc_table_exactly() -> None:
    solids = library.solids()
    for name, k, rho, cp, source in SOLID_ROWS:
        m = solids[name]
        along = re.match(r"^([\d.]+) along, ([\d.]+) across$", k)
        if along:
            assert m.k == Constant(scaled(along.group(1)))
            assert m.k2 == Constant(scaled(along.group(2)))
            assert m.orthotropic
        else:
            assert m.k == Constant(scaled(k))
            assert m.k2 is None
            assert not m.orthotropic
        assert m.rho == Constant(scaled(rho))
        assert m.cp == Constant(scaled(cp))
        table = re.search(r"A\.(\d)", source).group(0)
        assert f"Table {table}" in next(i for i in raw_solids() if i["name"] == name)["source"]


def test_orthotropic_solids_have_k2() -> None:
    raw = raw_solids()
    assert sorted(i["name"] for i in raw if "k2" in i) == sorted(ORTHOTROPIC)
    for name in ORTHOTROPIC:
        m = library.solid(name)
        assert m.orthotropic
        assert m.k2() > 0.0
    for m in library.solids().values():
        assert m.orthotropic == (m.name in ORTHOTROPIC)


def test_removed_solids_are_gone() -> None:
    for name in library.solids():
        assert not any(bad in name for bad in REMOVED), name
    for bad in REMOVED:
        with pytest.raises(ModelError, match="no solid"):
            library.solid(f"Aluminium {bad}" if bad == "6061" else bad)


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


def test_every_builtin_fluid_loads_with_ascending_rows_and_a_source() -> None:
    fluids = library.fluids()
    assert list(fluids) == list(FLUID_NAMES)
    for item in raw_fluids():
        fluid = fluids[item["name"]]
        assert isinstance(fluid, Fluid)
        assert fluid.T == item["T"]
        assert all(b > a for a, b in zip(fluid.T, fluid.T[1:], strict=False)), fluid.name
        assert len(fluid.T) == len(fluid.rho) == len(fluid.cp) == len(fluid.mu) == len(fluid.k)
        src = item["source"]
        assert any(t in src for t in ("Table A.4", "Table A.5", "NIST")), fluid.name
        if fluid.name == "Water":
            assert "NIST" in src and fluid.ideal_gas is False and fluid.beta is not None
        elif "Table A.4" in src:
            assert fluid.ideal_gas is True and fluid.beta is None, fluid.name
        else:
            assert "Table A.5" in src and fluid.ideal_gas is False and fluid.beta is not None


def test_fluid_row_counts_and_ranges_match_the_doc_table() -> None:
    fluids = library.fluids()
    checked = 0
    for name, _source, rows, _notes in FLUID_ROWS:
        match = re.match(r"^(\d+) \((\d+)–(\d+) K", rows)
        if match is None or "," in name:
            continue
        count, lo, hi = (int(g) for g in match.groups())
        fluid = fluids[name]
        assert (len(fluid.T), fluid.T[0], fluid.T[-1]) == (count, lo, hi), name
        checked += 1
    assert checked == 3  # Air, Water, Water Vapor (Steam)
    assert list(fluids["Water"].T) == [280.0 + 5.0 * i for i in range(19)]


def test_fluid_values_are_si() -> None:
    air = library.fluid("air")
    i = air.T.index(300.0)
    assert air.mu[i] == pytest.approx(184.6e-7, rel=1e-15)
    assert air.k[i] == pytest.approx(26.3e-3, rel=1e-15)
    assert air.rho[i] == 1.1614
    water = library.fluid("WATER")
    j = water.T.index(300.0)
    assert 990.0 < water.rho[j] < 1000.0
    assert 4100.0 < water.cp[j] < 4250.0
    assert 8.0e-4 < water.mu[j] < 9.0e-4
    assert 0.59 < water.k[j] < 0.62
    assert 2.0e-4 < water.beta[j] < 3.5e-4
    with pytest.raises(ModelError, match="no fluid"):
        library.fluid("Unobtainium")


def test_no_removed_name_remains_in_src_examples_or_guide() -> None:
    suffixes = {".py", ".md", ".json", ".tfea", ".txt", ".csv", ".toml", ".yaml", ".yml"}
    found = []
    for folder in ("src", "examples", "guide"):
        for path in (ROOT / folder).rglob("*"):
            if not path.is_file() or path.suffix not in suffixes:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for bad in ("6061-T6", "Ti-6Al-4V", "FR-4"):
                if bad in text:
                    found.append((path.relative_to(ROOT).as_posix(), bad))
    assert found == []


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
