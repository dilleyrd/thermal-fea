"""M11.45: region highlight, region names and load values as viewport labels."""

from __future__ import annotations

from typing import Any

import pytest

from thermalfea import api
from thermalfea.core.functions import Constant, Expression, Table
from thermalfea.core.units import UnitSettings
from thermalfea.gui.document import Document
from thermalfea.gui.load_symbols import attach_loads
from thermalfea.gui.overlay_labels import (
    LOAD_ACTION_ID,
    LOAD_LAYER,
    REGION_ACTION_ID,
    REGION_LAYER,
    attach_labels,
)
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.scene import OverlayText
from thermalfea.model.bcs import Convection, FixedTemperature, HeatFlux


class FakeView:
    """Records the overlay layers and highlights sent through the SceneView interface."""

    def __init__(self) -> None:
        self.layers: dict[str, list[Any]] = {}
        self.highlights: list[tuple[int, list[int]]] = []

    def set_symbols(self, symbols: Any) -> None: ...

    def set_entity_colors(self, dim, colors, legend) -> None: ...

    def set_overlay(self, layer: str, items: list[Any]) -> None:
        self.layers[layer] = list(items)

    def highlight(self, dim: int, tags: list[int]) -> None:
        self.highlights.append((dim, list(tags)))

    def texts(self, layer: str = LOAD_LAYER) -> list[str]:
        return [i.text for i in self.layers.get(layer, [])]


@pytest.fixture
def doc(qtbot) -> Document:
    """Two side-by-side squares (left, right) with a region each, edge selections."""
    model = api.new_model(name="two")
    g = api.Geometry(model)
    g.rectangle(0.0, 0.0, 1.0, 1.0, id="left")
    g.rectangle(1.0, 0.0, 3.0, 1.0, id="right")
    built = api.build(model)
    api.select_surfaces(model, built, "L", lambda fp: fp.center[0] < 1.0)
    api.select_surfaces(model, built, "R", lambda fp: fp.center[0] > 1.0)
    api.select_curves(model, built, "top", lambda fp: abs(fp.center[1] - 1.0) < 1e-9)
    api.select_curves(model, built, "bottom", lambda fp: abs(fp.center[1]) < 1e-9)
    api.assign_region(model, "L", "Copper (pure)")
    api.assign_region(model, "R", "Zinc")
    document = Document(model)
    document.set_built(built)
    return document


def add(doc: Document, *conditions: Any) -> None:
    doc.edit("add", lambda m: m.bcs.extend(conditions))


def make(window, doc):
    view = FakeView()
    ctl = attach_labels(window, doc, view)
    return view, ctl


def test_toggle_defaults_and_ids(window, doc) -> None:
    add(doc, HeatFlux("q1", "top", q=Constant(100.0)))
    view, ctl = make(window, doc)
    assert window.actions[REGION_ACTION_ID] is ctl.region_action
    assert window.actions[LOAD_ACTION_ID] is ctl.load_action
    assert not ctl.region_action.isChecked() and ctl.load_action.isChecked()
    assert view.layers[REGION_LAYER] == [] and len(view.layers[LOAD_LAYER]) == 1
    ctl.region_action.setChecked(True)
    assert len(view.layers[REGION_LAYER]) == 2
    ctl.load_action.setChecked(False)
    assert view.layers[LOAD_LAYER] == []
    ctl.region_action.setChecked(False)
    assert view.layers[REGION_LAYER] == []


def test_region_names_at_the_area_weighted_centre(window, doc) -> None:
    view, ctl = make(window, doc)
    ctl.region_action.setChecked(True)
    items = {i.text: i for i in view.layers[REGION_LAYER]}
    assert set(items) == {"L", "R"}  # the part names (M11.56); unnamed parts show their selection
    assert all(isinstance(i, OverlayText) for i in items.values())
    left = items["L"]
    assert (left.x, left.y) == pytest.approx((0.5, 0.5))
    assert (items["R"].x, items["R"].y) == pytest.approx((2.5, 0.5))


def test_label_text_constant_in_si_and_degc(window, doc) -> None:
    add(doc, Convection("cooling", "top", h=Constant(750.0), T_inf=Constant(300.0)))
    view, _ctl = make(window, doc)
    assert view.texts() == ["cooling: h = 750 W/(m^2 K), T∞ = 300 K"]
    doc.edit("zero", lambda m: setattr(m.bcs[0], "T_inf", Constant(273.15)))
    doc.edit("units", lambda m: setattr(m, "display_units", UnitSettings(temperature="degC")))
    assert view.texts() == ["cooling: h = 750 W/(m^2 K), T∞ = 0 °C"]


def test_label_text_table_and_expression(window, doc) -> None:
    add(
        doc,
        Convection(
            "mixed", "top", h=Table([0.0, 10.0], [5.0, 50.0], "t"), T_inf=Expression("300 + 2*t")
        ),
        HeatFlux("flux", "bottom", q=Table([300.0, 400.0], [1.0, 2.0], "T")),
    )
    view, _ctl = make(window, doc)
    assert view.texts() == ["mixed: h = table(t), T∞ = 300 + 2*t", "flux: q = table(T)"]


def test_label_position_is_at_the_longest_curve_midpoint(window, doc) -> None:
    add(doc, FixedTemperature("fixed", "top", T=Constant(300.0)))
    view, _ctl = make(window, doc)
    (item,) = view.layers[LOAD_LAYER]
    assert item.y == pytest.approx(1.0)
    assert 0.0 < item.x < 4.0


def test_labels_follow_undo_suppress_and_rename(window, qtbot, doc) -> None:
    view, _ctl = make(window, doc)
    assert view.texts() == []
    add(doc, HeatFlux("q1", "top", q=Constant(100.0)))
    assert view.texts() == ["q1: q = 100 W/m^2"]
    doc.undo_stack.undo()
    assert view.texts() == []
    doc.undo_stack.redo()
    assert view.texts() == ["q1: q = 100 W/m^2"]
    doc.edit("suppress", lambda m: setattr(m.bcs[0], "active", False))
    assert view.texts() == []
    doc.edit("unsuppress", lambda m: setattr(m.bcs[0], "active", True))
    doc.edit("rename", lambda m: setattr(m.bcs[0], "name", "renamed"))
    assert view.texts() == ["renamed: q = 100 W/m^2"]


def test_no_labels_without_a_built_geometry(window, doc) -> None:
    add(doc, HeatFlux("q1", "top", q=Constant(100.0)))
    view, ctl = make(window, doc)
    ctl.region_action.setChecked(True)
    doc.set_built(None)
    assert view.layers[REGION_LAYER] == [] and view.layers[LOAD_LAYER] == []


def test_region_and_material_highlight(window, doc) -> None:
    api.assign_region(doc.model, "R", "Copper (pure)")  # both regions now use Copper
    doc.edit("same material", lambda m: None)
    view = FakeView()
    attach_tree(window, doc)
    ctl = attach_loads(window, doc, view)
    left = list(doc.model.selections["L"].tags)
    right = list(doc.model.selections["R"].tags)
    ctl.highlight_address(("regions", 0))
    assert view.highlights[-1] == (2, left)
    ctl.highlight_address(("regions", 1))
    assert view.highlights[-1] == (2, right)
    ctl.highlight_address(("materials", "Copper (pure)"))
    assert view.highlights[-1] == (2, sorted(left + right))
    ctl.highlight_address(("materials", "Nothing"))
    assert view.highlights[-1] == (1, [])
    ctl.highlight_address(("materials",))
    assert view.highlights[-1] == (1, [])
    ctl.highlight_address(("regions", 7))
    assert view.highlights[-1] == (1, [])
