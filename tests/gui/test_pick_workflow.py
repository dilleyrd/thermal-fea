"""M11.69: one pick workflow (convention C2).

Every pick shows a strip while it runs (instruction, count, confirm, Cancel), switches the
toolbar to the kind of entity it needs and back, and answers Enter (confirm) and Esc
(cancel); one pick runs at a time. Covered: the pick manager itself, the Selections
panel's Add/Remove, the stream path (in ``test_flow_panels``), the probe and the geometry
tool dialogs.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLineEdit, QVBoxLayout, QWidget

# fixtures of the panels and tools under test
from tests.gui.test_geometry_tools import env  # noqa: F401
from tests.gui.test_probe_markers import steady_o  # noqa: F401
from tests.gui.test_results_display import steady_case  # noqa: F401
from tests.gui.test_selections_section import panel, shell  # noqa: F401

from thermalfea.gui.pick import PickManager, PickStrip, count_text, manager_for


class ToolbarWindow(QWidget):
    """A window with the selection toolbar's actions, like the main window."""

    def __init__(self) -> None:
        super().__init__()
        self.actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        for mode in ("none", "point", "curve", "surface", "node"):
            action = QAction(mode, self)
            action.setCheckable(True)
            group.addAction(action)
            self.actions[f"select.{mode}"] = action
        self.actions["select.surface"].setChecked(True)

    @property
    def selection_mode(self) -> str:
        for name, action in self.actions.items():
            if action.isChecked():
                return name.split(".", 1)[1]
        return "none"


class PickView(QWidget):
    """A viewport stand-in: a widget with pick modes."""

    point_picked = Signal(float, float, float)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.modes: list[str] = []

    def set_selection_mode(self, mode: str) -> None:
        self.modes.append(mode)


class Owner(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.log: list[str] = []


def setup(qtbot) -> tuple[ToolbarWindow, PickView, QLineEdit, PickManager]:
    window = ToolbarWindow()
    layout = QVBoxLayout(window)
    view = PickView(window)
    other = QLineEdit()
    layout.addWidget(view)
    layout.addWidget(other)
    qtbot.addWidget(window)
    return window, view, other, manager_for(view)


def start(manager: PickManager, owner: Owner, mode: str = "curve", **kw: Any) -> None:
    def cancel() -> None:
        owner.log.append("cancel")
        manager.finish(owner)

    def confirm() -> None:
        owner.log.append("confirm")
        manager.finish(owner)

    manager.start(owner, mode, cancel=cancel, confirm=confirm, **kw)


# ------------------------------------------------------------------- the manager
def test_a_pick_switches_the_toolbar_and_restores_it(qtbot) -> None:
    window, view, _other, manager = setup(qtbot)
    owner = Owner()
    start(manager, owner)
    assert view.modes[-1] == "curve" and window.selection_mode == "curve"
    assert manager.is_active(owner)
    manager.confirm_active()
    assert owner.log == ["confirm"] and manager.active is None
    assert view.modes[-1] == "surface" and window.selection_mode == "surface"  # restored


def test_esc_cancels_and_enter_confirms(qtbot) -> None:
    _window, view, other, manager = setup(qtbot)
    owner = Owner()
    start(manager, owner)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert owner.log == ["cancel"] and manager.active is None
    start(manager, owner)
    view.setFocus()
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert owner.log == ["cancel", "confirm"]
    # after the pick, keys reach the widgets as usual (the filter is gone)
    QTest.keyClick(view, Qt.Key.Key_Escape)
    assert owner.log == ["cancel", "confirm"]


def test_enter_elsewhere_keeps_its_own_meaning(qtbot) -> None:
    window, _view, other, manager = setup(qtbot)
    window.show()
    owner = Owner()
    start(manager, owner)
    other.setFocus()
    qtbot.waitUntil(other.hasFocus, timeout=2000)
    QTest.keyClick(other, Qt.Key.Key_Return)
    assert owner.log == [] and manager.is_active(owner)
    QTest.keyClick(other, Qt.Key.Key_Escape)  # Esc cancels wherever the focus is
    assert owner.log == ["cancel"]


def test_one_pick_at_a_time(qtbot) -> None:
    _window, _view, _other, manager = setup(qtbot)
    first, second = Owner(), Owner()
    stopped: list[str] = []
    manager.on_start.append(lambda: stopped.append("other tool"))
    start(manager, first)
    start(manager, second, mode="point")
    assert first.log == ["cancel"] and manager.is_active(second)
    assert stopped == ["other tool", "other tool"]


def test_the_strip_shows_only_while_picking(qtbot) -> None:
    strip = PickStrip("Add")
    qtbot.addWidget(strip)
    assert strip.isHidden()
    strip.show_pick("Click the boundaries.", count_text(0, "boundary", "boundaries"))
    assert not strip.isHidden() and strip.count_label.text() == "0 boundaries picked"
    strip.set_count(count_text(1, "boundary", "boundaries"))
    assert strip.count_label.text() == "1 boundary picked"
    seen: list[str] = []
    strip.confirmed.connect(lambda: seen.append("ok"))
    strip.cancelled.connect(lambda: seen.append("cancel"))
    strip.confirm_button.click()
    strip.cancel_button.click()
    assert seen == ["ok", "cancel"]
    strip.hide_pick()
    assert strip.isHidden()
    probe = PickStrip("")
    qtbot.addWidget(probe)
    assert probe.confirm_button.isHidden() and probe.cancel_button.text() == "Stop"


# ----------------------------------------------------------- the picks that use it
def test_selections_panel_answers_esc_and_enter(shell) -> None:  # noqa: F811
    doc, view = shell.doc, shell.view
    p = panel(shell, "spare")
    count = doc.undo_stack.count()
    p.add_button.click()
    view.pick(1, [shell.bottom])
    QTest.keyClick(p, Qt.Key.Key_Escape)
    assert p.picking is None and p.strip.isHidden() and doc.undo_stack.count() == count
    p.add_button.click()
    view.pick(1, [shell.bottom])
    QTest.keyClick(p.strip, Qt.Key.Key_Return)
    assert p.picking is None and doc.undo_stack.count() == count + 1
    assert sorted(doc.model.selections["spare"].tags) == sorted([shell.top, shell.bottom])


def test_the_probe_is_a_pick_that_esc_stops(steady_o) -> None:  # noqa: F811
    ctrl, view, window = steady_o.ctrl, steady_o.view, steady_o.window
    manager = manager_for(view)
    assert ctrl.probe_active and manager.is_active(ctrl)
    QTest.keyClick(window, Qt.Key.Key_Escape)
    assert not ctrl.probe_active and not window.actions["results.probe"].isChecked()
    assert manager.active is None


def test_a_placing_geometry_dialog_answers_esc(env) -> None:  # noqa: F811
    env.window.actions["geometry.point"].trigger()
    dialog = env.ctrl.active_dialog
    manager = manager_for(env.view)
    assert manager.is_active(dialog)
    n = len(env.geometry)
    QTest.keyClick(env.window, Qt.Key.Key_Escape)
    assert not dialog.isVisible() and manager.active is None
    assert len(env.geometry) == n  # nothing added
