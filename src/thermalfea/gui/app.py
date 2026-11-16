"""Application bootstrap: QApplication, global exception hook, ``main``."""

from __future__ import annotations

import logging
import sys
import traceback
from collections.abc import Callable
from types import TracebackType

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from thermalfea.core.errors import ThermalFEAError
from thermalfea.gui.document import Document
from thermalfea.gui.geometry_tools import attach_geometry_tools
from thermalfea.gui.main_window import MainWindow
from thermalfea.gui.panels import attach_tree
from thermalfea.gui.viewport_mpl import attach_viewport

ORGANIZATION = "ThermalFEA"
APPLICATION = "ThermalFEA"

_log = logging.getLogger("thermalfea.gui.app")


def create_app(argv: list[str] | None = None) -> QApplication:
    """Return the ``QApplication``, creating it if none exists.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments; defaults to ``sys.argv``.

    Returns
    -------
    QApplication
    """
    app = QApplication.instance()
    if app is None:
        app = QApplication(list(sys.argv if argv is None else argv))
    QCoreApplication.setOrganizationName(ORGANIZATION)
    QCoreApplication.setApplicationName(APPLICATION)
    return app  # type: ignore[return-value]


def install_exception_hook(window: MainWindow) -> Callable[[], None]:
    """Replace ``sys.excepthook`` so uncaught errors are logged and shown.

    A :class:`ThermalFEAError` is logged and its message shown through
    ``window.show_error``; any other exception is logged with its traceback and shown
    as an unexpected error. The hook never raises.

    Parameters
    ----------
    window : MainWindow
        Window whose error dialog is used.

    Returns
    -------
    Callable[[], None]
        Function restoring the previous ``sys.excepthook``.
    """
    previous = sys.excepthook

    def hook(
        exc_type: type[BaseException],
        exc: BaseException,
        tb: TracebackType | None,
    ) -> None:
        try:
            if issubclass(exc_type, KeyboardInterrupt):
                previous(exc_type, exc, tb)
                return
            if isinstance(exc, ThermalFEAError):
                _log.error("%s", exc)
                window.show_error("ThermalFEA error", str(exc))
            else:
                text = "".join(traceback.format_exception(exc_type, exc, tb))
                _log.error("Unexpected error:\n%s", text)
                window.show_error(
                    "Unexpected error", f"{exc_type.__name__}: {exc}\n\nSee the message log."
                )
        except Exception:  # the hook must never raise
            try:
                sys.__stderr__.write("exception hook failed\n")  # type: ignore[union-attr]
            except Exception:
                pass

    sys.excepthook = hook

    def restore() -> None:
        sys.excepthook = previous

    return restore


def main(argv: list[str] | None = None) -> int:
    """Run the GUI.

    Parameters
    ----------
    argv : list of str, optional
        Command-line arguments.

    Returns
    -------
    int
        Process exit code.
    """
    app = create_app(argv)
    window = MainWindow()
    document = Document()
    window.set_document(document)
    view = attach_viewport(window, document)
    attach_tree(window, document, view)
    attach_geometry_tools(window, document, view)
    install_exception_hook(window)
    window.show()
    return int(app.exec())
