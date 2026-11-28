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
    merge_key : str, optional
        Commands with the same key that follow each other merge into one: the merged
        command keeps the first "before" and the last "after" (M11.75).
    """

    def __init__(
        self,
        document: Document,
        text: str,
        before: str,
        after: str,
        merge_key: str | None = None,
    ) -> None:
        super().__init__(text)
        self._document = document
        self._before = before
        self._after = after
        self.merge_key = merge_key

    def id(self) -> int:  # noqa: A003 (Qt API)
        """One id for every mergeable command (``-1``: never merged); keys are compared in
        :meth:`mergeWith`."""
        return 1 if self.merge_key else -1

    def mergeWith(self, other: QUndoCommand) -> bool:  # noqa: N802 (Qt API)
        """Absorb ``other`` when it carries the same merge key."""
        if not isinstance(other, ModelEditCommand) or other.merge_key != self.merge_key:
            return False
        if other.before != self._after:  # pragma: no cover - the stack keeps them in order
            return False
        self._after = other.after
        return True

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
