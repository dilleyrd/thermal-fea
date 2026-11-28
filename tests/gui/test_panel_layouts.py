"""M11.72: panel layouts (C5, C7, C12; held items 4, 8, 18 and 20).

Boxes and advanced fields of the Mesh, Correlation convection, Stream, network and Part
panels, the Initial condition panel that shows only the rows of its kind with a browse icon,
the hint texts and named empty modes of the optional fields, and the empty mode of a formula
field that accepts no typing.
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtWidgets import QLineEdit

from thermalfea import api
from thermalfea.core.forms import form_for
from thermalfea.core.functions import Constant
from thermalfea.gui.document import Document
from thermalfea.gui.field_texts import empty_text
from thermalfea.gui.property_panels.correlation import CorrelationPanel
from thermalfea.gui.property_panels.form import FormPanel, NumberEdit
from thermalfea.gui.property_panels.function_editor import FunctionEditor
from thermalfea.gui.property_panels.initial_condition import InitialConditionPanel
from thermalfea.gui.property_panels.material import MaterialPanel
from thermalfea.gui.property_panels.mesh import MeshPanel
from thermalfea.gui.property_panels.network import NetworkPanel
from thermalfea.gui.property_panels.region import RegionPanel
from thermalfea.gui.property_panels.sections import forget_open_state
from thermalfea.gui.property_panels.stream import StreamPanel
from thermalfea.materials.material import Material
from thermalfea.model.bcs import CorrelationConvection, FlowNetwork, NetNode, Stream
from thermalfea.model.model import InitialCondition, Model, RegionAssignment
from thermalfea.model.settings import MeshSettings


@pytest.fixture(autouse=True)
def fresh_open_state():
    forget_open_state()
    yield
    forget_open_state()


def coolant(**changes: Any) -> Stream:
    base: dict[str, Any] = dict(
        name="coolant", fluid="Water", mode="in_plane", walls=["bottom"], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=300.0, mass_flow=0.25,
        path=[(0.0, 0.0), (1.0, 0.0)],
    )  # fmt: skip
    return Stream(**{**base, **changes})


@pytest.fixture
def doc() -> Document:
    model = api.new_model(name="plate")
    model.streams.append(coolant())
    model.bcs.append(
        CorrelationConvection(
            "Cc", "top", "vplate_natural", "Air", T_inf=Constant(300.0)
        )
    )
    model.materials["Plain"] = Material("Plain", Constant(1.0), Constant(1.0), Constant(1.0))
    model.materials["Grain"] = Material(
        "Grain", Constant(1.0), Constant(1.0), Constant(1.0), k2=Constant(0.5)
    )
    model.regions.append(RegionAssignment("all", "Plain", 0.01))
    return Document(model)


def make(qtbot, panel: Any) -> Any:
    qtbot.addWidget(panel)
    return panel


def mesh_panel(qtbot, doc: Document) -> MeshPanel:
    return make(qtbot, MeshPanel(form_for(MeshSettings), doc, ("mesh_settings",)))


def stream_panel(qtbot, doc: Document) -> StreamPanel:
    return make(qtbot, StreamPanel(form_for(Stream), doc, ("streams", 0)))


def correlation_panel(qtbot, doc: Document) -> CorrelationPanel:
    return make(
        qtbot, CorrelationPanel(form_for(CorrelationConvection), doc, ("bcs", 0))
    )


def region_panel(qtbot, doc: Document) -> RegionPanel:
    return make(qtbot, RegionPanel(form_for(RegionAssignment), doc, ("regions", 0)))


def ic_panel(qtbot, doc: Document) -> InitialConditionPanel:
    return make(
        qtbot,
        InitialConditionPanel(form_for(InitialCondition), doc, ("initial_condition",)),
    )


def in_box(panel: FormPanel, field: str, box: str, more: bool = False) -> bool:
    section = panel.sections[box]
    form = section.more.form if more else section.form
    return panel._rows[field][0] is form


# ---------------------------------------------------------------------------- Mesh panel
def test_mesh_boxes_in_order_with_extras_as_framed_boxes(qtbot, doc) -> None:
    panel = mesh_panel(qtbot, doc)
    assert list(panel.sections) == [
        "Element size", "Element type", "Structured mesh", "Refinements",
        "Statistics and quality",
    ]  # fmt: skip
    assert panel.sections["Element size"].description_label.text() == (
        "Target size of the elements, and local sizes along boundaries and at points."
    )
    assert panel.sections["Refinements"].description_label.text() == (
        "Smaller elements near a boundary or point, growing with distance."
    )
    for name in ("global_size", "curve_sizes", "point_sizes"):
        assert in_box(panel, name, "Element size")
    for name in ("order", "element_shape"):
        assert in_box(panel, name, "Element type")
    for name in ("algorithm", "smoothing_passes"):
        assert in_box(panel, name, "Element type", more=True)
    for name in ("structured_surfaces", "curve_divisions"):
        assert in_box(panel, name, "Structured mesh")


def test_mesh_extras_sit_in_their_boxes(qtbot, doc) -> None:
    panel = mesh_panel(qtbot, doc)
    refinements = panel.sections["Refinements"]
    stats = panel.sections["Statistics and quality"]
    assert refinements.isAncestorOf(panel.table)
    for widget in (panel.stats_label, panel.measure_combo, panel.histogram, panel.color_box):
        assert stats.isAncestorOf(widget)
    for section in panel.sections.values():  # "Generate mesh" is a command, not boxed
        assert not section.isAncestorOf(panel.generate_button)
    assert panel.generate_button.text() == "Generate mesh"


def test_mesh_has_no_bold_headings_left(qtbot, doc) -> None:
    panel = mesh_panel(qtbot, doc)
    from PySide6.QtWidgets import QLabel

    texts = {label.text() for label in panel.findChildren(QLabel)}
    assert not texts & {"Statistics", "Quality"}


# ------------------------------------------------------------------ Correlation panel
def test_correlation_box_and_advanced_fields(qtbot, doc) -> None:
    panel = correlation_panel(qtbot, doc)
    assert list(panel.sections) == ["Convection", "Correlation", "Preview of h"]
    box = panel.sections["Convection"]
    assert box.description_label.text() == (
        "The correlation, the fluid and the conditions far from the wall."
    )
    for name in ("selection", "correlation", "fluid", "T_inf", "velocity", "params"):
        assert in_box(panel, name, "Convection")
    for name in ("char_length", "face_direction", "wall_T_mode", "multiplier"):
        assert in_box(panel, name, "Convection", more=True)
    assert not box.more.is_open()


def test_correlation_groups_became_section_boxes(qtbot, doc) -> None:
    panel = correlation_panel(qtbot, doc)
    info, preview = panel.sections["Correlation"], panel.sections["Preview of h"]
    assert info.description_label.text() == (
        "Formula and range of validity of the chosen correlation."
    )
    assert preview.description_label.text() == (
        "Try the coefficient for a surface temperature; nothing is stored."
    )
    assert info.isAncestorOf(panel.formula_label)
    assert preview.isAncestorOf(panel.result_label)
    assert preview.isAncestorOf(panel.preview_edits["T_surface"])
    from PySide6.QtWidgets import QGroupBox

    assert not panel.findChildren(QGroupBox)


# ------------------------------------------------------------------------ Stream panel
def test_stream_boxes_and_advanced_fields(qtbot, doc) -> None:
    panel = stream_panel(qtbot, doc)
    assert list(panel.sections) == [
        "Fluid and flow", "Cross-section", "Path", "Heat-transfer coefficient",
    ]  # fmt: skip
    for name in ("fluid", "mode", "walls", "T_inlet", "mass_flow"):
        assert in_box(panel, name, "Fluid and flow")
    for name in ("cross_section", "flow_area", "wetted_perimeter", "diameter_ratio"):
        assert in_box(panel, name, "Cross-section")
    assert in_box(panel, "path", "Path")
    for name in ("roughness", "n_cells", "nu_option", "h_multiplier", "h_override"):
        assert in_box(panel, name, "Heat-transfer coefficient", more=True)
    assert panel.sections["Heat-transfer coefficient"].description_label.text() == (
        "From the duct correlation unless overridden."
    )


def test_stream_path_buttons_moved_into_the_path_box(qtbot, doc) -> None:
    from PySide6.QtWidgets import QGroupBox

    panel = stream_panel(qtbot, doc)
    section = panel.sections["Path"]
    for widget in (panel.pick_button, panel.clear_button, panel.path_label, panel.strip):
        assert section.isAncestorOf(widget)
    assert not panel.findChildren(QGroupBox)


def test_diameter_ratio_only_for_an_annulus(qtbot, doc) -> None:
    panel = stream_panel(qtbot, doc)
    assert not panel.is_field_shown("diameter_ratio")
    doc.edit(
        "annulus",
        lambda m: (
            setattr(m.streams[0], "cross_section", "annulus_inner"),
            setattr(m.streams[0], "diameter_ratio", 0.5),
        ),
    )
    assert panel.is_field_shown("diameter_ratio")
    doc.edit(
        "circle",
        lambda m: (
            setattr(m.streams[0], "diameter_ratio", None),
            setattr(m.streams[0], "cross_section", "circular"),
        ),
    )
    assert not panel.is_field_shown("diameter_ratio")
    doc.edit(
        "outer",
        lambda m: (
            setattr(m.streams[0], "diameter_ratio", 0.5),
            setattr(m.streams[0], "cross_section", "annulus_outer"),
        ),
    )
    assert panel.is_field_shown("diameter_ratio")


def test_path_box_only_for_in_plane_streams(qtbot, doc) -> None:
    panel = stream_panel(qtbot, doc)
    section = panel.sections["Path"]
    assert panel.is_field_shown("path") and section.isVisibleTo(panel)
    assert panel.pick_button.isVisibleTo(panel)
    doc.edit("through", lambda m: setattr(m.streams[0], "mode", "through_plane"))
    assert not panel.is_field_shown("path")
    assert not section.isVisibleTo(panel) and not panel.pick_button.isVisibleTo(panel)
    doc.edit("in plane", lambda m: setattr(m.streams[0], "mode", "in_plane"))
    assert section.isVisibleTo(panel) and panel.pick_button.isVisibleTo(panel)


# ------------------------------------------------------------------------ Network panel
def test_network_headings_became_boxes(qtbot, doc) -> None:
    doc.edit("net", lambda m: setattr(m, "network", FlowNetwork(nodes=[NetNode("N1")])))
    panel = make(qtbot, NetworkPanel(doc))
    nodes, branches = panel.nodes_section, panel.branches_section
    assert nodes.title_text() == "Nodes" and branches.title_text() == "Branches"
    assert nodes.description_label.text() == "Junctions with a fixed pressure or an inflow."
    assert branches.description_label.text() == (
        "Ducts or losses between two nodes, optionally carrying a stream."
    )
    assert nodes.isAncestorOf(panel.node_table)
    assert nodes.isAncestorOf(panel.add_node_button)
    assert nodes.isAncestorOf(panel.remove_node_button)
    assert branches.isAncestorOf(panel.branch_table)
    assert branches.isAncestorOf(panel.add_branch_button)
    assert branches.isAncestorOf(panel.remove_branch_button)


# -------------------------------------------------------------------------- Part panel
def test_material_angle_only_for_a_directional_material(qtbot, doc) -> None:
    panel = region_panel(qtbot, doc)
    assert not panel.is_field_shown("material_angle")  # "Plain" has no k2
    doc.edit("directional", lambda m: setattr(m.regions[0], "material", "Grain"))
    assert panel.is_field_shown("material_angle")
    doc.edit("unknown", lambda m: setattr(m.regions[0], "material", "Nowhere"))
    assert not panel.is_field_shown("material_angle")  # a material that does not exist
    doc.edit("directional", lambda m: setattr(m.regions[0], "material", "Grain"))
    doc.edit("drop k2", lambda m: setattr(m.materials["Grain"], "k2", None))
    assert not panel.is_field_shown("material_angle")  # the material changed under the part


# --------------------------------------------------------------- Initial condition panel
def test_initial_condition_shows_only_the_rows_of_its_kind(qtbot, doc) -> None:
    panel = ic_panel(qtbot, doc)
    expected = {
        "uniform": {"value"},
        "expression": {"value"},
        "per_region": {"per_region"},
        "from_results": {"results_path"},
    }
    assert panel.is_field_shown("kind")
    for kind, rows in expected.items():
        doc.edit(
            "kind",
            lambda m, k=kind: setattr(
                m, "initial_condition", InitialCondition(k, results_path="r.h5")
            ),
        )
        shown = {n for n in ("value", "per_region", "results_path") if panel.is_field_shown(n)}
        assert shown == rows, kind
        assert panel.is_field_shown("kind")


def test_browse_icon_sits_beside_the_results_box_and_applies_in_one_step(
    qtbot, doc
) -> None:
    doc.edit(
        "from results",
        lambda m: setattr(m, "initial_condition", InitialCondition("from_results")),
    )
    panel = ic_panel(qtbot, doc)
    line = panel.editors["results_path"]
    assert isinstance(line, QLineEdit)
    assert panel.browse_button.parent() is line.parent()
    assert panel.browse_button.toolTip() == "Choose the results file"
    asked: list[tuple[str, str]] = []

    def chooser(parent, caption: str, file_filter: str) -> str | None:
        asked.append((caption, file_filter))
        return "C:/runs/steady.h5"

    panel.choose_open = chooser
    before = doc.undo_stack.count()
    panel.browse_button.click()
    assert asked == [("Choose the results file", "Results (*.h5)")]
    assert doc.model.initial_condition.results_path == "C:/runs/steady.h5"
    assert doc.undo_stack.count() == before + 1
    assert line.text() == "C:/runs/steady.h5"  # loading still works
    doc.undo_stack.undo()
    assert doc.model.initial_condition.results_path is None


def test_browse_cancelled_changes_nothing(qtbot, doc) -> None:
    doc.edit(
        "from results",
        lambda m: setattr(m, "initial_condition", InitialCondition("from_results")),
    )
    panel = ic_panel(qtbot, doc)
    panel.choose_open = lambda parent, caption, file_filter: None
    before = doc.undo_stack.count()
    panel.browse_button.click()
    assert doc.undo_stack.count() == before
    assert doc.model.initial_condition.results_path is None


def test_initial_condition_panel_is_registered(qtbot, doc, window) -> None:
    from thermalfea.gui.panels import attach_tree

    tree, controller = attach_tree(window, doc)
    controller.show_object(("initial_condition",))
    assert isinstance(controller.panel, InitialConditionPanel)


# ------------------------------------------------------------------------------ C7 hints
HINTS = {
    ("Correlation Convection", "char_length"): "from the geometry",
    ("Correlation Convection", "velocity"): "not used",
    ("Stream", "n_cells"): "one per wall edge",
    ("Stream", "diameter_ratio"): "required for an annulus",
    ("Stream", "mass_flow"): "from network",
    ("Stream", "h_override"): "use the correlation",
    ("Material", "k2"): "isotropic",
    ("Initial condition", "results_path"): "results file (.h5)",
}


def test_hint_texts_are_registered() -> None:
    for (form, field), text in HINTS.items():
        assert empty_text(form, field) == text


def test_boxes_show_their_hint_as_placeholder_text(qtbot, doc) -> None:
    stream = stream_panel(qtbot, doc)
    for name, text in (
        ("n_cells", "one per wall edge"),
        ("diameter_ratio", "required for an annulus"),
    ):
        editor = stream.editors[name]
        assert isinstance(editor, NumberEdit) and editor.placeholderText() == text
    corr = correlation_panel(qtbot, doc)
    editor = corr.editors["char_length"]
    assert isinstance(editor, NumberEdit) and editor.placeholderText() == "from the geometry"
    ic = ic_panel(qtbot, doc)
    editor = ic.editors["results_path"]
    assert isinstance(editor, QLineEdit) and editor.placeholderText() == "results file (.h5)"


def test_empty_modes_of_formula_fields_are_named(qtbot, doc) -> None:
    def none_label(panel: FormPanel, name: str) -> str:
        editor = panel.editors[name]
        assert isinstance(editor, FunctionEditor)
        return editor.mode_combo.itemText(editor.mode_combo.findData("none"))

    stream = stream_panel(qtbot, doc)
    assert none_label(stream, "mass_flow") == "From network"
    assert none_label(stream, "h_override") == "Use the correlation"
    assert none_label(correlation_panel(qtbot, doc), "velocity") == "Not used"
    material = make(
        qtbot, MaterialPanel(form_for(Material), doc, ("materials", "Plain"))
    )
    assert none_label(material, "k2") == "Isotropic"


def test_material_k2_label_does_not_carry_the_meaning_of_empty() -> None:
    assert form_for(Material).field("k2").label == "Conductivity (across axis)"


# ------------------------------------------------------------- item 4: nothing typed lost
def test_empty_mode_accepts_no_typing(qtbot, doc) -> None:
    doc.edit("unset", lambda m: setattr(m.streams[0], "mass_flow", None))
    panel = stream_panel(qtbot, doc)
    editor = panel.editors["mass_flow"]
    assert isinstance(editor, FunctionEditor) and editor.mode == "none"
    assert not editor.value_edit.isEnabled() and not editor.expr_edit.isEnabled()
    # choosing Constant makes the box usable again
    editor.mode_combo.setCurrentIndex(editor.mode_combo.findData("constant"))
    assert editor.value_edit.isEnabled()


def test_required_formula_field_starts_in_constant(qtbot, doc) -> None:
    editor = FunctionEditor("temperature", optional=False)
    qtbot.addWidget(editor)
    assert editor.mode == "constant" and editor.value_edit.isEnabled()
    editor.set_function(None)
    assert editor.mode == "constant"
    stream = stream_panel(qtbot, doc)
    inlet = stream.editors["T_inlet"]
    assert isinstance(inlet, FunctionEditor) and inlet.mode == "constant"


def test_the_model_is_not_touched_by_building_panels(qtbot, doc) -> None:
    model: Model = doc.model
    before = doc.undo_stack.count()
    mesh_panel(qtbot, doc)
    stream_panel(qtbot, doc)
    correlation_panel(qtbot, doc)
    region_panel(qtbot, doc)
    ic_panel(qtbot, doc)
    assert doc.undo_stack.count() == before and doc.model is model
