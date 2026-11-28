"""Framed boxes, "More" lines and advanced boxes of the property panels (C5, C12; M11.68).

A panel that is long enough to need grouping shows its fields in framed boxes, each with a
title and a one-line description (convention C5). Advanced fields (C12) are collapsed:

* the advanced fields of a box sit under a collapsed **More** line at its bottom;
* a box that is wholly advanced is collapsed itself; its title says "(advanced)".

A collapsed part stays collapsed and its title counts the values that differ from their
defaults ("More · 1 changed", "Convergence (advanced) · 2 changed"; owner's decision C), so
a changed setting is never hidden without a trace. Whether a part is open is remembered for
the session per panel and part, so it does not close again each time the panel is shown.

A panel describes its boxes with :class:`Box` (see ``FormPanel.boxes``); a field in no box
stays in the plain form above the boxes.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QPalette
from PySide6.QtWidgets import (
    QFormLayout,
    QFrame,
    QLabel,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

#: Marker returned by :func:`default_value` for a field without a default.
NO_DEFAULT = object()

#: Open state of collapsible parts for this session: ``(panel key, part key) -> open``.
_OPEN: dict[tuple[str, str], bool] = {}


@dataclass(frozen=True)
class Box:
    """One framed box of a panel.

    Parameters
    ----------
    title : str
        Title of the box ("Time stepping").
    description : str
        One line saying what the box is for.
    fields : tuple of str
        Field names shown in the box, in order.
    more : tuple of str
        Advanced field names under the box's collapsed "More" line.
    advanced : bool
        The whole box is advanced: collapsed, titled "<title> (advanced)".
    """

    title: str
    description: str = ""
    fields: tuple[str, ...] = ()
    more: tuple[str, ...] = ()
    advanced: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        """Every field of the box, the "More" fields included."""
        return (*self.fields, *self.more)


def default_value(obj: Any, name: str) -> Any:
    """The dataclass default of field ``name`` of ``obj``, or :data:`NO_DEFAULT`."""
    if not dataclasses.is_dataclass(obj):
        return NO_DEFAULT
    for f in dataclasses.fields(obj):
        if f.name != name:
            continue
        if f.default is not dataclasses.MISSING:
            return f.default
        if f.default_factory is not dataclasses.MISSING:
            return f.default_factory()
    return NO_DEFAULT


def changed_count(obj: Any, names: tuple[str, ...] | list[str]) -> int:
    """Number of fields of ``names`` whose value in ``obj`` differs from the default."""
    count = 0
    for name in names:
        default = default_value(obj, name)
        if default is not NO_DEFAULT and getattr(obj, name, default) != default:
            count += 1
    return count


def _changed_suffix(n: int) -> str:
    return f" · {n} changed" if n else ""


def _toggle_button(text: str, bold: bool) -> QToolButton:
    """A flat line with an arrow; its arrow, not a pressed look, shows whether it is open."""
    button = QToolButton()
    button.setText(text)
    button.setAutoRaise(True)
    button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    button.setArrowType(Qt.ArrowType.RightArrow)
    if bold:
        font = QFont(button.font())
        font.setBold(True)
        button.setFont(font)
    return button


def _new_form() -> QFormLayout:
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    return form


class MoreSection(QWidget):
    """A collapsed "More" line holding the advanced fields of a box.

    Attributes
    ----------
    button : QToolButton
        The line itself ("More", "More · 1 changed"); a click opens or collapses it.
    body : QWidget
        Holds :attr:`form`; hidden while collapsed.
    form : QFormLayout
    """

    toggled = Signal(bool)

    def __init__(self, key: tuple[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._changed = 0
        self._open = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.button = _toggle_button("More", bold=False)
        self.button.clicked.connect(lambda _checked=False: self.set_open(not self._open))
        layout.addWidget(self.button)
        self.body = QWidget()
        self.form = _new_form()
        self.body.setLayout(self.form)
        layout.addWidget(self.body)
        self.set_open(_OPEN.get(key, False))

    def is_open(self) -> bool:
        """True when the advanced fields are shown."""
        return self._open

    def set_open(self, on: bool) -> None:
        """Open or collapse the line (remembered for the session)."""
        self._open = on
        _OPEN[self._key] = on
        self.body.setVisible(on)
        self.button.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)
        self.toggled.emit(on)

    def set_changed(self, n: int) -> None:
        """Show how many values under the line differ from their defaults."""
        self._changed = n
        self.button.setText("More" + _changed_suffix(n))


class SectionBox(QFrame):
    """A framed box with a title, a one-line description and a form of fields.

    Parameters
    ----------
    box : Box
        Title, description and whether the box is advanced (collapsed).
    panel_key : str
        Names the panel for the session memory of open parts (the form title).
    parent : QWidget, optional

    Attributes
    ----------
    form : QFormLayout
        The box's own fields.
    more : MoreSection or None
        The "More" line, when the box has advanced fields.
    title_label : QLabel or None
        The title of a box that cannot collapse.
    toggle : QToolButton or None
        The title of an advanced box; a click opens or collapses it.
    """

    def __init__(self, box: Box, panel_key: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.box = box
        self._summary = ""
        self._changed = 0
        self._open = True
        self.setObjectName("section")
        self.setStyleSheet(
            "QFrame#section { border: 1px solid palette(mid); border-radius: 4px; }"
        )
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        self.title_label: QLabel | None = None
        self.toggle: QToolButton | None = None
        if box.advanced:
            self.toggle = _toggle_button("", bold=True)
            self.toggle.clicked.connect(lambda _checked=False: self.set_open(not self._open))
            layout.addWidget(self.toggle)
        else:
            self.title_label = QLabel(box.title)
            font = QFont(self.title_label.font())
            font.setBold(True)
            self.title_label.setFont(font)
            layout.addWidget(self.title_label)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 0, 0)
        self.description_label = QLabel(box.description)
        self.description_label.setWordWrap(True)
        muted = self.description_label.palette()
        muted.setColor(
            QPalette.ColorRole.WindowText, muted.color(QPalette.ColorRole.PlaceholderText)
        )
        self.description_label.setPalette(muted)
        self.description_label.setVisible(bool(box.description))
        body.addWidget(self.description_label)
        self.form = _new_form()
        body.addLayout(self.form)
        self.more: MoreSection | None = None
        if box.more:
            self.more = MoreSection((panel_key, f"{box.title} › More"))
            body.addWidget(self.more)
        layout.addWidget(self.body)
        self._key = (panel_key, box.title)
        self._refresh_title()
        if self.toggle is not None:
            self.set_open(_OPEN.get(self._key, False))

    # ------------------------------------------------------------------ state
    def is_open(self) -> bool:
        """True unless the box is an advanced box that is collapsed."""
        return self._open

    def set_open(self, on: bool) -> None:
        """Open or collapse an advanced box (remembered for the session)."""
        if self.toggle is None:
            return
        self._open = on
        _OPEN[self._key] = on
        self.body.setVisible(on)
        self.toggle.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)

    def align_labels(self) -> None:
        """Give the labels of the box's form and its "More" form one width, so their fields
        line up in one column."""
        forms = [self.form] + ([self.more.form] if self.more is not None else [])
        labels = [
            item.widget()
            for form in forms
            for row in range(form.rowCount())
            if (item := form.itemAt(row, QFormLayout.ItemRole.LabelRole)) is not None
            and item.widget() is not None
        ]
        width = max((label.sizeHint().width() for label in labels), default=0)
        for label in labels:
            label.setMinimumWidth(width)

    def set_summary(self, text: str) -> None:
        """A short text shown after the title (e.g. the time-integration method)."""
        self._summary = text
        self._refresh_title()

    def set_changed(self, n: int) -> None:
        """Count of the box's own fields that differ from their defaults (advanced boxes)."""
        self._changed = n
        self._refresh_title()

    def title_text(self) -> str:
        """The title as shown."""
        if self.toggle is not None:
            return self.toggle.text()
        assert self.title_label is not None
        return self.title_label.text()

    def _refresh_title(self) -> None:
        if self.toggle is None:
            return
        text = f"{self.box.title} (advanced)"
        if self._summary:
            text += f" · {self._summary}"
        self.toggle.setText(text + _changed_suffix(self._changed))



def forget_open_state() -> None:
    """Forget which parts were opened this session (for tests)."""
    _OPEN.clear()
