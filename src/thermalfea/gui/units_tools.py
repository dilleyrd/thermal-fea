"""Display units in the GUI (Plan M10.4): the Tools menu entry and the units dialog.

:func:`attach_units` adds the action ``tools.units`` ("Units...") to the Tools menu.
Triggering it shows the :class:`~thermalfea.gui.dialogs.units.UnitsDialog` non-modally
(``show()``, never ``exec()``), loaded with the current settings of the model.
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from thermalfea.gui.dialogs.units import UnitsDialog
from thermalfea.gui.document import Document
from thermalfea.gui.main_window import MainWindow

ACTION_ID = "tools.units"


class UnitsController(QObject):
    """Owns the units action and its dialog of one window.

    Parameters
    ----------
    window : MainWindow
        Its Tools menu receives the action; the dialog is parented to it.
    document : Document

    Attributes
    ----------
    action : QAction
        The Tools menu entry.
    dialog : UnitsDialog or None
        Created on the first trigger.
    """

    def __init__(self, window: MainWindow, document: Document) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.dialog: UnitsDialog | None = None
        self.action = QAction("Units...", window)
        self.action.setToolTip("Choose the units numbers are shown and typed in.")
        self.action.triggered.connect(lambda _checked=False: self.show_dialog())
        window.actions[ACTION_ID] = self.action
        window.menus["tools"].addAction(self.action)

    def show_dialog(self) -> UnitsDialog:
        """Show the dialog (non-modal) with the model's current units; return it."""
        if self.dialog is None:
            self.dialog = UnitsDialog(self.document, self.window)
        else:
            self.dialog.reload()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        return self.dialog


def attach_units(window: MainWindow, document: Document) -> UnitsController:
    """Install the units entry in a main window.

    Parameters
    ----------
    window : MainWindow
    document : Document

    Returns
    -------
    UnitsController
    """
    return UnitsController(window, document)
