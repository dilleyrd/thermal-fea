"""M8.12: stream editor, network table, flow results window and HTC calculator.

Everything runs offscreen and non-modally. The viewport is a fake ``SceneView`` that records
``set_selection_mode`` and emits ``point_picked`` on request. The flow results come from a
small solved copper plate with one in-plane stream (as in ``tests/unit/test_coupling.py``).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal

from thermalfea import api
from thermalfea.convection.correlation_info import CORRELATION_INFO
from thermalfea.convection.correlations import CORRELATIONS
from thermalfea.core.forms import form_for
from thermalfea.core.units import UnitSettings
from thermalfea.gui.chart_tools import attach_charts
from thermalfea.gui.dialogs.htc_calculator import HtcCalculator
from thermalfea.gui.dialogs.new_stream import NewStreamDialog
from thermalfea.gui.document import Document
from thermalfea.gui.flow_results import FlowResultsWindow, attach_flow
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.network import NETWORK_ADDRESS, NetworkPanel, parse_number
from thermalfea.gui.property_panels.stream import StreamPanel
from thermalfea.gui.results_tools import attach_results
from thermalfea.materials import library
from thermalfea.model import bcs
from thermalfea.model.bcs import FlowNetwork, Stream
from thermalfea.model.model import Model
from thermalfea.model.validate import validate_model
from thermalfea.post.flow import stream_summary, wall_temperature
from thermalfea.post.results import Results

LENGTH, T_IN = 1.0, 300.0


class FakeView(QObject):
    """A SceneView stand-in: records selection modes, emits clicks on request."""

    selection_changed = Signal(int, list)
    point_picked = Signal(float, float, float)

    def __init__(self) -> None:
        super().__init__()
        self.modes: list[str] = []

    def widget(self) -> Any:  # pragma: no cover - never shown
        raise NotImplementedError

    def set_field(self, spec: Any) -> None: ...
    def set_geometry(self, built: Any) -> None: ...
    def set_mesh(self, mesh: Any, color_by: Any = None) -> None: ...
    def set_symbols(self, symbols: Any) -> None: ...
    def set_overlay(self, layer: str, items: Any) -> None: ...
    def highlight(self, dim: int, tags: Any) -> None: ...
    def fit(self) -> None: ...

    def set_selection_mode(self, mode: Any) -> None:
        self.modes.append(mode)

    def save_image(self, path: str, dpi: int = 200) -> None:  # pragma: no cover
        Path(path).write_bytes(b"image")


def coolant(**changes: Any) -> Stream:
    base: dict[str, Any] = dict(
        name="coolant", fluid="Water", mode="in_plane", walls=["bottom"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=T_IN, mass_flow=0.25,
        path=[(0.0, 0.0), (LENGTH, 0.0)],
    )  # fmt: skip
    return Stream(**{**base, **changes})


def pick(combo: Any, text: str) -> None:
    """Choose a combo entry by its text (``setCurrentText`` only works when editable)."""
    combo.setCurrentIndex(combo.findText(text))


@pytest.fixture
def view() -> FakeView:
    return FakeView()


@pytest.fixture
def stream_model() -> Model:
    model = api.new_model(name="flow")
    model.streams.append(coolant())
    return model


@pytest.fixture
def shell(window, view, stream_model):
    document = Document(stream_model)
    tree, controller = attach_tree(window, document, view)
    out = SimpleNamespace(
        window=window, document=document, view=view, tree=tree, controller=controller,
        undo=document.undo_stack,
    )  # fmt: skip
    return out


# ------------------------------------------------------------------ stream panel
def test_stream_panel_is_the_registered_panel(shell) -> None:
    shell.controller.show_object(("streams", 0))
    assert isinstance(shell.controller.panel, StreamPanel)


def test_editing_flow_area_is_one_undo_step(shell) -> None:
    panel = StreamPanel(form_for(Stream), shell.document, ("streams", 0), shell.view)
    before = shell.undo.count()
    editor = panel.editors["flow_area"]
    editor.setText("2e-4")
    editor.editingFinished.emit()
    assert shell.document.model.streams[0].flow_area == pytest.approx(2e-4)
    assert shell.undo.count() == before + 1
    shell.undo.undo()
    assert shell.document.model.streams[0].flow_area == pytest.approx(1e-4)
    assert panel.editors["flow_area"].text() == "0.0001"


def test_fluid_combo_lists_the_library_fluids(shell) -> None:
    panel = StreamPanel(form_for(Stream), shell.document, ("streams", 0), shell.view)
    combo = panel.editors["fluid"]
    items = [combo.itemText(i) for i in range(combo.count())]
    assert items == library.fluid_names()


def test_unset_mass_flow_shows_none_and_stays_none(shell) -> None:
    """Defect Q26.4(b): a network-fed stream has no mass flow and must not show 'Constant 0'."""
    shell.document.edit("Unset mass flow", lambda m: setattr(m.streams[0], "mass_flow", None))
    panel = StreamPanel(form_for(Stream), shell.document, ("streams", 0), shell.view)
    editor = panel.editors["mass_flow"]
    assert editor.mode == "none"
    assert editor.function() is None
    # applying the panel without the user typing anything leaves the value unset
    before = shell.undo.count()
    editor.commit()
    assert shell.document.model.streams[0].mass_flow is None
    assert shell.undo.count() == before


def test_unset_mass_flow_is_shown_unset_after_a_fresh_load(shell) -> None:
    """The first load of the editor (no prior function) must show the unset state too."""
    shell.document.edit("Unset mass flow", lambda m: setattr(m.streams[0], "mass_flow", None))
    panel = StreamPanel(form_for(Stream), shell.document, ("streams", 0), shell.view)
    panel.refresh()
    assert panel.editors["mass_flow"].mode == "none"
    assert shell.document.model.streams[0].mass_flow is None


def test_path_picking_appends_one_point_per_click(shell) -> None:
    panel = StreamPanel(form_for(Stream), shell.document, ("streams", 0), shell.view)
    panel.clear_path()
    assert shell.document.model.streams[0].path == []
    before = shell.undo.count()
    panel.pick_button.setChecked(True)
    assert shell.view.modes[-1] == "none"
    shell.view.point_picked.emit(0.1, 0.0, 0.0)
    shell.view.point_picked.emit(0.2, 0.05, 0.0)
    assert shell.document.model.streams[0].path == [(0.1, 0.0), (0.2, 0.05)]
    assert shell.undo.count() == before + 2


def test_clicks_are_ignored_while_the_toggle_is_off(shell) -> None:
    panel = StreamPanel(form_for(Stream), shell.document, ("streams", 0), shell.view)
    before = shell.undo.count()
    shell.view.point_picked.emit(0.5, 0.0, 0.0)
    assert shell.document.model.streams[0].path == [(0.0, 0.0), (LENGTH, 0.0)]
    assert shell.undo.count() == before
    panel.pick_button.setChecked(True)
    panel.pick_button.setChecked(False)
    shell.view.point_picked.emit(0.5, 0.0, 0.0)
    assert len(shell.document.model.streams[0].path) == 2  # noqa: PLR2004


def test_clear_path_empties_the_path(shell) -> None:
    panel = StreamPanel(form_for(Stream), shell.document, ("streams", 0), shell.view)
    panel.clear_button.click()
    assert shell.document.model.streams[0].path == []
    assert panel.path_label.text() == "0 path points"


# ------------------------------------------------------------------ add stream
def test_add_stream_copies_the_first_stream(shell) -> None:
    before = shell.undo.count()
    address = shell.tree.add_stream()
    streams = shell.document.model.streams
    assert address == ("streams", 1) and len(streams) == 2
    new = streams[1]
    assert new.name == "Stream 1" and new.mode == "in_plane" and new.walls == []
    assert new.path == streams[0].path and new.fluid == "Water"
    assert shell.undo.count() == before + 1
    shell.undo.undo()
    assert len(shell.document.model.streams) == 1


def test_add_stream_without_streams_asks_in_a_dialog(shell) -> None:
    shell.document.edit("Clear streams", lambda m: m.streams.clear())
    assert shell.tree.add_stream() is None
    dialog = shell.tree.stream_dialog
    assert isinstance(dialog, NewStreamDialog) and not dialog.isHidden()
    dialog.submit()  # nothing typed: refused, dialog stays
    assert dialog.message_label.text() != ""
    assert shell.document.model.streams == []
    pick(dialog.fluid_box, "Water")
    dialog.flow_area_edit.setText("1e-4")
    dialog.wetted_edit.setText("0.04")
    pick(dialog.cross_box, "circular")
    dialog.inlet_edit.setText("300")
    assert dialog.submit()
    streams = shell.document.model.streams
    assert len(streams) == 1
    assert streams[0].fluid == "Water" and streams[0].flow_area == pytest.approx(1e-4)
    assert streams[0].T_inlet.value == pytest.approx(300.0)
    shell.undo.undo()
    assert shell.document.model.streams == []


# ------------------------------------------------------------------ network panel
@pytest.fixture
def network_panel(shell) -> NetworkPanel:
    return NetworkPanel(shell.document)


def test_network_address_shows_the_panel_without_a_network(shell) -> None:
    shell.controller.show_object(NETWORK_ADDRESS)
    assert shell.controller.current_address == NETWORK_ADDRESS
    assert shell.controller.panel is None  # a table panel, not a FormPanel


def test_create_network_then_add_nodes_and_a_branch(shell, network_panel) -> None:
    panel = network_panel
    assert panel.editor_widget.isHidden() and not panel.empty_widget.isHidden()
    panel.create_button.click()
    assert isinstance(shell.document.model.network, FlowNetwork)
    assert panel.editor_widget.isHidden() is False
    panel.add_node()
    panel.add_node()
    assert [n.id for n in shell.document.model.network.nodes] == ["N1", "N2"]
    assert panel.add_branch()
    branch = shell.document.model.network.branches[0]
    assert (branch.id, branch.node_from, branch.node_to) == ("B1", "N1", "N2")
    assert panel.branch_table.rowCount() == 1


def test_node_pressure_and_inflow_cells(shell, network_panel) -> None:
    panel = network_panel
    panel.create_network()
    panel.add_node()
    panel.add_node()
    before = shell.undo.count()
    panel.node_table.item(0, 1).setText("1000")
    assert shell.document.model.network.nodes[0].pressure == 1000.0
    assert shell.undo.count() == before + 1
    panel.node_table.item(0, 2).setText("0.5")
    panel.node_table.item(0, 2).setText("")
    assert shell.document.model.network.nodes[0].inflow is None


def test_invalid_number_is_rejected(shell, network_panel) -> None:
    panel = network_panel
    panel.create_network()
    panel.add_node()
    panel.node_table.item(0, 1).setText("1000")
    before = shell.undo.count()
    panel.node_table.item(0, 1).setText("abc")
    assert shell.document.model.network.nodes[0].pressure == 1000.0
    assert shell.undo.count() == before
    assert "not a number" in panel.status_label.text()


def test_choosing_the_branch_stream(shell, network_panel) -> None:
    panel = network_panel
    panel.create_network()
    panel.add_node()
    panel.add_node()
    panel.add_branch()
    combo = panel.branch_table.cellWidget(0, 6)
    assert [combo.itemText(i) for i in range(combo.count())] == ["(none)", "coolant"]
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert shell.document.model.network.branches[0].stream == "coolant"
    combo.setCurrentIndex(0)
    combo.activated.emit(0)
    assert shell.document.model.network.branches[0].stream is None


def test_removing_a_used_node_is_refused(shell, network_panel) -> None:
    panel = network_panel
    panel.create_network()
    panel.add_node()
    panel.add_node()
    panel.add_branch()
    panel.node_table.setCurrentCell(0, 0)
    assert panel.remove_node() is False
    assert len(shell.document.model.network.nodes) == 2  # noqa: PLR2004
    assert "used by branch" in panel.status_label.text()


def test_undo_and_redo_keep_the_tables_in_sync(shell, network_panel) -> None:
    panel = network_panel
    panel.create_network()
    panel.add_node()
    panel.add_node()
    panel.add_branch()
    assert panel.branch_table.rowCount() == 1
    shell.undo.undo()
    assert panel.branch_table.rowCount() == 0
    shell.undo.redo()
    assert panel.branch_table.rowCount() == 1
    for _ in range(4):  # branch, two nodes, the network itself
        shell.undo.undo()
    assert shell.document.model.network is None
    assert panel.empty_widget.isHidden() is False


def test_remove_network_button(shell, network_panel) -> None:
    panel = network_panel
    panel.create_network()
    panel.remove_network_button.click()
    assert shell.document.model.network is None
    assert panel.editor_widget.isHidden()


# ------------------------------------------------------------------ flow results
@pytest.fixture(scope="module")
def solved(tmp_path_factory: pytest.TempPathFactory) -> tuple[Model, Results]:
    model = api.new_model(name="cold plate")
    api.Geometry(model).rectangle(0.0, 0.0, LENGTH, 0.05)
    model.mesh_settings.global_size = 0.05
    built = api.build(model)
    api.select_curves(model, built, "channel", where=lambda cv: abs(cv.center[1]) < 1e-9)
    api.select_curves(model, built, "hot", where=lambda cv: abs(cv.center[1] - 0.05) < 1e-9)
    api.assign_region(model, "all", material="Copper (pure)")
    model.bcs.append(bcs.HeatFlux("load", "hot", q=2000.0))
    model.streams.append(
        coolant(
            name="coolant", walls=["channel"], mass_flow=0.05, h_override=800.0,
            wetted_perimeter=0.04,
        )
    )  # fmt: skip
    mesh = api.mesh(model, built)
    results = api.solve(model, mesh, built=built)
    return model, results


@pytest.fixture
def flow_shell(window, view, solved):
    model, results = solved
    document = Document(model)
    attach_tree(window, document, view)
    results_ctrl = attach_results(window, document, view)
    charts = attach_charts(window, document, view, results_ctrl)
    flow = attach_flow(window, document, view, results_ctrl)
    document.set_results(results.path)
    out = SimpleNamespace(
        window=window, document=document, results=results, ctrl=results_ctrl, flow=flow,
        charts=charts,
    )  # fmt: skip
    yield out
    if flow.flow_window is not None:
        flow.flow_window.close()
    charts.close_windows()


def test_flow_table_equals_the_stream_summary(flow_shell) -> None:
    flow = flow_shell.flow
    window = flow.show_flow()
    assert isinstance(window, FlowResultsWindow)
    results = flow_shell.results
    last = results.n_steps - 1
    rows = stream_summary(results, last)
    assert window.step_spin.value() == last
    assert window.table.rowCount() == len(rows) == 1
    for column, text in enumerate(window.row_texts(rows[0])):
        assert window.table.item(0, column).text() == text
    assert window.table.item(0, 0).text() == "coolant"
    assert window.table.item(0, 2).text() == f"{rows[0].mass_flow:.6g}"
    assert window.table.item(0, 5).text() == f"{rows[0].h_mean:.6g}"


def test_plot_window_holds_the_fluid_and_wall_curves(flow_shell) -> None:
    window = flow_shell.flow.show_flow()
    window.table.setCurrentCell(0, 0)
    chart = window.plot_selected()
    assert chart is not None
    results = flow_shell.results
    last = results.n_steps - 1
    s_wall, t_wall = wall_temperature(results, "coolant", last)
    fluid_s, fluid_t = chart.stream_curves["fluid"]
    wall_s, wall_t = chart.stream_curves["mean wall"]
    np.testing.assert_allclose(fluid_t, results.fluid_temperature("coolant", last))
    np.testing.assert_allclose(wall_s, s_wall)
    np.testing.assert_allclose(wall_t, t_wall)
    lines = chart.axes.get_lines()
    assert [line.get_label() for line in lines] == ["fluid", "mean wall"]
    np.testing.assert_allclose(lines[0].get_ydata(), results.fluid_temperature("coolant", last))


def test_flow_window_step_says_steady_state(flow_shell) -> None:
    """M11.8 (Q26.4 f): the stream window labels the steady step, not "t = 0 s"."""
    window = flow_shell.flow.show_flow()
    assert window.step_label.text() == "steady state"


def test_flow_action_is_enabled_only_with_stream_results(window, view, solved) -> None:
    _model, results = solved
    empty = api.new_model(name="no streams")
    document = Document(empty)
    attach_tree(window, document, view)
    results_ctrl = attach_results(window, document, view)
    flow = attach_flow(window, document, view, results_ctrl)
    assert not window.actions["results.flow"].isEnabled()
    assert flow.show_flow() is None
    document.set_results(results.path)
    assert window.actions["results.flow"].isEnabled()


def test_flow_action_opens_its_window(flow_shell) -> None:
    flow_shell.window.actions["results.flow"].trigger()
    assert flow_shell.flow.flow_window is not None
    assert flow_shell.flow.flow_window.isVisible()


def test_stream_chart_has_no_csv_export(flow_shell) -> None:
    window = flow_shell.flow.show_flow()
    window.table.setCurrentCell(0, 0)
    chart = window.plot_selected()
    assert chart is not None
    assert not chart.csv_button.isEnabled()
    assert chart.csv_button.toolTip() != ""


def test_flow_plot_save_error_is_shown(flow_shell, dialogs, monkeypatch, tmp_path) -> None:
    window = flow_shell.flow.show_flow()
    window.table.setCurrentCell(0, 0)
    chart = window.plot_selected()

    def failing_savefig(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(chart.figure, "savefig", failing_savefig)
    assert chart.save_image(tmp_path / "plot.png") is None
    assert dialogs.calls and dialogs.calls[-1][0] == "Save image failed"
    assert "disk full" in dialogs.calls[-1][1]


def test_closed_flow_plot_is_forgotten(flow_shell) -> None:
    window = flow_shell.flow.show_flow()
    window.table.setCurrentCell(0, 0)
    first = window.plot_selected()
    second = window.plot_selected()
    assert first is not None and second is not None
    assert window.plot_windows == [first, second]
    first.close()
    assert window.plot_windows == [second]
    second.close()
    assert window.plot_windows == []


def test_flow_plot_is_marked_out_of_date(flow_shell) -> None:
    window = flow_shell.flow.show_flow()
    window.table.setCurrentCell(0, 0)
    chart = window.plot_selected()
    assert chart is not None and not chart.out_of_date
    assert "(out of date)" not in chart.windowTitle()
    flow_shell.document.results_changed.emit()
    assert chart.out_of_date
    assert "(out of date)" in chart.windowTitle()


# ------------------------------------------------------------------ HTC calculator
@pytest.fixture
def calc(qtbot) -> HtcCalculator:
    widget = HtcCalculator()
    qtbot.addWidget(widget)
    return widget


def test_natural_correlation_matches_api_htc(calc) -> None:
    pick(calc.correlation_box, "vplate_natural")
    pick(calc.fluid_box, "Air")
    calc.t_surface_edit.setText("350")
    calc.t_inf_edit.setText("300")
    calc.input_edits["length"].setText("0.5")
    result = calc.calculate()
    expected = api.htc("vplate_natural", "Air", 350.0, 300.0, length=0.5)
    assert result is not None and calc.result is result
    assert result.h == pytest.approx(expected.h, rel=1e-12)


def test_forced_correlation_matches_api_htc(calc) -> None:
    pick(calc.correlation_box, "plate_forced_avg")
    pick(calc.fluid_box, "Air")
    calc.t_surface_edit.setText("350")
    calc.t_inf_edit.setText("300")
    calc.input_edits["length"].setText("0.5")
    calc.input_edits["velocity"].setText("2")
    result = calc.calculate()
    expected = api.htc("plate_forced_avg", "Air", 350.0, 300.0, length=0.5, velocity=2.0)
    assert result is not None and result.h == pytest.approx(expected.h, rel=1e-12)


@pytest.mark.parametrize("correlation", sorted(CORRELATIONS))
def test_visible_inputs_are_the_listed_inputs(calc, correlation: str) -> None:
    pick(calc.correlation_box, correlation)
    assert set(calc.visible_inputs()) == set(CORRELATION_INFO[correlation].inputs)


def test_missing_input_gives_a_message_and_no_result(calc) -> None:
    pick(calc.correlation_box, "plate_forced_avg")
    pick(calc.fluid_box, "Air")
    calc.t_surface_edit.setText("350")
    calc.t_inf_edit.setText("300")
    calc.input_edits["length"].setText("0.5")
    result = calc.calculate()
    assert result is None and calc.result is None
    assert "Velocity" in calc.message


# ------------------------------------------------------------------ tools action
def test_htc_action_opens_the_calculator(flow_shell) -> None:
    flow_shell.window.actions["tools.htc"].trigger()
    assert flow_shell.flow.htc_window is not None
    assert flow_shell.flow.htc_window.isVisible()


NEW_IDS_M11_39 = [
    "square_corner_crossflow", "square_face_crossflow", "hexagon_face_crossflow",
    "hexagon_corner_crossflow", "plate_front_crossflow", "plate_back_crossflow",
    "sphere_forced", "sphere_natural", "vplate_natural_laminar",
]


def test_new_correlations_are_offered_with_their_inputs(calc) -> None:
    offered = [calc.correlation_box.itemText(i) for i in range(calc.correlation_box.count())]
    for cid in NEW_IDS_M11_39:
        assert cid in offered
        pick(calc.correlation_box, cid)
        shown = set(calc.visible_inputs())
        assert "length" in shown
        assert ("velocity" in shown) == (CORRELATIONS[cid].kind == "forced")
    pick(calc.correlation_box, "sphere_forced")
    assert "except μ_s at T_s" in calc.formula_label.text()
    assert "T∞, except μ_s" in calc.length_label.text()
    assert "film temperature" not in calc.length_label.text()
    pick(calc.correlation_box, "square_face_crossflow")
    assert "film temperature" in calc.length_label.text()


def test_vertical_channels_are_offered_with_the_spacing_input(calc) -> None:
    offered = [calc.correlation_box.itemText(i) for i in range(calc.correlation_box.count())]
    for cid in ("vchannel_natural", "vchannel_one_side_natural"):
        assert cid in offered
        pick(calc.correlation_box, cid)
        assert set(calc.visible_inputs()) == {"length", "S"}
        assert "Not stated" in calc.validity_label.text()


def test_jets_are_offered_with_their_inputs(calc) -> None:
    offered = [calc.correlation_box.itemText(i) for i in range(calc.correlation_box.count())]
    for cid, names in (
        ("slot_jet", {"velocity", "W", "H", "x_r"}),
        ("round_jet", {"velocity", "D", "H", "r_r"}),
    ):
        assert cid in offered
        pick(calc.correlation_box, cid)
        assert set(calc.visible_inputs()) == names


def test_stream_form_offers_the_new_sections_and_sieder_tate() -> None:
    from thermalfea.model.flow_forms import STREAM_FORM
    sections = STREAM_FORM.field("cross_section").choices
    for name in ("rectangle_1_43", "rectangle_2", "rectangle_3", "rectangle_4", "rectangle_8",
                 "triangle", "annulus_inner", "annulus_outer"):
        assert name in sections
    assert "sieder_tate" in STREAM_FORM.field("nu_option").choices
    assert STREAM_FORM.field("diameter_ratio").optional


def test_new_stream_dialog_offers_the_sections_and_the_ratio(qtbot) -> None:
    dialog = NewStreamDialog()
    qtbot.addWidget(dialog)
    offered = [dialog.cross_box.itemText(i) for i in range(dialog.cross_box.count())]
    assert "annulus_inner" in offered and "triangle" in offered
    assert dialog.diameter_ratio_edit is not None


def test_add_stream_from_a_through_plane_template_is_not_a_bad_in_plane_stream(shell) -> None:
    def make_through_plane(model: Model) -> None:
        model.streams[0].mode = "through_plane"
        model.streams[0].path = None

    shell.document.edit("Make through-plane", make_through_plane)
    shell.tree.add_stream()
    model = shell.document.model
    new = model.streams[1]
    assert new.name == "Stream 1" and new.path is None
    assert new.mode == "through_plane"  # the copy keeps the template's mode
    bad = [i for i in validate_model(model) if i.code == "bad-stream-path"]
    assert bad == []


def test_new_stream_dialog_refuses_zero_flow_area_and_perimeter(shell) -> None:
    shell.document.edit("Clear streams", lambda m: m.streams.clear())
    assert shell.tree.add_stream() is None
    dialog = shell.tree.stream_dialog
    pick(dialog.fluid_box, "Water")
    pick(dialog.cross_box, "circular")
    dialog.inlet_edit.setText("300")
    dialog.flow_area_edit.setText("0")
    dialog.wetted_edit.setText("0.04")
    assert dialog.submit() is False
    assert "positive" in dialog.message_label.text()
    dialog.flow_area_edit.setText("1e-4")
    dialog.wetted_edit.setText("0")
    assert dialog.submit() is False
    assert shell.document.model.streams == []
    dialog.wetted_edit.setText("0.04")
    assert dialog.submit() is True
    assert shell.document.model.streams[0].flow_area == pytest.approx(1e-4)


def test_network_number_accepts_a_decimal_comma() -> None:
    assert parse_number("0,5") == pytest.approx(0.5)
    assert parse_number("0.5") == pytest.approx(0.5)
    with pytest.raises(ValueError):
        parse_number("1,5.0")  # a dot is present: the comma is not a decimal point
    with pytest.raises(ValueError):
        parse_number("1,5,2")


def test_network_bound_message_is_in_the_display_unit() -> None:
    units = UnitSettings(length="mm")
    minimum = 0.001  # 1 mm, in SI
    assert parse_number("2", minimum=minimum, quantity="length", units=units) == pytest.approx(
        0.002
    )
    with pytest.raises(ValueError, match="at least 1 mm"):
        parse_number("0.5", minimum=minimum, quantity="length", units=units)


def test_loading_another_model_closes_the_flow_plots(flow_shell) -> None:
    """Seen on a real screen: after File > New the stream plot of the old model stayed open."""
    window = flow_shell.flow.show_flow()
    window.table.setCurrentCell(0, 0)
    chart = window.plot_selected()
    assert chart is not None and window.plot_windows == [chart]
    flow_shell.document.set_model(Model(), None)  # what New, Open and Examples do
    assert window.plot_windows == []


def test_cross_section_is_offered_only_for_the_duct_correlation(calc) -> None:
    """Defect Q26.4(c): the duct correlation needs the cross-section; no other correlation does."""
    pick(calc.correlation_box, "duct_internal")
    assert not calc.cross_box.isHidden() and not calc.cross_label.isHidden()
    items = [calc.cross_box.itemText(i) for i in range(calc.cross_box.count())]
    assert items == list(bcs.STREAM_CROSS_SECTIONS)
    pick(calc.correlation_box, "vplate_natural")
    assert calc.cross_box.isHidden() and calc.cross_label.isHidden()


def test_duct_htc_reproduces_the_cold_plate_tutorial(calc) -> None:
    """The cold-plate tutorial pins h = 770.2 W/(m^2 K) by hand (tests/verification, 0.05).

    Water in the channel: mass flow 0.02 kg/s, flow area 1e-4 m^2, wetted perimeter 0.104 m,
    one side insulated (parallel_plates_one_side). The tutorial's inlet is 300 K.
    """
    pick(calc.correlation_box, "duct_internal")
    pick(calc.fluid_box, "Water")
    pick(calc.cross_box, "parallel_plates_one_side")
    calc.t_surface_edit.setText("300")
    calc.t_inf_edit.setText("300")
    calc.input_edits["mass_flow"].setText("0.02")
    calc.input_edits["area"].setText("1e-4")
    calc.input_edits["wetted_perimeter"].setText("0.104")
    result = calc.calculate()
    assert result is not None and calc.message == ""
    assert result.h == pytest.approx(770.2, abs=0.05)
    assert result.regime == "laminar"
    expected = api.htc(
        "duct_internal", "Water", 300.0, 300.0, mass_flow=0.02, area=1e-4,
        wetted_perimeter=0.104, cross_section="parallel_plates_one_side",
    )  # fmt: skip
    assert result.h == pytest.approx(expected.h, rel=1e-12)


def test_duct_cross_section_changes_h_through_api_htc(calc) -> None:
    pick(calc.correlation_box, "duct_internal")
    pick(calc.fluid_box, "Water")
    calc.t_surface_edit.setText("300")
    calc.t_inf_edit.setText("300")
    calc.input_edits["mass_flow"].setText("0.02")
    calc.input_edits["area"].setText("1e-4")
    calc.input_edits["wetted_perimeter"].setText("0.104")
    circular = calc.calculate()
    pick(calc.cross_box, "parallel_plates_one_side")
    plates = calc.calculate()
    assert circular is not None and plates is not None
    assert circular.h != pytest.approx(plates.h, rel=1e-3)
    assert plates.h == pytest.approx(770.2, abs=0.05)


def test_htc_calculator_says_nothing_before_an_entry(calc) -> None:
    assert calc.message != "" and calc.message_label.text() == ""  # nothing typed yet
    calc.t_surface_edit.setText("350")
    assert calc.message_label.text() == calc.message != ""  # now the next missing entry
