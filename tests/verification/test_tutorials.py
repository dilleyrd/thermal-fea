"""M11.4: every number of the three tutorial pages, and the files the pages refer to.

``guide/tutorials/t4-plate.md``, ``fin-quench.md`` and ``cold-plate.md`` quote results of
``examples/tutorial_t4_plate.py``, ``tutorial_fin_quench.py`` and ``tutorial_cold_plate.py``.
Each quoted number is asserted here at the precision the page prints it (a page quotes a
number to the digits shown, so the check is "rounds to the printed value"), the energy
balance of every case is checked, no warning may be logged during a solve, the saved models
are the models the scripts build, and every picture and model file a page links exists.
"""

from __future__ import annotations

import logging
import re
import struct
from pathlib import Path

import numpy as np
import pytest
from cases import load

from thermalfea import api
from thermalfea.model.serialize import to_json

GUIDE = Path(__file__).resolve().parents[2] / "guide" / "tutorials"
PAGES = ("t4-plate", "fin-quench", "cold-plate")
BALANCE_STEADY = 1e-8  # V-34, linear steady
BALANCE_TRANSIENT = 1e-3  # V-34


def approx(value: float, rel: float = 5e-4, abs: float | None = None):
    """``pytest.approx`` with a default relative tolerance of 5e-4 (the printed digits)."""
    return pytest.approx(value, rel=rel, abs=abs)


# ---------------------------------------------------------------------------- tutorial 1


@pytest.fixture(scope="module")
def t4() -> dict:
    return load("tutorial_t4_plate").run()


def test_t4_the_model_is_v10(t4: dict) -> None:
    v10 = load("v10_nafems_t4")
    assert (v10.W, v10.HGT, v10.K_T4, v10.H, v10.YP) == (0.6, 1.0, 52.0, 750.0, 0.2)
    assert (v10.TARGET_C, v10.TOL_C) == (18.3, 0.15)
    assert t4["target_degC"] == 18.3 and t4["tol_degC"] == 0.15


def test_t4_convergence_table(t4: dict) -> None:
    # size, nodes, elements, T [degC] (2 decimals), heat entering at the base [W/m] (0 decimals)
    printed = [
        (0.1, 93, 152, 17.79, 11080),
        (0.05, 328, 590, 18.09, 10597),
        (0.025, 1210, 2290, 18.21, 10396),
        (0.0125, 4629, 9000, 18.24, 10324),
    ]
    assert [row["size"] for row in t4["table"]] == [p[0] for p in printed]
    for row, (size, nodes, elements, temperature, heat) in zip(t4["table"], printed, strict=True):
        assert (row["nodes"], row["elements"]) == (nodes, elements), size
        assert row["T_degC"] == pytest.approx(temperature, abs=5e-3), size
        assert row["heat_base"] == pytest.approx(heat, abs=0.5), size
        assert row["imbalance"] < BALANCE_STEADY, size
    temperatures = [row["T_degC"] for row in t4["table"]]
    assert temperatures == sorted(temperatures)  # linear triangles approach from below
    assert all(a < t4["target_degC"] for a in temperatures)
    # quadratic triangles: size, nodes, T [degC] (2 decimals); the limit is about 18.25
    printed6 = [
        (0.1, 337, 18.34), (0.05, 1245, 18.26), (0.025, 4709, 18.25), (0.0125, 18257, 18.25)
    ]
    assert [row["size"] for row in t4["table6"]] == [p[0] for p in printed6]
    for row, (size, nodes, temperature) in zip(t4["table6"], printed6, strict=True):
        assert row["nodes"] == nodes, size
        assert row["T_degC"] == pytest.approx(temperature, abs=5e-3), size
        assert row["imbalance"] < BALANCE_STEADY, size
    assert abs(t4["table6"][-1]["T_degC"] - t4["table6"][-2]["T_degC"]) < 1.5e-3
    assert t4["T6_nodes"] == 4709 and t4["T6_degC"] == pytest.approx(18.25, abs=5e-3)


