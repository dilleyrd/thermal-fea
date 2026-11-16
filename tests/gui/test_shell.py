"""M8.1: application shell."""

from __future__ import annotations

import logging
import sys
import threading

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel, QWidget

from conftest import DialogRecorder, make_settings
from thermalfea.core.errors import ModelError
from thermalfea.gui.app import create_app, install_exception_hook
from thermalfea.gui.main_window import SELECTION_MODES, MainWindow
from thermalfea.gui.message_panel import QtLogHandler


def test_docks(window: MainWindow) -> None:
    assert window.model_dock.windowTitle() == "Model"
    assert window.properties_dock.windowTitle() == "Properties"
    assert window.messages_dock.windowTitle() == "Messages"
    area = window.dockWidgetArea
    assert area(window.model_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert area(window.properties_dock) == Qt.DockWidgetArea.LeftDockWidgetArea
    assert area(window.messages_dock) == Qt.DockWidgetArea.BottomDockWidgetArea
    assert window.message_panel.isReadOnly()


def test_menus_and_actions(window: MainWindow) -> None:
    titles = [a.text().replace("&", "") for a in window.menuBar().actions()]
    assert titles == [
        "File", "Edit", "View", "Geometry", "Mesh", "Solve", "Results", "Tools", "Help",
    ]  # fmt: skip
    for key in (
        "file.new", "file.open", "file.save", "file.save_as", "file.exit",
        "edit.undo", "edit.redo", "view.fit", "help.about",
        "view.dock.model", "view.dock.properties", "view.dock.messages",
    ):  # fmt: skip
        assert key in window.actions
    assert not window.actions["file.new"].isEnabled()
    assert window.actions["file.exit"].isEnabled()
    assert window.actions["help.about"].isEnabled()


def test_selection_modes_exclusive(window: MainWindow, qtbot) -> None:
    assert window.selection_group.isExclusive()
    assert window.selection_mode == "none"
    seen: list[str] = []
    window.selection_mode_changed.connect(seen.append)
    for mode in SELECTION_MODES[1:]:
        window.actions[f"select.{mode}"].trigger()
        assert window.selection_mode == mode
        checked = [m for m in SELECTION_MODES if window.actions[f"select.{m}"].isChecked()]
        assert checked == [mode]
    assert seen == list(SELECTION_MODES[1:])


def test_placeholders_replaced(window: MainWindow) -> None:
    for setter, getter in (
        (window.set_viewport, lambda: window.viewport_widget),
        (window.set_tree, lambda: window.tree_widget),
        (window.set_property_panel, lambda: window.property_widget),
    ):
        w = QWidget()
        setter(w)
        assert getter() is w
        w2 = QLabel("x")
        setter(w2)
        assert getter() is w2


def test_status(window: MainWindow) -> None:
    window.show_status("x=1")
    assert window.status_text == "x=1"


def test_log_to_panel(window: MainWindow, qtbot) -> None:
    logging.getLogger("thermalfea.something").warning("hello")
    qtbot.waitUntil(lambda: "hello" in window.message_panel.toPlainText(), timeout=3000)


def test_log_from_thread(window: MainWindow, qtbot) -> None:
    t = threading.Thread(
        target=lambda: logging.getLogger("thermalfea.worker").error("from-thread")
    )
    t.start()
    t.join()
    qtbot.waitUntil(lambda: "from-thread" in window.message_panel.toPlainText(), timeout=3000)


def test_handler_removed_on_close(window: MainWindow) -> None:
    logger = logging.getLogger("thermalfea")
    assert any(isinstance(h, QtLogHandler) for h in logger.handlers)
    window.close()
    assert not any(isinstance(h, QtLogHandler) for h in logger.handlers)


def test_state_round_trip(qtbot, settings_path) -> None:
    first = MainWindow(settings=make_settings(settings_path))
    qtbot.addWidget(first)
    first.messages_dock.hide()
    first.close()
    second = MainWindow(settings=make_settings(settings_path))
    qtbot.addWidget(second)
    assert second.messages_dock.isHidden()
    assert not second.model_dock.isHidden()


def test_exception_hook(window: MainWindow, dialogs: DialogRecorder) -> None:
    original = sys.excepthook
    restore = install_exception_hook(window)
    try:
        assert sys.excepthook is not original
        try:
            raise ModelError("bad input")
        except ModelError:
            sys.excepthook(*sys.exc_info())
        assert dialogs.calls[-1][1] == "bad input"
        try:
            raise ValueError("boom")
        except ValueError:
            sys.excepthook(*sys.exc_info())
        title, message = dialogs.calls[-1]
        assert "Unexpected" in title and "boom" in message
    finally:
        restore()
    assert sys.excepthook is original


def test_hook_never_raises(window: MainWindow) -> None:
    def bad(title: str, message: str) -> None:
        raise RuntimeError("dialog failed")

    window.error_dialog = bad
    restore = install_exception_hook(window)
    try:
        sys.excepthook(ValueError, ValueError("x"), None)
    finally:
        restore()


def test_create_app_reuses_instance(qapp) -> None:
    assert create_app([]) is QApplication.instance()
    assert create_app([]) is qapp
