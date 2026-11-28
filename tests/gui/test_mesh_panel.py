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
        self.highlighted: list[tuple[int, object]] = []

    def set_mesh(self, mesh, color_by=None) -> None:
        self.calls.append((mesh, color_by))

    def highlight(self, dim, tags) -> None:
        self.highlighted.append((dim, tags))


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


def add_edge(shell: SimpleNamespace, *names: str) -> None:
    """Create curve selections (default: ``edge``) on the rectangle's west side."""
    for name in names or ("edge",):
        shell.doc.edit(
            f"Select {name}",
            lambda m, n=name: api.select_curves(
                m, shell.doc.built, n, where=lambda c: abs(c.center[0]) < 1e-9
            ),
        )


def choose(table, r: int, name: str) -> None:
    """Pick a selection in row ``r`` of a selection table, as the user does."""
    w = table.row_widgets(r)
    w.combo.setCurrentIndex(w.combo.findData(name))
    w.combo.activated.emit(w.combo.currentIndex())


def enter(table, r: int, texts: list[str]) -> None:
    """Type the values of row ``r`` and press Enter in the first box."""
    w = table.row_widgets(r)
    for edit, text in zip(w.edits, texts, strict=True):
        edit.setText(text)
    w.edits[0].returnPressed.emit()


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
    add_edge(shell)
    table = panel.editors["curve_divisions"]
    r = table.add_row()
    choose(table, r, "edge")
    enter(table, r, ["4"])
    divisions = shell.doc.model.mesh_settings.curve_divisions
    assert divisions == {"edge": 4} and type(divisions["edge"]) is int
    steps = shell.doc.undo_stack.count()
    w = table.row_widgets(0)
    w.edits[0].setText("4.5")
    w.edits[0].returnPressed.emit()
    assert shell.doc.model.mesh_settings.curve_divisions == {"edge": 4}
    assert shell.doc.undo_stack.count() == steps
    assert table.row_error(0) == "enter a whole number"
    # sizes stay real numbers
    sizes = panel.editors["curve_sizes"]
    r = sizes.add_row()
    choose(sizes, r, "edge")
    enter(sizes, r, ["0.025"])
    assert shell.doc.model.mesh_settings.curve_sizes == {"edge": 0.025}
    assert type(shell.doc.model.mesh_settings.curve_sizes["edge"]) is float


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
    add_edge(shell, "edge", "other")
    steps = shell.doc.undo_stack.count()

    r = panel.table.add_row()  # a draft: nothing is stored yet
    assert refinements(shell) == []
    assert shell.doc.undo_stack.count() == steps
    choose(panel.table, r, "edge")
    enter(panel.table, r, ["0.05", "0.1", "0", "0.2"])  # added: one step
    assert refinements(shell) == [Refinement("edge", 0.05, 0.1, 0.0, 0.2)]
    assert shell.doc.undo_stack.count() == steps + 1
    assert panel.table.rows() == [("edge", (0.05, 0.1, 0.0, 0.2))]

    w = panel.table.row_widgets(0)  # a value edit: one step
    w.edits[0].setText("0.02")
    w.edits[0].returnPressed.emit()
    assert refinements(shell)[0].size_min == pytest.approx(0.02)
    assert shell.doc.undo_stack.count() == steps + 2

    choose(panel.table, 0, "other")  # a selection change waits for Update
    assert refinements(shell)[0].selection == "edge"
    assert shell.doc.undo_stack.count() == steps + 2
    panel.table.row_widgets(0).update_button.click()
    assert refinements(shell)[0].selection == "other"
    assert refinements(shell)[0].size_min == pytest.approx(0.02)
    assert shell.doc.undo_stack.count() == steps + 3

    panel.table.row_widgets(0).remove_button.click()  # removed: one step
    assert refinements(shell) == []
    assert shell.doc.undo_stack.count() == steps + 4

    shell.doc.undo_stack.undo()
    assert refinements(shell)[0].selection == "other"
    assert refinements(shell)[0].size_min == pytest.approx(0.02)


