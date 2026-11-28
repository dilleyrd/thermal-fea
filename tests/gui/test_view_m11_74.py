"""M11.74: the view (held items 1, 5, 23 and 7; convention C10).

Labels stay in front of boundary lines and of the selection highlight; selecting a stream
highlights its walls and draws its path, selecting an enclosure highlights its surfaces;
View > Stretch stretches one axis for slender models, says so in the view, and picking
still finds what is nearest on the screen.
"""

# ruff: noqa: F811  (the fixtures `doc` and `view` are imported from other test modules)
from __future__ import annotations

from typing import Any

import pytest
from tests.gui.test_overlay_labels import FakeView, doc  # noqa: F401
from tests.gui.test_viewport_overlay import view  # noqa: F401

from thermalfea import api
from thermalfea.core.functions import Constant
from thermalfea.gui.document import Document
from thermalfea.gui.load_symbols import SELECTED_PATH_LAYER, attach_loads
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.scene import OverlayMarker, OverlayPolyline, OverlayText
from thermalfea.gui.viewport_mpl import STRETCH_FACTORS, MplSceneView, attach_stretch_menu
from thermalfea.model.bcs import Enclosure, EnclosureSurface, Stream


# ------------------------------------------------------------------ labels in front
def test_labels_are_drawn_after_the_highlight(view: MplSceneView) -> None:
    view.set_overlay("loads", [OverlayText(1.0, 0.0, "Fixed Temperature 1: T = 373.15 K")])
    (label,) = view.label_artists()
    assert label.get_bbox_patch().get_alpha() >= 0.9  # in front of the symbol line
    curve = next(iter(view._curve_tags))
    view.highlight(1, [curve])
    order: list[Any] = []
    original = view._ax.draw_artist
    view._ax.draw_artist = lambda artist: (order.append(artist), original(artist))[-1]
    try:
        view._draw_animated()
    finally:
        view._ax.draw_artist = original
    selection = [a for a in view._selection.artists if a in order]
    assert selection and label in order
    assert order.index(label) > max(order.index(a) for a in selection)


def test_without_a_highlight_labels_are_not_drawn_twice(view: MplSceneView) -> None:
    view.set_overlay("loads", [OverlayText(1.0, 0.0, "label")])
    view.highlight(1, [])
    order: list[Any] = []
    original = view._ax.draw_artist
    view._ax.draw_artist = lambda artist: (order.append(artist), original(artist))[-1]
    try:
        view._draw_animated()
    finally:
        view._ax.draw_artist = original
    assert view.label_artists()[0] not in order


# --------------------------------------------------------- streams and enclosures
def add_stream_and_enclosure(doc: Document) -> None:
    def change(m: Any) -> None:
        m.streams.append(
            Stream(
                name="S", fluid="Water", mode="in_plane", walls=["L", "R"], flow_area=1e-4,
                wetted_perimeter=0.03, cross_section="circular", T_inlet=Constant(300.0),
                path=[(0.0, -0.1), (2.0, -0.1)],
            )
        )
        m.enclosures.append(Enclosure("E", [EnclosureSurface("L", 0.8)]))

    doc.edit("add", change)


def test_a_stream_highlights_its_walls_and_draws_its_path(window, doc) -> None:
    add_stream_and_enclosure(doc)
    fake = FakeView()
    attach_tree(window, doc)
    ctl = attach_loads(window, doc, fake)
    walls = doc.model.selections["L"], doc.model.selections["R"]
    ctl.highlight_address(("streams", 0))
    dim, tags = fake.highlights[-1]
    assert dim == walls[0].dim
    assert sorted(tags) == sorted({*walls[0].tags, *walls[1].tags})
    items = fake.layers[SELECTED_PATH_LAYER]
    assert isinstance(items[0], OverlayPolyline) and items[0].points == [(0.0, -0.1), (2.0, -0.1)]
    assert [m.text for m in items if isinstance(m, OverlayMarker)] == ["inlet", "outlet"]
    ctl.highlight_address(("enclosures", 0))
    assert fake.highlights[-1] == (walls[0].dim, sorted(walls[0].tags))
    assert fake.layers[SELECTED_PATH_LAYER] == []  # the path goes with the stream


# ------------------------------------------------------------------------ stretch
@pytest.fixture
def slender(qtbot) -> MplSceneView:
    """A 1 mm x 1 m strip, as slender as a heat-exchanger wall."""
    v = MplSceneView()
    qtbot.addWidget(v.widget())
    v.widget().resize(640, 480)
    model = api.new_model()
    api.Geometry(model).rectangle(0.0, 0.0, 0.001, 1.0)
    v.set_geometry(api.build(model))
    v.fit()
    return v


def test_stretch_widens_one_axis_and_says_so(slender: MplSceneView) -> None:
    true_width = slender._ax.get_xlim()[1] - slender._ax.get_xlim()[0]
    slender.set_stretch("x", 50, "r")
    assert slender.stretch == (50.0, 1.0)
    assert slender.stretch_note() == "Stretched r × 50: not true scale"
    x0, x1 = slender._ax.get_xlim()
    y0, y1 = slender._ax.get_ylim()
    assert x0 <= 0.0 and x1 >= 0.001 and y0 <= 0.0 and y1 >= 1.0  # still all in view
    assert (x1 - x0) < true_width  # the thin wall takes more of the screen
    slender.set_stretch(None)
    assert slender.stretch == (1.0, 1.0) and slender.stretch_note() == ""
    with pytest.raises(ValueError):
        slender.set_stretch("z", 2)


def test_picking_in_a_stretched_view_uses_screen_distances(slender: MplSceneView) -> None:
    slender.set_stretch("x", 50)
    slender.set_selection_mode("curve")
    ents = slender._built.entities(1)
    right = max(ents, key=lambda t: ents[t].center[0])
    left = min(ents, key=lambda t: ents[t].center[0])
    per_px_x = slender._view[2] / 50.0  # data metres per screen pixel along x
    near_right = 0.001 + 3.0 * per_px_x  # 3 pixels to the right of the right wall
    assert slender._pick(near_right, 0.5) == right
    assert slender._pick(0.0 - 3.0 * per_px_x, 0.5) == left
    far = 0.001 + 40.0 * per_px_x  # 40 pixels away: nothing
    assert slender._pick(far, 0.5) is None


def test_the_view_menu_offers_the_stretches(window, doc) -> None:
    view = MplSceneView()
    attach_stretch_menu(window, doc, view)
    assert window.actions["view.stretch.none"].isChecked()
    for axis in ("x", "y"):
        for factor in STRETCH_FACTORS:
            assert f"view.stretch.{axis}{factor}" in window.actions
    assert window.actions["view.stretch.x20"].text() == "Stretch x × 20"
    doc.edit("axisym", lambda m: setattr(m, "analysis", "axisymmetric"))
    assert window.actions["view.stretch.x20"].text() == "Stretch r × 20"
    assert window.actions["view.stretch.y5"].text() == "Stretch z × 5"
    window.actions["view.stretch.x20"].trigger()
    assert view.stretch == (20.0, 1.0) and "r × 20" in view.stretch_note()
    window.actions["view.stretch.none"].trigger()
    assert view.stretch == (1.0, 1.0)
