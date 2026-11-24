"""M11.45: the overlay layers of the Matplotlib viewport (``SceneView.set_overlay``)."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.core.meshgen import rect_mesh
from thermalfea.gui import viewport_mpl as vm
from thermalfea.gui.scene import (
    FieldDisplay,
    LoadSymbol,
    OverlayMarker,
    OverlayPolyline,
    OverlayText,
    SceneView,
)
from thermalfea.gui.viewport_mpl import MplSceneView
from thermalfea.post.plots import display_triangulation


@pytest.fixture
def view(qtbot):
    v = MplSceneView()
    qtbot.addWidget(v.widget())
    v.widget().resize(640, 480)
    model = api.new_model()
    api.Geometry(model).rectangle(0, 0, 2, 1, id="plate")
    v.set_geometry(api.build(model))
    return v


def test_set_overlay_is_in_the_protocol(view) -> None:
    assert isinstance(view, SceneView)
    assert hasattr(view, "set_overlay")


def test_set_replace_clear_per_layer(view) -> None:
    view.set_overlay("a", [OverlayText(0.5, 0.5, "one"), OverlayMarker(1.0, 0.5, "p")])
    view.set_overlay("b", [OverlayPolyline([(0.0, 0.0), (1.0, 1.0)])])
    assert len(view.overlay_artists("a")) == 3  # text, marker dot, marker note
    assert len(view.overlay_artists("b")) == 1
    view.set_overlay("a", [OverlayText(0.2, 0.2, "two")])
    assert len(view.overlay_artists("a")) == 1
    assert view.overlay_artists("a")[0].get_text() == "two"
    assert len(view.overlay_artists("b")) == 1  # other layers untouched
    view.set_overlay("a", [])
    assert view.overlay_artists("a") == [] and len(view.overlay_artists("b")) == 1
    assert view.overlay_artists("never") == []


def test_overlay_survives_content_changes_and_is_cleared_with_the_model(view) -> None:
    mesh = rect_mesh(0.0, 0.0, 2.0, 1.0, 4, 2, "T3")
    view.set_overlay("a", [OverlayText(0.5, 0.5, "kept")])
    view.set_mesh(mesh)
    dm = display_triangulation(mesh)
    view.set_field(
        FieldDisplay(
            xy=mesh.nodes[:, :2], triangles=dm.triangles, values=mesh.nodes[:, 0],
            vmin=0.0, vmax=2.0, levels=4,
        )
    )
    view.set_symbols([LoadSymbol("temperature", "hot", 1, [1])])
    view.fit()
    view.set_field(None)
    view.set_mesh(None)
    view.set_symbols([])
    assert len(view.overlay_artists("a")) == 1
    view.set_geometry(None)
    assert view.overlay_artists("a") == []


def test_overlay_is_drawn_between_symbols_and_highlight(view) -> None:
    view.set_overlay(
        "a",
        [OverlayText(0.5, 0.5, "t"), OverlayMarker(1, 0.5, "m"), OverlayPolyline([(0, 0), (1, 1)])],
    )
    assert vm.Z_SYMBOLS < vm.Z_OVERLAY < vm.Z_HIGHLIGHT
    assert all(vm.Z_SYMBOLS < a.get_zorder() < vm.Z_HIGHLIGHT for a in view.overlay_artists("a"))


def test_overlay_is_not_part_of_the_fit_bounds(view) -> None:
    view.fit()
    before = (view.axes.get_xlim(), view.axes.get_ylim())
    view.set_overlay("a", [OverlayText(500.0, 500.0, "far"), OverlayPolyline([(0, 0), (900, 900)])])
    view.fit()
    assert (view.axes.get_xlim(), view.axes.get_ylim()) == before
    view.canvas.draw()  # drawing every kind of item does not fail
