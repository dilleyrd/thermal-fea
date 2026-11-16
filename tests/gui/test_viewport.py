"""The Matplotlib viewport, driven with synthetic Matplotlib mouse events (offscreen Qt)."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from matplotlib.backend_bases import MouseEvent

from thermalfea import api
from thermalfea.core.meshgen import rect_mesh
from thermalfea.gui import viewport_mpl as vm
from thermalfea.gui.scene import (
    ELEMENT_DIM,
    NODE_DIM,
    FieldDisplay,
    LoadSymbol,
    SceneView,
)
from thermalfea.gui.viewport_mpl import MplSceneView
from thermalfea.post.plots import display_triangulation

# ----------------------------------------------------------------------------- helpers


def event(view, name, x, y, button=None, ctrl=False, step=0):
    """A synthetic Matplotlib mouse event at data position ``(x, y)``."""
    px, py = view.axes.transData.transform((x, y)) + 1e-6  # events truncate to whole pixels
    return MouseEvent(
        name, view.canvas, px, py, button=button, step=step, modifiers=["ctrl"] if ctrl else None
    )


def fire(ev):
    ev._process()


def click(view, x, y, ctrl=False):
    fire(event(view, "button_press_event", x, y, button=1, ctrl=ctrl))
    fire(event(view, "button_release_event", x, y, button=1, ctrl=ctrl))


def drag(view, p0, p1, ctrl=False):
    fire(event(view, "button_press_event", *p0, button=1, ctrl=ctrl))
    fire(event(view, "motion_notify_event", *p1, ctrl=ctrl))
    fire(event(view, "button_release_event", *p1, button=1, ctrl=ctrl))


def hover(view, x, y):
    fire(event(view, "motion_notify_event", x, y))


@pytest.fixture(scope="module")
def built_model():
    """A 4 x 2 plate with a round hole next to a 2 x 2 square (two surfaces)."""
    model = api.new_model()
    g = api.Geometry(model)
    g.rectangle(0, 0, 4, 2, id="plate")
    g.circle(2, 1, 0.5, id="hole")
    g.cut(["plate"], ["hole"])
    g.rectangle(4, 0, 2, 2, id="side")
    return api.build(model)


@pytest.fixture
def small_mesh():
    return rect_mesh(0.0, 0.0, 6.0, 2.0, 12, 4, "T3")


@pytest.fixture
def view(qtbot):
    v = MplSceneView()
    qtbot.addWidget(v.widget())
    v.widget().resize(640, 480)
    return v


@pytest.fixture
def loaded(view, built_model, small_mesh):
    view.set_geometry(built_model)
    view.set_mesh(small_mesh)
    return view


def tag_at(built, dim, x, y):
    """Tag of the entity of ``dim`` whose centre is nearest to ``(x, y)``."""
    ents = built.entities(dim)
    return min(ents, key=lambda t: (ents[t].center[0] - x) ** 2 + (ents[t].center[1] - y) ** 2)


def containing_element(mesh, x, y):
    """Global id of the T3 element containing ``(x, y)`` (brute force)."""
    block = mesh.blocks[0]
    p = mesh.nodes[block.conn][:, :, :2]
    a, b, c = p[:, 0], p[:, 1], p[:, 2]
    d = (b[:, 1] - c[:, 1]) * (a[:, 0] - c[:, 0]) + (c[:, 0] - b[:, 0]) * (a[:, 1] - c[:, 1])
    l1 = ((b[:, 1] - c[:, 1]) * (x - c[:, 0]) + (c[:, 0] - b[:, 0]) * (y - c[:, 1])) / d
    l2 = ((c[:, 1] - a[:, 1]) * (x - c[:, 0]) + (a[:, 0] - c[:, 0]) * (y - c[:, 1])) / d
    inside = (l1 >= 0) & (l2 >= 0) & (1 - l1 - l2 >= 0)
    return int(block.elem_ids[np.flatnonzero(inside)[0]])


# ------------------------------------------------------------------------- interface


def test_implements_scene_view(view) -> None:
    assert isinstance(view, SceneView)
    for name in (
        "selection_changed", "point_picked", "widget", "set_geometry", "set_mesh", "set_field",
        "set_symbols", "set_selection_mode", "highlight", "fit", "save_image",
    ):
        assert hasattr(view, name), name
    assert view.widget() is view.canvas


def test_layers_and_zorder(loaded, small_mesh) -> None:
    v = loaded
    geom, mesh = v.layer_artists("geometry"), v.layer_artists("mesh")
    assert geom and mesh and not v.layer_artists("results") and not v.layer_artists("symbols")
    dm = display_triangulation(small_mesh)
    spec = FieldDisplay(
        xy=small_mesh.nodes[:, :2], triangles=dm.triangles, values=small_mesh.nodes[:, 0],
        vmin=0.0, vmax=6.0, levels=6, label="x [m]", title="x",
        vector_xy=np.array([[1.0, 1.0]]), vector_uv=np.array([[1.0, 0.0]]),
        markers=[(0.0, 0.0, "min 0")],
    )
    v.set_field(spec)
    symbols = [
        LoadSymbol("temperature", "hot", 1, [2]),
        LoadSymbol("temperature", "pt", 0, [1]),
        LoadSymbol("flux", "q", 2, [2]),
    ]
    v.set_symbols(symbols)
    results, syms = v.layer_artists("results"), v.layer_artists("symbols")
    assert results and len(syms) == 4  # three symbols and a legend
    z = {
        "geometry": max(a.get_zorder() for a in geom),
        "mesh_lo": min(a.get_zorder() for a in mesh),
        "results": min(a.get_zorder() for a in results),
        "symbols": min(a.get_zorder() for a in syms),
        "highlight": min(a.get_zorder() for a in v._animated()),
    }
    assert z["geometry"] < z["mesh_lo"] < z["results"] < z["symbols"] < z["highlight"]
    assert vm.Z_GEOMETRY < vm.Z_MESH < vm.Z_RESULTS < vm.Z_SYMBOLS < vm.Z_HIGHLIGHT
    assert all(a.get_animated() for a in v._animated())
    assert len(v.canvas.figure.axes) == 2  # model axes + colour bar
    # without show_mesh the mesh is hidden under a field; with it, lifted above the field
    assert not any(a.get_visible() for a in mesh)
    spec.show_mesh = True
    v.set_field(spec)
    lines = [a for a in v.layer_artists("mesh") if a.get_visible()]
    assert lines and all(a.get_zorder() > vm.Z_RESULTS for a in lines)
    # smooth shading and vectors without a scalar field also work
    spec.levels = None
    v.set_field(spec)
    assert v.layer_artists("results")
    v.set_field(None)
    v.set_symbols([])
    assert not v.layer_artists("results") and not v.layer_artists("symbols")
    assert len(v.canvas.figure.axes) == 1
    v.set_mesh(None)
    v.set_geometry(None)
    assert not v.layer_artists("geometry") and not v.layer_artists("mesh")


def test_color_by_and_vector_only_field(loaded, small_mesh) -> None:
    n = small_mesh.n_elements
    loaded.set_mesh(small_mesh, color_by=np.arange(n) % 3)
    assert len(loaded.layer_artists("mesh")) == 2  # colour fill + outlines
    loaded.set_field(
        FieldDisplay(
            xy=np.zeros((0, 2)), triangles=np.zeros((0, 3), int), values=np.zeros(0),
            vmin=0.0, vmax=1.0, vector_xy=np.array([[1.0, 1.0], [2.0, 1.0]]),
            vector_uv=np.array([[1.0, 0.0], [0.0, 1.0]]), vector_values=np.array([1.0, 2.0]),
            vector_label="q",
        )
    )
    assert loaded.layer_artists("results")


def test_equal_aspect_and_fit(loaded, built_model) -> None:
    ax = loaded.axes
    assert ax.get_aspect() == 1.0
    loaded.fit()
    xlim, ylim = ax.get_xlim(), ax.get_ylim()
    b = built_model.bbox
    assert xlim[0] <= b[0] and xlim[1] >= b[3] and ylim[0] <= b[1] and ylim[1] >= b[4]
    # equal aspect: one data unit has the same length on both axes
    bbox = ax.bbox
    assert (xlim[1] - xlim[0]) / bbox.width == pytest.approx((ylim[1] - ylim[0]) / bbox.height)
    ax.set_xlim(100.0, 101.0)
    loaded.fit()
    assert ax.get_xlim()[0] <= b[0]


def test_wheel_zoom_keeps_cursor_point_fixed(loaded) -> None:
    ax = loaded.axes
    before_px = np.array([240.0, 180.0])  # whole pixels: events carry integer positions
    p = tuple(ax.transData.inverted().transform(before_px))
    span = ax.get_xlim()[1] - ax.get_xlim()[0]
    fire(event(loaded, "scroll_event", *p, button="up", step=1))
    assert ax.get_xlim()[1] - ax.get_xlim()[0] == pytest.approx(span / vm.ZOOM_STEP)
    assert np.allclose(ax.transData.transform(p), before_px, atol=1e-6)
    fire(event(loaded, "scroll_event", *p, button="down", step=-1))
    fire(event(loaded, "scroll_event", *p, button="down", step=-1))
    assert ax.get_xlim()[1] - ax.get_xlim()[0] == pytest.approx(span * vm.ZOOM_STEP)
    assert np.allclose(ax.transData.transform(p), before_px, atol=1e-6)


def test_middle_drag_pans(loaded) -> None:
    ax = loaded.axes
    x0, y0 = ax.get_xlim(), ax.get_ylim()
    px, py = ax.transData.transform((3.0, 1.0))
    for name, dx, dy in (
        ("button_press_event", 0, 0),
        ("motion_notify_event", 40, 30),
        ("button_release_event", 40, 30),
    ):
        ev = MouseEvent(name, loaded.canvas, px + dx, py + dy, button=2)
        fire(ev)
    per_px_x = (x0[1] - x0[0]) / ax.bbox.width
    per_px_y = (y0[1] - y0[0]) / ax.bbox.height
    assert ax.get_xlim()[0] == pytest.approx(x0[0] - 40 * per_px_x)
    assert ax.get_ylim()[0] == pytest.approx(y0[0] - 30 * per_px_y)
    # after release, plain motion no longer pans
    after = ax.get_xlim()
    fire(MouseEvent("motion_notify_event", loaded.canvas, px + 90, py, button=None))
    assert ax.get_xlim() == after


def test_coordinate_readout_and_point_picked(loaded, qtbot) -> None:
    with qtbot.waitSignal(loaded.coordinates_changed, timeout=1000) as blocker:
        hover(loaded, 2.5, 0.5)
    assert blocker.args == [pytest.approx(2.5, abs=0.02), pytest.approx(0.5, abs=0.02)]
    with qtbot.waitSignal(loaded.point_picked, timeout=1000) as blocker:
        click(loaded, 1.5, 1.25)
    assert blocker.args == [pytest.approx(1.5, abs=0.02), pytest.approx(1.25, abs=0.02), 0.0]


# ---------------------------------------------------------------------------- picking


def pick(view, qtbot, mode, x, y, ctrl=False):
    view.set_selection_mode(mode)
    with qtbot.waitSignal(view.selection_changed, timeout=1000) as blocker:
        click(view, x, y, ctrl=ctrl)
    return blocker.args


def test_pick_point(loaded, qtbot, built_model) -> None:
    assert pick(loaded, qtbot, "point", 4.0, 2.0) == [0, [tag_at(built_model, 0, 4.0, 2.0)]]
    assert not loaded._selection.is_empty()


def test_pick_curve_straight_and_curved(loaded, qtbot, built_model) -> None:
    bottom = tag_at(built_model, 1, 2.0, 0.0)
    assert pick(loaded, qtbot, "curve", 1.3, 0.0) == [1, [bottom]]
    hole = tag_at(built_model, 1, 2.0, 1.0)
    on_circle = (2.0 + 0.5 * np.cos(0.7), 1.0 + 0.5 * np.sin(0.7))
    assert pick(loaded, qtbot, "curve", *on_circle) == [1, [hole]]


def test_pick_surface_with_hole_and_neighbour(loaded, qtbot, built_model) -> None:
    plate = tag_at(built_model, 2, 2.0, 1.0)
    side = tag_at(built_model, 2, 5.0, 1.0)
    assert pick(loaded, qtbot, "surface", 0.5, 0.5) == [2, [plate]]
    assert pick(loaded, qtbot, "surface", 5.0, 1.0) == [2, [side]]
    # inside the hole nothing is picked, and the selection is cleared
    assert pick(loaded, qtbot, "surface", 2.0, 1.0) == [2, []]


def test_pick_node_and_element(loaded, qtbot, small_mesh) -> None:
    x, y = 1.02, 0.52
    dist = np.hypot(small_mesh.nodes[:, 0] - x, small_mesh.nodes[:, 1] - y)
    assert pick(loaded, qtbot, "node", x, y) == [NODE_DIM, [int(np.argmin(dist))]]
    x, y = 2.2, 1.3
    expected = containing_element(small_mesh, x, y)
    assert pick(loaded, qtbot, "element", x, y) == [ELEMENT_DIM, [expected]]
    assert not loaded._selection.is_empty()


def test_ctrl_click_adds_and_removes(loaded, qtbot, built_model) -> None:
    a, b = tag_at(built_model, 0, 0.0, 0.0), tag_at(built_model, 0, 4.0, 0.0)
    assert pick(loaded, qtbot, "point", 0.0, 0.0) == [0, [a]]
    with qtbot.waitSignal(loaded.selection_changed, timeout=1000) as blocker:
        click(loaded, 4.0, 0.0, ctrl=True)
    assert blocker.args == [0, sorted([a, b])]
    with qtbot.waitSignal(loaded.selection_changed, timeout=1000) as blocker:
        click(loaded, 4.0, 0.0, ctrl=True)
    assert blocker.args == [0, [a]]
    # a plain click elsewhere replaces; a click on nothing clears
    with qtbot.waitSignal(loaded.selection_changed, timeout=1000) as blocker:
        click(loaded, 4.0, 2.0)
    assert blocker.args == [0, [tag_at(built_model, 0, 4.0, 2.0)]]
    with qtbot.waitSignal(loaded.selection_changed, timeout=1000) as blocker:
        click(loaded, 1.0, 1.0)
    assert blocker.args == [0, []]


def test_box_selection_in_every_mode(loaded, qtbot, built_model, small_mesh) -> None:
    v = loaded

    def box(mode, p0, p1, ctrl=False):
        v.set_selection_mode(mode)
        with qtbot.waitSignal(v.selection_changed, timeout=1000) as blocker:
            drag(v, p0, p1, ctrl=ctrl)
        return blocker.args

    pts = [t for t, f in built_model.points.items() if f.center[0] >= 3.9]
    assert box("point", (3.5, -0.5), (6.2, 2.5)) == [0, sorted(pts)]
    curves = [t for t, f in built_model.curves.items() if f.bbox[0] >= 3.9]
    assert box("curve", (3.5, -0.5), (6.2, 2.5)) == [1, sorted(curves)]
    side = tag_at(built_model, 2, 5.0, 1.0)
    assert box("surface", (3.5, -0.5), (6.2, 2.5)) == [2, [side]]
    both = sorted(built_model.surfaces)
    assert box("surface", (6.2, 2.5), (-0.2, -0.5)) == [2, both]  # reversed corners
    nodes = np.flatnonzero(
        (small_mesh.nodes[:, 0] <= 1.2) & (small_mesh.nodes[:, 1] <= 1.2)
    )
    assert box("node", (-0.2, -0.2), (1.2, 1.2)) == [NODE_DIM, nodes.tolist()]
    block = small_mesh.blocks[0]
    cent = small_mesh.nodes[block.conn][:, :, :2].mean(axis=1)
    inside = (cent[:, 0] < 1.0) & (cent[:, 1] < 1.0)
    got = box("element", (-0.2, -0.2), (1.0, 1.0))
    assert got == [ELEMENT_DIM, sorted(block.elem_ids[inside].tolist())]
    # Ctrl adds a second box to the selection
    more = box("element", (5.0, 1.0), (6.2, 2.2), ctrl=True)
    assert len(more[1]) > len(got[1]) and set(got[1]) < set(more[1])
    # a drag that is too short is a click, not a box
    v.set_selection_mode("point")
    with qtbot.waitSignal(v.selection_changed, timeout=1000):
        click(v, 4.0, 2.0)


def test_highlight_does_not_emit(loaded, qtbot, built_model) -> None:
    tag = tag_at(built_model, 2, 5.0, 1.0)
    with qtbot.assertNotEmitted(loaded.selection_changed):
        loaded.highlight(2, [tag])
        loaded.highlight(NODE_DIM, [0, 1, 2])
        loaded.highlight(ELEMENT_DIM, [0, 1])
        loaded.highlight(1, [99999])  # unknown tags are ignored
    assert loaded.selection == (1, [99999])
    assert loaded._selection.is_empty()
    loaded.highlight(2, [tag])
    assert loaded.selection == (2, [tag]) and not loaded._selection.is_empty()
    loaded.highlight(2, [])
    assert loaded._selection.is_empty()


def test_mode_none_disables_picking_and_mode_change_clears(loaded, qtbot, built_model) -> None:
    pick(loaded, qtbot, "point", 4.0, 2.0)
    with qtbot.waitSignal(loaded.selection_changed, timeout=1000) as blocker:
        loaded.set_selection_mode("curve")
    assert blocker.args == [1, []]
    loaded.set_selection_mode("none")
    with qtbot.assertNotEmitted(loaded.selection_changed):
        click(loaded, 4.0, 2.0)
        drag(loaded, (0.0, 0.0), (5.0, 2.0))
        hover(loaded, 4.0, 2.0)
    assert loaded.hover is None
    with pytest.raises(ValueError):
        loaded.set_selection_mode("volume")


def test_hover_updates_highlight_without_selecting(loaded, qtbot, built_model) -> None:
    loaded.set_selection_mode("point")
    with qtbot.assertNotEmitted(loaded.selection_changed):
        hover(loaded, 4.0, 2.0)
        assert loaded.hover == (0, tag_at(built_model, 0, 4.0, 2.0))
        assert not loaded._hover_overlay.is_empty()
        hover(loaded, 1.0, 1.0)
    assert loaded.hover is None and loaded._hover_overlay.is_empty()
    assert loaded._selection.is_empty()
    loaded.set_selection_mode("surface")
    hover(loaded, 0.5, 0.5)
    assert loaded.hover is not None
    loaded.set_selection_mode("curve")  # mode change clears the hover
    assert loaded.hover is None and loaded._hover_overlay.is_empty()


def test_save_image(loaded, tmp_path: Path) -> None:
    out = tmp_path / "view.png"
    loaded.highlight(2, [tag for tag in loaded._surf_tags][:1])
    loaded.save_image(str(out), dpi=80)
    assert out.stat().st_size > 1000
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert all(a.get_animated() for a in loaded._selection.artists)


def test_blitting_hover_does_not_redraw_canvas(loaded) -> None:
    calls: list[int] = []
    original = loaded.canvas.draw

    def counting_draw(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    loaded.canvas.draw = counting_draw
    loaded.set_selection_mode("point")
    hover(loaded, 4.0, 2.0)  # may draw once to cache the background
    calls.clear()
    for x, y in ((4.0, 0.0), (0.0, 0.0), (1.0, 1.0), (4.0, 2.0), (4.0, 2.0)):
        hover(loaded, x, y)
    assert calls == []
    # a zoom invalidates the cache; the next overlay update draws once
    fire(event(loaded, "scroll_event", 2.0, 1.0, button="up", step=1))
    hover(loaded, 4.0, 0.0)
    hover(loaded, 0.0, 0.0)
    assert len(calls) <= 1


def test_attach_viewport_wires_window_and_document(window, qtbot, built_model, small_mesh) -> None:
    from thermalfea.gui.document import Document

    document = Document()
    view = vm.attach_viewport(window, document)
    assert window.viewport_widget is view.widget()
    assert window.actions["view.fit"].isEnabled()
    window.selection_mode_changed.emit("surface")
    assert view.selection_mode == "surface"
    document.set_built(built_model)
    assert view.layer_artists("geometry")
    document.set_mesh(small_mesh)
    assert view.layer_artists("mesh")
    view.axes.set_xlim(50.0, 51.0)
    window.actions["view.fit"].trigger()
    assert view.axes.get_xlim()[0] <= 0.0
    hover(view, 2.5, 0.5)
    assert "x =" in window.status_text


# ------------------------------------------------------------------------ performance


def test_hover_100k_elements_is_fast_and_blitted(view, qtbot) -> None:
    mesh = rect_mesh(0.0, 0.0, 2.0, 1.0, 316, 158, "T3")
    assert mesh.n_elements > 99_000
    view.set_mesh(mesh)
    view.set_selection_mode("element")
    calls: list[int] = []
    original = view.canvas.draw

    def counting_draw(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    view.canvas.draw = counting_draw
    rng = np.random.default_rng(0)
    first = time.perf_counter()
    hover(view, 1.0, 0.5)  # builds the cached background and the element finder
    first = time.perf_counter() - first
    calls.clear()
    pts = rng.uniform([0.05, 0.05], [1.95, 0.95], size=(50, 2))
    start = time.perf_counter()
    for x, y in pts:
        hover(view, float(x), float(y))
    elapsed = time.perf_counter() - start
    print(f"first hover {first:.2f} s, 50 hovers {elapsed:.3f} s")
    assert view.hover is not None
    assert calls == [], "hover must be blitted, not trigger a full canvas draw"
    assert elapsed < 5.0
    # picking agrees with a brute-force containment test at a few points
    for x, y in pts[:5]:
        hit = view._pick(float(x), float(y))
        ids = view._elem_ids
        tri = view._display.triangles[np.flatnonzero(view._display.element == view._elem_pos[hit])]
        p = mesh.nodes[tri][:, :, :2]
        assert p[:, :, 0].min() - 1e-12 <= x <= p[:, :, 0].max() + 1e-12
        assert ids is not None