def test_t4_answer_of_the_page(t4: dict) -> None:
    assert t4["T_K"] == pytest.approx(291.356, abs=5e-4)
    assert t4["T_degC"] == pytest.approx(18.206, abs=5e-4)
    assert t4["error_degC"] == pytest.approx(0.094, abs=5e-4) and t4["error_degC"] < t4["tol_degC"]
    assert t4["heat_base"] == pytest.approx(10395.9, abs=0.05)
    assert t4["heat_cooling"] == pytest.approx(-10395.9, abs=0.05)
    assert t4["imbalance"] < BALANCE_STEADY


def test_t4_saved_model_is_the_model_of_the_page(tmp_path: Path) -> None:
    example = load("tutorial_t4_plate")
    saved = api.load(GUIDE / "models" / "t4-plate.tfea")
    assert saved == example.gui_named_model()
    assert [bc.name for bc in saved.bcs] == ["Fixed Temperature 1", "Convection 1", "Adiabatic 1"]
    built = api.build(saved)
    results = api.solve(saved, api.mesh(saved, built), built=built, path=tmp_path / "t4.h5")
    nodes = results.mesh.nodes[:, :2]
    node = int(np.argmin(np.linalg.norm(nodes - [0.6, 0.2], axis=1)))
    assert float(results.temperature()[node]) - 273.15 == pytest.approx(18.206, abs=5e-4)


# ---------------------------------------------------------------------------- tutorial 2


@pytest.fixture(scope="module")
def fin_logged() -> tuple[dict, list[logging.LogRecord]]:
    """The fin run with every warning of the ``thermalfea`` loggers collected."""
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING:
                records.append(record)

    handler = Collect()
    logger = logging.getLogger("thermalfea")
    logger.addHandler(handler)
    try:
        result = load("tutorial_fin_quench").run()
    finally:
        logger.removeHandler(handler)
    return result, records


def test_fin_inputs_are_library_materials_and_in_range() -> None:
    from thermalfea.materials import library

    fin = load("tutorial_fin_quench")
    assert fin.MATERIAL in library.solids() and fin.FLUID in library.fluids()
    air = library.fluid("Air")
    for film in (0.5 * (fin.T_INIT + fin.T_AMBIENT), fin.T_AMBIENT):  # hottest and coolest film
        assert not bool(air.props(film).clamped)
    assert (fin.THICKNESS, fin.HEIGHT, fin.DEPTH) == (0.01, 0.10, 0.10)
    assert (fin.T_INIT, fin.T_AMBIENT, fin.EMISSIVITY) == (500.0, 300.0, 0.8)
    assert (fin.END_TIME, fin.LATER_END_TIME, fin.INITIAL_DT) == (3600.0, 7200.0, 1.0)


def test_fin_runs_without_a_warning(fin_logged) -> None:
    _result, records = fin_logged
    assert [r.getMessage() for r in records] == []


def test_fin_the_suggested_first_step_is_not_warned_about(caplog) -> None:
    """M11.10 (Q26.4(e), Q27.3): the suggested step fails the per-element test on this mesh
    (86 % of the elements) but is not warned about; the same step typed by the user is."""
    import common

    fin = load("tutorial_fin_quench")
    model, built = fin.build()
    model.solution.initial_dt = None
    model.solution.end_time = 10.0
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        common.solve(model, built)
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING] == []
    model.solution.initial_dt = 0.0367
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        common.solve(model, built)
    messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(messages) == 1 and "oscillate" in messages[0]
    assert messages[0].startswith("the time step of 0.0367 s is below h^2 rho c / (6 k) in 86 %")
    assert "lumped capacitance" in messages[0] and "finer mesh" in messages[0]


