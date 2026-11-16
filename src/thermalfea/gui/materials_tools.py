"""Material library in the GUI (Plan M8.6): the Tools menu entry and the library dialog.

:func:`attach_materials` adds the action ``tools.material_library`` ("Material library...")
to the Tools menu. Triggering it shows the :class:`MaterialLibraryDialog` non-modally
(``show()``, never ``exec()``), re-reading the libraries each time.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from thermalfea.gui.dialogs.material_library import MaterialLibraryDialog
from thermalfea.gui.document import Document
from thermalfea.gui.main_window import MainWindow

ACTION_ID = "tools.material_library"


class MaterialLibraryController(QObject):
    """Owns the library action and its dialog of one window.

    Parameters
    ----------
    window : MainWindow
        Its Tools menu receives the action; the dialog is parented to it.
    document : Document
    user_path : Path, optional
        User library file for the dialog; default the library's own location.

    Attributes
    ----------
    action : QAction
        The Tools menu entry.
    dialog : MaterialLibraryDialog or None
        Created on the first trigger.
    """

    def __init__(
        self, window: MainWindow, document: Document, user_path: Path | None = None
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.user_path = user_path
        self.dialog: MaterialLibraryDialog | None = None
        self.action = QAction("Material library...", window)
        self.action.triggered.connect(lambda _checked=False: self.show_dialog())
        window.actions[ACTION_ID] = self.action
        window.menus["tools"].addAction(self.action)

    def show_dialog(self) -> MaterialLibraryDialog:
        """Show the dialog (non-modal) with the libraries re-read; return it."""
        if self.dialog is None:
            self.dialog = MaterialLibraryDialog(self.document, self.user_path, self.window)
        else:
            self.dialog.reload()
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        return self.dialog


def attach_materials(
    window: MainWindow, document: Document, user_path: Path | None = None
) -> MaterialLibraryController:
    """Install the material library entry in a main window.

    Parameters
    ----------
    window : MainWindow
    document : Document
    user_path : Path, optional
        User library file; defaults to the library's own location.

    Returns
    -------
    MaterialLibraryController
    """
    return MaterialLibraryController(window, document, user_path)
