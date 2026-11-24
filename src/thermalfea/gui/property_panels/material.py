"""Property panel of a material, with a "From library" box (task M11.44).

:class:`MaterialPanel` is a :class:`~thermalfea.gui.property_panels.form.FormPanel` with one
extra row above the property fields: a searchable list of the built-in solids followed by
the user library's solids, and a **Use library values** button. The button copies the
chosen entry's ``k``, ``k2``, ``rho``, ``cp`` and ``phase_change`` into this material in one
``Document.edit``; the material keeps its own name, so the regions that use it stay
assigned. The values remain editable.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from thermalfea.core.errors import ModelError
from thermalfea.core.forms import FormSpec
from thermalfea.gui.addressing import Address, resolve
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.form import FormPanel
from thermalfea.gui.scene import SceneView
from thermalfea.materials import library
from thermalfea.materials.material import Material, MaterialSource

USER_SUFFIX = " (user)"
USE_VALUES_TEXT = "Use library values"
RESTORE_VALUES_TEXT = "Restore library values"
_LIBRARY_KEY = "library"
_USE_KEY = "library-use"
_COPIED = ("k", "k2", "rho", "cp", "phase_change")


class MaterialPanel(FormPanel):
    """Form of a :class:`~thermalfea.materials.material.Material` plus the library box.

    Parameters
    ----------
    spec : FormSpec
        The material form.
    document : Document
    address : tuple
        Address ``("materials", name)`` of the material.
    view : SceneView, optional
    parent : QWidget, optional
    library_path : Path, optional
        User library file; defaults to :func:`thermalfea.materials.library.user_library_path`
        (looked up on every refresh).

    Attributes
    ----------
    library_combo : QComboBox
        Editable, with a contains-search completer.
    use_button : QPushButton
    """

    def __init__(
        self,
        spec: FormSpec,
        document: Document,
        address: Address,
        view: SceneView | None = None,
        parent: QWidget | None = None,
        library_path: Path | None = None,
    ) -> None:
        self._library_path = library_path
        self._entries: dict[str, Material] = {}
        self._sources: dict[str, MaterialSource] = {}
        self._ready = False
        super().__init__(spec, document, address, view, parent)

        self.library_combo = QComboBox()
        self.library_combo.setEditable(True)
        self.library_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.library_combo.setToolTip("Type to search the built-in and user materials.")
        completer = QCompleter(self.library_combo.model(), self.library_combo)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.library_combo.setCompleter(completer)
        self.use_button = QPushButton(USE_VALUES_TEXT)
        self.use_button.setToolTip(
            "Copy the chosen entry's conductivity, density, specific heat and phase change "
            "into this material; its name is kept."
        )
        self.use_button.clicked.connect(self.use_library_values)
        self.restore_button = QPushButton(RESTORE_VALUES_TEXT)
        self.restore_button.setToolTip(
            "Copy the library entry's values back into this material (enabled when edited)."
        )
        self.restore_button.clicked.connect(self.restore_library_values)
        self.source_label = QLabel()
        self.source_label.setWordWrap(True)

        box = QWidget()
        column = QVBoxLayout(box)
        column.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("From library"))
        row.addWidget(self.library_combo, 1)
        row.addWidget(self.use_button)
        column.addLayout(row)
        state_row = QHBoxLayout()
        state_row.setContentsMargins(0, 0, 0, 0)
        state_row.addWidget(self.source_label, 1)
        state_row.addWidget(self.restore_button)
        column.addLayout(state_row)
        outer = self.layout()
        assert isinstance(outer, QVBoxLayout)
        outer.insertWidget(outer.indexOf(self.form_layout), box)
        self._ready = True
        self._fill_library()

    # ------------------------------------------------------------------ the list
    def refresh(self) -> None:
        """Reload the editors and re-read the library."""
        super().refresh()
        if self._ready:
            self._fill_library()

    def library_names(self) -> list[str]:
        """The labels offered by the box: built-in names, then user names with a suffix."""
        return list(self._entries)

    def _fill_library(self) -> None:
        entries: dict[str, Material] = dict(library.solids())
        sources = {name: MaterialSource("builtin", name) for name in entries}
        try:
            user, _ = library.load_user_library(self._library_path)
        except ModelError as exc:
            user = {}
            self._set_error(_LIBRARY_KEY, str(exc))
        else:
            self._set_error(_LIBRARY_KEY, "")
        for name, material in user.items():
            entries[name + USER_SUFFIX] = material
            sources[name + USER_SUFFIX] = MaterialSource("user", name)
        self._entries = entries
        self._sources = sources
        combo = self.library_combo
        text = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        for label, src in sources.items():
            combo.addItem(label, src)  # the (library, entry) travels as item data
        combo.setCurrentIndex(-1)
        combo.setEditText(text)
        combo.blockSignals(False)
        self._update_source_state()

    def _material(self) -> Material | None:
        try:
            obj = self.current_object()
        except ModelError:  # the material is gone (e.g. undone) while the panel closes
            return None
        return obj if isinstance(obj, Material) else None

    def _update_source_state(self) -> None:
        """Show where the material stands against its library entry."""
        material = self._material()
        if material is None:
            return
        state, _, diff = library.source_state(material, self._library_path)
        src = material.source
        text = "Custom values"
        if src is not None:
            kind = "built-in" if src.library == "builtin" else "user"
            if state == "library":
                text = f"Values from the {kind} library: {src.entry}"
            elif state == "edited":
                text = (
                    f"Values from the {kind} library: {src.entry}; edited: {', '.join(diff)}"
                )
            else:
                text = f"{src.entry} · library entry not found in the {kind} library"
        self.source_label.setText(text)
        self.restore_button.setEnabled(state == "edited")

    # ----------------------------------------------------------------- the button
    def _chosen_label(self) -> str | None:
        text = self.library_combo.currentText().strip()
        if text in self._entries:
            return text
        folded = [k for k in self._entries if k.casefold() == text.casefold()]
        return folded[0] if text and len(folded) == 1 else None

    def chosen_entry(self) -> Material | None:
        """The library entry named by the box text (``None`` if none matches)."""
        label = self._chosen_label()
        return self._entries[label] if label is not None else None

    def chosen_source(self) -> MaterialSource | None:
        """The ``(library, entry)`` of the chosen box entry (``None`` if none matches)."""
        label = self._chosen_label()
        return self._sources[label] if label is not None else None

    def use_library_values(self) -> bool:
        """Copy the chosen entry's properties into this material (one undo step).

        The material's ``source`` is set to the chosen ``(library, entry)`` in the same step.

        Returns
        -------
        bool
            ``False`` (with a message in the panel, no edit) if nothing valid is chosen.
        """
        entry = self.chosen_entry()
        source = self.chosen_source()
        if entry is None or source is None:
            text = self.library_combo.currentText().strip()
            self._set_error(
                _USE_KEY,
                f"no library material is called {text!r}; choose one from the list"
                if text
                else "choose a library material first",
            )
            return False
        return self._copy_values(USE_VALUES_TEXT, entry, source)

    def restore_library_values(self) -> bool:
        """Copy the source entry's values back (one undo step); name and source are kept.

        Returns
        -------
        bool
            ``False`` if the material has no source or its entry cannot be found.
        """
        material = self._material()
        entry = library.source_entry(material, self._library_path) if material else None
        if material is None or material.source is None or entry is None:
            self._set_error(_USE_KEY, "the library entry of this material cannot be found")
            return False
        return self._copy_values(RESTORE_VALUES_TEXT, entry, material.source)

    def _copy_values(self, text: str, entry: Material, source: MaterialSource) -> bool:
        values: dict[str, Any] = {n: copy.deepcopy(getattr(entry, n)) for n in _COPIED}
        new_source = MaterialSource(source.library, source.entry)

        def mutate(model: Any) -> None:
            target = resolve(model, self.address)
            for n, v in values.items():
                setattr(target, n, copy.deepcopy(v))
            target.source = new_source
            post = getattr(target, "__post_init__", None)
            if post is not None:
                post()

        try:
            self.document.edit(text, mutate)
        except ModelError as exc:
            self._set_error(_USE_KEY, str(exc))
            return False
        self._set_error(_USE_KEY, "")
        self.value_changed.emit("library", entry.name)
        return True