def test_fin_hand_calculation(fin_logged) -> None:
    ref, _ = fin_logged
    hand = ref["hand"]
    assert hand["h_conv"] == pytest.approx(8.58, abs=5e-3)
    assert hand["Nu"] == pytest.approx(25.4, abs=0.05)
    assert hand["Ra"] == pytest.approx(4.85e6, rel=1e-3)
    assert hand["Pr"] == pytest.approx(0.690, abs=5e-4)
    assert hand["T_film"] == 400.0 and hand["warnings"] == []
    assert hand["h_rad"] == pytest.approx(12.34, abs=5e-3)
    assert hand["h_total"] == pytest.approx(20.91, abs=5e-3)
    assert (hand["k"], hand["rho"], hand["cp"]) == (177.0, 2770.0, 875.0)
    assert hand["area"] == approx(0.02) and hand["volume"] == approx(1e-4)
    assert hand["biot"] == pytest.approx(5.9e-4, abs=5e-6)
    assert hand["tau"] == pytest.approx(579.4, abs=0.5)
    assert hand["q_initial"] == pytest.approx(83.7, abs=0.05)
    # the program's heat loss at the first step agrees with the hand value to 0.3 %
    first = ref["split_first"]
    assert first["conv"] + first["rad"] == pytest.approx(83.4, abs=0.05)
    assert abs((first["conv"] + first["rad"]) / hand["q_initial"] - 1.0) < 5e-3
    # h falls as the plate cools, so the constant-h exponential cools too fast
    assert ref["T_lumped_at_tau"] == pytest.approx(373.6, abs=0.05)
    assert ref["T_at_tau"] == pytest.approx(388.3, abs=0.05)
    assert ref["T_at_tau"] > ref["T_lumped_at_tau"] + 10.0


def test_fin_results_of_the_page(fin_logged) -> None:
    ref, _ = fin_logged
    assert ref["t_first"] == 1.0
    assert ref["n_steps_3600"] == 218 and ref["n_steps_7200"] == 248
    assert ref["time_end"] == 7200.0
    assert ref["T_end"] == pytest.approx(306.17, abs=5e-3)
    assert ref["T_later"] == pytest.approx(300.68, abs=5e-3)
    # nearly isothermal: the Biot number is tiny
    assert ref["spread_first"] == pytest.approx(0.062, abs=5e-4)
    assert ref["spread_end"] < 1e-3
    first, end, later = ref["split_first"], ref["split_end"], ref["split_later"]
    assert (first["conv"], first["rad"]) == (approx(34.2, 2e-3), approx(49.2, 2e-3))
    assert first["rad_share"] == pytest.approx(0.590, abs=5e-4)
    assert (end["conv"], end["rad"]) == (approx(0.460, 2e-3), approx(0.623, 2e-3))
    assert end["rad_share"] == pytest.approx(0.575, abs=5e-4)
    assert (later["conv"], later["rad"]) == (approx(0.0291, 5e-3), approx(0.0664, 5e-3))
    assert later["rad_share"] == pytest.approx(0.695, abs=5e-4)
    # the share dips to about one half and rises again
    assert ref["share_min"] == pytest.approx(0.496, abs=5e-4)
    assert 1000.0 < ref["t_share_min"] < 1200.0 and ref["t_share_min"] == approx(1081.0, 2e-3)


def test_fin_energy_balance_every_step(fin_logged) -> None:
    ref, _ = fin_logged
    assert ref["worst_imbalance_3600"] < 1e-5 and ref["worst_imbalance"] < 1e-5
    assert ref["worst_imbalance"] == pytest.approx(7.1e-7, rel=0.02)
    assert ref["worst_imbalance"] < BALANCE_TRANSIENT
    results = ref["results"]
    balance = results.energy_balance()
    assert np.isnan(balance["relative_imbalance"][0])  # the initial state has no step
    # the heat leaving through the two conditions is the energy stored: stored = -(conv + rad)
    assert np.all(balance["heat_in"][1:] == 0.0)
    assert np.allclose(balance["net"][1:], -balance["heat_out"][1:], rtol=1e-12)
    assert np.allclose(balance["stored_rate"][1:], balance["net"][1:], rtol=1e-4, atol=1e-6)
    stored = balance["stored_rate"][1:]
    names = ("Correlation Convection 1", "Radiation to Ambient 1")
    leaving = sum(results.heat_flow(name)[1:] for name in names)
    assert np.allclose(stored, leaving, rtol=1e-4, atol=1e-6)


