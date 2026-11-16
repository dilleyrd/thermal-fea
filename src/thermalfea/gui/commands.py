"""Undo commands for the GUI (Plan M8.2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

if TYPE_CHECKING:
    from thermalfea.gui.document import Document


class ModelEditCommand(QUndoCommand):
    """One undoable edit of the whole model, stored as two JSON snapshots.

    The snapshots are JSON *strings* (immutable), taken with
    :func:`thermalfea.model.serialize.to_json`. ``redo`` makes the document's model the
    "after" snapshot and ``undo`` the "before" one; the document works out what each
    direction invalidates (see :mod:`thermalfea.gui.document`).

    Parameters
    ----------
    document : Document
        The document the command acts on.
    text : str
        Command name shown in the Edit menu ("Undo <text>").
    before, after : str
        Model JSON text before and after the edit.
    """

    def __init__(self, document: Document, text: str, before: str, after: str) -> None:
        super().__init__(text)
        self._document = document
        self._before = before
        self._after = after

    @property
    def before(self) -> str:
        """Model JSON text before the edit."""
        return self._before

    @property
    def after(self) -> str:
        """Model JSON text after the edit."""
        return self._after

    def redo(self) -> None:
        """Apply the "after" snapshot (also called once by ``QUndoStack.push``)."""
        self._document.apply_snapshot(self._after, self._before)

    def undo(self) -> None:
        """Apply the "before" snapshot."""
        self._document.apply_snapshot(self._before, self._after)
