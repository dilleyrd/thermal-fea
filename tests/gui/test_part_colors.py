"""M11.62: color by part / material (``SceneView.set_entity_colors``)."""

from __future__ import annotations

import numpy as np
import pytest

from thermalfea import api
from thermalfea.core.meshgen import rect_mesh
from thermalfea.gui.document import Document
from thermalfea.gui.part_colors import (
    MATERIAL_ACTION_ID,
    NONE_ACTION_ID,
    PART_ACTION_ID,
    PartColorController,
    color_of_material,
    color_of_part,
)
from thermalfea.gui.scene import FieldDisplay, LoadSymbol, SceneView
from thermalfea.gui.viewport_mpl import MplSceneView
from thermalfea.post.plots import display_triangulation

COPPER = "Copper (pure)"
ALUMINUM = "Aluminum, Alloy 2024-T6"


class RecordingView:
    """Records ``set_entity_colors``; the rest of the protocol is not needed here."""

    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[int, str], list[tuple[str, str]]]] = []

    def set_entity_colors(self, dim, colors, legend) -> None:
        self.calls.append((dim, dict(colors), list(legend)))

    @property
    def last(self):
        return self.calls[-1]


def stacked(materials=(COPPER, ALUMINUM)) -> Document:
    model = api.new_model(name="stack")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 0.6, 0.2)
    geo.rectangle(0.0, 0.2, 0.6, 0.8)
    built = api.build(model)
    api.select_surfaces(model, built, "lower", where=lambda s: s.bbox[4] < 0.21)
    api.select_surfaces(model, built, "upper", where=lambda s: s.bbox[1] > 0.19)
    api.assign_region(model, "lower", material=materials[0])
    api.assign_region(model, "upper", material=materials[1])
    document = Document(model)
    document.set_built(built)
    return document


@pytest.fixture
def setup(window):
    document = stacked()
    view = RecordingView()
    controller = PartColorController(window, document, view)
    return window, document, view, controller


def tags_of(document: Document, name: str) -> list[int]:
    return [int(t) for t in document.model.selections[name].tags]


def test_actions_and_default_mode(setup) -> None:
    window, _, view, controller = setup
    for key in (PART_ACTION_ID, MATERIAL_ACTION_ID, NONE_ACTION_ID):
        assert window.actions[key].isCheckable()
    assert window.actions[PART_ACTION_ID].isChecked() and controller.mode == "part"
    assert any(a.menu() is controller.menu for a in window.menus["view"].actions())
    assert isinstance(view, SceneView) is False  # a partial fake; only the call matters


def test_part_mode_colors_each_region(setup) -> None:
    _, document, view, _ = setup
    dim, colors, legend = view.last
    lower, upper = tags_of(document, "lower"), tags_of(document, "upper")
    assert dim == 2
    assert set(colors) == set(lower) | set(upper)
    assert colors[lower[0]] != colors[upper[0]]
    assert colors[lower[0]] == color_of_part(0) and colors[upper[0]] == color_of_part(1)
    assert [label for label, _ in legend] == ["lower", "upper"]
    assert [c for _, c in legend] == [colors[lower[0]], colors[upper[0]]]


def test_material_mode_groups_by_material(setup) -> None:
    window, document, view, _ = setup
    window.actions[MATERIAL_ACTION_ID].setChecked(True)
    _, colors, legend = view.last
    lower, upper = tags_of(document, "lower")[0], tags_of(document, "upper")[0]
    assert colors[lower] == color_of_material(COPPER, document.model)
    assert colors[upper] == color_of_material(ALUMINUM, document.model)
    assert colors[lower] != colors[upper]
    assert [label for label, _ in legend] == [COPPER, ALUMINUM]


def test_model_change_updates_the_grouping(setup) -> None:
    window, document, view, _ = setup
    window.actions[MATERIAL_ACTION_ID].setChecked(True)
    document.edit("same material", lambda m: setattr(m.regions[1], "material", COPPER))
    _, colors, legend = view.last
    assert len(set(colors.values())) == 1
    assert [label for label, _ in legend] == [COPPER]


def test_none_clears_and_part_restores(setup) -> None:
    window, _, view, _ = setup
    window.actions[NONE_ACTION_ID].setChecked(True)
    assert view.last[1] == {} and view.last[2] == []
    window.actions[PART_ACTION_ID].setChecked(True)
    assert len(view.last[1]) == 2


def test_no_build_clears(window) -> None:
    document = Document(api.new_model())
    view = RecordingView()
    PartColorController(window, document, view)
    assert view.last[1] == {} and view.last[2] == []