def test_fin_continuing_the_run_equals_one_run(fin_logged) -> None:
    """Continue transient run reaches the end time the second solve asked for."""
    import common

    ref, _ = fin_logged
    fin = load("tutorial_fin_quench")
    model, built = fin.build()
    model.solution.end_time = fin.LATER_END_TIME
    one_run = common.solve(model, built)
    # not the same steps, so not identical: the two agree to the accuracy of the time stepping
    one = float(one_run.results.temperature()[ref["node"]])
    assert one == pytest.approx(ref["T_later"], abs=0.05)
    assert one_run.worst_imbalance < BALANCE_TRANSIENT


def test_fin_saved_model_is_the_model_of_the_page(fin_logged, tmp_path: Path) -> None:
    ref, _ = fin_logged
    saved = api.load(GUIDE / "models" / "fin-quench.tfea")
    assert saved == ref["model"]
    assert to_json(saved) == to_json(ref["model"])
    assert saved.solution.end_time == 3600.0 and saved.solution.initial_dt == 1.0
    built = api.build(saved)
    mesh = api.mesh(saved, built)
    assert mesh.n_nodes == ref["mesh"].n_nodes
    results = api.solve(saved, mesh, built=built, path=tmp_path / "fin.h5")
    assert float(results.temperature()[ref["node"]]) == pytest.approx(ref["T_end"], rel=1e-9)


# ---------------------------------------------------------------------------- tutorial 3


@pytest.fixture(scope="module")
def cold_logged() -> tuple[dict, list[logging.LogRecord]]:
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            if record.levelno >= logging.WARNING:
                records.append(record)

    handler = Collect()
    logger = logging.getLogger("thermalfea")
    logger.addHandler(handler)
    try:
        result = load("tutorial_cold_plate").run()
    finally:
        logger.removeHandler(handler)
    return result, records


def test_cold_plate_inputs_are_library_entries_and_in_range() -> None:
    from thermalfea.materials import library

    cold = load("tutorial_cold_plate")
    assert cold.MATERIAL in library.solids() and cold.FLUID in library.fluids()
    assert (cold.LENGTH, cold.THICKNESS, cold.DEPTH, cold.GAP) == (0.20, 0.01, 0.05, 0.002)
    assert (cold.FLUX, cold.T_INLET, cold.MASS_FLOW, cold.WHAT_IF) == (
        20000.0, 300.0, 0.02, (0.005, 0.1)
    )
    assert cold.flow_area() == pytest.approx(1.0e-4) and cold.wetted_perimeter() == approx(0.104)
    assert cold.NU_LAMINAR == 4.86  # Theory 8.1: parallel plates, one side insulated
    water = library.fluid("Water")
    assert water.to_json()["T"][0] <= cold.T_INLET and water.to_json()["T"][-1] >= 340.0


def test_cold_plate_runs_without_a_warning(cold_logged) -> None:
    _result, records = cold_logged
    assert [r.getMessage() for r in records] == []


