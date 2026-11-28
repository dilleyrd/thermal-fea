"""The one icon set of the window (convention C6, task M11.68).

An action on one field or one table row is an icon button: :func:`icon_button` gives a flat
tool button with the icon, a tooltip and an accessible name that say what it does. A
command on a whole object or panel keeps words (Generate mesh, Validate, Solve).

The icons are drawn here with ``QPainter`` in the palette's text color, so they need no
image files and follow the window's palette, like the tree's role and swatch icons.

======== =============================================
name     drawing and use
======== =============================================
add      plus: add a row, a selection, an item
remove   cross: remove this row or entry
edit     pencil: change the entities of a selection
update   check mark: apply a pending change (C1)
revert   curved arrow back: drop a pending change (C1)
pick     crosshair: pick in the view (C2)
browse   folder: choose a file
======== =============================================
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QToolButton, QWidget

#: The names of the icon set, in the order of the table above.
ICON_NAMES: tuple[str, ...] = ("add", "remove", "edit", "update", "revert", "pick", "browse")

_SIZE = 16  # logical pixels
_SCALE = 2  # drawn at twice the size, so the icons stay sharp on high-DPI screens


def _ink() -> QColor:
    app = QApplication.instance()
    if isinstance(app, QApplication):
        return app.palette().color(QPalette.ColorRole.ButtonText)
    return QColor("#202020")


def _draw(name: str, p: QPainter) -> None:
    s = float(_SIZE)
    if name == "add":
        p.drawLine(QPointF(s / 2, 3), QPointF(s / 2, s - 3))
        p.drawLine(QPointF(3, s / 2), QPointF(s - 3, s / 2))
    elif name == "remove":
        p.drawLine(QPointF(4, 4), QPointF(s - 4, s - 4))
        p.drawLine(QPointF(s - 4, 4), QPointF(4, s - 4))
    elif name == "edit":
        p.drawLine(QPointF(4, s - 4), QPointF(s - 5, 5))
        p.drawLine(QPointF(s - 5, 5), QPointF(s - 3, 7))
        p.drawLine(QPointF(s - 3, 7), QPointF(6, s - 2))
        p.drawLine(QPointF(4, s - 4), QPointF(3, s - 1))
        p.drawLine(QPointF(3, s - 1), QPointF(6, s - 2))
    elif name == "update":
        path = QPainterPath(QPointF(3, s / 2 + 1))
        path.lineTo(QPointF(6.5, s - 4))
        path.lineTo(QPointF(s - 3, 4))
        p.drawPath(path)
    elif name == "revert":
        rect = QRectF(4, 4, s - 7, s - 7)
        p.drawArc(rect, 90 * 16, -250 * 16)  # from the top, clockwise round to the left
        tip = QPointF(rect.center().x(), rect.top())
        p.drawLine(tip, tip + QPointF(3, -2.5))
        p.drawLine(tip, tip + QPointF(3, 2.5))
    elif name == "pick":
        c = QPointF(s / 2, s / 2)
        p.drawEllipse(c, 4.5, 4.5)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            p.drawLine(c + QPointF(dx * 2.5, dy * 2.5), c + QPointF(dx * 7, dy * 7))
    elif name == "browse":
        path = QPainterPath(QPointF(2, 4))
        path.lineTo(QPointF(6, 4))
        path.lineTo(QPointF(7.5, 5.5))
        path.lineTo(QPointF(s - 2, 5.5))
        path.lineTo(QPointF(s - 2, s - 3))
        path.lineTo(QPointF(2, s - 3))
        path.closeSubpath()
        p.drawPath(path)
        p.drawLine(QPointF(2, 7.5), QPointF(s - 2, 7.5))
    else:  # pragma: no cover - guarded by icon()
        raise KeyError(name)


def icon(name: str) -> QIcon:
    """The icon ``name`` of :data:`ICON_NAMES`.

    Raises
    ------
    KeyError
        For a name that is not in the set.
    """
    if name not in ICON_NAMES:
        raise KeyError(f"no icon {name!r}; the set is {', '.join(ICON_NAMES)}")
    pixmap = QPixmap(_SIZE * _SCALE, _SIZE * _SCALE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(_SCALE, _SCALE)
    pen = QPen(_ink(), 1.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    _draw(name, painter)
    painter.end()
    pixmap.setDevicePixelRatio(_SCALE)
    return QIcon(pixmap)


def icon_button(name: str, tooltip: str, parent: QWidget | None = None) -> QToolButton:
    """A flat tool button showing icon ``name``; ``tooltip`` is also its accessible name.

    Parameters
    ----------
    name : str
        One of :data:`ICON_NAMES`.
    tooltip : str
        What the button does, e.g. "Remove this row". Required: an icon alone does not say.
    parent : QWidget, optional
    """
    if not tooltip.strip():
        raise ValueError("an icon button needs a tooltip that says what it does")
    button = QToolButton(parent)
    button.setIcon(icon(name))
    button.setToolTip(tooltip)
    button.setAccessibleName(tooltip)
    button.setAutoRaise(True)
    button.setObjectName(f"icon_{name}")
    return button


__all__ = ["ICON_NAMES", "icon", "icon_button"]