def test_non_numeric_refinement_entry_is_rejected(shell) -> None:
    panel = open_panel(shell)
    add_edge(shell)
    r = panel.table.add_row()
    choose(panel.table, r, "edge")
    steps = shell.doc.undo_stack.count()
    before = refinements(shell)
    w = panel.table.row_widgets(r)
    for edit, text in zip(w.edits, ["0.05", "abc", "0", "0.2"], strict=True):
        edit.setText(text)
    assert panel.table.apply_row(r) is False
    assert refinements(shell) == before
    assert shell.doc.undo_stack.count() == steps
    assert "abc" in panel.table.row_error(r)
    assert panel.table.rows() == []
    # a stored row rejects a bad value too and keeps its stored value
    w.edits[1].setText("0.1")
    assert panel.table.apply_row(r) is True
    steps = shell.doc.undo_stack.count()
    w = panel.table.row_widgets(0)
    w.edits[1].setText("abc")
    w.edits[1].returnPressed.emit()
    assert refinements(shell) == [Refinement("edge", 0.05, 0.1, 0.0, 0.2)]
    assert shell.doc.undo_stack.count() == steps
    assert "abc" in panel.table.row_error(0)


def test_refinement_order_is_checked_like_the_mesher(shell) -> None:
    panel = open_panel(shell)
    add_edge(shell)
    r = panel.table.add_row()
    choose(panel.table, r, "edge")
    enter(panel.table, r, ["0.05", "0.1", "0", "0.2"])
    steps = shell.doc.undo_stack.count()
    w = panel.table.row_widgets(0)
    w.edits[0].setText("0.5")  # size min above size max (0.1)
    w.edits[0].returnPressed.emit()
    assert shell.doc.undo_stack.count() == steps
    assert refinements(shell)[0].size_min != 0.5
    assert panel.table.row_error(0) == "sizes need 0 < size min <= size max"
    w.edits[0].setText("0.05")
    w.edits[2].setText("0.3")  # dist min above dist max (0.2)
    w.edits[2].returnPressed.emit()
    assert shell.doc.undo_stack.count() == steps
    assert refinements(shell)[0].dist_min != 0.3
    assert panel.table.row_error(0) == "distances need 0 <= dist min < dist max"


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


def test_color_by_quality_calls_set_mesh_and_unchecking_clears(shell) -> None:
    panel = open_panel(shell)
    shell.mesh.generate()
    mesh = shell.doc.mesh
    panel.color_box.setChecked(True)
    _, color_by = shell.view.calls[-1]
    assert isinstance(color_by, np.ndarray)
    assert color_by.shape == (mesh.n_elements,)

    report = quality.report(mesh)
    by_id = dict(zip(report.elem_ids.tolist(), report.min_angle.tolist(), strict=True))
    block_ids = [int(i) for b in mesh.blocks for i in b.elem_ids]
    assert np.allclose(color_by, [by_id[i] for i in block_ids])

    panel.color_box.setChecked(False)
    assert shell.view.calls[-1] == (mesh, None)


def test_leaving_the_panel_ends_the_quality_coloring(shell) -> None:
    """The check box and the viewport stay in step when the panel is shown again."""
    panel = open_panel(shell)
    shell.mesh.generate()
    mesh = shell.doc.mesh
    panel.color_box.setChecked(True)
    assert isinstance(shell.view.calls[-1][1], np.ndarray)
    shell.props.show_object(("solution",))  # another tree item replaces the panel
    assert shell.view.calls[-1] == (mesh, None)
    again = open_panel(shell)
    assert not again.color_box.isChecked()


def test_generate_button_and_action_follow_the_geometry_state(window, qtbot) -> None:
    doc = make_document(built=False)
    shell = make_shell(window, doc)
    panel = open_panel(shell)
    assert not button(panel, "Generate mesh").isEnabled()
    assert not window.actions[ACTION_ID].isEnabled()

    doc.set_built(api.build(doc.model))
    assert button(panel, "Generate mesh").isEnabled()
    assert window.actions[ACTION_ID].isEnabled()


def test_histogram_of_equal_qualities_up_to_round_off(qtbot) -> None:
    """A structured strip has qualities equal up to round-off; the histogram must still draw."""
    from thermalfea.gui.property_panels.quality_histogram import QualityHistogram

    histogram = QualityHistogram()
    qtbot.addWidget(histogram)
    histogram.set_values(np.array([1.0, 1.0 + 2.2e-16, 1.0]), "Aspect ratio")
    assert histogram.counts.sum() == 3
    assert histogram.edges[0] < 1.0 < histogram.edges[-1]