def test_cold_plate_hand_calculation(cold_logged) -> None:
    ref, _ = cold_logged
    hand = ref["hand"]
    assert hand["D_h"] == pytest.approx(3.846e-3, abs=5e-7)
    assert hand["velocity"] == pytest.approx(0.2007, abs=5e-5)
    assert (hand["k"], hand["mu"], hand["rho"], hand["cp"]) == (
        0.609499, 8.53743e-4, 996.556, 4180.64
    )
    assert hand["Re"] == pytest.approx(901.0, abs=0.5)
    assert hand["h"] == pytest.approx(770.2, abs=0.05)
    assert hand["heat"] == 200.0
    assert ref["dT_hand"] == pytest.approx(2.392, abs=5e-4)
    assert ref["dT"] == pytest.approx(ref["dT_hand"], rel=1e-8)  # c_p at the inlet temperature
    assert hand["superheat"] == pytest.approx(25.97, abs=5e-3)
    assert hand["dp"] == pytest.approx(74.1, abs=0.05)  # f = 64/Re, L/D_h, rho V^2/2
    assert abs(hand["dp"] / ref["dp"] - 1.0) < 0.03
    # the program uses the water properties along the path: within 3 % of the inlet values
    # (2 % with the old 20 K water table; 3 % since the NIST table, owner 2026-11-23)
    assert abs(ref["Re"] / hand["Re"] - 1.0) < 0.03 and abs(ref["h_mean"] / hand["h"] - 1) < 3e-3


def test_cold_plate_results_of_the_page(cold_logged) -> None:
    ref, _ = cold_logged
    assert ref["regime"] == "laminar" and ref["n_cells"] == 40 and ref["iterations"] == 3
    assert ref["case"].mesh.n_nodes == 126 and ref["case"].mesh.n_elements == 166
    assert ref["mass_flow"] == 0.02 and ref["T_in"] == 300.0
    assert ref["Re"] == pytest.approx(923.0, abs=0.5)
    assert ref["h_mean"] == pytest.approx(772.4, abs=0.05)
    assert ref["dp"] == pytest.approx(72.4, abs=0.05)
    assert ref["T_out"] == pytest.approx(302.39, abs=5e-3)
    assert ref["heat"] == pytest.approx(200.0, abs=1e-6)
    assert ref["T_max"] == pytest.approx(328.82, abs=5e-3)
    assert ref["T_min"] == pytest.approx(326.49, abs=5e-3)
    assert ref["superheat_mid"] == pytest.approx(25.89, abs=5e-3)
    assert abs(ref["superheat_mid"] / ref["hand"]["superheat"] - 1.0) < 5e-3


def test_cold_plate_energy_balance(cold_logged) -> None:
    ref, _ = cold_logged
    assert ref["heat_in"] == pytest.approx(200.0, rel=1e-9)  # flux x length x depth
    assert ref["heat_stream"] == pytest.approx(-ref["heat_in"], rel=1e-9)
    # V-29: boundary heat flows + m c_p (T_in - T_out) = 0
    cp = ref["hand"]["cp"]
    total = ref["heat_in"] + ref["heat_stream"]
    assert abs(total) / ref["heat_in"] < 1e-8
    assert abs(ref["mass_flow"] * cp * (ref["T_in"] - ref["T_out"]) + ref["heat_in"]) < 1e-6
    for row in (ref, *ref["what_if"]):
        assert row["imbalance"] < 1e-10


def test_cold_plate_what_if_table(cold_logged) -> None:
    ref, _ = cold_logged
    low, high = ref["what_if"]
    # mass flow, Re, regime, h, dp, T_out, T_max
    assert (low["mass_flow"], low["regime"]) == (0.005, "laminar")
    assert low["Re"] == pytest.approx(249.0, abs=0.5)
    assert low["h_mean"] == pytest.approx(779.2, abs=0.05)
    assert low["dp"] == pytest.approx(16.8, abs=0.05)
    assert low["T_out"] == pytest.approx(309.57, abs=5e-3)
    assert low["T_max"] == pytest.approx(334.06, abs=5e-3)
    assert (high["mass_flow"], high["regime"]) == (0.1, "turbulent")
    assert high["Re"] == pytest.approx(4527.0, abs=0.5)
    assert high["h_mean"] == pytest.approx(5398.0, abs=0.5)
    assert high["dp"] == pytest.approx(1019.0, abs=0.5)
    assert high["T_out"] == pytest.approx(300.48, abs=5e-3)
    assert high["T_max"] == pytest.approx(305.26, abs=5e-3)
    assert high["heat"] == pytest.approx(200.0, abs=1e-6) == pytest.approx(low["heat"], abs=1e-6)
    # wall above the water at mid-length: about 26 K while laminar, 3.7 K when turbulent
    assert low["superheat_mid"] == pytest.approx(25.6, abs=0.05)
    assert ref["superheat_mid"] == pytest.approx(25.89, abs=0.005)
    assert high["superheat_mid"] == pytest.approx(3.7, abs=0.05)
    assert ref["T_max"] - low["T_max"] < 0 < ref["T_max"] - high["T_max"]
    assert ref["T_max"] - high["T_max"] == pytest.approx(23.6, abs=0.05)
    assert high["h_mean"] > 6.5 * ref["h_mean"] and high["dp"] > 13.0 * ref["dp"]


