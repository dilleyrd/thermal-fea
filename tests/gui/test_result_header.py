"""M11.59: the result header and the changes since the solve (plan section 6)."""

# ruff: noqa: F811
from __future__ import annotations

import h5py

# fixtures (``steady``, ``transient``, ``steady_case``, ...) and helpers of the display tests
from tests.gui.test_results_display import (  # noqa: F401
    RecordingView,
    make_shell,
    open_panel,
    steady,
    steady_case,
    transient,
    transient_case,
)

from thermalfea.core.units import UnitSettings
from thermalfea.gui.document import Document
from thermalfea.gui.results_tools import OUT_OF_DATE_SUFFIX, result_status
from thermalfea.model.serialize import from_json, to_json
from thermalfea.post.results import Results


def edit_h(shell, value: float = 150.0) -> None:
    assert shell.doc.edit("h", lambda m: setattr(m.bcs[1], "h", value))


def first_item(shell) -> tuple:
    return shell.ctrl.tree_items()[0][1]


def test_header_after_a_solve(steady) -> None:
    status = result_status(steady.doc)
    assert status.available and status.current is True and status.changes == []
    text = "\n".join(status.lines)
    assert "Analysis: steady" in text
    assert "Mesh: T3" in text or "Mesh: T6" in text
    assert "nodes" in text and "elements" in text
    assert "Results written " in text and "current" in text
    panel = open_panel(steady)
    assert "Results written" in panel.header_label.text()
    assert panel.stale_label.isHidden()


def test_transient_header_names_the_end_time(transient) -> None:
    text = "\n".join(result_status(transient.doc).lines)
    assert "transient 0–" in text


def test_edit_undo_redo(steady) -> None:
    ctrl = steady.ctrl
    assert ctrl.status().current is True
    edit_h(steady)
    status = ctrl.status()
    assert status.current is False and len(status.changes) >= 1
    assert "out of date" in status.state
    panel = open_panel(steady)
    assert not panel.stale_label.isHidden()
    assert any(c in panel.stale_label.text() for c in status.changes)
    steady.doc.undo_stack.undo()  # the old flag stayed raised here
    assert ctrl.status().current is True and ctrl.status().changes == []
    assert panel.stale_label.isHidden()
    steady.doc.undo_stack.redo()
    assert ctrl.status().current is False
    assert not panel.stale_label.isHidden()


def test_long_change_list_is_cut(steady) -> None:
    from thermalfea.gui.property_panels.results import _changes_text
    from thermalfea.gui.results_tools import ResultStatus

    status = ResultStatus(True, False, [f"c{i}" for i in range(25)], [])
    lines = _changes_text(status).splitlines()
    assert lines[-1] == "… and 5 more" and len(lines) == 22


def test_unchanged_remesh_stays_current(steady) -> None:
    steady.doc.set_mesh(Results(steady.path).mesh)
    assert steady.doc.results_stale
    assert steady.ctrl.status().current is True


def test_display_unit_change_stays_current(steady) -> None:
    assert steady.doc.edit("units", lambda m: setattr(m, "display_units", UnitSettings()))
    assert steady.ctrl.status().current is True


def test_save_and_reopen_is_current(steady, window) -> None:
    reopened = from_json(to_json(steady.doc.model))
    doc = Document(reopened)
    doc.set_results(steady.path)
    assert result_status(doc).current is True
    edit_h(steady)
    assert result_status(steady.doc).current is False


def test_missing_snapshot_is_unavailable(steady) -> None:
    with h5py.File(steady.path, "r+") as f:
        f["meta"].attrs["model"] = ""
    steady.doc.set_results(steady.path)
    status = steady.ctrl.status()
    assert status.available and status.current is None
    assert status.state == "comparison unavailable"
    assert steady.ctrl.tree_summary(first_item(steady)) == "contour · comparison unavailable"
    assert not open_panel(steady).header_label.text().endswith("current")
    assert not (steady.view.last.title or "").endswith(OUT_OF_DATE_SUFFIX)


def test_tree_summary_and_viewport_title(steady) -> None:
    address = first_item(steady)
    assert steady.ctrl.tree_summary(address) == "contour · current"
    assert not steady.view.last.title.endswith(OUT_OF_DATE_SUFFIX)
    edit_h(steady)
    assert steady.ctrl.tree_summary(address) == "contour · out of date"
    assert steady.view.last.title.endswith(OUT_OF_DATE_SUFFIX)
    steady.doc.undo_stack.undo()
    assert steady.ctrl.tree_summary(address) == "contour · current"
    assert not steady.view.last.title.endswith(OUT_OF_DATE_SUFFIX)


def test_no_results_has_no_header(steady) -> None:
    doc = Document(steady.doc.model)
    status = result_status(doc)
    assert not status.available and status.lines == [] and status.state == ""
