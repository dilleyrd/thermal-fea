"""Message log widget and the thread-safe ``logging`` handler that feeds it."""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtGui import QColor, QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit, QWidget

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"

_COLOURS: dict[int, str] = {
    logging.WARNING: "#a65e00",
    logging.ERROR: "#c00000",
    logging.CRITICAL: "#c00000",
}


def _colour_for(levelno: int) -> str | None:
    """Return the text colour for a logging level, or ``None`` for the default."""
    for level in sorted(_COLOURS, reverse=True):
        if levelno >= level:
            return _COLOURS[level]
    return None


class MessagePanel(QPlainTextEdit):
    """Read-only message log; warnings and errors are coloured.

    Parameters
    ----------
    parent : QWidget, optional
        Parent widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setObjectName("MessagePanel")

    @Slot(str, int)
    def append_message(self, text: str, levelno: int = logging.INFO) -> None:
        """Append one line, coloured according to ``levelno``.

        Parameters
        ----------
        text : str
            The formatted message.
        levelno : int
            ``logging`` level number of the record.
        """
        fmt = QTextCharFormat()
        colour = _colour_for(levelno)
        if colour is not None:
            fmt.setForeground(QColor(colour))
        cursor = self.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        if not self.document().isEmpty():
            cursor.insertBlock()
        cursor.insertText(text, fmt)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()


class _Emitter(QObject):
    """Carrier of the signal a :class:`QtLogHandler` emits from any thread."""

    message = Signal(str, int)


class QtLogHandler(logging.Handler):
    """``logging`` handler forwarding records to a :class:`MessagePanel`.

    ``emit`` may run in any thread. It only emits a Qt signal, which is connected to the
    panel's slot with a queued connection, so the widget is always touched in the thread
    it lives in.

    Parameters
    ----------
    panel : MessagePanel
        Destination widget.
    level : int
        Minimum level handled.
    """

    def __init__(self, panel: MessagePanel, level: int = logging.INFO) -> None:
        super().__init__(level)
        self.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
        self._emitter = _Emitter(panel)
        self._emitter.message.connect(
            panel.append_message, Qt.ConnectionType.QueuedConnection
        )

    def emit(self, record: logging.LogRecord) -> None:
        """Format ``record`` and queue it for the panel."""
        try:
            self._emitter.message.emit(self.format(record), record.levelno)
        except RuntimeError:  # panel already destroyed
            pass
        except Exception:
            self.handleError(record)
