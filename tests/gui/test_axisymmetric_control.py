"""M11.7: the "Geometry type" control of Analysis Settings (Planar / Axisymmetric).

The control writes ``Model.analysis`` through the undo stack, marks the mesh and the results
out of date, hides the region Thickness for an axisymmetric model and shows the axis x = 0 in
the viewport. The last test builds V-05 (hollow cylinder) from nothing in the window and
checks the verification target of ``docs/verification.md`` with its tolerance. Offscreen,
nothing modal, every wait bounded.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pytest
import test_tutorials_gui as tutorial
from test_tutorials_gui import (
    WAIT,
    choose,
    enter,
    open_panel,
    pick_in_viewport,
    results_of,
    set_function,
    solve,
    tree_action,
    trigger,
)

from thermalfea.gui.app import AppContext
from thermalfea.gui.scene import KIND_COLORS
from thermalfea.gui.viewport_mpl import _AXIS_COLOR

app = tutorial.app  # the fixture of the tutorial tests: the whole application, offscreen
GEOMETRY = "Geometry type"


def set_geometry_type(ctx: AppContext, text: str) -> Any:
    """Analysis Settings > Geometry type: choose an entry like a click on the list."""
    panel = open_panel(ctx, ("solution",))
    combo = panel.analysis_combo
    index = combo.findText(text)
    assert index >= 0
    combo.setCurrentIndex(index)
    combo.activated.emit(index)
    return panel


def draw_rectangle_at(
    ctx: AppContext, qtbot: Any, x: float, y: float, width: float, height: float
) -> None:
    """Geometry > Rectangle...: the given corner and size, OK; wait for the rebuild."""
    trigger(ctx, "geometry.rectangle")
    dialog = ctx.geometry.active_dialog
    assert dialog is not None
    for name, value in (("x", x), ("y", y), ("width", width), ("height", height)):
        dialog.editors[name].setText(str(value))
    ok = dialog.buttons.button(dialog.buttons.StandardButton.Ok)
    with qtbot.waitSignal(ctx.geometry.rebuilt, timeout=WAIT) as blocker:
        ok.click()
    assert blocker.args == [True], ctx.geometry.last_error
    trigger(ctx, "view.fit")
    ctx.view.canvas.draw()


def test_switching_marks_mesh_and_results_and_undoes(app: AppContext) -> None:
    ctx, doc = app, app.document
    assert doc.model.analysis == "planar"
    panel = open_panel(ctx, ("solution",))
    assert panel.analysis_combo.currentData() == "planar"
    assert [panel.analysis_combo.itemText(i) for i in range(2)] == ["Planar", "Axisymmetric"]
    # the choice sits above the analysis type
    labels = [w.text() for w in panel.findChildren(type(panel.title_label)) if w.text() == GEOMETRY]
    assert labels == [GEOMETRY]

    # a mesh and results that are current, as after a solve
    doc._clear_stale(False, False, False)
    assert not doc.mesh_stale and not doc.results_stale
    steps = doc.undo_stack.count()

    panel = set_geometry_type(ctx, "Axisymmetric")
    assert doc.model.analysis == "axisymmetric" and doc.model.axisymmetric
    assert doc.undo_stack.count() == steps + 1  # one command
    assert doc.undo_stack.undoText() == "Edit Geometry type"
    assert doc.mesh_stale and doc.results_stale and not doc.geometry_stale
    assert panel.analysis_combo.currentData() == "axisymmetric"

    doc.undo_stack.undo()
    assert doc.model.analysis == "planar"
    assert ctx.properties.panel.analysis_combo.currentData() == "planar"
    doc.undo_stack.redo()
    assert doc.model.analysis == "axisymmetric"
    assert ctx.properties.panel.analysis_combo.currentData() == "axisymmetric"

    # choosing the entry that is already set pushes nothing
    steps = doc.undo_stack.count()
    set_geometry_type(ctx, "Axisymmetric")
    assert doc.undo_stack.count() == steps


def test_thickness_field_follows_the_geometry_type(app: AppContext, qtbot) -> None:
    ctx, doc = app, app.document
    ctx.tree.add_material()
    address = ctx.tree.add_region()
    panel = open_panel(ctx, address)
    assert panel.is_thickness_shown()

    set_geometry_type(ctx, "Axisymmetric")
    panel = open_panel(ctx, address)
    assert not panel.is_thickness_shown()
    assert panel.is_thickness_shown() is False

    # an open region panel follows undo and redo
    doc.undo_stack.undo()
    assert doc.model.analysis == "planar" and ctx.properties.panel.is_thickness_shown()
    doc.undo_stack.redo()
    assert not ctx.properties.panel.is_thickness_shown()
    # the stored thickness is untouched
    assert doc.model.regions[0].thickness == 1.0


def test_axis_line_in_the_viewport(app: AppContext, qtbot) -> None:
    ctx, doc, view = app, app.document, app.view
    assert not view.axis_visible
    draw_rectangle_at(ctx, qtbot, 0.05, 0.0, 0.05, 0.005)

    set_geometry_type(ctx, "Axisymmetric")
    assert view.axis_visible
    line = view._axis_line
    assert not line.pickable() and line.get_linestyle() == "-."
    assert line.get_color() == _AXIS_COLOR and _AXIS_COLOR not in KIND_COLORS
    assert list(line.get_xdata()) == [0.0, 0.0]
    view.canvas.draw()
    # it spans the view: from the bottom to the top of the axes
    (x0, y0), (x1, y1) = line.get_transform().transform(np.column_stack(
        [line.get_xdata(), line.get_ydata()]
    ))
    bbox = view.axes.bbox
    assert (y0, y1) == pytest.approx((bbox.y0, bbox.y1))
    assert x0 == pytest.approx(x1)
    # it is a viewport overlay, not a layer of the geometry
    assert line not in view.layer_artists("geometry")

    doc.undo_stack.undo()
    assert not view.axis_visible
    doc.undo_stack.redo()
    assert view.axis_visible

    # a model replaced by another one (File > Open, New) sets it again
    from thermalfea.model.model import Model

    doc.set_model(Model())
    assert not view.axis_visible
    doc.set_model(Model(analysis="axisymmetric"))
    assert view.axis_visible


def test_negative_x_is_reported_when_validating(app: AppContext, qtbot) -> None:
    """A planar model drawn around x = 0 turned axisymmetric: Validate says why it fails."""
    ctx = app
    draw_rectangle_at(ctx, qtbot, -0.05, 0.0, 0.1, 0.01)
    ctx.tree.add_material()
    ctx.tree.add_region()
    all_field = open_panel(ctx, ("regions", 0)).editors["selection"]
    all_field.choose("all")
    assert all_field.update()  # choosing waits for Update
    set_geometry_type(ctx, "Axisymmetric")
    open_panel(ctx, ("mesh_settings",))
    enter(ctx.properties.panel.editors["global_size"], "0.02")
    with qtbot.waitSignal(ctx.mesh.meshed, timeout=WAIT):
        ctx.properties.panel.generate_button.click()
    trigger(ctx, "solve.validate")
    assert any(i.code == "negative-radius" for i in ctx.solve.last_issues), ctx.solve.last_issues


# ------------------------------------------------------------------------------- V-05

RI, RO, TI, TO, K = 0.05, 0.1, 400.0, 300.0, 50.0
HEIGHT = (RO - RI) / 10
N_RADIAL = 40
TOLERANCE = 1e-3  # linear elements (docs/verification.md, V-05)


def test_v05_built_from_scratch_in_the_window(app: AppContext, qtbot) -> None:
    ctx, doc = app, app.document
    assert doc.model.analysis == "planar"

    # geometry: the rectangle r_i .. r_o in x; then the control makes the model axisymmetric
    draw_rectangle_at(ctx, qtbot, RI, 0.0, RO - RI, HEIGHT)
    set_geometry_type(ctx, "Axisymmetric")
    assert doc.model.analysis == "axisymmetric" and ctx.view.axis_visible

    # a material of the verification (k = 50) and a region on the whole surface
    address = ctx.tree.add_material()
    for name, value in (("k", K), ("rho", 7800.0), ("cp", 500.0)):
        set_function(ctx, address, name, str(value))
    region = ctx.tree.add_region()
    all_field = open_panel(ctx, region).editors["selection"]
    all_field.choose("all")
    assert all_field.update()  # choosing waits for Update
    choose(ctx, region, "material", address[1])
    assert not open_panel(ctx, region).is_thickness_shown()

    # fixed temperatures on the inner and the outer curve
    for x, value in ((RI, TI), (RO, TO)):
        tree_action(ctx, "loads", ("add_bc", "fixed_temperature"))
        bc = ("bcs", len(doc.model.bcs) - 1)
        panel = ctx.properties.panel
        dim, tags = pick_in_viewport(ctx, qtbot, panel, [(x, HEIGHT / 2)], "curve")
        assert dim == 1 and len(tags) == 1
        set_function(ctx, bc, "T", str(value))
    assert [bc.T.value for bc in doc.model.bcs] == [TI, TO]
    inner = doc.model.bcs[0].name

    # mesh: 40 elements in the radial direction (structured), linear triangles
    size = (RO - RI) / N_RADIAL
    enter(open_panel(ctx, ("mesh_settings",)).editors["global_size"], str(size))
    with qtbot.waitSignal(ctx.mesh.meshed, timeout=WAIT) as blocker:
        ctx.properties.panel.generate_button.click()
    assert blocker.args == [True], ctx.errors.calls  # type: ignore[attr-defined]
    assert doc.mesh.axisymmetric
    nodes = doc.mesh.nodes
    assert nodes[:, 0].min() == pytest.approx(RI) and nodes[:, 0].max() == pytest.approx(RO)

    solve(ctx, qtbot)
    results = results_of(ctx)
    r = results.mesh.nodes[:, 0]
    exact = TI - (TI - TO) * np.log(r / RI) / np.log(RO / RI)
    error = float(np.max(np.abs(results.temperature() - exact) / np.abs(exact)))
    assert error < TOLERANCE, error
    per_height = 2.0 * np.pi * K * (TI - TO) / np.log(RO / RI)
    heat = float(results.heat_flow(inner)[-1]) / HEIGHT
    assert abs(heat - per_height) / per_height < TOLERANCE, (heat, per_height)
    assert abs(float(results.energy_balance()["relative_imbalance"][-1])) < 1e-6
    assert ctx.errors.calls == []  # type: ignore[attr-defined]
