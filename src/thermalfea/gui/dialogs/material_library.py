"""The material library dialog (Plan M8.6): built-in and user materials, copied into a model.

:class:`MaterialLibraryDialog` is used *non-modally* (``show()``, never ``exec()``). It lists
the built-in solids (:func:`thermalfea.materials.library.solids`) and the user library
(:func:`thermalfea.materials.library.load_user_library`) on two tabs and shows the selected
material read-only. Three actions:

* "Copy into model" adds a copy of the selected material to the document's model (one undo
  step); a name already in use gets a new one (``"Copper (pure) 2"``);
* "Save model material to user library" writes a material of the model to the user library;
* "Remove from user library" deletes the selected user material from the library.

Errors are shown in a status line of the dialog, never in a modal box. The user library
file is ``user_path`` (default :func:`thermalfea.materials.library.user_library_path`), so
tests can use a temporary file.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import copy_name, form_for, unit_label
from thermalfea.core.functions import Constant
from thermalfea.core.units import UnitSettings, from_si
from thermalfea.gui.document import Document
from thermalfea.materials import library
from thermalfea.materials.material import Material
from thermalfea.model.model import Model

_BUILTIN = "builtin"
_USER = "user"
_ERROR_STYLE = "color: #b00020;"


def _value_text(value: object, quantity: str | None, settings: UnitSettings) -> str:
    if isinstance(value, Constant):
        shown = value.value if quantity is None else from_si(value.value, quantity, settings)
        return f"{float(shown):.6g}"
    if value is None:
        return "-"
    return "tabulated or expression"


def describe(material: Material, settings: UnitSettings) -> str:
    """Read-only text summary of a material: one line per property, with its unit.

    Parameters
    ----------
    material : Material
    settings : UnitSettings
        Display units (for the unit labels).
    """
    lines = [material.name]
    for spec in form_for(Material).fields:
        unit = unit_label(spec.quantity, settings)
        text = _value_text(getattr(material, spec.name), spec.quantity, settings)
        lines.append(f"{spec.label}: {text} {unit}".rstrip())
    if material.phase_change is not None:
        pc = material.phase_change
        t_sol = float(from_si(pc.T_sol, "temperature", settings))
        t_liq = float(from_si(pc.T_liq, "temperature", settings))
        unit = unit_label("temperature", settings)
        lines.append(f"Phase change: {t_sol:.6g} {unit} to {t_liq:.6g} {unit}")
    return "\n".join(lines)


class MaterialLibraryDialog(QDialog):
    """Browse the material libraries and copy or save materials.

    Parameters
    ----------
    document : Document
        Its model receives copies; its materials can be saved to the user library.
    user_path : Path, optional
        The user library file; defaults to
        :func:`thermalfea.materials.library.user_library_path`.
    parent : QWidget, optional

    Attributes
    ----------
    user_path : Path
        The user library file this dialog reads and writes.
    builtin_list, user_list : QListWidget
        The two tabs' lists.
    summary : QPlainTextEdit
        Read-only properties of the selected material.
    status : QLabel
        Messages of the last action (errors in red).
    """

    def __init__(
        self, document: Document, user_path: Path | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Material library")
        self.document = document
        self.user_path = library.user_library_path() if user_path is None else Path(user_path)
        self._source: tuple[str, str] | None = None

        self.builtin_list = QListWidget()
        self.user_list = QListWidget()
        self.tabs = QTabWidget()
        self.tabs.addTab(self.builtin_list, "Built-in")
        self.tabs.addTab(self.user_list, "User")
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.copy_button = QPushButton("Copy into model")
        self.model_combo = QComboBox()
        self.save_button = QPushButton("Save model material to user library")
        self.remove_button = QPushButton("Remove from user library")
        self.status = QLabel("")
        self.status.setWordWrap(True)

        grid = QGridLayout()
        grid.addWidget(QLabel("Model material:"), 0, 0)
        grid.addWidget(self.model_combo, 0, 1)
        grid.addWidget(self.save_button, 1, 1)
        buttons = QHBoxLayout()
        buttons.addWidget(self.copy_button)
        buttons.addWidget(self.remove_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabs)
        layout.addWidget(self.summary)
        layout.addLayout(buttons)
        layout.addLayout(grid)
        layout.addWidget(self.status)
        self.resize(560, 520)

        self.builtin_list.currentItemChanged.connect(
            lambda cur, _prev: self._select(_BUILTIN, cur)
        )
        self.user_list.currentItemChanged.connect(lambda cur, _prev: self._select(_USER, cur))
        self.copy_button.clicked.connect(lambda _c=False: self.copy_into_model())
        self.save_button.clicked.connect(lambda _c=False: self.save_to_user_library())
        self.remove_button.clicked.connect(lambda _c=False: self.remove_from_user_library())
        document.model_changed.connect(self._refresh_model_combo)
        self.reload()

    # ------------------------------------------------------------------ loading
    def reload(self) -> None:
        """Re-read both libraries and the model's materials; clears the selection."""
        self._source = None
        self.builtin_list.clear()
        self.user_list.clear()
        self.builtin_list.addItems(list(library.solids()))
        try:
            user_solids, _fluids = library.load_user_library(self.user_path)
        except ModelError as exc:
            self._message(str(exc), error=True)
            user_solids = {}
        self.user_list.addItems(list(user_solids))
        self._refresh_model_combo()
        self._show()

    def _refresh_model_combo(self) -> None:
        names = list(self.document.model.materials)
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(names)
        self.model_combo.blockSignals(False)

    def _select(self, source: str, item: QListWidgetItem | None) -> None:
        if item is None:
            return
        self._source = (source, item.text())
        other = self.user_list if source == _BUILTIN else self.builtin_list
        other.blockSignals(True)
        other.setCurrentRow(-1)
        other.blockSignals(False)
        self._show()

    def _library_material(self, source: tuple[str, str]) -> Material:
        kind, name = source
        if kind == _BUILTIN:
            return library.solid(name)
        solids, _fluids = library.load_user_library(self.user_path)
        if name not in solids:
            raise ModelError(f"{name!r} is not in the user library")
        return solids[name]

    def selected_material(self) -> Material | None:
        """The library material selected in either tab (``None`` if none, or unreadable)."""
        if self._source is None:
            return None
        try:
            return self._library_material(self._source)
        except ModelError:
            return None

    def _show(self) -> None:
        material = self.selected_material()
        if material is None:
            self.summary.setPlainText("Select a material to see its properties.")
        else:
            self.summary.setPlainText(describe(material, self.document.model.display_units))
        self.remove_button.setEnabled(self._source is not None and self._source[0] == _USER)

    # ----------------------------------------------------------------- actions
    def _message(self, text: str, error: bool = False) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(_ERROR_STYLE if error else "")

    def copy_into_model(self) -> bool:
        """Add a copy of the selected library material to the model (one undo step).

        Returns
        -------
        bool
            ``True`` if a material was added; errors are shown in :attr:`status`.
        """
        if self._source is None:
            self._message("Select a material to copy.", error=True)
            return False
        try:
            material = self._library_material(self._source)
        except ModelError as exc:
            self._message(str(exc), error=True)
            return False
        holder: list[str] = []

        def mutate(model: Model) -> None:
            materials = model.materials
            name = material.name
            if name in materials:
                name = copy_name(name, materials, keep_digits=True)
            materials[name] = Material.from_json({**material.to_json(), "name": name})
            holder.append(name)

        try:
            self.document.edit(f"Copy {material.name} into model", mutate)
        except ModelError as exc:
            self._message(str(exc), error=True)
            return False
        self._message(f"Copied into the model as {holder[0]!r}.")
        return True

    def save_to_user_library(self) -> bool:
        """Write the model material chosen in :attr:`model_combo` to the user library.

        Returns
        -------
        bool
            ``True`` if it was saved; a name already in the user library is refused.
        """
        name = self.model_combo.currentText()
        material = self.document.model.materials.get(name)
        if material is None:
            self._message("Choose a material of the model to save.", error=True)
            return False
        try:
            solids, fluids = library.load_user_library(self.user_path)
            if name in solids:
                raise ModelError(f"{name!r} is already in the user library; remove it first")
            solids[name] = Material.from_json(material.to_json())
            library.save_user_library(solids, fluids, self.user_path)
        except (ModelError, OSError) as exc:
            self._message(str(exc), error=True)
            return False
        self.reload()
        self._message(f"Saved {name!r} to the user library.")
        return True

    def remove_from_user_library(self) -> bool:
        """Remove the selected user material from the user library.

        Returns
        -------
        bool
            ``True`` if it was removed; errors are shown in :attr:`status`.
        """
        if self._source is None or self._source[0] != _USER:
            self._message("Select a user material to remove.", error=True)
            return False
        name = self._source[1]
        try:
            solids, fluids = library.load_user_library(self.user_path)
            if name not in solids:
                raise ModelError(f"{name!r} is not in the user library")
            del solids[name]
            library.save_user_library(solids, fluids, self.user_path)
        except (ModelError, OSError) as exc:
            self._message(str(exc), error=True)
            return False
        self.reload()
        self._message(f"Removed {name!r} from the user library.")
        return True
