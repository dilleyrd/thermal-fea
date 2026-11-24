"""M11.47: the Energy balance window has a table and draws no imbalance line."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtGui import QGuiApplication

from thermalfea import api
from thermalfea.core.units import UnitSettings, from_si
from thermalfea.gui.charts import ENERGY_POWER_COLUMNS, NO_VALUE, ChartWindow
from thermalfea.model import bcs
from thermalfea.model.settings import SolutionSettings
from thermalfea.post.plots import history_data
from thermalfea.post.results import Results

HEADS = ["time", "heat_in", "heat_out", "net", "stored_rate", "imbalance", "relative_imbalance"]


def solve_plate(folder: Path, kind: str) -> Path:
    model = api.new_model(name=f"plate-{kind}")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5)
    model.mesh_settings.global_size = 0.1
    built = api.build(model)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs += [
        bcs.FixedTemperature("hot", "west", T=400.0),
        bcs.Convection("cool", "east", h=100.0, T_inf=300.0),
    ]
    if kind == "transient":
        model.solution = SolutionSettings(
            kind="transient", end_time=60.0, auto_timestep=False, initial_dt=10.0,
            output="every_n", output_every=1,
        )  # fmt: skip
    mesh = api.mesh(model, built)
    path = folder / f"{kind}.h5"
    api.solve(model, mesh, built=built, path=path)
    return path


@pytest.fixture(scope="module")
def transient(tmp_path_factory) -> Results:
    return Results(solve_plate(tmp_path_factory.mktemp("energy-t"), "transient"))


@pytest.fixture(scope="module")
def steady(tmp_path_factory) -> Results:
    return Results(solve_plate(tmp_path_factory.mktemp("energy-s"), "steady"))


@pytest.fixture
def chart(qtbot):
    window = ChartWindow()
    qtbot.addWidget(window)
    window.show()
    return window


def cell_values(chart: ChartWindow) -> np.ndarray:
    """The table's numbers; a cell with no stored value (NO_VALUE) must be a stored NaN."""
    t = chart.table

    def number(text: str) -> float:
        return float("nan") if text == NO_VALUE else float(text)

    return np.array(
        [[number(t.item(r, c).text()) for c in range(t.columnCount())] for r in range(t.rowCount())]
    )


def test_a_cell_without_a_stored_value_shows_a_dash(chart, transient) -> None:
    chart.show_energy_balance(transient)
    texts = [chart.table.item(r, c).text()
             for r in range(chart.table.rowCount()) for c in range(chart.table.columnCount())]
    assert "nan" not in [s.lower() for s in texts]
    stored = np.asarray(transient.energy_balance()["relative_imbalance"], dtype=float)
    assert np.isnan(stored).any()  # the initial row of a transient has no balance
    assert NO_VALUE in texts


def test_transient_chart_has_no_imbalance_line(chart, transient) -> None:
    chart.show_energy_balance(transient)
    columns = transient.energy_balance()
    got = [np.asarray(line.get_ydata(), float) for line in chart.axes.get_lines()]
    assert len(got) == len(ENERGY_POWER_COLUMNS) == 4  # imbalance is not drawn
    for y, name in zip(got, ENERGY_POWER_COLUMNS, strict=True):
        np.testing.assert_allclose(y, columns[name])
    assert chart.canvas.isVisible() and chart.table.isVisible()
    assert chart.save_button.isVisible()
    assert chart.windowTitle() == "Energy balance"


def check_table(chart: ChartWindow, results: Results, units: UnitSettings, tag: str) -> None:
    columns = results.energy_balance()
    t = chart.table
    heads = [t.horizontalHeaderItem(c).text() for c in range(t.columnCount())]
    assert [h.split(" [")[0] for h in heads] == HEADS
    assert heads[0] == f"time [{tag[0]}]" and heads[1] == f"heat_in [{tag[1]}]"
    assert heads[-1] == "relative_imbalance [-]"
    assert t.rowCount() == len(results.times) > 1
    got = cell_values(chart)
    np.testing.assert_allclose(got[:, 0], from_si(np.asarray(results.times), "time", units),
                               rtol=1e-5, atol=1e-30)
    for j, name in enumerate(HEADS[1:-1], start=1):
        ref = from_si(np.asarray(columns[name], float), "power", units)
        atol = 1e-9 * np.nanmax(np.abs(ref))
        np.testing.assert_allclose(got[:, j], ref, rtol=1e-5, atol=atol, equal_nan=True)
    np.testing.assert_allclose(got[:, -1], columns["relative_imbalance"], rtol=1e-5, atol=1e-30,
                               equal_nan=True)
    flags = t.item(0, 0).flags()
    assert not flags & flags.__class__.ItemIsEditable


def test_table_in_si(chart, transient) -> None:
    chart.show_energy_balance(transient)
    check_table(chart, transient, transient.display_units, ("s", "W"))


def test_table_in_other_display_units(chart, transient) -> None:
    units = UnitSettings(power="kW", time="min")
    transient.display_units = units
    try:
        chart.show_energy_balance(transient)
        check_table(chart, transient, units, ("min", "kW"))
    finally:
        transient.display_units = None


def test_steady_window_is_table_only(chart, steady) -> None:
    chart.show_energy_balance(steady)
    assert chart.table.isVisible() and not chart.canvas.isVisible()
    assert chart.table.rowCount() == 1
    assert chart.windowTitle() == "Energy balance (steady state)"
    assert not chart.save_button.isVisible()
    assert chart.csv_button.isVisible()
    check_row = cell_values(chart)[0]
    assert check_row[0] == 0.0


def test_export_csv_unchanged(chart, transient, tmp_path) -> None:
    chart.show_energy_balance(transient)
    out = chart.export_csv(tmp_path / "e.csv")
    rows = out.read_text(encoding="utf-8").splitlines()
    assert rows[0].split(",")[1:] == ["heat_in", "heat_out", "net", "stored_rate", "imbalance"]
    assert len(rows) == 1 + len(transient.times)
    imbalance = transient.energy_balance()["imbalance"]
    last = float(rows[-1].split(",")[-1])  # step 0 may store NaN
    assert last == pytest.approx(imbalance[-1], abs=1e-12)


def test_copy_is_tab_separated_with_headers(chart, transient) -> None:
    chart.show_energy_balance(transient)
    chart.table.selectRow(1)
    chart.copy_table()
    text = QGuiApplication.clipboard().text()
    head, row = text.strip("\n").split("\n")
    assert head.split("\t") == [
        chart.table.horizontalHeaderItem(c).text() for c in range(chart.table.columnCount())
    ]
    assert row.split("\t") == [
        chart.table.item(1, c).text() for c in range(chart.table.columnCount())
    ]


def test_reusing_the_window_hides_the_table(chart, transient, steady) -> None:
    chart.show_energy_balance(steady)
    assert not chart.canvas.isVisible()
    chart.show_nodal_history(transient, [0, 1])
    assert chart.canvas.isVisible() and not chart.table.isVisible()
    assert chart.save_button.isVisible() and chart.kind == "history"
    expected = history_data(transient, nodes=[0, 1])
    assert len(chart.axes.get_lines()) == len(expected.series)
    chart.show_energy_balance(transient)
    assert chart.table.isVisible()
    chart.show_nodal_history(transient, [0])
    assert not chart.table.isVisible()
