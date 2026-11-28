"""M11.73: readable choice texts (C8), words for geometry (C9) and field symbols (decision H).

Only what the window shows changes; the stored values of the model stay as they were.
"""

from __future__ import annotations

from typing import Any

import pytest
from PySide6.QtWidgets import QComboBox, QLabel
from test_selections_section import FakeView as SelectionView
from test_selections_section import curve_at

from thermalfea import api
from thermalfea.convection.correlation_info import CORRELATION_INFO
from thermalfea.core.forms import form_for
from thermalfea.core.functions import Constant
from thermalfea.gui import tree_summary as ts
from thermalfea.gui.dialogs.htc_calculator import HtcCalculator
from thermalfea.gui.dialogs.new_load import NewCorrelationConvectionDialog
from thermalfea.gui.dialogs.new_stream import NewStreamDialog
from thermalfea.gui.document import Document
from thermalfea.gui.field_texts import CHOICE_TEXTS, SYMBOLS, choice_text, symbol_of
from thermalfea.gui.issues import object_text
from thermalfea.gui.load_symbols import attach_loads
from thermalfea.gui.overlay_labels import REGION_ACTION_ID, attach_labels, label_text
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.correlation import CorrelationPanel
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.property_panels.network import NetworkPanel
from thermalfea.gui.property_panels.selection_panel import SelectionPanel
from thermalfea.model.bcs import (
    Convection,
    CorrelationConvection,
    Enclosure,
    EnclosureSurface,
    FlowNetwork,
    NetNode,
    RadiationAmbient,
    Stream,
)
from thermalfea.model.contact_forms import CONTACT_FORM
from thermalfea.model.model import InitialCondition, RegionAssignment
from thermalfea.model.settings import MeshSettings
from thermalfea.model.validate import Issue, validate, validate_model


def choose(panel: Any, name: str, value: Any) -> None:
    """Choose the entry of a panel's combo whose stored value is ``value``, as a click does."""
    combo = panel.editors[name]
    assert isinstance(combo, QComboBox)
    index = combo.findData(value)
    assert index >= 0, (name, value)
    combo.setCurrentIndex(index)
    combo.activated.emit(index)


def texts_of(combo: QComboBox) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def label_texts(panel: Any) -> list[str]:
    return [label.text() for label in panel.findChildren(QLabel)]


@pytest.fixture
def doc(qtbot) -> Document:
    model = api.new_model(name="plate")
    g = api.Geometry(model)
    g.rectangle(0.0, 0.0, 0.6, 0.2, id="plate")
    built = api.build(model)
    api.select_curves(model, built, "cooled", lambda fp: abs(fp.center[1]) < 1e-9)
    api.select_surfaces(model, built, "body", lambda fp: True)
    api.assign_region(model, "body", "Copper (pure)")
    model.bcs.append(Convection("cool", "cooled", h=Constant(750.0), T_inf=Constant(273.15)))
    document = Document(model)
    document.set_built(built)
    return document


def form_panel(qtbot, doc: Document, cls: type, address: tuple, panel_cls: type = FormPanel):
    panel = panel_cls(form_for(cls), doc, address)
    qtbot.addWidget(panel)
    return panel


# ------------------------------------------------------------- readable choices (C8)
def test_mesh_choices_are_readable_and_store_the_same_values(qtbot, doc) -> None:
    panel = form_panel(qtbot, doc, MeshSettings, ("mesh_settings",))
    assert texts_of(panel.editors["order"]) == ["Linear (1)", "Quadratic (2)"]
    assert texts_of(panel.editors["element_shape"]) == [
        "Triangles", "Quadrilaterals (quad-dominant)",
    ]
    assert texts_of(panel.editors["algorithm"]) == [
        "Delaunay", "Frontal", "Frontal for quadrilaterals",
    ]
    choose(panel, "order", 2)
    choose(panel, "element_shape", "quad")
    choose(panel, "algorithm", "frontal_quad")
    settings = doc.model.mesh_settings
    assert (settings.order, settings.element_shape, settings.algorithm) == (
        2, "quad", "frontal_quad",
    )
    assert panel.editors["order"].currentText() == "Quadratic (2)"


