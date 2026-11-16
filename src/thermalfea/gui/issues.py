"""The validation issue list (Plan M8.9).

:class:`IssuePanel` is a table of the findings of :func:`thermalfea.model.validate.validate`:
severity, object and message per row, errors in bold red and warnings in amber. Double-clicking
a row (or calling :meth:`IssuePanel.activate`) selects the offending object in the model
tree, which opens its property panel.

Issue kind to tree address
--------------------------
:func:`address_for_issue` maps ``Issue.kind`` / ``Issue.name`` to an object address
(:mod:`thermalfea.gui.addressing`):

=============== ==========================================================================
``bc``,         ``("bcs", i)`` of the boundary condition with that name
``boundary condition``
``stream``      ``("streams", i)``
``enclosure``   ``("enclosures", i)``
``contact``     ``("contacts", i)``
``material``    ``("materials", name)``
``region``      ``("regions", i)`` of the assignment whose selection is ``name``; with no
                name (a surface without region) the *Regions* section node
``mesh``        ``("mesh_settings",)``
``solution``    ``("solution",)``
``model``       ``("initial_condition",)`` when the name starts with "initial condition";
                otherwise nothing
=============== ==========================================================================

Kinds the tree has no node for (``selection``, anything unknown) map to
``None``: activating such a row does nothing.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)

from thermalfea.gui.addressing import Address
from thermalfea.gui.tree import ModelTree
from thermalfea.model.model import Model
from thermalfea.model.validate import Issue

COLUMNS: tuple[str, ...] = ("Severity", "Object", "Message")
_ERROR_BRUSH = QBrush(QColor("#b00020"))
_WARNING_BRUSH = QBrush(QColor("#a65e00"))
#: ``Issue.kind`` -> model list searched by name (``attribute of the object``).
_LISTS: dict[str, str] = {
    "bc": "bcs",
    "boundary condition": "bcs",  # the kind validate uses for selection checks
    "stream": "streams",
    "enclosure": "enclosures",
    "contact": "contacts",
}
REGIONS_SECTION = ("section", "regions")


def address_for_issue(model: Model, issue: Issue) -> Address | None:
    """Return the tree address of the object an issue concerns, or ``None``.

    Parameters
    ----------
    model : Model
    issue : Issue

    Returns
    -------
    tuple or None
        An object address, :data:`REGIONS_SECTION` for a surface without region, or
        ``None`` when the object has no tree node.
    """
    kind, name = issue.kind, issue.name
    if kind in _LISTS:
        for i, obj in enumerate(getattr(model, _LISTS[kind])):
            if obj.name == name:
                return (_LISTS[kind], i)
        return None
    if kind == "material":
        return ("materials", name) if name in model.materials else None
    if kind == "region":
        if not name:
            return REGIONS_SECTION
        for i, region in enumerate(model.regions):
            if region.selection == name:
                return ("regions", i)
        return None
    if kind == "mesh":
        return ("mesh_settings",)
    if kind == "solution":
        return ("solution",)
    if kind == "model" and name.startswith("initial condition"):
        return ("initial_condition",)
    return None


def object_text(issue: Issue) -> str:
    """Text of the "Object" column of an issue."""
    return f"{issue.kind} {issue.name}".strip() if issue.name else issue.kind


class IssuePanel(QTableWidget):
    """Table of validation issues.

    Parameters
    ----------
    tree : ModelTree
        Where an activated issue is selected.
    parent : QWidget, optional

    Signals
    -------
    activated_address(object)
        The address that :meth:`activate` selected.

    Attributes
    ----------
    issues : list of Issue
        The issues shown, in row order.
    model_getter : callable
        ``model_getter() -> Model``; the model the addresses are looked up in (set by the
        controller to the document's current model).
    """

    activated_address = Signal(object)

    def __init__(self, tree: ModelTree, parent: QWidget | None = None) -> None:
        super().__init__(0, len(COLUMNS), parent)
        self.tree = tree
        self.issues: list[Issue] = []
        self.model_getter = lambda: tree.document.model
        self.setHorizontalHeaderLabels(list(COLUMNS))
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        header = self.horizontalHeader()
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.verticalHeader().setVisible(False)
        self.cellDoubleClicked.connect(lambda row, _col: self.activate(row))

    def set_issues(self, issues: list[Issue]) -> None:
        """Replace the list (errors first, otherwise in the order given)."""
        ordered = sorted(issues, key=lambda i: i.severity != "error")
        self.issues = ordered
        self.setRowCount(len(ordered))
        bold = QFont(self.font())
        bold.setBold(True)
        for row, issue in enumerate(ordered):
            brush = _ERROR_BRUSH if issue.severity == "error" else _WARNING_BRUSH
            for col, text in enumerate(
                (issue.severity.capitalize(), object_text(issue), issue.message)
            ):
                item = QTableWidgetItem(text)
                item.setForeground(brush)
                if issue.severity == "error":
                    item.setFont(bold)
                item.setToolTip(issue.message)
                self.setItem(row, col, item)

    def clear_issues(self) -> None:
        """Empty the list."""
        self.set_issues([])

    def activate(self, row: int) -> bool:
        """Select the object of the issue in ``row`` in the model tree.

        Returns
        -------
        bool
            ``True`` if an object was selected.
        """
        if not 0 <= row < len(self.issues):
            return False
        address = address_for_issue(self.model_getter(), self.issues[row])
        if address is None:
            return False
        if address[0] == "section":
            item = self.tree.section_item(address[1])
            self.tree.setCurrentItem(item)
            selected = True
        else:
            selected = self.tree.select_address(address)
        if selected:
            self.activated_address.emit(address)
        return selected
