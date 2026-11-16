"""Main window: docks, menus, toolbar, status bar and window-state persistence."""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from thermalfea.gui.message_panel import MessagePanel, QtLogHandler

SELECTION_MODES: tuple[str, ...] = ("none", "point", "curve", "surface", "node", "element")
_MENU_TITLES: tuple[tuple[str, str], ...] = (
    ("file", "&File"),
    ("edit", "&Edit"),
    ("view", "&View"),
    ("geometry", "&Geometry"),
    ("mesh", "&Mesh"),
    ("solve", "&Solve"),
    ("results", "&Results"),
    ("tools", "&Tools"),
    ("help", "&Help"),
)
_LOGGER_NAME = "thermalfea"


def _default_error_dialog(title: str, message: str) -> None:
    """Show a modal critical message box."""
    QMessageBox.critical(None, title, message)


class _Holder(QWidget):
    """Container with a placeholder label that can be replaced by a real widget."""

    def __init__(self, placeholder: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._placeholder = QLabel(placeholder, self)
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._layout.addWidget(self._placeholder)
        self.content: QWidget = self._placeholder

    def set_content(self, widget: QWidget) -> None:
        """Replace the current content with ``widget``."""
        if widget is self.content:
            return
        self._layout.removeWidget(self.content)
        self.content.setParent(None)
        self.content = widget
        self._layout.addWidget(widget)


class MainWindow(QMainWindow):
    """Application shell modelled on ANSYS Mechanical.

    Model tree on the left, viewport in the centre, property panel under the tree,
    message log at the bottom, a toolbar with selection-mode buttons.

    Parameters
    ----------
    settings : QSettings, optional
        Where window geometry and dock state are persisted. Defaults to the
        application's own settings; tests pass a temporary ini-file instance.
    parent : QWidget, optional
        Parent widget.

    Attributes
    ----------
    actions : dict[str, QAction]
        Every action by stable id, e.g. ``"file.new"``.
    error_dialog : Callable[[str, str], None]
        Called with ``(title, message)`` by :meth:`show_error`; replaceable.
    """

    selection_mode_changed = Signal(str)

    def __init__(
        self, settings: QSettings | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("ThermalFEA")
        self.resize(1280, 800)
        self.settings: QSettings = settings if settings is not None else QSettings()
        self.error_dialog: Callable[[str, str], None] = _default_error_dialog
        self.actions: dict[str, QAction] = {}
        self.menus: dict[str, QMenu] = {}
        self._log_handler: QtLogHandler | None = None

        self._viewport_holder = _Holder("Viewport")
        self.setCentralWidget(self._viewport_holder)
        self._tree_holder = _Holder("Model tree")
        self._property_holder = _Holder("Properties")
        self.message_panel = MessagePanel()

        self.model_dock = self._make_dock("Model", "ModelDock", self._tree_holder)
        self.properties_dock = self._make_dock(
            "Properties", "PropertiesDock", self._property_holder
        )
        self.messages_dock = self._make_dock("Messages", "MessagesDock", self.message_panel)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.model_dock)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.properties_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.messages_dock)
        self.splitDockWidget(
            self.model_dock, self.properties_dock, Qt.Orientation.Vertical
        )

        self._build_actions()
        self._build_menus()
        self._build_toolbar()

        self._status_label = QLabel("Ready")
        self.statusBar().addPermanentWidget(self._status_label)

        self._install_log_handler()
        self.restore_state()

    # ------------------------------------------------------------------ docks
    def _make_dock(self, title: str, name: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(name)
        dock.setWidget(widget)
        return dock

    def set_viewport(self, widget: QWidget) -> None:
        """Install ``widget`` as the central viewport."""
        self._viewport_holder.set_content(widget)

    def set_tree(self, widget: QWidget) -> None:
        """Install ``widget`` as the model tree."""
        self._tree_holder.set_content(widget)

    def set_property_panel(self, widget: QWidget) -> None:
        """Install ``widget`` as the property panel."""
        self._property_holder.set_content(widget)

    @property
    def viewport_widget(self) -> QWidget:
        """The widget currently shown in the centre."""
        return self._viewport_holder.content

    @property
    def tree_widget(self) -> QWidget:
        """The widget currently shown in the model dock."""
        return self._tree_holder.content

    @property
    def property_widget(self) -> QWidget:
        """The widget currently shown in the properties dock."""
        return self._property_holder.content

    # ---------------------------------------------------------------- actions
    def _add_action(
        self,
        key: str,
        text: str,
        *,
        shortcut: QKeySequence.StandardKey | str | None = None,
        enabled: bool = False,
        slot: Callable[[], object] | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(QKeySequence(shortcut))
        action.setEnabled(enabled)
        if slot is not None:
            action.triggered.connect(slot)
        self.actions[key] = action
        return action

    def _build_actions(self) -> None:
        std = QKeySequence.StandardKey
        self._add_action("file.new", "&New", shortcut=std.New)
        self._add_action("file.open", "&Open...", shortcut=std.Open)
        self._add_action("file.save", "&Save", shortcut=std.Save)
        self._add_action("file.save_as", "Save &As...", shortcut=std.SaveAs)
        self._add_action(
            "file.exit", "E&xit", shortcut=std.Quit, enabled=True, slot=self.close
        )
        self._add_action("edit.undo", "&Undo", shortcut=std.Undo)
        self._add_action("edit.redo", "&Redo", shortcut=std.Redo)
        self._add_action("view.fit", "&Fit view", shortcut="F")
        for key, dock in (
            ("view.dock.model", self.model_dock),
            ("view.dock.properties", self.properties_dock),
            ("view.dock.messages", self.messages_dock),
        ):
            self.actions[key] = dock.toggleViewAction()
        self._add_action("help.about", "&About ThermalFEA", enabled=True, slot=self._about)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        for key, title in _MENU_TITLES:
            self.menus[key] = bar.addMenu(title)
        for key in ("file.new", "file.open", "file.save", "file.save_as"):
            self.menus["file"].addAction(self.actions[key])
        self.menus["file"].addSeparator()
        self.menus["file"].addAction(self.actions["file.exit"])
        self.menus["edit"].addAction(self.actions["edit.undo"])
        self.menus["edit"].addAction(self.actions["edit.redo"])
        self.menus["view"].addAction(self.actions["view.fit"])
        self.menus["view"].addSeparator()
        for key in ("view.dock.model", "view.dock.properties", "view.dock.messages"):
            self.menus["view"].addAction(self.actions[key])
        self.menus["help"].addAction(self.actions["help.about"])

    def _build_toolbar(self) -> None:
        bar = self.addToolBar("Selection")
        bar.setObjectName("SelectionToolBar")
        self.selection_group = QActionGroup(self)
        self.selection_group.setExclusive(True)
        for mode in SELECTION_MODES:
            action = QAction(mode.capitalize(), self)
            action.setCheckable(True)
            action.setData(mode)
            action.setToolTip(f"Selection mode: {mode}")
            self.selection_group.addAction(action)
            bar.addAction(action)
            self.actions[f"select.{mode}"] = action
        self.actions["select.none"].setChecked(True)
        self.selection_group.triggered.connect(self._on_selection_triggered)
        bar.addSeparator()
        bar.addAction(self.actions["view.fit"])

    def _on_selection_triggered(self, action: QAction) -> None:
        self.selection_mode_changed.emit(str(action.data()))

    @property
    def selection_mode(self) -> str:
        """The currently checked selection mode."""
        checked = self.selection_group.checkedAction()
        return str(checked.data()) if checked is not None else "none"

    def _about(self) -> None:
        QMessageBox.about(self, "About ThermalFEA", "ThermalFEA - 2D thermal finite elements.")

    # ----------------------------------------------------------------- status
    def show_status(self, text: str) -> None:
        """Show ``text`` in the permanent status-bar label."""
        self._status_label.setText(text)

    @property
    def status_text(self) -> str:
        """Text currently in the permanent status-bar label."""
        return self._status_label.text()

    # ----------------------------------------------------------------- errors
    def show_error(self, title: str, message: str) -> None:
        """Show an error dialog through :attr:`error_dialog`."""
        self.error_dialog(title, message)

    # ---------------------------------------------------------------- logging
    def _install_log_handler(self) -> None:
        self._log_handler = QtLogHandler(self.message_panel)
        logger = logging.getLogger(_LOGGER_NAME)
        logger.addHandler(self._log_handler)
        if logger.getEffectiveLevel() > logging.INFO:
            logger.setLevel(logging.INFO)

    def _remove_log_handler(self) -> None:
        if self._log_handler is not None:
            logging.getLogger(_LOGGER_NAME).removeHandler(self._log_handler)
            self._log_handler = None

    # ------------------------------------------------------------- persistence
    def save_state(self) -> None:
        """Write window geometry and dock layout to the settings."""
        self.settings.setValue("MainWindow/geometry", self.saveGeometry())
        self.settings.setValue("MainWindow/state", self.saveState())
        self.settings.sync()

    def restore_state(self) -> bool:
        """Restore geometry and dock layout from the settings.

        Returns
        -------
        bool
            ``True`` if a stored state was found and applied.
        """
        geometry = self.settings.value("MainWindow/geometry")
        state = self.settings.value("MainWindow/state")
        ok = False
        if geometry is not None:
            ok = bool(self.restoreGeometry(geometry)) or ok
        if state is not None:
            ok = bool(self.restoreState(state)) or ok
        return ok

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 (Qt override)
        """Persist window state and detach the log handler."""
        self.save_state()
        self._remove_log_handler()
        super().closeEvent(event)
