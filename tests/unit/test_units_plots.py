"""M10.4: unit systems in forms and plots (Qt-free): labels, scaled data, defaults unchanged."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from handmade import make_problem
from matplotlib.figure import Figure

from thermalfea.core import forms
from thermalfea.core.forms import FieldSpec, from_display, to_display
from thermalfea.core.units import PRESETS, QUANTITIES, UnitSettings
from thermalfea.model import (
    bc_forms,
    flow_forms,
    geometry_forms,
    material_forms,
    mesh_forms,
    solution_forms,
)
from thermalfea.model.bcs import Convection, FixedTemperature
from thermalfea.model.settings import SolutionSettings
from thermalfea.physics.capacitance import CapacitanceTerm
from thermalfea.post import flow as post_flow
from thermalfea.post import plots
from thermalfea.post.results import Results
from thermalfea.solver.run import run_transient

BTU, FOOT, INCH, HOUR = 1055.05585262, 0.3048, 0.0254, 3600.0
US = PRESETS["US customary"]
MM = PRESETS["SI (mm)"]
SIDES = ("bottom", "right", "top", "left")


@pytest.fixture(scope="module")
def results(tmp_path_factory: pytest.TempPathFactory) -> Results:
    """A short transient with convection on every side, so flux and heat flow are non-zero."""
    problem = make_problem("Q4", size=(0.02, 0.01), cells=(4, 2), k=400.0, bcs=tuple(
        Convection(f"conv-{s}", s, h=20.0, T_inf=300.0) for s in SIDES))
    term = CapacitanceTerm()
    term.setup(problem)
    problem.terms.append(term)
    problem.settings = SolutionSettings(
        kind="transient", initial_dt=60.0, end_time=600.0, auto_timestep=False
    )
    path = tmp_path_factory.mktemp("units") / "r.h5"
    run_transient(problem, path, T0=400.0)
    return Results(path)


@pytest.fixture
def fresh(results: Results):
    """The shared results with their display units restored afterwards."""
    yield results
    results.display_units = None


def hot_results(path: Path) -> Results:
    problem = make_problem("Q4", size=(0.1, 0.01), cells=(10, 1), bcs=(
        FixedTemperature("hot", "left", T=400.0), FixedTemperature("cold", "right", T=300.0)))
    from thermalfea.solver.results_writer import ResultsWriter
    from thermalfea.solver.steady import solve_steady

    T = solve_steady(problem)
    with ResultsWriter(path, problem) as writer:
        writer.append_step(0.0, T)
    return Results(path)


# ------------------------------------------------------------------------------ forms


def _all_forms() -> list[forms.FormSpec]:
    out = list(bc_forms.BC_FORMS.values())
    out += list(geometry_forms.FORMS.values())
    out += [flow_forms.STREAM_FORM, material_forms.MATERIAL_FORM, material_forms.REGION_FORM,
            mesh_forms.MESH_FORM, solution_forms.SOLUTION_FORM,
            solution_forms.INITIAL_CONDITION_FORM]
    return out


def test_no_unit_is_written_in_a_label_of_a_field_with_a_quantity() -> None:
    for spec in _all_forms():
        for f in spec.fields:
            if f.quantity is not None:
                assert "[" not in f.label and "(rad)" not in f.label, (spec.title, f.name)


def test_dimensional_fields_got_their_quantities() -> None:
    assert bc_forms.BC_FORMS["correlation_convection"].field("velocity").quantity == "velocity"
    assert flow_forms.STREAM_FORM.field("flow_area").quantity == "area"
    assert flow_forms.STREAM_FORM.field("wetted_perimeter").quantity == "length"
    assert flow_forms.STREAM_FORM.field("path").quantity == "length"
    assert material_forms.REGION_FORM.field("material_angle").quantity == "angle"
    assert mesh_forms.MESH_FORM.field("curve_sizes").quantity == "length"
    assert mesh_forms.MESH_FORM.field("point_sizes").quantity == "length"
    assert mesh_forms.MESH_FORM.field("curve_divisions").quantity is None
    assert solution_forms.SOLUTION_FORM.field("output_times").quantity == "time"
    assert solution_forms.INITIAL_CONDITION_FORM.field("per_region").quantity == "temperature"
    assert geometry_forms.FORMS[geometry_forms.g.Polygon].field("vertices").quantity == "length"


def test_to_and_from_display_of_numbers_lists_and_mappings() -> None:
    length = FieldSpec("x", "x", "float", quantity="length")
    assert to_display(length, 0.025, MM) == pytest.approx(25.0)
    assert from_display(length, 25.0, MM) == pytest.approx(0.025)
    pairs = FieldSpec("p", "p", "xy_list", quantity="length")
    assert to_display(pairs, [(0.0254, 0.0508)], US) == [pytest.approx((1.0, 2.0))]
    assert from_display(pairs, [(1.0, 2.0)], US) == [pytest.approx((0.0254, 0.0508))]
    numbers = FieldSpec("t", "t", "float_list", quantity="time")
    assert to_display(numbers, [60.0, 7200.0], UnitSettings(time="h")) == pytest.approx(
        [60 / 3600, 2.0])
    mapping = FieldSpec("d", "d", "dict", quantity="temperature")
    shown = to_display(mapping, {"a": 373.15}, US)
    assert shown["a"] == pytest.approx(212.0)
    assert from_display(mapping, shown, US)["a"] == pytest.approx(373.15)
    plain = FieldSpec("n", "n", "dict")  # no quantity: untouched
    assert to_display(plain, {"a": 3}, US) == {"a": 3}
    assert to_display(length, None, US) is None


# ----------------------------------------------------------------------- plot labels


def test_default_settings_give_the_labels_and_numbers_of_si(fresh: Results) -> None:
    data = plots.contour_data(fresh, -1, "T")
    assert data.label == "Temperature [K]" and data.unit == "K"
    assert data.title == "Temperature, t = 600 s"
    assert plots.contour_data(fresh, -1, "qx").label == "Heat flux qx [W/m^2]"
    assert plots.contour_data(fresh, -1, "gradmag").label == (
        "Temperature gradient magnitude [K/m]")
    vec = plots.vector_data(fresh, -1)
    assert vec.label == "Heat flux [W/m²]" and vec.title == "Heat flux, t = 600 s"
    hist = plots.history_data(fresh, nodes=[0])
    assert hist.xlabel == "Time [s]" and hist.ylabel == "Temperature [K]"
    np.testing.assert_array_equal(hist.times, fresh.times)
    assert plots.heat_flow_history_data(fresh).ylabel == "Heat flow into the body [W]"
    path = plots.path_data(fresh, -1, [(0.0, 0.005), (0.02, 0.005)], 5, "T")
    assert path.xlabel == "Distance along path [m]"
    assert path.s[-1] == pytest.approx(0.02)
    fig = plots.contour(fresh, -1, "T")
    ax = fig.axes[0]
    assert ax.get_xlabel() == "x [m]" and ax.get_ylabel() == "y [m]"


def test_us_units_scale_values_and_labels(fresh: Results) -> None:
    si = {f: plots.contour_data(fresh, -1, f) for f in plots.FIELDS}
    fresh.display_units = US
    for name in plots.FIELDS:
        data = plots.contour_data(fresh, -1, name)
        got = np.concatenate([p.values for p in data.parts])
        want = np.concatenate([p.values for p in si[name].parts])
        if name == "T":
            np.testing.assert_allclose(got, (want - 273.15) * 1.8 + 32.0)
            assert data.label == "Temperature [°F]"
        elif name.startswith("q"):
            np.testing.assert_allclose(got, want * HOUR * FOOT**2 / BTU)
            assert data.unit == "BTU/(h ft^2)"
        else:
            np.testing.assert_allclose(got, want * 1.8 * INCH)
            assert data.unit == "°F/in"
        # the geometry of the parts stays in metres
        np.testing.assert_array_equal(data.parts[0].xy, si[name].parts[0].xy)
    assert plots.contour_data(fresh, -1, "T").title == "Temperature, t = 600 s"


def test_time_unit_in_titles_and_history(fresh: Results) -> None:
    fresh.display_units = UnitSettings(time="min", power="kW")
    assert plots.contour_data(fresh, -1, "T").title == "Temperature, t = 10 min"
    hist = plots.history_data(fresh, nodes=[0, 1])
    assert hist.xlabel == "Time [min]"
    np.testing.assert_allclose(hist.times, fresh.times / 60.0)
    stat = plots.history_stat_data(fresh, "corner", "mean") if "corner" in (
        fresh.mesh.node_sets) else None
    assert stat is None or stat.xlabel == "Time [min]"
    flows = plots.heat_flow_history_data(fresh)
    assert flows.ylabel == "Heat flow into the body [kW]" and flows.xlabel == "Time [min]"
    first = fresh.heat_flow_names[0]
    np.testing.assert_allclose(flows.series[first], np.asarray(fresh.heat_flow(first)) / 1e3)
    fig = plots.heat_flow_history(fresh)
    assert fig.axes[0].get_xlabel() == "Time [min]"


def test_history_labels_give_the_coordinates_in_the_length_unit(fresh: Results) -> None:
    fresh.display_units = MM
    data = plots.history_data(fresh, nodes=[2])
    x, y = fresh.mesh.nodes[2, :2] * 1000.0
    assert list(data.series) == [f"node 2 ({x:g}, {y:g})"]


def test_vectors_in_btu_units(fresh: Results) -> None:
    si = plots.vector_data(fresh, -1)
    fresh.display_units = US
    data = plots.vector_data(fresh, -1)
    assert data.label == "Heat flux [BTU/(h ft^2)]"
    np.testing.assert_allclose(data.q, si.q * HOUR * FOOT**2 / BTU)
    np.testing.assert_allclose(data.magnitude, si.magnitude * HOUR * FOOT**2 / BTU)
    np.testing.assert_array_equal(data.xy, si.xy)  # positions stay in metres
    fig = plots.vectors(fresh, -1)
    assert fig.axes[1].get_ylabel() == "Heat flux [BTU/(h ft^2)]" or (
        "BTU/(h ft^2)" in (fig.axes[1].get_xlabel(), fig.axes[1].get_ylabel()))


def test_path_distance_in_the_length_unit(fresh: Results) -> None:
    fresh.display_units = MM
    data = plots.path_data(fresh, -1, [(0.0, 0.005), (0.02, 0.005)], 5, "T")
    assert data.xlabel == "Distance along path [mm]"
    assert data.s[-1] == pytest.approx(20.0)
    assert data.title.endswith("t = 600 s")
    fig = plots.path(fresh, [(0.0, 0.005), (0.02, 0.005)], -1, "T", 5)
    assert fig.axes[0].get_xlabel() == "Distance along path [mm]"


def test_contour_axes_follow_the_length_unit(fresh: Results) -> None:
    fresh.display_units = MM
    fig = plots.contour(fresh, -1, "T")
    ax = fig.axes[0]
    assert ax.get_xlabel() == "x [mm]" and ax.get_ylabel() == "y [mm]"
    fig.canvas.draw()
    ticks, labels = ax.get_xticks(), [t.get_text() for t in ax.get_xticklabels()]
    assert len(labels) == len(ticks) > 2
    for tick, text in zip(ticks, labels, strict=True):  # labels are millimetres, ticks metres
        assert float(text.replace("−", "-")) == pytest.approx(tick * 1000.0, abs=1e-9)


def test_length_axes_return_to_default() -> None:
    fig = Figure()
    ax = fig.add_subplot(1, 1, 1)
    ax.plot([0, 0.01], [0, 0.01])
    plots.length_axes(ax, UnitSettings())  # nothing to do
    plots.length_axes(ax, MM)
    fig.canvas.draw()
    assert ax.get_xticklabels()[0].get_text() != ""
    plots.length_axes(ax, UnitSettings())
    fig.canvas.draw()
    assert type(ax.xaxis.get_major_formatter()).__name__ == "ScalarFormatter"


def test_display_value_and_inverse(fresh: Results) -> None:
    fresh.display_units = US
    value, unit = plots.display_value(fresh, "T", 373.15)
    assert value == pytest.approx(212.0) and unit == "°F"
    value, unit = plots.display_value(fresh, "gradx", 10.0)
    assert value == pytest.approx(10.0 * 1.8 * INCH) and unit == "°F/in"
    for name in plots.FIELDS:
        shown, _ = plots.field_display_values(name, np.array([310.0, 12.5]), US)
        np.testing.assert_allclose(plots.field_si_values(name, shown, US), [310.0, 12.5])
    with pytest.raises(Exception, match="unknown contour field"):
        plots.field_display_values("nope", 1.0, US)


# ------------------------------------------------------------------------ flow tables


def test_stream_summary_table_in_display_units() -> None:
    row = post_flow.StreamSummary(
        name="coolant", mode="in_plane", mass_flow=0.05, Re=500.0, regime="laminar",
        h_mean=800.0, dp=6894.757293168361, T_in=300.0, T_out=305.0, heat=2000.0,
    )
    default = post_flow.format_stream_summary([row])
    assert "m_dot [kg/s]" in default and "h [W/(m^2 K)]" in default and "dp [Pa]" in default
    assert default == post_flow.format_stream_summary([row], UnitSettings())
    us = post_flow.format_stream_summary([row], US)
    assert "m_dot [lbm/s]" in us and "dp [psi]" in us and "T_in [°F]" in us
    assert "heat [BTU/h]" in us and "h [BTU/(h ft^2 °F)]" in us
    numbers = post_flow.summary_numbers(row, US)
    assert numbers[3] == pytest.approx(1.0, rel=1e-6)  # one psi
    assert numbers[4] == pytest.approx(80.33)
    assert post_flow.summary_numbers(row)[0] == 0.05
    assert len(QUANTITIES) >= len(post_flow.SUMMARY_QUANTITIES)