def test_initial_condition_kinds_are_readable(qtbot, doc) -> None:
    panel = form_panel(qtbot, doc, InitialCondition, ("initial_condition",))
    assert texts_of(panel.editors["kind"]) == [
        "Uniform", "Expression of x and y", "Per part", "From a results file",
    ]
    choose(panel, "kind", "per_region")
    assert doc.model.initial_condition.kind == "per_region"
    assert panel.editors["kind"].currentText() == "Per part"


def test_stream_choices_are_readable_and_store_the_same_values(qtbot, doc) -> None:
    doc.edit("stream", lambda m: m.streams.append(Stream(
        name="s", fluid="Water", mode="in_plane", walls=[], flow_area=1e-4,
        wetted_perimeter=0.04, cross_section="circular", T_inlet=Constant(300.0),
    )))  # fmt: skip
    panel = form_panel(qtbot, doc, Stream, ("streams", 0))
    assert texts_of(panel.editors["mode"]) == ["Along a path in the plane", "Through the plane"]
    assert texts_of(panel.editors["cross_section"]) == [
        "Circular", "Parallel plates, both heated", "Parallel plates, one side insulated",
        "Square", "Rectangle, sides 1.43 : 1", "Rectangle, sides 2 : 1",
        "Rectangle, sides 3 : 1", "Rectangle, sides 4 : 1", "Rectangle, sides 8 : 1",
        "Triangle", "Annulus, inner surface heated", "Annulus, outer surface heated",
    ]
    assert texts_of(panel.editors["nu_option"]) == [
        "Automatic", "Dittus–Boelter", "Sieder–Tate",
    ]
    choose(panel, "cross_section", "rectangle_2")
    choose(panel, "nu_option", "sieder_tate")
    stream = doc.model.streams[0]
    assert (stream.cross_section, stream.nu_option) == ("rectangle_2", "sieder_tate")


def test_correlation_panel_shows_titles_and_keeps_ids(qtbot, doc) -> None:
    doc.edit("add", lambda m: m.bcs.append(CorrelationConvection(
        "cc", "cooled", "vplate_natural", "Air", T_inf=Constant(300.0),
    )))  # fmt: skip
    panel = form_panel(qtbot, doc, CorrelationConvection, ("bcs", 1), CorrelationPanel)
    combo = panel.editors["correlation"]
    assert combo.currentText() == CORRELATION_INFO["vplate_natural"].title
    assert combo.currentData() == "vplate_natural"
    choose(panel, "correlation", "hcyl_natural")
    assert doc.model.bcs[1].correlation == "hcyl_natural"
    assert texts_of(panel.editors["face_direction"]) == [
        "Facing up", "Facing down", "(automatic)",
    ]
    assert texts_of(panel.editors["wall_T_mode"]) == [
        "Local wall temperature", "Mean wall temperature",
    ]
    choose(panel, "wall_T_mode", "average")
    choose(panel, "face_direction", "down")
    assert (doc.model.bcs[1].wall_T_mode, doc.model.bcs[1].face_direction) == ("average", "down")


def test_geometry_kinds_have_readable_texts() -> None:
    assert choice_text("Boolean", "kind", "cut") == "Cut (subtract the tools)"
    assert choice_text("Boolean", "kind", "union") == "Union"
    assert choice_text("Boolean", "kind", "intersect") == "Intersection"
    kinds = ("translate", "rotate", "mirror", "scale")
    assert [choice_text("Transform", "kind", k) for k in kinds] == [
        "Move", "Rotate", "Mirror", "Scale",
    ]
    assert [choice_text("Import File", "format", k) for k in ("step", "brep", "dxf")] == [
        "STEP", "BREP", "DXF",
    ]
    assert choice_text("Boolean", "kind", "other") == "other"  # an unknown value is kept


def test_every_stored_choice_of_a_listed_field_has_a_text() -> None:
    from thermalfea.model.bcs import STREAM_CROSS_SECTIONS, STREAM_NU_OPTIONS

    assert set(CHOICE_TEXTS[("Stream", "cross_section")]) == set(STREAM_CROSS_SECTIONS)
    assert set(CHOICE_TEXTS[("Stream", "nu_option")]) == set(STREAM_NU_OPTIONS)
    assert set(CHOICE_TEXTS[("Correlation Convection", "correlation")]) == set(CORRELATION_INFO)


