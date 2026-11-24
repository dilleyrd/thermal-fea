"""M11.60: the report of what is on one geometry entity."""

from __future__ import annotations

import pytest

from thermalfea import api
from thermalfea.gui.document import Document
from thermalfea.gui.inspect import entity_report
from thermalfea.model import bcs


def _on(axis: int, value: float):
    return lambda c: abs(c.bbox[axis] - value) < 1e-6 and abs(c.bbox[axis + 3] - value) < 1e-6


@pytest.fixture
def doc() -> Document:
    """Two stacked strips (two parts) with a convection on the right edges."""
    model = api.new_model(name="strips")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 0.6, 0.2)
    geo.rectangle(0.0, 0.2, 0.6, 0.8)
    built = api.build(model)
    api.select_surfaces(model, built, "lower", where=lambda s: s.bbox[4] < 0.21)
    api.select_surfaces(model, built, "upper", where=lambda s: s.bbox[1] > 0.19)
    api.select_curves(model, built, "right", where=_on(0, 0.6))
    api.select_curves(model, built, "middle", where=_on(1, 0.2))
    api.select_points(
        model, built, "check", where=lambda p: p.bbox[0] > 0.59 and abs(p.bbox[1] - 0.2) < 1e-6
    )
    api.assign_region(model, "lower", material="Copper (pure)")
    api.assign_region(model, "upper", material="Copper (pure)")
    off = bcs.Convection("spare", "right", h=5.0, T_inf=300.0)
    off.active = False
    model.bcs += [bcs.Convection("cooling", "right", h=750.0, T_inf=273.15), off]
    document = Document(model)
    document.set_built(built)
    return document


def tag_of(doc: Document, name: str, index: int = 0) -> tuple[int, int]:
    sel = doc.model.selections[name]
    return int(sel.dim), int(sel.tags[index])


def test_a_boundary_with_loads(doc) -> None:
    dim, tag = tag_of(doc, "right", 0)
    report = entity_report(doc, dim, tag)
    assert report.role == "boundary" and report.title == f"Boundary {tag}"
    assert report.selections == ["right"]
    labels = {(u.label, u.suppressed) for u in report.uses}
    assert labels == {("convection cooling", False), ("convection spare", True)}
    assert len(report.parts) == 1  # an outer edge bounds one part
    text = report.lines()
    assert "convection spare (suppressed)" in text and "in: right" in text


def test_an_interface_touches_both_parts(doc) -> None:
    report = entity_report(doc, *tag_of(doc, "middle"))
    assert [label for _, label in report.parts] == ["lower", "upper"]
    assert report.uses == []
    assert ("regions", 0) in report.addresses() and ("selections", "middle") in report.addresses()


def test_a_point_and_a_part(doc) -> None:
    point = entity_report(doc, *tag_of(doc, "check"))
    assert point.role == "point" and point.selections == ["check"]
    assert [label for _, label in point.parts] == ["lower", "upper"]
    part = entity_report(doc, *tag_of(doc, "upper"))
    assert part.role == "part" and "upper" in part.selections and "all" in part.selections
    assert [label for _, label in part.parts] == ["upper"]


def test_no_current_build(doc) -> None:
    dim, tag = tag_of(doc, "right")
    doc.edit("move", lambda m: setattr(m.geometry[0], "width", 0.5))  # geometry now stale
    report = entity_report(doc, dim, tag)
    assert not report.built and report.selections == [] and report.parts == []
    assert report.lines()[1] == "the geometry is not built"
