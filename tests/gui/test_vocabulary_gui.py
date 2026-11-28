"""M11.49: part / boundary / point wording in the selection toolbar and selection editor."""

from __future__ import annotations

from test_selection_editor import SPEC, FakeView, built_doc, top_curve  # noqa: F401

from thermalfea import api
from thermalfea.gui.document import Document
from thermalfea.gui.property_panels.selection_editor import SelectionEditor


def labels(window) -> dict[str, str]:
    return {m: window.actions[f"select.{m}"].text() for m in
            ("none", "point", "curve", "surface", "node", "element")}  # fmt: skip


def test_toolbar_labels_without_a_document(window) -> None:
    assert labels(window) == {
        "none": "None", "point": "Point", "curve": "Boundary", "surface": "Part",
        "node": "Node", "element": "Element",
    }  # fmt: skip
    assert window.actions["select.curve"].toolTip() == "Pick boundaries (curves)"
    assert window.actions["select.surface"].toolTip() == "Pick parts (surfaces)"
    assert window.actions["select.point"].toolTip() == "Pick points"


def test_toolbar_labels_with_a_document_and_mode_values_unchanged(window) -> None:
    window.set_document(Document(api.new_model("axisymmetric")))
    assert labels(window)["curve"] == "Boundary" and labels(window)["surface"] == "Part"
    window.actions["select.curve"].trigger()
    assert window.selection_mode == "curve"  # the internal value is not renamed


def test_editor_status_text_names_boundaries(qtbot, built_doc) -> None:  # noqa: F811
    view = FakeView()
    editor = SelectionEditor(built_doc, view, SPEC)
    qtbot.addWidget(editor)
    editor.new_button.click()
    ents = built_doc.built.entities(1)
    tags = sorted(ents)[:2]
    view.pick(1, tags)
    assert editor.strip.count_label.text() == "2 boundaries picked"
    view.pick(1, tags[:1])
    assert editor.strip.count_label.text() == "1 boundary picked"
