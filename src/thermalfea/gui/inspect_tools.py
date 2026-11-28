"""Hover and inspect in the viewport (M11.61).

:class:`InspectController` listens to the viewport's ``entity_hovered`` and ``entity_clicked``
signals. Hovering shows the :func:`~thermalfea.gui.inspect.entity_report` as a tooltip; a plain
click shows it in the status bar and marks the tree items it involves (``tree.mark_addresses``).
Clicks are ignored while something else is using the viewport for picking (:meth:`busy`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QToolTip, QWidget

from thermalfea.gui.document import Document
from thermalfea.gui.inspect import EntityReport, entity_report

STATUS_MS = 30000


def _lines_to_status(lines: list[str]) -> str:
    if not lines:
        return ""
    return lines[0] if len(lines) == 1 else f"{lines[0]} — " + "; ".join(lines[1:])


class InspectController(QObject):
    """Tooltip on hover, report and tree marks on click.

    Parameters
    ----------
    window : QMainWindow
        Gives the status bar.
    document : Document
        The model the reports are made from.
    view : object
        The viewport; ``entity_hovered`` / ``entity_clicked`` are connected if it has them.
    tree : object, optional
        The model tree; ``mark_addresses(list)`` is called if it has one.
    extra_busy : list of callable, optional
        More predicates (``-> bool``) that tell that a tool is picking in the viewport.

    Attributes
    ----------
    tooltip_text : str
        The text of the last tooltip shown (empty after the pointer left).
    report : EntityReport or None
        The report of the last accepted click.
    """

    def __init__(
        self,
        window: Any,
        document: Document,
        view: Any,
        tree: Any = None,
        extra_busy: list[Callable[[], bool]] | None = None,
    ) -> None:
        super().__init__(window)
        self.window = window
        self.document = document
        self.view = view
        self.tree = tree
        self.extra_busy: list[Callable[[], bool]] = list(extra_busy or [])
        self.tooltip_text = ""
        self.report: EntityReport | None = None
        hovered = getattr(view, "entity_hovered", None)
        if hovered is not None:
            hovered.connect(self.on_hovered)
        clicked = getattr(view, "entity_clicked", None)
        if clicked is not None:
            clicked.connect(self.on_clicked)
        document.geometry_built.connect(self._on_geometry_built)

    # --------------------------------------------------------------------- busy
    def busy(self) -> bool:
        """``True`` while a selection editor, the selection panel, a stream path pick, a
        placing geometry dialog, the results probe or a chart path pick uses the viewport.
        """
        # imported here: these modules import the viewport stack
        from thermalfea.gui.dialogs.geometry import GeometryOpDialog
        from thermalfea.gui.pick import manager_for
        from thermalfea.gui.property_panels.selection_editor import SelectionEditor

        if self.view is not None and manager_for(self.view).active is not None:
            return True  # a pick of the one pick workflow (C2) runs

        # only this window's widgets: panels of another window (or left over from a closed
        # one) must not block inspecting here; geometry dialogs are parented to the window
        if isinstance(self.window, QWidget):
            widgets = self.window.findChildren(QWidget)
        else:
            app = QApplication.instance()
            widgets = app.allWidgets() if app is not None else []
        for w in widgets:
            try:
                if isinstance(w, SelectionEditor) and w.pick_button.isChecked():
                    return True
                if isinstance(w, GeometryOpDialog) and getattr(w, "_connected", False):
                    return True
            except RuntimeError:  # the C++ widget is already deleted
                continue
        return any(check() for check in self.extra_busy)

    # -------------------------------------------------------------------- hover
    def on_hovered(self, dim: int, tag: int) -> None:
        """Show (``dim >= 0``) or hide the tooltip of the entity under the pointer."""
        if dim < 0:
            self.tooltip_text = ""
            QToolTip.hideText()
            return
        text = "\n".join(entity_report(self.document, int(dim), int(tag)).lines())
        self.tooltip_text = text
        widget = self._viewport_widget()
        if widget is not None and QApplication.platformName() != "offscreen":
            QToolTip.showText(QCursor.pos(), text, widget)

    def _viewport_widget(self) -> QWidget | None:
        getter = getattr(self.view, "widget", None)
        return getter() if callable(getter) else None

    # -------------------------------------------------------------------- click
    def on_clicked(self, dim: int, tag: int) -> None:
        """Report the clicked entity (status bar and tree marks) unless a tool is picking."""
        if dim < 0:
            self._clear()
            return
        if self.busy():
            if self.report is not None:
                self._clear()
            return
        report = entity_report(self.document, int(dim), int(tag))
        self.report = report
        bar = self.window.statusBar()
        bar.showMessage(_lines_to_status(report.lines()), STATUS_MS)
        self._mark(report.addresses())

    def clear(self) -> None:
        """Drop the report and the tree marks (empty space clicked, picking started)."""
        self._clear()

    def _clear(self) -> None:
        self.report = None
        self._mark([])

    def _mark(self, addresses: list[tuple]) -> None:
        mark = getattr(self.tree, "mark_addresses", None)
        if callable(mark):
            mark(addresses)

    def _on_geometry_built(self, *_args: object) -> None:
        if self.report is not None:
            self._clear()


def attach_inspect(
    window: Any,
    document: Document,
    view: Any,
    tree: Any = None,
    extra_busy: list[Callable[[], bool]] | None = None,
) -> InspectController:
    """Create the :class:`InspectController` of the application window."""
    return InspectController(window, document, view, tree, extra_busy)
