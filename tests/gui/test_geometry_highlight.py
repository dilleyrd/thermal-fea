"""M11.52: selecting a geometry step highlights what it owns in the current build."""

from __future__ import annotations

from typing import Any

from thermalfea import api
from thermalfea.gui.document import Document
from thermalfea.gui.load_symbols import attach_loads


class FakeView:
    """Records the highlights sent through the SceneView interface."""

    def __init__(self) -> None:
        self.highlights: list[tuple[int, list[int]]] = []

    def set_symbols(self, symbols: Any) -> None: ...

    def set_overlay(self, layer: str, items: list[Any]) -> None: ...

    def highlight(self, dim: int, tags: list[int]) -> None:
        self.highlights.append((dim, list(tags)))


def setup(window, build: bool = True):
    model = api.new_model(name="geo")
    g = api.Geometry(model)
    return model, g, lambda: _finish(window, model, build)


def _finish(window, model, build):
    doc = Document(model)
    if build:
        doc.set_built(api.build(model))
    view = FakeView()
    ctl = attach_loads(window, doc, view)
    return doc, view, ctl


def index(model, op_id: str) -> int:
    return [op.id for op in model.geometry].index(op_id)


def message(window) -> str:
    return window.statusBar().currentMessage()


def test_rectangle_highlights_its_surface(window) -> None:
    model, g, finish = setup(window)
    g.rectangle(0.0, 0.0, 1.0, 1.0, id="r")
    doc, view, ctl = finish()
    ctl.highlight_address(("geometry", index(model, "r")))
    dim, tags = view.highlights[-1]
    assert dim == 2
    assert tags == sorted(t for d, t in doc.built.op_entities["r"] if d == 2)
    assert len(tags) == 1


def test_cut_object_survives_and_tool_owns_nothing(window) -> None:
    model, g, finish = setup(window)
    g.rectangle(0.0, 0.0, 4.0, 4.0, id="obj")
    g.circle(2.0, 2.0, 1.0, id="tool")
    g.cut(["obj"], ["tool"], id="cut")
    doc, view, ctl = finish()
    ctl.highlight_address(("geometry", index(model, "obj")))
    assert view.highlights[-1][0] == 2
    assert view.highlights[-1][1]
    ctl.highlight_address(("geometry", index(model, "tool")))
    assert view.highlights[-1] == (1, [])
    assert message(window) == (
        "tool: nothing left in the geometry (used by a later operation or deleted)"
    )


def test_union_inputs_and_result_highlight_the_same_surface(window) -> None:
    model, g, finish = setup(window)
    g.rectangle(0.0, 0.0, 2.0, 2.0, id="a")
    g.rectangle(1.0, 1.0, 3.0, 3.0, id="b")
    g.union(["a"], ["b"], id="u")
    doc, view, ctl = finish()
    seen = []
    for op_id in ("a", "b", "u"):
        ctl.highlight_address(("geometry", index(model, op_id)))
        seen.append(view.highlights[-1])
    assert seen[2][0] == 2 and seen[2][1]
    assert seen[0] == seen[1] == seen[2]


def test_line_highlights_a_curve(window) -> None:
    model, g, finish = setup(window)
    for i, (x, y) in enumerate([(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]):
        g.point(x, y, id=f"p{i}")
    g.line("p0", "p1", id="l0")
    g.line("p1", "p2", id="l1")
    g.line("p2", "p0", id="l2")
    g.surface(["l0", "l1", "l2"], id="s")
    doc, view, ctl = finish()
    ctl.highlight_address(("geometry", index(model, "l1")))
    dim, tags = view.highlights[-1]
    assert dim == 1
    assert tags == sorted(t for d, t in doc.built.op_entities["l1"] if d == 1)
    assert len(tags) == 1


def test_delete_owns_nothing(window) -> None:
    model, g, finish = setup(window)
    g.rectangle(0.0, 0.0, 1.0, 1.0, id="keep")
    g.rectangle(2.0, 0.0, 3.0, 1.0, id="gone")
    g.delete(["gone"], id="del")
    doc, view, ctl = finish()
    ctl.highlight_address(("geometry", index(model, "del")))
    assert view.highlights[-1] == (1, [])
    assert message(window).startswith("del: nothing left in the geometry")


def test_no_build_clears_with_a_status(window) -> None:
    model, g, finish = setup(window, build=False)
    g.rectangle(0.0, 0.0, 1.0, 1.0, id="r")
    doc, view, ctl = finish()
    ctl.highlight_address(("geometry", 0))
    assert view.highlights[-1] == (1, [])
    assert message(window) == "r: the geometry is not built"


def test_stale_build_clears_with_a_status(window) -> None:
    model, g, finish = setup(window)
    g.rectangle(0.0, 0.0, 1.0, 1.0, id="r")
    doc, view, ctl = finish()
    doc.edit("more", lambda m: api.Geometry(m).rectangle(5.0, 5.0, 6.0, 6.0, id="s"))
    assert doc.geometry_stale
    ctl.highlight_address(("geometry", 0))
    assert view.highlights[-1] == (1, [])
    assert message(window) == "r: the geometry is not built"


def test_other_addresses_behave_as_before(window) -> None:
    model, g, finish = setup(window)
    g.rectangle(0.0, 0.0, 1.0, 1.0, id="r")
    doc, view, ctl = finish()
    ctl.highlight_address(("geometry", 0))
    assert view.highlights[-1][0] == 2
    ctl.highlight_address(("bcs", 0))
    assert view.highlights[-1] == (1, [])
    ctl.highlight_address(("geometry", 9))
    assert view.highlights[-1] == (1, [])
    ctl.highlight_address(())
    assert view.highlights[-1] == (1, [])
