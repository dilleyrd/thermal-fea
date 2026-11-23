"""M8.5: geometry tools - dialogs, click-to-place, selection tools, history, rebuild."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QAbstractItemView, QCheckBox, QComboBox

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.units import UnitSettings
from thermalfea.geometry.gmsh_session import fresh_model
from thermalfea.gui.dialogs.geometry import GeometryOpDialog, RefEditor
from thermalfea.gui.document import Document
from thermalfea.gui.geometry_defs import TOOLS
from thermalfea.gui.geometry_tools import attach_geometry_tools
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.property_panels.form import FormPanel, NumberEdit
from thermalfea.gui.viewport_mpl import attach_viewport
from thermalfea.model import geometry_ops as g


class FakeView(QObject):
    """The two signals of a SceneView that the geometry tools use."""

    selection_changed = Signal(int, list)
    point_picked = Signal(float, float, float)


def base_model(shapes: bool = True):
    """Points p1..p4 and lines l1..l4 (a square far away) and two overlapping rectangles."""
    model = api.new_model(name="tools")
    geo = api.Geometry(model)
    for i, (x, y) in enumerate([(10, 10), (11, 10), (11, 11), (10, 11)], start=1):
        geo.point(x, y, id=f"p{i}")
    for i, (a, b) in enumerate([("p1", "p2"), ("p2", "p3"), ("p3", "p4"), ("p4", "p1")], 1):
        geo.line(a, b, id=f"l{i}")
    if shapes:
        geo.rectangle(0.0, 0.0, 1.0, 1.0, id="a")
        geo.rectangle(0.5, 0.5, 1.0, 1.0, id="b")
    return model


class Env:
    """Window, document, fake viewport, tree and geometry controller."""

    def __init__(self, window, model, view=None, build: bool = True) -> None:
        self.window = window
        self.doc = Document(model)
        self.view = view if view is not None else FakeView()
        self.tree, self.props = attach_tree(window, self.doc, self.view)
        self.ctrl = attach_geometry_tools(window, self.doc, self.view)
        if build:
            assert self.ctrl.rebuild()

    @property
    def geometry(self) -> list[g.GeometryOp]:
        return self.doc.model.geometry

    def op(self, op_id: str) -> g.GeometryOp:
        return next(op for op in self.geometry if op.id == op_id)

    def surfaces(self) -> int:
        return len(self.doc.built.surfaces)

    def tags(self, op_id: str, only: bool = False) -> list[int]:
        """Surface tags owned by an operation (``only``: not also owned by another)."""
        owned = self.doc.built.op_entities[op_id]
        others = {e for k, v in self.doc.built.op_entities.items() if k != op_id for e in v}
        return sorted(t for d, t in owned if d == 2 and not (only and (d, t) in others))

    def select(self, tags: list[int], dim: int = 2) -> None:
        self.view.selection_changed.emit(dim, tags)


@pytest.fixture
def env(qtbot, window) -> Env:
    return Env(window, base_model())


def fill(dialog: GeometryOpDialog, **texts: Any) -> None:
    """Numeric / text entry into the editors, like a user typing."""
    for name, value in texts.items():
        editor = dialog.editors[name]
        if isinstance(editor, NumberEdit):
            editor.setText(str(value))
        elif isinstance(editor, RefEditor):
            editor.line.setText(value if isinstance(value, str) else ", ".join(value))
        elif isinstance(editor, QCheckBox):
            editor.setChecked(bool(value))
        elif isinstance(editor, QComboBox):
            editor.setCurrentText(str(value))
        else:
            editor.setText(str(value))


def run_tool(env: Env, key: str, **texts: Any) -> GeometryOpDialog:
    """Open a tool's dialog, fill it with typed numbers and accept it.

    Selection-based tools have disabled menu actions while nothing is selected, so the
    dialog is opened through the controller (what the action calls) for those.
    """
    action = env.window.actions[f"geometry.{key}"]
    if action.isEnabled():
        action.trigger()
    else:
        env.ctrl.open_tool(key)
    dialog = env.ctrl.active_dialog
    assert dialog is not None
    fill(dialog, **texts)
    dialog.accept()
    assert dialog.error_label.text() == "", dialog.error_label.text()
    assert dialog.result() == dialog.DialogCode.Accepted
    return dialog


# ------------------------------------------------------------------------------ menu


EXPECTED_ACTIONS = [
    "point", "line", "arc", "spline", "rectangle", "circle", "polygon", "surface",
    "union", "cut", "intersect", "translate", "rotate", "mirror", "scale", "delete",
    "import", "snap", "rebuild",
]  # fmt: skip


def test_geometry_menu_actions(env) -> None:
    menu_actions = env.window.menus["geometry"].actions()
    for key in EXPECTED_ACTIONS:
        assert env.window.actions[f"geometry.{key}"] in menu_actions
    assert set(TOOLS) | {"snap", "rebuild"} == set(EXPECTED_ACTIONS)
    # creation tools are always usable, selection tools follow the selection
    assert env.window.actions["geometry.rectangle"].isEnabled()
    assert env.window.actions["geometry.import"].isEnabled()
    for key in ("union", "cut", "intersect", "translate", "rotate", "mirror", "scale", "delete"):
        assert not env.window.actions[f"geometry.{key}"].isEnabled()


# ------------------------------------------------------------- every op kind: dialogs


def n_ops(env: Env) -> int:
    return len(env.geometry)


# key, entered values, check(op), surfaces after (None: do not check)
CASES: list[tuple[str, dict[str, Any], dict[str, Any], int | None]] = [
    ("point", {"x": 0.5, "y": 0.25}, {"__class__": g.Point, "x": 0.5, "y": 0.25}, 3),
    ("line", {"p1": "p1", "p2": "p3"}, {"__class__": g.Line, "p1": "p1", "p2": "p3"}, 3),
    ("arc", {"p_start": "p2", "p_center": "p1", "p_end": "p4"},
     {"__class__": g.Arc, "p_start": "p2", "p_center": "p1", "p_end": "p4"}, 3),
    ("spline", {"points": "p1, p2, p3"},
     {"__class__": g.Spline, "points": ["p1", "p2", "p3"]}, 3),
    ("rectangle", {"x": 3, "y": 3, "width": 2, "height": 1, "corner_radius": 0.1},
     {"__class__": g.Rectangle, "x": 3.0, "width": 2.0, "height": 1.0, "corner_radius": 0.1}, 4),
    ("circle", {"xc": 6, "yc": 6, "radius": 0.5},
     {"__class__": g.Circle, "xc": 6.0, "radius": 0.5}, 4),
    ("polygon", {"vertices": "5,5; 6,5; 6,6"},
     {"__class__": g.Polygon, "vertices": [(5.0, 5.0), (6.0, 5.0), (6.0, 6.0)]}, 4),
    ("surface", {"curves": "l1, l2, l3, l4"},
     {"__class__": g.SurfaceFromCurves, "curves": ["l1", "l2", "l3", "l4"], "holes": []}, 4),
    ("union", {"objects": "a", "tools": "b"},
     {"__class__": g.Boolean, "kind": "union", "objects": ["a"], "tools": ["b"]}, 1),
    ("cut", {"objects": "a", "tools": "b"},
     {"__class__": g.Boolean, "kind": "cut", "objects": ["a"], "tools": ["b"]}, 1),
    ("intersect", {"objects": "a", "tools": "b"},
     {"__class__": g.Boolean, "kind": "intersect", "objects": ["a"], "tools": ["b"]}, 1),
    ("translate", {"targets": "a", "dx": 5, "dy": 0},
     {"__class__": g.Transform, "kind": "translate", "targets": ["a"],
      "params": {"dx": 5.0, "dy": 0.0}, "copy": False}, 2),
    ("rotate", {"targets": "a", "angle": 1.5707963267948966, "cx": 0, "cy": 0, "copy": True},
     {"__class__": g.Transform, "kind": "rotate", "copy": True,
      "params": {"angle": 1.5707963267948966, "cx": 0.0, "cy": 0.0}}, 4),
    ("mirror", {"targets": "b", "x0": 0, "y0": 0, "x1": 0, "y1": 1},
     {"__class__": g.Transform, "kind": "mirror", "targets": ["b"],
      "params": {"x0": 0.0, "y0": 0.0, "x1": 0.0, "y1": 1.0}}, 2),
    ("scale", {"targets": "a", "factor": 2, "cx": 0, "cy": 0},
     {"__class__": g.Transform, "kind": "scale", "params": {"factor": 2.0, "cx": 0.0, "cy": 0.0}},
     2),
    ("delete", {"targets": "b"}, {"__class__": g.Delete, "targets": ["b"]}, 1),
]  # fmt: skip


@pytest.mark.parametrize(("key", "texts", "expect", "surfaces"), CASES, ids=[c[0] for c in CASES])
def test_dialog_adds_each_operation(env, key, texts, expect, surfaces) -> None:
    count, steps = n_ops(env), env.doc.undo_stack.count()
    assert env.surfaces() == 3  # the two overlapping rectangles: a, shared piece, b
    run_tool(env, key, **texts)
    assert n_ops(env) == count + 1
    assert env.doc.undo_stack.count() == steps + 1  # one undo step
    op = env.geometry[-1]
    assert op.id == f"{type(op).__name__.lower()}1"  # generated like a script's id
    for name, value in expect.items():
        if name == "__class__":
            assert type(op) is value
        else:
            assert getattr(op, name) == value, name
    # automatic rebuild: not stale, the build is current
    assert not env.doc.geometry_stale
    if surfaces is not None:
        assert env.surfaces() == surfaces
    env.doc.undo_stack.undo()
    assert n_ops(env) == count
    assert env.surfaces() == 3


def test_transform_changes_the_geometry(env) -> None:
    run_tool(env, "translate", targets="a, b", dx=5, dy=0)
    assert env.doc.built.bbox[0] == pytest.approx(5.0)
    run_tool(env, "mirror", targets="transform1", x0=0, y0=0, x1=0, y1=1)
    assert env.doc.built.bbox[3] == pytest.approx(-5.0, abs=1e-5)  # mirrored about x = 0


def test_dialog_can_add_several_and_keeps_the_given_id(env) -> None:
    env.window.actions["geometry.rectangle"].trigger()
    dialog = env.ctrl.active_dialog
    fill(dialog, x=3, y=3, width=1, height=1)
    dialog.id_edit.setText("mine")
    assert dialog.apply()
    assert dialog.isVisible()  # Apply keeps the dialog open
    fill(dialog, x=5, y=3, width=1, height=1)
    assert dialog.apply()  # a second one gets a generated id
    assert [op.id for op in env.geometry[-2:]] == ["mine", "rectangle1"]
    fill(dialog, x=7, y=3, width=1, height=1)
    dialog.id_edit.setText("mine")
    assert not dialog.apply()
    assert "already used" in dialog.error_label.text()
    dialog.reject()
    assert env.ctrl.active_dialog is None


def test_import_cancelled_adds_nothing(env) -> None:
    env.ctrl.file_chooser = lambda parent: None
    env.window.actions["geometry.import"].trigger()
    assert env.ctrl.active_dialog is None  # cancelled


def test_dialog_errors_are_shown_not_raised(env) -> None:
    count = n_ops(env)
    env.window.actions["geometry.rectangle"].trigger()
    dialog = env.ctrl.active_dialog
    dialog.apply()  # nothing entered
    assert "required" in dialog.error_label.text()
    fill(dialog, x=0, y=0, width=0, height=1)
    assert not dialog.apply()
    assert "width" in dialog.error_label.text()
    fill(dialog, x="abc", y=0, width=1, height=1)
    assert not dialog.apply()
    assert "x" in dialog.error_label.text()
    dialog.reject()
    env.window.actions["geometry.line"].trigger()
    dialog = env.ctrl.active_dialog
    fill(dialog, p1="p1", p2="nope")
    assert not dialog.apply()
    assert "nope" in dialog.error_label.text()
    fill(dialog, p1="p1", p2="a")  # a rectangle is not a point
    assert not dialog.apply()
    assert "not a point" in dialog.error_label.text()
    assert n_ops(env) == count
    assert env.doc.undo_stack.count() == 0


def test_reference_combo_lists_the_right_kind(env) -> None:
    env.window.actions["geometry.line"].trigger()
    dialog = env.ctrl.active_dialog
    combo = dialog.editors["p1"].combo
    assert [combo.itemText(i) for i in range(1, combo.count())] == ["p1", "p2", "p3", "p4"]
    combo.setCurrentIndex(2)
    combo.activated.emit(2)
    assert dialog.editors["p1"].value() == "p2"
    env.window.actions["geometry.spline"].trigger()
    dialog = env.ctrl.active_dialog
    for index in (1, 3):
        dialog.editors["points"].combo.setCurrentIndex(index)
        dialog.editors["points"].combo.activated.emit(index)
    assert dialog.editors["points"].value() == ["p1", "p3"]
    combo = env.ctrl.open_tool("union").editors["objects"].combo
    assert [combo.itemText(i) for i in range(1, combo.count())] == ["a", "b"]


# ------------------------------------------------------------------- click-to-place


def value_of(dialog: GeometryOpDialog, name: str) -> Any:
    return dialog.value(name)


def test_click_places_a_point(env) -> None:
    env.window.actions["geometry.point"].trigger()
    dialog = env.ctrl.active_dialog
    env.view.point_picked.emit(0.123, 0.267, 0.0)
    assert value_of(dialog, "x") == pytest.approx(0.123)
    assert value_of(dialog, "y") == pytest.approx(0.267)
    env.ctrl.set_snap(enabled=True, spacing=0.1)
    assert env.window.actions["geometry.snap"].isChecked()
    env.view.point_picked.emit(0.123, 0.267, 0.0)
    assert value_of(dialog, "x") == pytest.approx(0.1)
    assert value_of(dialog, "y") == pytest.approx(0.3)
    dialog.accept()
    op = env.geometry[-1]
    assert (op.x, op.y) == pytest.approx((0.1, 0.3))


def test_snap_controls_in_dialog_and_menu(env) -> None:
    env.window.actions["geometry.point"].trigger()
    dialog = env.ctrl.active_dialog
    dialog.snap_box.setChecked(True)
    assert env.ctrl.snap.enabled
    assert env.window.actions["geometry.snap"].isChecked()
    dialog.snap_spacing.setText("0.25")
    dialog.snap_spacing.commit()
    assert env.ctrl.snap.spacing == pytest.approx(0.25)
    env.window.actions["geometry.snap"].trigger()  # toggles off
    assert not env.ctrl.snap.enabled
    assert not dialog.snap_box.isChecked()


@pytest.mark.parametrize("snap", [False, True])
def test_click_places_a_rectangle(env, snap) -> None:
    env.ctrl.set_snap(enabled=snap, spacing=0.5)
    env.window.actions["geometry.rectangle"].trigger()
    dialog = env.ctrl.active_dialog
    env.view.point_picked.emit(2.2, 3.1, 0.0)
    assert value_of(dialog, "x") == pytest.approx(2.0 if snap else 2.2)
    env.view.point_picked.emit(1.1, 4.9, 0.0)  # the opposite corner may be any corner
    x, y, w, h = (value_of(dialog, n) for n in ("x", "y", "width", "height"))
    if snap:
        assert (x, y, w, h) == pytest.approx((1.0, 3.0, 1.0, 2.0))
    else:
        assert (x, y, w, h) == pytest.approx((1.1, 3.1, 1.1, 1.8))
    dialog.accept()
    assert env.surfaces() == 4


@pytest.mark.parametrize("snap", [False, True])
def test_click_places_a_circle(env, snap) -> None:
    env.ctrl.set_snap(enabled=snap, spacing=0.5)
    env.window.actions["geometry.circle"].trigger()
    dialog = env.ctrl.active_dialog
    env.view.point_picked.emit(5.1, 5.1, 0.0)
    env.view.point_picked.emit(6.4, 5.1, 0.0)
    expected = (5.0, 5.0, 1.5) if snap else (5.1, 5.1, 1.3)
    got = tuple(value_of(dialog, n) for n in ("xc", "yc", "radius"))
    assert got == pytest.approx(expected)


def test_click_places_polygon_vertices(env) -> None:
    env.ctrl.set_snap(enabled=True, spacing=0.5)
    env.window.actions["geometry.polygon"].trigger()
    dialog = env.ctrl.active_dialog
    for x, y in [(5.1, 5.1), (6.2, 5.0), (6.1, 6.4), (9.0, 9.0)]:
        env.view.point_picked.emit(x, y, 0.0)
    assert value_of(dialog, "vertices")[-1] == (9.0, 9.0)
    dialog.remove_last_vertex()
    assert value_of(dialog, "vertices") == [(5.0, 5.0), (6.0, 5.0), (6.0, 6.5)]
    dialog.finish_button.click()  # the explicit finish button
    assert dialog.result() == dialog.DialogCode.Accepted
    assert env.geometry[-1].vertices == [(5.0, 5.0), (6.0, 5.0), (6.0, 6.5)]
    assert env.surfaces() == 4


def test_clicks_after_the_dialog_closed_are_ignored(env) -> None:
    env.window.actions["geometry.point"].trigger()
    dialog = env.ctrl.active_dialog
    dialog.reject()
    count = n_ops(env)
    env.view.point_picked.emit(1.0, 1.0, 0.0)
    assert n_ops(env) == count
    assert dialog.editors["x"].text() == ""


def test_dialog_follows_a_display_unit_change(env) -> None:
    dialog = env.ctrl.open_tool("rectangle")
    dialog.set_value("width", 0.2)  # stored in SI (m)
    assert dialog.editors["width"].text() == "0.2"
    env.doc.edit("Units", lambda m: setattr(m, "display_units", UnitSettings(length="mm")))
    assert dialog.editors["width"].text() == "200"
    assert "[mm]" in dialog._labels["width"].text()
    assert dialog.value("width") == pytest.approx(0.2)


def test_click_places_transform_fields(env) -> None:
    env.window.actions["geometry.translate"].setEnabled(True)
    env.window.actions["geometry.translate"].trigger()
    dialog = env.ctrl.active_dialog
    env.view.point_picked.emit(1.0, 1.0, 0.0)
    env.view.point_picked.emit(4.0, 0.5, 0.0)
    assert (value_of(dialog, "dx"), value_of(dialog, "dy")) == pytest.approx((3.0, -0.5))


# --------------------------------------------------------------- selection tools


def test_union_of_the_selection(env) -> None:
    act = env.window.actions["geometry.union"]
    assert not act.isEnabled()
    env.select(sorted(env.doc.built.surfaces))
    assert env.ctrl.selected_ops() == ["a", "b"]
    assert act.isEnabled()
    act.trigger()
    dialog = env.ctrl.active_dialog
    assert dialog.value("objects") == ["a"]  # the earliest selected shape is the object
    assert dialog.value("tools") == ["b"]
    dialog.accept()
    op = env.geometry[-1]
    assert (op.kind, op.objects, op.tools) == ("union", ["a"], ["b"])
    assert env.surfaces() == 1
    assert not env.window.actions["geometry.union"].isEnabled()  # selection was reset


def test_cut_in_two_steps_objects_then_tools(env) -> None:
    env.select(env.tags("a", only=True))
    env.window.actions["geometry.cut"].trigger()
    dialog = env.ctrl.active_dialog
    assert dialog.value("objects") == ["a"]
    assert dialog.value("tools") == []
    dialog.accept()  # a cut needs a tool
    assert "tool" in dialog.error_label.text()
    env.select(sorted(env.doc.built.surfaces))  # step two: pick the tools
    dialog.editors["tools"].selection_button.click()
    assert dialog.value("tools") == ["b"]  # what is already an object is left out
    dialog.accept()
    op = env.geometry[-1]
    assert (op.kind, op.objects, op.tools) == ("cut", ["a"], ["b"])
    assert env.surfaces() == 1


def test_intersect_of_the_selection(env) -> None:
    env.select(sorted(env.doc.built.surfaces))
    env.window.actions["geometry.intersect"].trigger()
    env.ctrl.active_dialog.accept()
    assert env.geometry[-1].kind == "intersect"
    assert env.surfaces() == 1


def test_translate_the_selection(env) -> None:
    env.select(env.tags("a", only=True))
    assert env.ctrl.selected_ops() == ["a"]
    act = env.window.actions["geometry.translate"]
    assert act.isEnabled()
    act.trigger()
    dialog = env.ctrl.active_dialog
    assert dialog.value("targets") == ["a"]
    fill(dialog, dx=10, dy=0)
    dialog.accept()
    op = env.geometry[-1]
    assert (op.kind, op.targets, op.params) == ("translate", ["a"], {"dx": 10.0, "dy": 0.0})
    assert env.doc.built.bbox[3] == pytest.approx(11.0)


def test_delete_the_selection(env) -> None:
    env.select(env.tags("b", only=True))
    env.window.actions["geometry.delete"].trigger()
    env.ctrl.active_dialog.accept()
    op = env.geometry[-1]
    assert isinstance(op, g.Delete)
    assert op.targets == ["b"]


def test_selection_without_owning_operations_disables_the_tools(env) -> None:
    # the curves of the rectangles are owned by no operation (only their surfaces are)
    env.select(sorted(env.doc.built.curves), dim=1)
    assert env.ctrl.selected_ops() == []
    for key in ("union", "translate", "delete"):
        assert not env.window.actions[f"geometry.{key}"].isEnabled()


# ---------------------------------------------------------------------------- history


def test_history_edit_rebuilds_and_undoes(env) -> None:
    def area() -> float:
        return sum(fp.measure for fp in env.doc.built.surfaces.values())

    before = area()
    assert before == pytest.approx(1.75)
    address = ("geometry", [op.id for op in env.geometry].index("a"))
    assert env.tree.select_address(address)
    panel = env.props.panel
    assert isinstance(panel, FormPanel)
    assert set(panel.editors) == {"x", "y", "width", "height", "corner_radius"}
    editor = panel.editors["width"]
    editor.setText("2")
    editor.commit()
    assert env.op("a").width == 2.0
    assert env.doc.undo_stack.count() == 1
    assert not env.doc.geometry_stale
    assert area() == pytest.approx(2.5)  # 2x1 plus 1x1 overlapping by 1.0 x 0.5
    env.doc.undo_stack.undo()
    assert env.op("a").width == 1.0
    assert area() == pytest.approx(before)
    assert not env.doc.geometry_stale
    env.doc.undo_stack.redo()
    assert area() == pytest.approx(2.5)


def test_history_edit_of_a_list_field(env) -> None:
    env.doc.edit("add", lambda m: api.Geometry(m).delete(["b"], id="del"))
    assert env.surfaces() == 1
    env.tree.select_address(("geometry", len(env.geometry) - 1))
    panel = env.props.panel
    panel.editors["targets"].setText("a")
    panel.editors["targets"].editingFinished.emit()
    assert env.op("del").targets == ["a"]
    assert env.surfaces() == 1


def test_tree_actions_for_geometry_items(env) -> None:
    item = env.tree.item_for(("geometry", 0))
    actions = env.tree.actions_for(item)
    kinds = [a.data()[0] for a in actions]
    assert kinds == ["edit_op", "delete_op"]
    texts = [a.text() for a in actions]
    assert "Edit" in texts
    assert not [t for t in texts if "up" in t.lower() or "down" in t.lower() or "move" in t.lower()]
    assert env.tree.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
    assert not env.tree.acceptDrops()
    seen: list[Any] = []
    env.tree.edit_requested.connect(seen.append)
    actions[0].trigger()
    assert seen == [("geometry", 0)]
    assert env.props.current_address == ("geometry", 0)


def test_delete_operation_refused_when_referenced(env, dialogs) -> None:
    steps = env.doc.undo_stack.count()
    item = env.tree.item_for(("geometry", 0))  # p1, used by l1 and l4
    delete = next(a for a in env.tree.actions_for(item) if a.data()[0] == "delete_op")
    delete.trigger()
    assert dialogs.calls
    title, message = dialogs.calls[-1]
    assert "p1" in message
    assert "l1" in message
    assert env.op("p1")
    assert env.doc.undo_stack.count() == steps
    with pytest.raises(ModelError):
        env.tree.delete_operation(("geometry", 0))


def test_delete_operation_of_an_unreferenced_op(env) -> None:
    index = [op.id for op in env.geometry].index("b")
    assert env.surfaces() == 3
    assert env.tree.delete_operation(("geometry", index))
    assert [op.id for op in env.geometry].count("b") == 0
    assert env.surfaces() == 1  # rebuilt
    assert env.doc.undo_stack.count() == 1
    env.doc.undo_stack.undo()
    assert env.surfaces() == 3
    # after deleting the user of a reference its target can go too
    for op_id in ("l4", "l1", "p1"):
        i = [op.id for op in env.geometry].index(op_id)
        env.tree.delete_operation(("geometry", i))
    assert "p1" not in [op.id for op in env.geometry]


# ----------------------------------------------------------------------- rebuild


def test_rebuild_failure_keeps_the_app_alive(env, dialogs) -> None:
    old = env.doc.built
    assert not env.doc.geometry_stale
    env.doc.edit("bad", lambda m: api.Geometry(m).line("p1", "ghost", id="bad"))
    assert env.doc.built is old  # the old build stays
    assert env.doc.geometry_stale
    assert env.op("bad")  # the offending operation stays in the history
    assert "ghost" in env.ctrl.last_error
    assert len(dialogs.calls) == 1
    assert dialogs.calls[0][0] == "Geometry build failed"
    # an unrelated edit does not report the same failure again
    env.doc.edit("name", lambda m: setattr(m, "name", "renamed"))
    assert len(dialogs.calls) == 1
    # a manual rebuild is attempted (and fails again)
    assert not env.ctrl.rebuild()
    assert len(dialogs.calls) == 2
    # fix by undoing the edit that is last on the stack, then the bad op
    env.doc.undo_stack.undo()
    env.doc.undo_stack.undo()
    assert not env.doc.geometry_stale
    assert env.ctrl.last_error == ""
    assert env.doc.built is not old
    assert env.surfaces() == 3


def test_a_boolean_that_removes_everything_is_reported(env, dialogs) -> None:
    def mutate(model) -> None:
        geo = api.Geometry(model)
        geo.rectangle(20.0, 20.0, 1.0, 1.0, id="far")
        geo.cut(["far"], ["a"], id="c1")  # disjoint: nothing is removed
        geo.intersect(["far"], ["a"], id="c2")  # nothing is left of "far"

    old = env.doc.built
    env.doc.edit("bad", mutate)
    assert env.doc.built is old
    assert env.doc.geometry_stale
    assert "c2" in dialogs.calls[-1][1]
    env.doc.undo_stack.undo()
    assert not env.doc.geometry_stale


def test_editing_a_broken_operation_fixes_it(env, dialogs) -> None:
    env.doc.edit("bad", lambda m: api.Geometry(m).rectangle(3, 3, 1, 1, id="r"))
    assert env.surfaces() == 4
    index = [op.id for op in env.geometry].index("r")
    env.tree.select_address(("geometry", index))
    panel = env.props.panel
    panel.editors["width"].setText("0")
    panel.editors["width"].commit()  # width 0 is accepted by the form, refused by the builder
    assert env.doc.geometry_stale
    assert dialogs.calls
    panel.editors["width"].setText("2")
    panel.editors["width"].commit()
    assert not env.doc.geometry_stale
    assert env.surfaces() == 4


def test_auto_rebuild_can_be_switched_off(env) -> None:
    env.ctrl.auto_rebuild = False
    run_tool(env, "rectangle", x=3, y=3, width=1, height=1)
    assert env.doc.geometry_stale
    assert env.surfaces() == 3
    assert env.ctrl.rebuild()
    assert not env.doc.geometry_stale
    assert env.surfaces() == 4


def test_rebuild_is_not_reentrant(env) -> None:
    env.ctrl._busy = True
    assert env.ctrl.rebuild() is False
    env.ctrl._busy = False
    assert env.ctrl.rebuild() is True


def test_undo_of_a_geometry_edit_rebuilds(env) -> None:
    run_tool(env, "rectangle", x=3, y=3, width=1, height=1)
    assert env.surfaces() == 4
    env.doc.undo_stack.undo()
    assert env.surfaces() == 3
    env.doc.undo_stack.redo()
    assert env.surfaces() == 4


def test_new_document_builds_an_empty_geometry(env) -> None:
    env.doc.new()
    assert env.surfaces() == 0
    assert not env.doc.geometry_stale


# ----------------------------------------------------------------------------- import


def write_brep(path: Path) -> Path:
    with fresh_model("export") as gmsh:
        gmsh.model.occ.addRectangle(20.0, 20.0, 0.0, 2.0, 1.0)
        gmsh.model.occ.synchronize()
        gmsh.write(str(path))
    return path


def test_import_builds_a_brep_file(env, tmp_path) -> None:
    path = write_brep(tmp_path / "part.brep")
    env.ctrl.file_chooser = lambda parent: str(path)
    env.window.actions["geometry.import"].trigger()
    dialog = env.ctrl.active_dialog
    assert dialog.value("path") == str(path)
    assert dialog.value("format") == "brep"
    fill(dialog, scale=0.5)
    dialog.accept()
    op = env.geometry[-1]
    assert isinstance(op, g.ImportFile)
    assert (op.path, op.format, op.scale) == (str(path), "brep", 0.5)
    assert env.surfaces() == 4
    assert env.doc.built.bbox[3] == pytest.approx(11.0)  # 22 * 0.5
    env.doc.undo_stack.undo()
    assert env.surfaces() == 3


def test_import_of_a_missing_file_is_a_readable_error(env, tmp_path) -> None:
    missing = tmp_path / "gone.step"
    env.ctrl.file_chooser = lambda parent: str(missing)
    env.window.actions["geometry.import"].trigger()
    dialog = env.ctrl.active_dialog
    assert dialog.value("format") == "step"
    assert not dialog.apply()
    assert "file not found" in dialog.error_label.text()
    assert env.doc.undo_stack.count() == 0


def test_import_of_an_unknown_file_type_is_reported(env, dialogs) -> None:
    env.ctrl.file_chooser = lambda parent: "model.xyz"
    env.window.actions["geometry.import"].trigger()
    assert env.ctrl.active_dialog is None
    assert "model.xyz" in dialogs.calls[-1][1]


# ---------------------------------------------------------------- real viewport


def test_with_the_real_viewport(qtbot, window) -> None:
    model = base_model()
    doc = Document(model)
    view = attach_viewport(window, doc)
    attach_tree(window, doc, view)
    ctrl = attach_geometry_tools(window, doc, view)
    assert ctrl.rebuild()
    assert view.selection_mode == "none"
    view.set_selection_mode("surface")
    tags = sorted(doc.built.surfaces)
    view.highlight(2, tags)
    view.selection_changed.emit(2, tags)  # what a click in the viewport reports
    assert ctrl.selected_ops() == ["a", "b"]
    assert window.actions["geometry.union"].isEnabled()
    window.actions["geometry.point"].trigger()
    view.point_picked.emit(0.3, 0.4, 0.0)
    assert ctrl.active_dialog.value("x") == pytest.approx(0.3)
    ctrl.active_dialog.accept()
    assert isinstance(doc.model.geometry[-1], g.Point)