def test_cold_plate_saved_model_is_the_model_of_the_page(cold_logged, tmp_path: Path) -> None:
    ref, _ = cold_logged
    saved = api.load(GUIDE / "models" / "cold-plate.tfea")
    assert saved == ref["model"]
    assert [s.name for s in saved.streams] == ["Stream 1"]
    assert [bc.name for bc in saved.bcs] == ["Heat Flux 1", "Adiabatic 1"]
    built = api.build(saved)
    mesh = api.mesh(saved, built)
    results = api.solve(saved, mesh, built=built, path=tmp_path / "cold.h5")
    assert float(results.temperature().max()) == pytest.approx(ref["T_max"], rel=1e-9)


# ------------------------------------------------------------------------- pages and files


def _png_width(path: Path) -> int:
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">I", data[16:20])[0]


def _references(page: str) -> tuple[set[str], set[str]]:
    text = (GUIDE / f"{page}.md").read_text(encoding="utf-8")
    images = set(re.findall(r"\]\((img/[^)\s]+)\)", text))
    models = set(re.findall(r"(models/[\w.-]+\.tfea)", text))
    return images, models


def test_pages_exist_and_their_images_and_models_exist() -> None:
    all_images: set[str] = set()
    for page in PAGES:
        assert (GUIDE / f"{page}.md").is_file(), page
        images, models = _references(page)
        assert images, f"{page} shows no picture"
        assert models == {f"models/{page}.tfea"}, page
        for name in (*images, *models):
            assert (GUIDE / name).is_file(), (page, name)
        all_images |= images
    for name in all_images:
        assert 890 <= _png_width(GUIDE / name) <= 910, name  # about 900 px wide
        assert (GUIDE / name).stat().st_size < 400_000, name  # reasonably small
    folder = {f"img/{p.name}" for p in (GUIDE / "img").glob("*.png")}
    assert folder == all_images, "a picture is unused or a link is dead"


def test_make_figures_writes_the_pictures_the_pages_link(tmp_path: Path, fin_logged,
                                                         cold_logged) -> None:
    expected: set[str] = set()
    for page in PAGES:
        expected |= {Path(name).name for name in _references(page)[0]}
    written = {
        p.name
        for p in (
            *load("tutorial_t4_plate").make_figures(tmp_path),
            *load("tutorial_fin_quench").make_figures(tmp_path, fin_logged[0]),
            *load("tutorial_cold_plate").make_figures(tmp_path, cold_logged[0]),
        )
    }
    assert written == expected
    for name in written:
        assert (tmp_path / name).stat().st_size > 5_000


def test_the_scripts_save_the_models_the_pages_link(tmp_path: Path, fin_logged,
                                                    cold_logged) -> None:
    saved = [
        load("tutorial_t4_plate").save_model(tmp_path),
        load("tutorial_fin_quench").save_model(fin_logged[0], tmp_path),
        load("tutorial_cold_plate").save_model(cold_logged[0], tmp_path),
    ]
    for path in saved:
        assert path.read_text(encoding="utf-8") == (GUIDE / "models" / path.name).read_text(
            encoding="utf-8"
        ), path.name