def test_network_branch_kind_is_readable(qtbot, doc) -> None:
    doc.edit("net", lambda m: setattr(m, "network", FlowNetwork(nodes=[NetNode("N1")])))
    panel = NetworkPanel(doc)
    qtbot.addWidget(panel)
    panel.add_node()
    assert panel.add_branch()
    combo = panel.branch_table.cellWidget(0, 3)
    assert texts_of(combo) == ["Duct", "Loss (K factor)"]
    combo.setCurrentIndex(1)
    combo.activated.emit(1)
    assert doc.model.network.branches[0].kind == "loss"


def test_dialogs_show_texts_and_keep_the_ids(qtbot) -> None:
    dialog = NewCorrelationConvectionDialog()
    qtbot.addWidget(dialog)
    box = dialog.correlation_box
    index = box.findData("vplate_natural")
    box.setCurrentIndex(index)
    assert box.currentText() == CORRELATION_INFO["vplate_natural"].title
    dialog.fluid_box.setCurrentText("Air")
    dialog.ambient_edit.setText("300")
    load = dialog.build_load()
    assert load.correlation == "vplate_natural"

    stream = NewStreamDialog()
    qtbot.addWidget(stream)
    stream.cross_box.setCurrentIndex(stream.cross_box.findData("annulus_inner"))
    assert stream.cross_box.currentText() == "Annulus, inner surface heated"
    assert stream.cross_box.currentData() == "annulus_inner"

    calc = HtcCalculator()
    qtbot.addWidget(calc)
    calc.correlation_box.setCurrentIndex(calc.correlation_box.findData("duct_internal"))
    assert calc.correlation == "duct_internal"
    assert calc.correlation_box.currentText() == CORRELATION_INFO["duct_internal"].title
    calc.cross_box.setCurrentIndex(calc.cross_box.findData("triangle"))
    assert calc.cross_box.currentText() == "Triangle"
    assert "area averaged over" in " ".join(
        label.text() for label in calc.findChildren(QLabel)
    )


# ------------------------------------------------------------ words for geometry (C9)
def test_view_menu_says_part_names(window, doc) -> None:
    class View:
        def set_overlay(self, layer: str, items: list[Any]) -> None: ...

    attach_labels(window, doc, View())
    assert window.actions[REGION_ACTION_ID].text().replace("&", "") == "Part names"


def test_toolbar_tooltips_have_no_shape_words(window) -> None:
    assert window.actions["select.curve"].toolTip() == "Pick boundaries"
    assert window.actions["select.surface"].toolTip() == "Pick parts"


def test_form_texts_say_part_and_boundary() -> None:
    tooltip = CONTACT_FORM.fields[0].tooltip
    assert "two parts" in tooltip and "curves" not in tooltip and "region" not in tooltip
    assert "between two parts" in CONTACT_FORM.description
    part = form_for(RegionAssignment)
    assert part.description == "A part: the material and thickness of the selection's parts."
    assert "surfaces" not in part.field("selection").tooltip
    assert "per part" in form_for(InitialCondition).field("kind").tooltip
    assert "curves" not in form_for(Stream).field("walls").tooltip


def test_selections_panel_kind_line_uses_role_words(window) -> None:
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5, id="plate")
    built = api.build(model)
    api.select_surfaces(model, built, "plate", where=lambda fp: True)
    top, bottom = curve_at(built, 0.5), curve_at(built, 0.0)
    api.select_curves(model, built, "cooled", tags=[top, bottom])
    api.select_curves(model, built, "spare", tags=[top])
    document = Document(model)
    document.set_built(built)
    view = SelectionView()
    tree, props = attach_tree(window, document, view)
    attach_loads(window, document, view)
    kinds = {}
    for name in ("cooled", "spare", "plate"):
        tree.select_address(("selections", name))
        assert isinstance(props.panel, SelectionPanel)
        kinds[name] = props.panel.kind_label.text()
    assert kinds == {"cooled": "2 boundaries", "spare": "1 boundary", "plate": "1 part"}


