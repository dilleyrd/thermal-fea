"""M11.61: hover and inspect (viewport signals and InspectController)."""

from __future__ import annotations

import pytest
from matplotlib.backend_bases import MouseEvent
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QMainWindow

from thermalfea import api
from thermalfea.gui.document import Document
from thermalfea.gui.inspect import entity_report
from thermalfea.gui.inspect_tools import InspectController
from thermalfea.gui.viewport_mpl import MplSceneView
from thermalfea.model import bcs

# ------------------------------------------------------------------ viewport signals


def event(view, name, x, y, button=None, ctrl=False):
    px, py = view.axes.transData.transform((x, y)) + 1e-6
    return MouseEvent(
        name, view.canvas, px, py, button=button, modifiers=["ctrl"] if ctrl else None
    )


def fire(ev):
    ev._process()


def click(view, x, y, ctrl=False):
    fire(event(view, "button_press_event", x, y, button=1, ctrl=ctrl))
    fire(event(view, "button_release_event", x, y, button=1, ctrl=ctrl))


@pytest.fixture
def view(qtbot):
    v = MplSceneView()
    qtbot.addWidget(v.widget())
    v.widget().resize(640, 480)
    model = api.new_model()
    api.Geometry(model).rectangle(0, 0, 4, 2, id="plate")
    v.built = api.build(model)
    v.set_geometry(v.built)
    return v


def curve_tag(view, x, y):
    ents = view.built.entities(1)
    return min(ents, key=lambda t: (ents[t].center[0] - x) ** 2 + (ents[t].center[1] - y) ** 2)


def test_hover_emits_tag_and_none_on_leave(view, qtbot) -> None:
    view.set_selection_mode("curve")
    tag = curve_tag(view, 2.0, 0.0)
    with qtbot.waitSignal(view.entity_hovered, timeout=1000) as blocker:
        fire(event(view, "motion_notify_event", 2.0, 0.0))
    assert blocker.args == [1, tag]
    with qtbot.waitSignal(view.entity_hovered, timeout=1000) as blocker:
        fire(event(view, "motion_notify_event", 2.0, 1.0))
    assert blocker.args == [-1, -1]
    fire(event(view, "motion_notify_event", 2.0, 0.0))
    with qtbot.waitSignal(view.entity_hovered, timeout=1000) as blocker:
        view.set_selection_mode("none")
    assert blocker.args == [-1, -1]


def test_single_click_emits_entity_clicked(view, qtbot) -> None:
    view.set_selection_mode("curve")
    tag = curve_tag(view, 2.0, 0.0)
    with qtbot.waitSignal(view.entity_clicked, timeout=1000) as blocker:
        click(view, 2.0, 0.0)
    assert blocker.args == [1, tag]
    with qtbot.waitSignal(view.entity_clicked, timeout=1000) as blocker:
        click(view, 2.0, 1.0)  # empty space
    assert blocker.args == [-1, -1]


def test_ctrl_click_and_box_do_not_emit_entity_clicked(view, qtbot) -> None:
    view.set_selection_mode("curve")
    view.fit()
    with qtbot.assertNotEmitted(view.entity_clicked):
        with qtbot.waitSignal(view.selection_changed, timeout=1000):
            click(view, 2.0, 0.0, ctrl=True)
        with qtbot.waitSignal(view.selection_changed, timeout=1000):
            fire(event(view, "button_press_event", -0.1, -0.1, button=1))
            fire(event(view, "motion_notify_event", 4.1, 2.1))
            fire(event(view, "button_release_event", 4.1, 2.1, button=1))


# ----------------------------------------------------------------------- controller


class FakeView(QObject):
    entity_hovered = Signal(int, int)
    entity_clicked = Signal(int, int)


class FakeTree:
    def __init__(self) -> None:
        self.calls: list[list[tuple]] = []

    def mark_addresses(self, addresses) -> None:
        self.calls.append(list(addresses))


def _on(axis: int, value: float):
    return lambda c: abs(c.bbox[axis] - value) < 1e-6 and abs(c.bbox[axis + 3] - value) < 1e-6


@pytest.fixture
def doc() -> Document:
    model = api.new_model(name="strips")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 0.6, 0.2)
    geo.rectangle(0.0, 0.2, 0.6, 0.8)
    built = api.build(model)
    api.select_surfaces(model, built, "lower", where=lambda s: s.bbox[4] < 0.21)
    api.select_surfaces(model, built, "upper", where=lambda s: s.bbox[1] > 0.19)
    api.select_curves(model, built, "right", where=_on(0, 0.6))
    api.assign_region(model, "lower", material="Copper (pure)")
    api.assign_region(model, "upper", material="Copper (pure)")
    model.bcs += [bcs.Convection("cooling", "right", h=750.0, T_inf=273.15)]
    document = Document(model)
    document.set_built(built)
    return document


@pytest.fixture
def setup(qtbot, doc):
    window = QMainWindow()
    qtbot.addWidget(window)
    fake, tree = FakeView(), FakeTree()
    ctrl = InspectController(window, doc, fake, tree)
    return window, fake, tree, ctrl


def right_tag(doc: Document) -> int:
    return int(doc.model.selections["right"].tags[0])


def test_hover_sets_tooltip_text_and_leaving_clears(setup, doc) -> None:
    _window, fake, _tree, ctrl = setup
    tag = right_tag(doc)
    fake.entity_hovered.emit(1, tag)
    assert ctrl.tooltip_text == "\n".join(entity_report(doc, 1, tag).lines())
    assert "convection cooling" in ctrl.tooltip_text
    fake.entity_hovered.emit(-1, -1)
    assert ctrl.tooltip_text == ""


def test_click_sets_status_and_marks_tree(setup, doc) -> None:
    window, fake, tree, ctrl = setup
    tag = right_tag(doc)
    fake.entity_clicked.emit(1, tag)
    report = entity_report(doc, 1, tag)
    assert ctrl.report is not None and ctrl.report.title == report.title
    assert window.statusBar().currentMessage().startswith(report.title)
    assert tree.calls[-1] == report.addresses()
    fake.entity_clicked.emit(-1, -1)
    assert tree.calls[-1] == [] and ctrl.report is None


def test_click_ignored_while_busy(setup, doc) -> None:
    window, fake, tree, ctrl = setup
    flag = {"on": True}
    ctrl.extra_busy.append(lambda: flag["on"])
    assert ctrl.busy()
    fake.entity_clicked.emit(1, right_tag(doc))
    assert ctrl.report is None and window.statusBar().currentMessage() == ""
    assert not any(tree.calls)
    flag["on"] = False
    assert not ctrl.busy()
    fake.entity_clicked.emit(1, right_tag(doc))
    assert ctrl.report is not None


def test_busy_sees_a_picking_selection_editor(setup, doc, qtbot) -> None:
    from thermalfea.gui.property_panels.form import FieldSpec
    from thermalfea.gui.property_panels.selection_editor import SelectionEditor

    window, fake, _tree, ctrl = setup
    spec = FieldSpec("selection", "Selection", "selection", selection_dims=(1,))
    editor = SelectionEditor(doc, None, spec)
    editor.setParent(window)  # only the controller's own window counts
    assert not ctrl.busy()
    editor.pick_button.setEnabled(True)
    editor.pick_button.setChecked(True)
    assert ctrl.busy()
    fake.entity_clicked.emit(1, right_tag(doc))
    assert ctrl.report is None