def test_stale_selection_is_skipped(setup) -> None:
    _, document, view, _ = setup
    document.edit("move", lambda m: setattr(m.geometry[0], "width", 0.5))
    document.set_built(None)
    assert view.last[1] == {}


# ----------------------------------------------------------------- the real viewport


@pytest.fixture
def real(qtbot):
    v = MplSceneView()
    qtbot.addWidget(v.widget())
    v.widget().resize(640, 480)
    return v


def holed():
    model = api.new_model()
    g = api.Geometry(model)
    g.rectangle(0, 0, 4, 2, id="plate")
    g.circle(2, 1, 0.5, id="hole")
    g.cut(["plate"], ["hole"])
    g.rectangle(4, 0, 2, 2, id="side")
    return api.build(model)


def fill_artists(view):
    return view.layer_artists("entity_colors")


def test_protocol_has_set_entity_colors(real) -> None:
    assert isinstance(real, SceneView)


def test_fills_are_drawn_for_the_given_tags(real) -> None:
    built = holed()
    real.set_geometry(built)
    tags = sorted(built.surfaces)
    real.set_entity_colors(2, {tags[0]: "#ff0000"}, [("one", "#ff0000")])
    fills = [a for a in fill_artists(real) if hasattr(a, "get_paths")]
    assert len(fills) == 1 and len(fills[0].get_paths()) == 1
    assert fills[0].get_zorder() > 1.0
    assert fills[0].get_zorder() < real.axes.collections[-1].get_zorder() + 10
    legends = [a for a in fill_artists(real) if not hasattr(a, "get_paths")]
    assert len(legends) == 1 and [t.get_text() for t in legends[0].get_texts()] == ["one"]
    real.set_entity_colors(2, {}, [])
    assert fill_artists(real) == []


def test_a_surface_with_a_hole_keeps_the_hole(real) -> None:
    built = holed()
    real.set_geometry(built)
    holed_tag = next(t for t, fp in built.surfaces.items() if fp.bbox[3] < 4.1)
    real.set_entity_colors(2, {holed_tag: "#00aa00"}, [("plate", "#00aa00")])
    path = fill_artists(real)[0].get_paths()[0]
    loops = int(np.sum(path.codes == path.CLOSEPOLY))
    assert loops == 2
    # the hole is a loop around its centre wound against the outer loop (non-zero winding
    # sum 0 there, which is what the renderer leaves empty)
    ends = np.flatnonzero(path.codes == path.CLOSEPOLY)
    outer, hole = (path.vertices[a:b] for a, b in zip([0, ends[0] + 1], ends, strict=True))

    def area(v):
        return 0.5 * float(np.sum(v[:-1, 0] * v[1:, 1] - v[1:, 0] * v[:-1, 1]))

    assert area(outer) * area(hole) < 0.0
    from matplotlib.path import Path as MplPath

    assert MplPath(outer).contains_point((2.0, 1.0)) and MplPath(hole).contains_point((2.0, 1.0))
    assert not MplPath(hole).contains_point((1.0, 1.0))


def test_fills_hide_while_a_field_is_shown(real) -> None:
    built = holed()
    real.set_geometry(built)
    real.set_entity_colors(2, {t: "#123456" for t in built.surfaces}, [("all", "#123456")])
    assert all(a.get_visible() for a in fill_artists(real))
    mesh = rect_mesh(0.0, 0.0, 6.0, 2.0, 6, 2, "T3")
    dm = display_triangulation(mesh)
    spec = FieldDisplay(
        xy=mesh.nodes[:, :2], triangles=dm.triangles, values=mesh.nodes[:, 0],
        vmin=0.0, vmax=6.0, levels=4,
    )
    real.set_field(spec)
    assert fill_artists(real) and not any(a.get_visible() for a in fill_artists(real))
    real.set_field(None)
    assert all(a.get_visible() for a in fill_artists(real))


def test_load_legend_is_kept_and_geometry_clears(real) -> None:
    built = holed()
    real.set_geometry(built)
    real.set_symbols([LoadSymbol("temperature", "hot", 1, [sorted(built.curves)[0]])])
    real.set_entity_colors(2, {t: "#123456" for t in built.surfaces}, [("all", "#123456")])
    legends = [a for a in real.axes.get_children() if type(a).__name__ == "Legend"]
    texts = sorted(t.get_text() for lg in legends for t in lg.get_texts())
    assert texts == ["all", "temperature"]
    real.set_geometry(None)
    assert fill_artists(real) == []
