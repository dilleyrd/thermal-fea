"""Property panel of the analysis settings (Plan M8.9).

:class:`SolutionPanel` is a :class:`~thermalfea.gui.property_panels.form.FormPanel` for
:class:`~thermalfea.model.settings.SolutionSettings`. It shows only the fields that matter
for the chosen analysis kind:

* steady: the kind and the nonlinear controls (tolerances, iterations, line search);
* transient: also end time, time stepping, integration and output; "store every n-th step"
  only when the output is ``every_n`` and the output times only when it is ``times``.

Below the form are the "Validate" and "Solve" buttons. They call the solve controller
(``validate()`` and ``solve()``), so the panel needs no solver knowledge. "Solve" is enabled
when the controller says a solve can start.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from thermalfea.core.forms import FormSpec
from thermalfea.gui.addressing import Address
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.scene import SceneView
from thermalfea.model.solution_forms import (
    OUTPUT_EVERY_FIELD,
    OUTPUT_TIMES_FIELD,
    TRANSIENT_ONLY_FIELDS,
)


class SolutionPanel(FormPanel):
    """Form of the analysis settings with the Validate and Solve buttons.

    Parameters
    ----------
    spec : FormSpec
        The solution form (:data:`thermalfea.model.solution_forms.SOLUTION_FORM`).
    document : Document
    address : tuple
        Address ``("solution",)``.
    view : SceneView, optional
    parent : QWidget, optional
    controller : object, optional
        The solve controller: ``validate()``, ``solve()``, ``can_solve() -> bool`` and a
        ``state_changed`` signal. Without one the buttons are disabled.

    Attributes
    ----------
    validate_button, solve_button : QPushButton
    """

    _extras_built = False

    def __init__(
        self,
        spec: FormSpec,
        document: Document,
        address: Address,
        view: SceneView | None = None,
        parent: QWidget | None = None,
        controller: Any = None,
    ) -> None:
        super().__init__(spec, document, address, view, parent)
        self._controller = controller
        self._row = {field.name: i for i, field in enumerate(spec.fields)}
        row = QHBoxLayout()
        self.validate_button = QPushButton("Validate")
        self.validate_button.clicked.connect(lambda _checked=False: self._on_validate())
        self.solve_button = QPushButton("Solve")
        self.solve_button.clicked.connect(lambda _checked=False: self._on_solve())
        row.addWidget(self.validate_button)
        row.addWidget(self.solve_button)
        row.addStretch(1)
        outer = self.layout()
        outer.insertLayout(outer.count() - 1, row)  # before the trailing stretch
        self._extras_built = True
        for signal in (
            document.mesh_changed,
            document.geometry_built,
            document.stale_changed,
        ):
            signal.connect(self._refresh_buttons)
        state = getattr(controller, "state_changed", None)
        if state is not None:
            state.connect(self._refresh_buttons)
        self._update_visibility()
        self._refresh_buttons()

    # ------------------------------------------------------------------ refresh
    def refresh(self) -> None:
        """Reload the editors and show the fields that suit the analysis kind."""
        super().refresh()
        if self._extras_built:
            self._update_visibility()

    def is_field_shown(self, name: str) -> bool:
        """``True`` if the field's row is shown (independent of the window being visible)."""
        return self.form_layout.isRowVisible(self._row[name])

    def _update_visibility(self) -> None:
        try:
            settings = self.current_object()
        except Exception:  # the object is gone; the panel is disabled by refresh()
            return
        transient = settings.kind == "transient"
        for name, row in self._row.items():
            shown = transient or name not in TRANSIENT_ONLY_FIELDS
            if name == OUTPUT_EVERY_FIELD:
                shown = shown and settings.output == "every_n"
            elif name == OUTPUT_TIMES_FIELD:
                shown = shown and settings.output == "times"
            self.form_layout.setRowVisible(row, shown)

    # ------------------------------------------------------------------ buttons
    def _refresh_buttons(self) -> None:
        controller = self._controller
        self.validate_button.setEnabled(
            controller is not None and self.document.built is not None
        )
        self.solve_button.setEnabled(controller is not None and bool(controller.can_solve()))

    def _on_validate(self) -> None:
        if self._controller is not None:
            self._controller.validate()

    def _on_solve(self) -> None:
        if self._controller is not None:
            self._controller.solve()
