"""M8.7: mesh panel, refinements table, mesh generation controller, quality views.

Real gmsh meshes a tiny rectangle; the viewport is a fake that records ``set_mesh`` calls.
No window is shown and nothing is executed modally.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtWidgets import QPushButton

from thermalfea import api
from thermalfea.gui.document import Document
from thermalfea.gui.mesh_tools import ACTION_ID, MeshController, attach_mesh_tools
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.mesh import MeshPanel, parse_refinement
from thermalfea.meshing import quality
from thermalfea.model.settings import Refinement


class FakeView:
    """Records every ``set_mesh`` call as ``(mesh, color_by)``."""

    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []

    def set_mesh(self, mesh, color_by=None) -> None:
        self.calls.append((mesh, color_by))


def make_document(built: bool = True) -> Document:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0, 0, 1, 0.5)
    model.mesh_settings.global_size = 0.1
    document = Document(model)
    if built:
        document.set_built(api.build(model))
    return document


def make_shell(window, document: Document) -> SimpleNamespace:
    """Tree, property controller, mesh controller and fake viewport, as in the application."""
    view = FakeView()
    _tree, props = attach_tree(window, document, view)
    mesh = attach_mesh_tools(window, document, view)
    props.generate_mesh = mesh.generate
    return SimpleNamespace(window=window, doc=document, view=view, props=props, mesh=mesh)


@pytest.fixture
def shell(window) -> SimpleNamespace:
    return make_shell(window, make_document())


def open_panel(shell: SimpleNamespace) -> MeshPanel:
    shell.props.show_object(("mesh_settings",))
    panel = shell.props.panel
    assert isinstance(panel, MeshPanel)
    return panel


def button(panel: MeshPanel, text: str) -> QPushButton:
    return next(b for b in panel.findChildren(QPushButton) if b.text() == text)


def refinements(shell: SimpleNamespace) -> list[Refinement]:
    return list(shell.doc.model.mesh_settings.refinements)


# ----------------------------------------------------------------- settings form
def test_global_size_edit_is_one_undo_step_and_marks_mesh_stale(shell) -> None:
    shell.mesh.generate()
    panel = open_panel(shell)
    assert not shell.doc.mesh_stale
    steps = shell.doc.undo_stack.count()
    editor = panel.editors["global_size"]
    editor.setText("0.05")
    editor.editingFinished.emit()
    assert shell.doc.model.mesh_settings.global_size == pytest.approx(0.05)
    assert shell.doc.undo_stack.count() == steps + 1
    assert shell.doc.mesh_stale
    shell.doc.undo_stack.undo()
    assert shell.doc.model.mesh_settings.global_size == pytest.approx(0.1)


def test_divisions_are_whole_numbers_kept_as_int(shell) -> None:
    panel = open_panel(shell)
    line = panel.editors["curve_divisions"]
    line.setText("edge=4")
    line.editingFinished.emit()
    divisions = shell.doc.model.mesh_settings.curve_divisions
    assert divisions == {"edge": 4} and type(divisions["edge"]) is int
    line.setText("edge=4.5")
    line.editingFinished.emit()
    assert shell.doc.model.mesh_settings.curve_divisions == {"edge": 4}
    assert panel.error_text("curve_divisions")
    # sizes stay real numbers
    sizes = panel.editors["curve_sizes"]
    sizes.setText("edge=0.025")
    sizes.editingFinished.emit()
    assert shell.doc.model.mesh_settings.curve_sizes == {"edge": 0.025}


def test_element_shape_edit_is_one_undo_step(shell) -> None:
    panel = open_panel(shell)
    steps = shell.doc.undo_stack.count()
    combo = panel.editors["element_shape"]
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert shell.doc.model.mesh_settings.element_shape == "quad"
    assert shell.doc.undo_stack.count() == steps + 1
    assert shell.doc.mesh_stale
    shell.doc.undo_stack.undo()
    assert shell.doc.model.mesh_settings.element_shape == "tri"


# -------------------------------------------------------------- refinements table
def test_refinement_add_edit_remove_are_one_undo_step_each(shell) -> None:
    panel = open_panel(shell)
    steps = shell.doc.undo_stack.count()

    button(panel, "Add").click()
    assert len(refinements(shell)) == 1
    assert shell.doc.undo_stack.count() == steps + 1
    assert panel.table.rowCount() == 1

    panel.table.item(0, 0).setText("edge")  # the default selection is empty
    assert refinements(shell)[0].selection == "edge"
    panel.table.item(0, 1).setText("0.02")
    assert refinements(shell)[0].size_min == pytest.approx(0.02)
    assert shell.doc.undo_stack.count() == steps + 3

    panel.table.setCurrentCell(0, 0)
    button(panel, "Remove").click()
    assert refinements(shell) == []
    assert shell.doc.undo_stack.count() == steps + 4

    shell.doc.undo_stack.undo()
    assert refinements(shell)[0].size_min == pytest.approx(0.02)


def test_non_numeric_refinement_entry_is_rejected(shell) -> None:
    panel = open_panel(shell)
    button(panel, "Add").click()
    steps = shell.doc.undo_stack.count()
    before = refinements(shell)
    panel.table.item(0, 2).setText("abc")
    assert refinements(shell) == before
    assert shell.doc.undo_stack.count() == steps
    assert panel.refinement_error.text() != ""
    assert panel.table.item(0, 2).background().color().name() == "#ffd0d0"


def test_refinement_order_is_checked_like_the_mesher(shell) -> None:
    panel = open_panel(shell)
    button(panel, "Add").click()
    panel.table.item(0, 0).setText("edge")
    steps = shell.doc.undo_stack.count()
    panel.table.item(0, 1).setText("0.5")  # size min above size max (0.1)
    assert shell.doc.undo_stack.count() == steps
    assert refinements(shell)[0].size_min != 0.5


def test_parse_refinement_rules() -> None:
    row = parse_refinement(["edge", "0.01", "0.1", "0", "0.2"])
    assert row == Refinement("edge", 0.01, 0.1, 0.0, 0.2)
    for bad in (["", "0.01", "0.1", "0", "0.2"], ["e", "x", "1", "0", "1"],
                ["e", "0.1", "0.01", "0", "1"], ["e", "0.1", "1", "1", "1"],
                ["e", "inf", "1", "0", "1"]):  # fmt: skip
        with pytest.raises(ValueError):
            parse_refinement(bad)


# ----------------------------------------------------------------------- generate
def test_generate_stores_a_mesh_and_emits_mesh_changed(shell, qtbot) -> None:
    doc = shell.doc
    assert doc.mesh is None and doc.mesh_stale
    with qtbot.waitSignal(doc.mesh_changed):
        assert shell.mesh.generate() is True
    assert doc.mesh is not None
    assert not doc.mesh_stale


def test_generate_without_built_geometry_refuses_and_reports(window) -> None:
    doc = make_document(built=False)
    controller = MeshController(window, doc)
    assert controller.generate() is False
    assert doc.mesh is None
    assert "Build the geometry" in window.statusBar().currentMessage()


def test_generate_with_stale_geometry_refuses(window) -> None:
    doc = make_document()
    controller = MeshController(window, doc)
    doc.edit("Add rectangle", lambda m: api.Geometry(m).rectangle(2, 0, 1, 1))
    assert doc.geometry_stale
    assert controller.generate() is False
    assert "Rebuild" in window.statusBar().currentMessage()


def test_meshing_failure_is_reported_and_keeps_old_mesh(shell, dialogs) -> None:
    assert shell.mesh.generate()
    old = shell.doc.mesh
    shell.doc.edit(
        "Divide unknown curve",
        lambda m: m.mesh_settings.curve_divisions.update({"no_such_curve": 4}),
    )
    assert shell.mesh.generate() is False
    assert shell.doc.mesh is old
    assert len(dialogs.calls) == 1
    assert dialogs.calls[0][0] == "Meshing failed"
    assert "no_such_curve" in dialogs.calls[0][1]


# --------------------------------------------------------------- statistics, quality
def test_statistics_show_no_mesh_before_generating(shell) -> None:
    panel = open_panel(shell)
    assert panel.stats_label.text() == "No mesh"
    assert panel.histogram.n_values == 0


def test_statistics_and_histogram_after_generating(shell) -> None:
    panel = open_panel(shell)
    shell.mesh.generate()
    mesh = shell.doc.mesh
    text = panel.stats_label.text()
    assert f"Nodes: {mesh.n_nodes}" in text
    assert f"Elements: {mesh.n_elements}" in text
    assert panel.histogram.counts.sum() == mesh.n_elements
    assert panel.histogram.n_values == mesh.n_elements


def test_switching_the_measure_redraws_the_histogram(shell) -> None:
    panel = open_panel(shell)
    shell.mesh.generate()
    assert panel.histogram.axes.get_xlabel() == "Minimum angle [deg]"
    panel.measure_combo.setCurrentIndex(2)
    assert panel.histogram.axes.get_xlabel() == "Jacobian ratio"
    assert panel.histogram.counts.sum() == shell.doc.mesh.n_elements


def test_colour_by_quality_calls_set_mesh_and_unchecking_clears(shell) -> None:
    panel = open_panel(shell)
    shell.mesh.generate()
    mesh = shell.doc.mesh
    panel.colour_box.setChecked(True)
    _, color_by = shell.view.calls[-1]
    assert isinstance(color_by, np.ndarray)
    assert color_by.shape == (mesh.n_elements,)

    report = quality.report(mesh)
    by_id = dict(zip(report.elem_ids.tolist(), report.min_angle.tolist(), strict=True))
    block_ids = [int(i) for b in mesh.blocks for i in b.elem_ids]
    assert np.allclose(color_by, [by_id[i] for i in block_ids])

    panel.colour_box.setChecked(False)
    assert shell.view.calls[-1] == (mesh, None)


def test_leaving_the_panel_ends_the_quality_colouring(shell) -> None:
    """The check box and the viewport stay in step when the panel is shown again."""
    panel = open_panel(shell)
    shell.mesh.generate()
    mesh = shell.doc.mesh
    panel.colour_box.setChecked(True)
    assert isinstance(shell.view.calls[-1][1], np.ndarray)
    shell.props.show_object(("solution",))  # another tree item replaces the panel
    assert shell.view.calls[-1] == (mesh, None)
    again = open_panel(shell)
    assert not again.colour_box.isChecked()


def test_generate_button_and_action_follow_the_geometry_state(window, qtbot) -> None:
    doc = make_document(built=False)
    shell = make_shell(window, doc)
    panel = open_panel(shell)
    assert not button(panel, "Generate mesh").isEnabled()
    assert not window.actions[ACTION_ID].isEnabled()

    doc.set_built(api.build(doc.model))
    assert button(panel, "Generate mesh").isEnabled()
    assert window.actions[ACTION_ID].isEnabled()
