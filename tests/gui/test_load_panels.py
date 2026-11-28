"""M8.8: one panel per boundary-condition class, load symbols and the correlation panel."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from PySide6.QtWidgets import QComboBox

from thermalfea import api
from thermalfea.convection.correlation_info import CORRELATION_INFO
from thermalfea.convection.correlations import CORRELATIONS
from thermalfea.core import registry
from thermalfea.core.forms import form_for
from thermalfea.core.functions import Constant, Function, Table
from thermalfea.gui.document import Document
from thermalfea.gui.load_symbols import ACTION_ID, LoadSymbolController, attach_loads
from thermalfea.gui.panels import attach_tree, register_panel
from thermalfea.gui.property_panels.correlation import CorrelationPanel
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.scene import KIND_COLORS, LoadSymbol
from thermalfea.gui.viewport_mpl import MplSceneView
from thermalfea.materials import library
from thermalfea.model import bcs
from thermalfea.model.bcs import (
    Adiabatic,
    Convection,
    CorrelationConvection,
    HeatFlux,
    HeatGeneration,
)

# ------------------------------------------------------------------------------ helpers


class FakeView:
    """Records what the controller sends through the ``SceneView`` interface."""

    def __init__(self) -> None:
        self.symbol_calls: list[list[LoadSymbol]] = []
        self.highlights: list[tuple[int, list[int]]] = []

    @property
    def symbols(self) -> list[LoadSymbol]:
        return self.symbol_calls[-1] if self.symbol_calls else []

    def set_symbols(self, symbols: list[LoadSymbol]) -> None:
        self.symbol_calls.append(list(symbols))

    def set_entity_colors(self, dim, colors, legend) -> None: ...

    def set_overlay(self, layer: str, items: list) -> None:
        pass

    def highlight(self, dim: int, tags: list[int]) -> None:
        self.highlights.append((dim, list(tags)))


def edge(model, built, name: str, side: str) -> None:
    """Select one edge of the 1 x 0.5 rectangle: bottom, top, left or right."""
    where = {
        "bottom": lambda fp: abs(fp.center[1]) < 1e-9,
        "top": lambda fp: abs(fp.center[1] - 0.5) < 1e-9,
        "left": lambda fp: abs(fp.center[0]) < 1e-9,
        "right": lambda fp: abs(fp.center[0] - 1.0) < 1e-9,
    }[side]
    api.select_curves(model, built, name, where)


@pytest.fixture
def built_doc(qtbot) -> Document:
    """A built 1 x 0.5 rectangle with four edge selections and no conditions."""
    model = api.new_model(name="plate")
    api.Geometry(model).rectangle(0.0, 0.0, 1.0, 0.5, id="plate")
    built = api.build(model)
    for side in ("bottom", "top", "left", "right"):
        edge(model, built, side, side)
    api.select_surfaces(model, built, "body", lambda fp: True)
    doc = Document(model)
    doc.set_built(built)
    return doc


def tags_of(doc: Document, name: str) -> list[int]:
    return list(doc.model.selections[name].tags)


def two_loads(doc: Document) -> None:
    def mutate(m) -> None:
        m.bcs.append(HeatFlux("Flux", "bottom", q=Constant(100.0)))
        m.bcs.append(Convection("Conv", "top", h=Constant(10.0), T_inf=Constant(300.0)))
        m.bcs.append(HeatFlux("Hidden", "left", q=Constant(5.0), active=False))

    doc.edit("Add loads", mutate)


# ----------------------------------------------------------- a panel for every BC class


def sample_value(field, current):
    """A value for a field of a different kind, valid for it."""
    if field.kind == "function":
        return Constant(123.0) if current != Constant(123.0) else Constant(124.0)
    if field.kind in ("float", "int"):
        return 2.0 if current != 2.0 else 3.0
    if field.kind == "bool":
        return not current
    if field.kind == "choice":
        return next(c for c in field.choices if c != current)
    if field.kind == "dict":
        return {"a": 1.0}
    if field.kind == "str":
        return "abc"
    return "bottom"  # selection


@pytest.mark.parametrize("tag", registry.bc_tags())
def test_every_registered_bc_class_has_a_working_panel(qtbot, window, built_doc, tag) -> None:
    tree, controller = attach_tree(window, built_doc)
    tree.add_bc(tag)
    assert built_doc.undo_stack.count() == 1
    panel = controller.panel
    assert isinstance(panel, FormPanel) and controller.current_address == ("bcs", 0)
    spec = form_for(registry.class_by_tag("bc", tag))
    assert set(panel.editors) == {f.name for f in spec.fields} and spec.fields
    # one edit of one field is one undo step
    field = next((f for f in spec.fields if f.kind != "selection"), spec.fields[0])
    before = built_doc.undo_stack.count()
    assert panel.apply(field.name, sample_value(field, getattr(built_doc.model.bcs[0], field.name)))
    assert built_doc.undo_stack.count() == before + 1
    # and so is a change of the selection
    assert panel.apply("selection", "top") and built_doc.undo_stack.count() == before + 2
    built_doc.undo_stack.undo()
    assert built_doc.model.bcs[0].selection != "top"


def test_panel_registry_chooses_the_correlation_panel(qtbot, window, built_doc) -> None:
    tree, controller = attach_tree(window, built_doc)
    tree.add_bc("correlation_convection")
    assert isinstance(controller.panel, CorrelationPanel)
    tree.add_bc("convection")
    assert type(controller.panel) is FormPanel

    @dataclass
    class Special(bcs.BoundaryCondition):
        power: Function

    class SpecialPanel(FormPanel):
        pass

    registry.register_bc("test_special_panel", Special)
    register_panel(Special, lambda c, spec, address: SpecialPanel(spec, c.document, address))
    try:
        tree.add_bc("test_special_panel")
        assert isinstance(controller.panel, SpecialPanel)
    finally:
        registry._CLASSES["bc"].pop("test_special_panel")
        registry._BCS.pop("test_special_panel")
        from thermalfea.gui import panels

        panels._PANELS.pop(Special)


def test_correlation_and_fluid_are_lists(qtbot, built_doc) -> None:
    built_doc.edit(
        "add",
        lambda m: m.bcs.append(
            CorrelationConvection("C", "top", "vplate_natural", "Air", T_inf=Constant(300.0))
        ),
    )
    panel = CorrelationPanel(form_for(CorrelationConvection), built_doc, ("bcs", 0))
    qtbot.addWidget(panel)
    corr, fluid = panel.editors["correlation"], panel.editors["fluid"]
    assert isinstance(corr, QComboBox) and isinstance(fluid, QComboBox)
    # every correlation except the internal-flow ones, which streams use (M11.29)
    offered = [corr.itemText(i) for i in range(corr.count())]
    assert offered == [c for c, info in CORRELATIONS.items() if info.kind != "internal"]
    assert "duct_internal" not in offered
    assert [fluid.itemText(i) for i in range(fluid.count())] == library.fluid_names()
    assert corr.currentText() == "vplate_natural" and fluid.currentText() == "Air"
    fluid.setCurrentIndex(fluid.findText("Water"))
    fluid.activated.emit(fluid.currentIndex())
    assert built_doc.model.bcs[0].fluid == "Water" and built_doc.undo_stack.count() == 2
    # a value outside the list is kept visible, not replaced
    built_doc.edit("odd", lambda m: setattr(m.bcs[0], "fluid", "Helium"))
    assert fluid.currentText() == "Helium"


# ------------------------------------------------------------------------------ symbols


def test_symbols_follow_the_active_conditions(qtbot, window, built_doc) -> None:
    view = FakeView()
    ctl = LoadSymbolController(window, built_doc, view)
    assert view.symbols == []
    two_loads(built_doc)
    flux_color = view.symbols[0].color
    assert view.symbols == [
        LoadSymbol("heat_flux", "Flux", 1, tags_of(built_doc, "bottom"), flux_color),
        LoadSymbol("convection", "Conv", 1, tags_of(built_doc, "top"), view.symbols[1].color),
    ]
    assert view.symbols[0].color != view.symbols[1].color
    assert ctl.symbols == view.symbols

    # suppress / unsuppress
    built_doc.edit("suppress", lambda m: setattr(m.bcs[0], "active", False))
    assert [s.label for s in view.symbols] == ["Conv"]
    built_doc.edit("unsuppress", lambda m: setattr(m.bcs[2], "active", True))
    assert [s.label for s in view.symbols] == ["Conv", "Hidden"]
    built_doc.undo_stack.undo()
    built_doc.undo_stack.undo()
    assert [s.label for s in view.symbols] == ["Flux", "Conv"]

    # delete and undo
    built_doc.edit("delete", lambda m: m.bcs.pop(1))
    assert [s.label for s in view.symbols] == ["Flux"]
    built_doc.undo_stack.undo()
    assert [s.label for s in view.symbols] == ["Flux", "Conv"]

    # an empty or unknown selection draws nothing
    built_doc.edit("blank", lambda m: setattr(m.bcs[0], "selection", ""))
    built_doc.edit("unknown", lambda m: setattr(m.bcs[1], "selection", "nowhere"))
    assert view.symbols == []
    built_doc.undo_stack.undo()
    built_doc.undo_stack.undo()

    # a rebuild updates them (geometry_built)
    calls = len(view.symbol_calls)
    built_doc.set_built(api.build(built_doc.model))
    assert len(view.symbol_calls) > calls
    assert [s.label for s in view.symbols] == ["Flux", "Conv"]


def test_symbols_need_a_built_geometry(qtbot, window) -> None:
    model = api.new_model()
    model.bcs.append(HeatFlux("Flux", "bottom", q=Constant(1.0)))
    doc = Document(model)
    view = FakeView()
    LoadSymbolController(window, doc, view)
    assert view.symbols == []


def test_a_condition_on_surfaces_and_two_dimensions(qtbot, window, built_doc) -> None:
    view = FakeView()
    LoadSymbolController(window, built_doc, view)
    built_doc.edit(
        "add",
        lambda m: m.bcs.extend(
            [HeatGeneration("Gen", "body", Q=Constant(1e3)), Adiabatic("Adi", "right")]
        ),
    )
    assert [(s.kind, s.dim) for s in view.symbols] == [("heat_generation", 2), ("adiabatic", 1)]


def test_toggle_action_hides_and_shows(qtbot, window, built_doc) -> None:
    view = FakeView()
    ctl = attach_loads(window, built_doc, view)
    assert isinstance(ctl, LoadSymbolController)
    action = window.actions[ACTION_ID]
    assert action is ctl.action and action.isCheckable() and action.isChecked()
    assert action in window.menus["view"].actions()
    two_loads(built_doc)
    assert len(view.symbols) == 2
    action.setChecked(False)
    assert view.symbols == []
    built_doc.edit("more", lambda m: m.bcs.append(HeatFlux("F2", "right", q=Constant(1.0))))
    assert view.symbols == []  # still hidden
    action.setChecked(True)
    assert [s.label for s in view.symbols] == ["Flux", "Conv", "F2"]


def test_tree_selection_highlights_the_load(qtbot, window, built_doc) -> None:
    view = FakeView()
    tree, _ = attach_tree(window, built_doc)
    two_loads(built_doc)
    attach_loads(window, built_doc, view)
    tree.setCurrentItem(tree.item_for(("bcs", 1)))
    assert view.highlights[-1] == (1, tags_of(built_doc, "top"))


def test_distinct_stable_colors_and_a_legend_in_the_real_view(qtbot, window, built_doc) -> None:
    view = MplSceneView()
    qtbot.addWidget(view.widget())
    view.set_geometry(built_doc.built)
    attach_loads(window, built_doc, view)
    built_doc.edit(
        "add",
        lambda m: m.bcs.extend(
            [
                HeatFlux("F1", "bottom", q=Constant(1.0)),
                HeatFlux("F2", "left", q=Constant(1.0)),
                Convection("C1", "top", h=Constant(1.0), T_inf=Constant(300.0)),
                Adiabatic("A1", "right"),
            ]
        ),
    )
    artists = view.layer_artists("symbols")
    assert len(artists) == 4 + 1  # four symbols and one legend
    legend = artists[-1]
    assert [t.get_text() for t in legend.get_texts()] == ["heat_flux", "convection", "adiabatic"]
    colors = [h.get_color() for h in legend.legend_handles]
    assert len(set(colors)) == 3
    # the color of a kind does not depend on which other kinds are present
    built_doc.edit("drop", lambda m: m.bcs.pop(0))
    legend = view.layer_artists("symbols")[-1]
    pairs = zip(legend.get_texts(), legend.legend_handles, strict=True)
    again = {t.get_text(): h.get_color() for t, h in pairs}
    assert again["convection"] == colors[1] and again["adiabatic"] == colors[2]


def test_a_new_load_class_gets_panel_symbol_color_and_legend(qtbot, window, built_doc) -> None:
    @dataclass
    class WallPower(bcs.BoundaryCondition):
        power: Function

    registry.register_bc("test_wall_power_sym", WallPower)
    try:
        view = MplSceneView()
        qtbot.addWidget(view.widget())
        view.set_geometry(built_doc.built)
        tree, controller = attach_tree(window, built_doc, view)
        attach_loads(window, built_doc, view)
        tree.add_bc("test_wall_power_sym")
        assert isinstance(controller.panel, FormPanel)
        assert set(controller.panel.editors) == {"selection", "power"}
        assert controller.panel.apply("selection", "left")
        built_doc.edit("a", lambda m: m.bcs.append(HeatFlux("F", "top", q=Constant(1.0))))
        legend = view.layer_artists("symbols")[-1]
        names = [t.get_text() for t in legend.get_texts()]
        assert "test_wall_power_sym" in names
        colors = dict(zip(names, (h.get_color() for h in legend.legend_handles), strict=True))
        assert colors["test_wall_power_sym"] in KIND_COLORS
        assert colors["test_wall_power_sym"] != colors["heat_flux"]
    finally:
        registry._CLASSES["bc"].pop("test_wall_power_sym")
        registry._BCS.pop("test_wall_power_sym")


def test_every_kind_gets_a_distinct_color() -> None:
    from thermalfea.gui.load_symbols import color_of

    tags = registry.bc_tags()
    assert len(KIND_COLORS) >= len(tags) + 1
    assert len({color_of(t) for t in tags}) == len(tags)


# ------------------------------------------------------------------ correlation panel


def make_panel(qtbot, doc: Document, **fields):
    bc = dict(correlation="vplate_natural", fluid="Air", T_inf=Constant(300.0))
    bc.update(fields)
    doc.edit("add", lambda m: m.bcs.append(CorrelationConvection("Cc", "top", **bc)))
    panel = CorrelationPanel(form_for(CorrelationConvection), doc, ("bcs", len(doc.model.bcs) - 1))
    qtbot.addWidget(panel)
    return panel


@pytest.mark.parametrize("cid", list(CORRELATIONS))
def test_panel_shows_formula_and_validity_of_every_correlation(qtbot, built_doc, cid) -> None:
    panel = make_panel(qtbot, built_doc)
    panel.apply("correlation", cid)  # False when it is the current one already
    info = CORRELATION_INFO[cid]
    assert info.formula in panel.formula_label.text()
    assert info.validity in panel.validity_label.text()
    assert info.title == panel.title_label_info.text()
    assert info.length in panel.length_label.text()
    assert panel.editors["correlation"].currentText() == cid


def test_unknown_correlation_is_reported_not_raised(qtbot, built_doc) -> None:
    panel = make_panel(qtbot, built_doc, correlation="nonsense")
    assert "nonsense" in panel.title_label_info.text()
    panel.set_preview_input("T_surface", 350.0)
    assert panel.preview_h is None


def test_natural_convection_preview_equals_api_htc(qtbot, built_doc) -> None:
    panel = make_panel(qtbot, built_doc, char_length=0.5)
    assert panel.preview_h is None and "surface temperature" in panel.preview_text
    panel.set_preview_input("T_surface", 350.0)
    expected = api.htc("vplate_natural", "Air", 350.0, 300.0, length=0.5, multiplier=1.0)
    assert panel.preview_h == expected.h
    assert panel.preview_result == expected
    for text in ("h =", "Nu =", "Ra =", "Pr =", "Regime:", "T_film = 325"):
        assert text in panel.preview_text
    assert "Re =" not in panel.preview_text
    # length comes from the condition, so the preview does not ask for it
    assert "length" not in panel.needed_inputs() and "T_surface" in panel.needed_inputs()
    # a change of a field refreshes the preview
    assert panel.apply("multiplier", 2.0)
    assert panel.preview_h == pytest.approx(2.0 * expected.h, rel=1e-12)
    assert panel.apply("fluid", "Water")
    water = api.htc("vplate_natural", "Water", 350.0, 300.0, length=0.5, multiplier=2.0)
    assert panel.preview_h == water.h
    assert panel.apply("char_length", None)  # now the length must be typed
    assert panel.preview_h is None and "length" in panel.needed_inputs()
    panel.set_preview_input("length", 0.25)
    assert panel.preview_h == api.htc(
        "vplate_natural", "Water", 350.0, 300.0, length=0.25, multiplier=2.0
    ).h


def test_forced_convection_preview_and_missing_velocity(qtbot, built_doc) -> None:
    panel = make_panel(
        qtbot, built_doc, correlation="plate_forced_avg", char_length=1.0, velocity=Constant(2.0)
    )
    panel.set_preview_input("T_surface", 350.0)
    expected = api.htc(
        "plate_forced_avg", "Air", 350.0, 300.0, length=1.0, velocity=2.0, multiplier=1.0
    )
    assert panel.preview_h == expected.h and "Re =" in panel.preview_text
    assert "velocity" not in panel.needed_inputs()
    # no velocity in the condition: the preview asks for one, and api.htc's error is shown
    assert panel.apply("velocity", None)
    assert "velocity" in panel.needed_inputs()
    assert panel.preview_h is None
    assert "Cannot compute h" in panel.preview_text and "velocity" in panel.preview_text
    panel.set_preview_input("velocity", 3.0)
    assert panel.preview_h == api.htc(
        "plate_forced_avg", "Air", 350.0, 300.0, length=1.0, velocity=3.0, multiplier=1.0
    ).h


def test_preview_with_typed_distance_and_table_temperature(qtbot, built_doc) -> None:
    table = Table([0.0, 10.0], [290.0, 310.0], "t")
    panel = make_panel(
        qtbot, built_doc, correlation="plate_forced_local", velocity=Constant(1.5), T_inf=table
    )
    assert {"T_inf", "x", "T_surface"} <= set(panel.needed_inputs())
    panel.set_preview_input("T_surface", 340.0)
    panel.set_preview_input("T_inf", 300.0)
    panel.set_preview_input("x", 0.3)
    expected = api.htc(
        "plate_forced_local", "Air", 340.0, 300.0, x=0.3, velocity=1.5, multiplier=1.0
    )
    assert panel.preview_h == expected.h


def test_power_law_uses_params_and_no_fluid(qtbot, built_doc) -> None:
    panel = make_panel(
        qtbot, built_doc, correlation="power_law", fluid="", params={"C": 2.0, "n": 0.25}
    )
    panel.set_preview_input("T_surface", 340.0)
    assert panel.preview_h == api.htc("power_law", None, 340.0, 300.0, C=2.0, n=0.25).h
    assert "Nu =" not in panel.preview_text


def test_validity_warnings_are_displayed(qtbot, built_doc) -> None:
    panel = make_panel(
        qtbot, built_doc, correlation="hplate_up_natural", char_length=0.001, face_direction="up"
    )
    panel.set_preview_input("T_surface", 310.0)
    expected = api.htc(
        "hplate_up_natural", "Air", 310.0, 300.0, length=0.001, face_direction="up",
        multiplier=1.0,
    )
    assert expected.warnings
    assert panel.preview_h == expected.h
    for warning in expected.warnings:
        assert f"Warning: {warning}" in panel.preview_text


def test_preview_respects_display_units_and_survives_bad_input(qtbot, built_doc) -> None:
    panel = make_panel(qtbot, built_doc, char_length=0.5)
    built_doc.edit("units", lambda m: setattr(m.display_units, "temperature", "degC"))
    edit = panel.preview_edits["T_surface"]
    panel.set_preview_input("T_surface", 350.0)
    assert float(edit.text()) == pytest.approx(76.85)
    assert "T_film = 51.85" in panel.preview_text and "°C" in panel.preview_text
    edit.setText("abc")
    edit.editingFinished.emit()
    assert edit.error_text() and panel.preview_h is not None  # no exception; the last result stays
    edit.setText("100")  # typed in degC
    edit.editingFinished.emit()
    assert panel.preview_h == api.htc(
        "vplate_natural", "Air", 373.15, 300.0, length=0.5, multiplier=1.0
    ).h
    panel.set_preview_input("T_surface", 0.0)  # api.htc refuses a non-positive temperature
    assert panel.preview_h is None and "Cannot compute h" in panel.preview_text


def test_selecting_another_object_clears_the_load_highlight(qtbot, window, built_doc) -> None:
    """Seen on a real screen: a load's highlight stayed while the mesh panel was shown."""
    view = FakeView()
    tree, _ = attach_tree(window, built_doc)
    two_loads(built_doc)
    attach_loads(window, built_doc, view)
    tree.setCurrentItem(tree.item_for(("bcs", 1)))
    assert view.highlights[-1] == (1, tags_of(built_doc, "top"))
    tree.setCurrentItem(tree.item_for(("mesh_settings",)))
    assert view.highlights[-1] == (1, [])


def test_overlay_colors_are_not_load_colors() -> None:
    """An orange selection on a convection edge looked like an adiabatic edge."""
    from thermalfea.gui import viewport_mpl
    from thermalfea.gui.scene import KIND_COLORS

    for color in (viewport_mpl._SELECT_COLOR, viewport_mpl._HOVER_COLOR):
        assert color.lower() not in {c.lower() for c in KIND_COLORS}