def test_part_summary_has_no_surface_count_and_enclosure_uses_role_words(doc) -> None:
    summary = ts.summary_for(doc, "regions", ("regions", 0))
    assert summary == "Copper (pure) · t 1 m"
    doc.edit("none", lambda m: m.regions.append(RegionAssignment("", "Copper (pure)", 1.0, 0.0)))
    assert ts.summary_for(doc, "regions", ("regions", 1)) == (
        "Copper (pure) · no selection · t 1 m"
    )
    doc.edit("enc", lambda m: m.enclosures.append(Enclosure(
        "box", [EnclosureSurface("cooled", 0.9)],
    )))  # fmt: skip
    assert ts.summary_for(doc, "enclosures", ("enclosures", 0)) == "1 boundary"
    doc.edit("enc2", lambda m: m.enclosures[0].surfaces.append(EnclosureSurface("cooled", 0.8)))
    assert ts.summary_for(doc, "enclosures", ("enclosures", 0)) == "2 boundaries"
    assert "surface" not in ts.summary_for(doc, "enclosures", ("enclosures", 0))


def test_initial_condition_summary_uses_the_panel_texts(doc) -> None:
    def kind(value: InitialCondition) -> str:
        doc.model.initial_condition = value
        return ts.initial_summary(doc.model)

    assert kind(InitialCondition("per_region", None, {})) == "per part"
    assert kind(InitialCondition("from_results", None, None, "r.h5")) == "from a results file"


def test_validation_messages_and_issue_objects_say_part(doc) -> None:
    doc.model.regions[0].material = "Unobtainium"
    issue = next(i for i in validate_model(doc.model) if i.code == "missing-material")
    assert issue.message == "part 'body' uses material 'Unobtainium', which is not in the model"
    assert issue.kind == "region"  # the code and the kind that maps to the tree do not change
    assert object_text(issue) == "part body"
    assert object_text(Issue("error", "x", "m", "bc", "cool")) == "load cool"
    assert object_text(Issue("error", "x", "m", "boundary condition", "cool")) == "load cool"
    assert object_text(Issue("error", "x", "m", "mesh", "")) == "mesh"
    doc.model.regions.clear()
    found = validate(doc.model, doc.built, None)
    unassigned = next(i for i in found if i.code == "no-region")
    assert "no part assignment" in unassigned.message and "region" not in unassigned.message
    assert object_text(unassigned) == "part"


# ----------------------------------------------------------------- symbols (decision H)
def test_symbol_table_and_labels_in_panels(qtbot, doc) -> None:
    fields = ("T", "q", "P", "Q", "h", "T_inf", "emissivity", "conductance")
    assert [symbol_of(n) for n in fields] == ["T", "q", "P", "Q", "h", "T∞", "ε", "h"]
    assert symbol_of("velocity") == "velocity" and "T_inf" in SYMBOLS
    panel = form_panel(qtbot, doc, Convection, ("bcs", 0))
    shown = " | ".join(label_texts(panel))
    assert "Heat-transfer coefficient h" in shown and "Fluid temperature T∞" in shown
    doc.edit("rad", lambda m: m.bcs.append(RadiationAmbient(
        "r", "cooled", emissivity=Constant(0.5), T_inf=Constant(300.0),
    )))  # fmt: skip
    radiation = form_panel(qtbot, doc, RadiationAmbient, ("bcs", 1))
    shown = " | ".join(label_texts(radiation))
    assert "Emissivity ε" in shown and "Ambient temperature T∞" in shown
    assert form_for(Convection).field("h").label == "Heat-transfer coefficient h"
    assert CONTACT_FORM.field("conductance").label == "Contact conductance h"


def test_other_load_labels_carry_their_symbols() -> None:
    from thermalfea.model.bcs import FixedTemperature, HeatFlow, HeatFlux, HeatGeneration, HeatPower

    labels = {
        FixedTemperature: ("T", "Temperature T"),
        HeatFlux: ("q", "Heat flux q"),
        HeatFlow: ("P", "Heat flow P"),
        HeatGeneration: ("Q", "Heat generation Q"),
        HeatPower: ("P", "Power P"),
    }
    for cls, (name, label) in labels.items():
        assert form_for(cls).field(name).label == label


def test_view_label_and_tree_summary_use_the_symbol(doc) -> None:
    bc = doc.model.bcs[0]
    assert label_text(bc, doc.model.display_units) == (
        "cool: h = 750 W/(m^2 K), T∞ = 273.15 K"
    )
    text = ts.summary_for(doc, "loads", ("bcs", 0))
    assert "T∞ " in text and "T_inf" not in text and "h 750" in text
