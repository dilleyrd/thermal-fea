"""Property panel of the initial condition (Plan M8.9; layout of M11.72).

:class:`InitialConditionPanel` is a :class:`~thermalfea.gui.property_panels.form.FormPanel`
for :class:`~thermalfea.model.model.InitialCondition` that shows only the rows of the chosen
kind (held item 8): the temperature for "uniform" and "expression", the temperature per part
for "per_region", the results file for "from_results". The "Kind" row is always shown.

A browse icon beside the results file box opens a file chooser (convention C6). The chooser is
an injectable attribute, :attr:`InitialConditionPanel.choose_open`, so tests need no dialog.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QVBoxLayout, QWidget

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FieldSpec
from thermalfea.gui.icons import icon_button
from thermalfea.gui.property_panels.form import FormPanel

_RESULTS = "results_path"
_RESULTS_FILTER = "Results (*.h5)"

#: The field rows shown for each kind (besides "kind" itself).
KIND_FIELDS: dict[str, tuple[str, ...]] = {
    "uniform": ("value",),
    "expression": ("value",),
    "per_region": ("per_region",),
    "from_results": (_RESULTS,),
}


def default_choose_open(parent: QWidget, caption: str, file_filter: str) -> str | None:
    """Ask for an existing file with the system dialog; ``None`` if cancelled."""
    path, _selected = QFileDialog.getOpenFileName(parent, caption, "", file_filter)
    return path or None


class InitialConditionPanel(FormPanel):
    """Form of the initial condition with the rows of its kind and a browse icon.

    Parameters
    ----------
    spec : FormSpec
        The initial-condition form.
    document : Document
    address : tuple
        Address ``("initial_condition",)``.
    view : SceneView, optional
    parent : QWidget, optional

    Attributes
    ----------
    choose_open : callable
        ``choose_open(parent, caption, file_filter) -> str | None``: the file chooser behind
        the browse button; replace it to avoid a dialog.
    browse_button : QToolButton
        The folder icon beside the results file box.
    """

    choose_open: Callable[[QWidget, str, str], str | None] = staticmethod(default_choose_open)

    def _add_field(self, field: FieldSpec) -> None:
        super()._add_field(field)
        if field.name != _RESULTS:
            return
        # put the browse icon in the same line as the box; the box stays the field's editor
        _form, cell = self._rows[_RESULTS]
        column = cell.layout()
        assert isinstance(column, QVBoxLayout)
        line = self.editors[_RESULTS]
        self.browse_button = icon_button("browse", "Choose the results file")
        self.browse_button.clicked.connect(lambda _checked=False: self.browse())
        row = QWidget()
        box = QHBoxLayout(row)
        box.setContentsMargins(0, 0, 0, 0)
        column.removeWidget(line)
        box.addWidget(line)
        box.addWidget(self.browse_button)
        column.insertWidget(0, row)

    def browse(self) -> bool:
        """Choose the results file and store it (one undo step); ``False`` if cancelled."""
        path = self.choose_open(self, "Choose the results file", _RESULTS_FILTER)
        if not path:
            return False
        return self.apply(_RESULTS, path)

    def refresh(self) -> None:
        """Reload the editors and show the rows of the chosen kind."""
        super().refresh()
        try:
            kind = self.current_object().kind
        except ModelError:
            return
        shown = KIND_FIELDS.get(kind, ())
        for name in ("value", "per_region", _RESULTS):
            if name in self.editors:
                self.set_field_visible(name, name in shown)
