"""One pick workflow for every pick in the view (convention C2, task M11.69).

Every pick works the same way: the Selections panel's Add and Remove, a stream's path, the
probe and the geometry tool dialogs (later also the selection fields, the nodal history and
the path plot):

* a strip (:class:`PickStrip`) shows an instruction and a running count while picking,
  and only then; it has the confirm button and Cancel;
* what has been picked is marked in the view (the owner draws it: highlight or overlay);
* the toolbar switches to the kind of entity the pick needs and back afterwards;
* **Enter confirms and Esc cancels**, besides the strip's buttons; Cancel changes nothing.

:class:`PickManager` keeps one pick at a time per view (:func:`manager_for`): starting a
pick cancels the running one. While a pick runs it filters the application's key presses:
Esc cancels (unless a popup such as an open dropdown takes it), Enter confirms when the
focus is in the view, in the pick's strip, or nowhere; elsewhere Enter keeps its own
meaning (a number box applies its value).
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QEvent, QObject, Qt, Signal
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

_ENTER_KEYS = (Qt.Key.Key_Return, Qt.Key.Key_Enter)


class PickStrip(QFrame):
    """The strip shown while picking: instruction, count, confirm and Cancel.

    Parameters
    ----------
    confirm_text : str
        Text of the confirm button ("Add", "Use path"); ``""`` for a pick without one (the
        probe), whose Cancel button then reads "Stop".
    parent : QWidget, optional

    Signals
    -------
    confirmed, cancelled
        The buttons were pressed.
    """

    confirmed = Signal()
    cancelled = Signal()

    def __init__(self, confirm_text: str = "Done", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pickstrip")
        self.setStyleSheet(
            "QFrame#pickstrip { border: 1px solid #e0b000; border-radius: 4px;"
            " background: #fff8d6; }"
        )
        column = QVBoxLayout(self)
        column.setContentsMargins(8, 6, 8, 6)
        self.instruction_label = QLabel("")
        self.instruction_label.setWordWrap(True)
        column.addWidget(self.instruction_label)
        self.count_label = QLabel("")
        column.addWidget(self.count_label)
        self._column = column
        row = QHBoxLayout()
        self._buttons = row
        row.addStretch(1)
        self.confirm_button = QPushButton(confirm_text or "Done")
        self.confirm_button.setVisible(bool(confirm_text))
        self.confirm_button.setToolTip("Confirm the pick (Enter)")
        self.cancel_button = QPushButton("Cancel" if confirm_text else "Stop")
        self.cancel_button.setToolTip("Stop picking without changing anything (Esc)")
        row.addWidget(self.confirm_button)
        row.addWidget(self.cancel_button)
        column.addLayout(row)
        self.confirm_button.clicked.connect(lambda _c=False: self.confirmed.emit())
        self.cancel_button.clicked.connect(lambda _c=False: self.cancelled.emit())
        self.setVisible(False)

    def insert_widget(self, widget: QWidget) -> None:
        """Add ``widget`` (e.g. a name box) between the count and the buttons."""
        self._column.insertWidget(self._column.count() - 1, widget)

    def add_button(self, text: str) -> QPushButton:
        """Add a second action button before the confirm button (e.g. "Save as new")."""
        button = QPushButton(text)
        self._buttons.insertWidget(1, button)
        return button

    def show_pick(self, instruction: str, count: str = "") -> None:
        """Show the strip with an instruction and the first count."""
        self.instruction_label.setText(instruction)
        self.set_count(count)
        self.setVisible(True)

    def set_count(self, text: str) -> None:
        """The running count ("2 boundaries picked")."""
        self.count_label.setText(text)
        self.count_label.setVisible(bool(text))

    def set_confirm_enabled(self, on: bool) -> None:
        """Enable the confirm button (e.g. only once enough has been picked)."""
        self.confirm_button.setEnabled(on)

    def hide_pick(self) -> None:
        """Hide the strip (the pick ended)."""
        self.setVisible(False)


@dataclass
class PickSession:
    """One running pick (see :meth:`PickManager.start`)."""

    owner: object
    mode: str
    confirm: Callable[[], Any] | None
    cancel: Callable[[], Any]
    strip: QWidget | None = None
    saved_mode: str = "none"
    done: bool = field(default=False)


class PickManager(QObject):
    """One pick at a time in a view: toolbar mode, Enter and Esc.

    Parameters
    ----------
    view : object
        The viewport (``set_selection_mode``); a QWidget whose window has the selection
        toolbar (``actions["select.<mode>"]``, ``selection_mode``) for the toolbar to follow.

    Attributes
    ----------
    active : PickSession or None
    on_start : list of callable
        Called before a pick starts, to stop picks that do not run through the manager.
    """

    def __init__(self, view: Any) -> None:
        super().__init__()
        self.view = view
        self.active: PickSession | None = None
        self.on_start: list[Callable[[], Any]] = []
        #: The window with the selection toolbar; set by the controllers that know it (else
        #: found as the view's own window).
        self.window: Any = None
        self._filtering = False

    # ----------------------------------------------------------------- toolbar
    def _window(self) -> Any:
        window = self.window
        if window is None and isinstance(self.view, QWidget):
            window = self.view.window()
        return window if hasattr(window, "actions") else None

    def current_mode(self) -> str:
        """The toolbar's selection mode ("none" without a toolbar)."""
        window = self._window()
        return str(getattr(window, "selection_mode", "none")) if window is not None else "none"

    def set_mode(self, mode: str) -> None:
        """Set the view's selection mode and check the toolbar action that mirrors it."""
        setter = getattr(self.view, "set_selection_mode", None)
        if setter is not None:  # a stand-in view without pick modes has none
            setter(mode)
        window = self._window()
        action = window.actions.get(f"select.{mode}") if window is not None else None
        if action is not None and not action.isChecked():
            action.setChecked(True)

    # ----------------------------------------------------------------- sessions
    def start(
        self,
        owner: object,
        mode: str,
        *,
        cancel: Callable[[], Any],
        confirm: Callable[[], Any] | None = None,
        strip: QWidget | None = None,
    ) -> PickSession:
        """Start a pick; a running one is cancelled first.

        Parameters
        ----------
        owner : object
            Who picks (for :meth:`is_active`).
        mode : str
            Selection mode the pick needs ("curve", "surface", "point", "node", "none").
        cancel : callable
            Ends the pick without changing anything (Esc, Cancel, another pick starts).
        confirm : callable, optional
            Ends the pick and applies it (Enter, the confirm button); ``None`` when the
            pick has nothing to confirm (the probe).
        strip : QWidget, optional
            The pick's strip; Enter in it confirms.
        """
        self.cancel_active()
        for stop in list(self.on_start):
            stop()
        session = PickSession(owner, mode, confirm, cancel, strip, self.current_mode())
        self.active = session
        self.set_mode(mode)
        self._filter(True)
        return session

    def finish(self, owner: object) -> None:
        """End the pick of ``owner`` (after it confirmed or cancelled) and restore the mode."""
        session = self.active
        if session is None or session.owner is not owner:
            return
        session.done = True
        self.active = None
        self._filter(False)
        self.set_mode(session.saved_mode)

    def is_active(self, owner: object) -> bool:
        """True while ``owner``'s pick runs."""
        return self.active is not None and self.active.owner is owner

    def cancel_active(self) -> None:
        """Cancel the running pick, if any (its ``cancel`` is expected to call finish)."""
        session = self.active
        if session is None:
            return
        session.cancel()
        if self.active is session:  # an owner that did not finish itself
            self.finish(session.owner)

    def confirm_active(self) -> None:
        """Confirm the running pick, if it can be confirmed."""
        session = self.active
        if session is None or session.confirm is None:
            return
        session.confirm()

    # ------------------------------------------------------------------- keys
    def _filter(self, on: bool) -> None:
        app = QApplication.instance()
        if app is None or on == self._filtering:
            return
        if on:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)
        self._filtering = on

    def _enter_confirms(self) -> bool:
        focus = QApplication.focusWidget()
        if focus is None:
            return True
        for owner in (self.view, self.active.strip if self.active else None):
            if isinstance(owner, QWidget) and (focus is owner or owner.isAncestorOf(focus)):
                return True
        return False

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 (Qt API)
        if self.active is None or event.type() != QEvent.Type.KeyPress:
            return False
        assert isinstance(event, QKeyEvent)
        if event.key() == Qt.Key.Key_Escape and QApplication.activePopupWidget() is None:
            self.cancel_active()
            return True
        if (
            event.key() in _ENTER_KEYS
            and self.active.confirm is not None
            and self._enter_confirms()
        ):
            self.confirm_active()
            return True
        return False


#: Every manager made, so a test harness can end what a test left running.
_MANAGERS: weakref.WeakSet[PickManager] = weakref.WeakSet()


def manager_for(view: Any) -> PickManager:
    """The one :class:`PickManager` of ``view`` (made on first use)."""
    manager = getattr(view, "_pick_manager", None)
    if manager is None:
        manager = PickManager(view)
        view._pick_manager = manager
        _MANAGERS.add(manager)
    return manager


def end_all_picks() -> None:
    """Cancel every running pick and remove the key filters (for test teardown).

    A pick left running keeps its application-wide Esc/Enter filter; ending them all keeps
    one test's pick from reaching into the next.
    """
    for manager in list(_MANAGERS):
        try:
            manager.cancel_active()
        except RuntimeError:  # the owner's widgets are already deleted
            manager.active = None
        manager._filter(False)
        manager.on_start.clear()


def count_text(n: int, word: str, plural: str | None = None) -> str:
    """``"1 boundary picked"`` / ``"3 boundaries picked"``."""
    noun = word if n == 1 else (plural or word + "s")
    return f"{n} {noun} picked"
