"""M2.8 — size controls and structured meshing."""

from __future__ import annotations

import numpy as np
import pytest

from thermalfea import api
from thermalfea.core.errors import MeshError
from thermalfea.core.mesh import Mesh
from thermalfea.geometry.builder import build
from thermalfea.meshing.mesher import generate
from thermalfea.model import geometry_ops as g
from thermalfea.model.model import Model
from thermalfea.model.settings import MeshSettings, Refinement
from thermalfea.physics.kernel import geometry

W, H = 2.0, 1.0


def rect_model(**mesh) -> tuple[Model, object]:
    model = Model(
        geometry=[g.Rectangle("r", 0.0, 0.0, W, H)],
        mesh_settings=MeshSettings(**{"global_size": 0.25, **mesh}),
    )
    built = build(model)
    api.select_curves(model, built, "bottom", where=lambda c: abs(c.center[1]) < 1e-9)
    api.select_curves(model, built, "top", where=lambda c: abs(c.center[1] - H) < 1e-9)
    api.select_curves(model, built, "left", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "right", where=lambda c: abs(c.center[0] - W) < 1e-9)
    api.select_surfaces(model, built, "all", where=lambda s: True)
    api.select_points(model, built, "origin", where=lambda p: p.center[0] + p.center[1] < 1e-9)
    return model, built


def element_sizes(mesh: Mesh) -> tuple[np.ndarray, np.ndarray]:
    """Centroid and sqrt(area) of every element."""
    centroids, sizes = [], []
    for b in mesh.blocks:
        centroids.append(mesh.nodes[b.conn].mean(axis=1))
        sizes.append(np.sqrt(geometry(b, mesh.nodes).dV.sum(axis=1)))
    return np.concatenate(centroids), np.concatenate(sizes)


def n_edges(mesh: Mesh, built, name_tags: list[int]) -> int:
    return sum(f.conn.shape[0] for f in mesh.facets_on(name_tags))


# ------------------------------------------------------------------------- structured


@pytest.mark.parametrize("order", [1, 2])
def test_transfinite_rectangle_has_exactly_nx_ny_quads(order: int) -> None:
    nx, ny = 7, 3
    model, built = rect_model(
        element_shape="quad", order=order, curve_divisions={"bottom": nx, "left": ny},
        structured_surfaces=["all"],
    )
    mesh = generate(model, built)
    (block,) = mesh.blocks
    assert block.etype == ("Q4" if order == 1 else "Q8")
    assert block.conn.shape[0] == nx * ny
    assert mesh.n_elements == nx * ny
    # a regular grid: every element has area (W/nx)(H/ny)
    np.testing.assert_allclose(geometry(block, mesh.nodes).dV.sum(axis=1), W * H / (nx * ny))
    for name, n in (("bottom", nx), ("top", nx), ("left", ny), ("right", ny)):
        assert n_edges(mesh, built, model.selections[name].tags) == n
    expected_nodes = (nx + 1) * (ny + 1) + (order - 1) * (nx * (ny + 1) + ny * (nx + 1))
    assert mesh.n_nodes == expected_nodes


def test_transfinite_triangles_and_default_divisions() -> None:
    model, built = rect_model(structured_surfaces=["all"])  # tri, no divisions given
    mesh = generate(model, built)
    nx, ny = round(W / 0.25), round(H / 0.25)
    assert mesh.n_elements == 2 * nx * ny
    assert {b.etype for b in mesh.blocks} == {"T3"}


def test_three_sided_structured_surface() -> None:
    model = Model(
        geometry=[g.Polygon("t", [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])],
        mesh_settings=MeshSettings(global_size=0.25, structured_surfaces=["all"]),
    )
    built = build(model)
    api.select_surfaces(model, built, "all", where=lambda s: True)
    mesh = generate(model, built)
    mesh.validate()
    n = round(2**0.5 / 0.25)  # the longest side sets the common number of divisions
    assert sum(f.conn.shape[0] for f in mesh.facets) == 3 * n  # n elements on every side
    assert sum(geometry(blk, mesh.nodes).dV.sum() for blk in mesh.blocks) == pytest.approx(0.5)
    # structured: the element count depends only on n (gmsh collapses one side of an
    # n x n grid of split quads), not on the free-meshing algorithm
    assert mesh.n_elements == 2 * n * n - n


def test_structured_needs_three_or_four_sides() -> None:
    model = Model(
        geometry=[g.Polygon("L", [(0, 0), (2, 0), (2, 1), (1, 1), (1, 2), (0, 2)])],
        mesh_settings=MeshSettings(global_size=0.25, structured_surfaces=["all"]),
    )
    built = build(model)
    api.select_surfaces(model, built, "all", where=lambda s: True)
    with pytest.raises(MeshError, match="3- or 4-sided.*'all' has 6"):
        generate(model, built)


def test_conflicting_divisions_on_opposite_sides() -> None:
    model, built = rect_model(
        curve_divisions={"bottom": 4, "top": 5}, structured_surfaces=["all"]
    )
    with pytest.raises(MeshError, match="opposite sides.*\\[4, 5\\]"):
        generate(model, built)


def test_curve_divisions_without_structured_surface() -> None:
    model, built = rect_model(curve_divisions={"bottom": 13})
    mesh = generate(model, built)
    assert n_edges(mesh, built, model.selections["bottom"].tags) == 13
    assert n_edges(mesh, built, model.selections["top"].tags) == round(W / 0.25)


# ------------------------------------------------------------------------------ sizes


def test_curve_size() -> None:
    model, built = rect_model(curve_sizes={"left": 0.05})
    mesh = generate(model, built)
    assert n_edges(mesh, built, model.selections["left"].tags) == pytest.approx(H / 0.05, abs=2)
    assert n_edges(mesh, built, model.selections["right"].tags) == pytest.approx(H / 0.25, abs=1)
    centroids, sizes = element_sizes(mesh)
    assert sizes[centroids[:, 0] < 0.1].mean() < 0.5 * sizes[centroids[:, 0] > 1.5].mean()


def test_point_size() -> None:
    plain_model, plain_built = rect_model()
    plain = generate(plain_model, plain_built)
    model, built = rect_model(point_sizes={"origin": 0.02})
    mesh = generate(model, built)
    assert mesh.n_elements > 1.5 * plain.n_elements
    centroids, sizes = element_sizes(mesh)
    near = np.linalg.norm(centroids, axis=1) < 0.15
    far = np.linalg.norm(centroids - [W, H], axis=1) < 0.5
    assert sizes[near].mean() < 0.4 * sizes[far].mean()


@pytest.mark.parametrize("target", ["left", "origin"])
def test_refinement_gives_smaller_elements_near_the_chosen_entity(target: str) -> None:
    model, built = rect_model(
        refinements=[Refinement(target, size_min=0.03, size_max=0.25, dist_min=0.1, dist_max=0.8)]
    )
    mesh = generate(model, built)
    mesh.validate()
    centroids, sizes = element_sizes(mesh)
    distance = centroids[:, 0] if target == "left" else np.linalg.norm(centroids, axis=1)
    near, far = sizes[distance < 0.1], sizes[distance > 1.2]
    assert near.size > 5 and far.size > 5
    assert near.mean() < 0.3 * far.mean()
    assert near.mean() == pytest.approx(0.03 * 0.66, rel=0.5)  # sqrt(area) of size-0.03 triangles


def test_controls_do_not_leak_into_the_next_generation() -> None:
    model, built = rect_model()
    plain = generate(model, built).n_elements
    model.mesh_settings.refinements = [Refinement("left", 0.02, 0.25, 0.0, 0.5)]
    model.mesh_settings.curve_divisions = {"bottom": 40}
    model.mesh_settings.structured_surfaces = []
    refined = generate(model, built).n_elements
    assert refined > 3 * plain
    model.mesh_settings.refinements = []
    model.mesh_settings.curve_divisions = {}
    assert generate(model, built).n_elements == plain
    model.mesh_settings.element_shape = "quad"
    model.mesh_settings.structured_surfaces = ["all"]
    assert generate(model, built).n_elements == 8 * 4
    model.mesh_settings.element_shape = "tri"
    model.mesh_settings.structured_surfaces = []
    assert generate(model, built).n_elements == plain


@pytest.mark.parametrize(
    ("mesh", "message"),
    [
        ({"curve_sizes": {"nope": 0.1}}, "unknown selection 'nope'"),
        ({"curve_sizes": {"all": 0.1}}, "'all' has dimension 2"),
        ({"curve_sizes": {"left": 0.0}}, "must be positive"),
        ({"point_sizes": {"left": 0.1}}, "'left' has dimension 1"),
        ({"point_sizes": {"origin": -1.0}}, "must be positive"),
        ({"curve_divisions": {"left": 0}}, "at least 1"),
        ({"structured_surfaces": ["left"]}, "'left' has dimension 1"),
        ({"refinements": [Refinement("all", 0.01, 0.1, 0.0, 1.0)]}, "'all' has dimension 2"),
        ({"refinements": [Refinement("left", 0.2, 0.1, 0.0, 1.0)]}, "size_min <= size_max"),
        ({"refinements": [Refinement("left", 0.1, 0.2, 1.0, 1.0)]}, "dist_min < dist_max"),
    ],
)
def test_bad_controls_raise_mesh_error(mesh: dict, message: str) -> None:
    model, built = rect_model(**mesh)
    with pytest.raises(MeshError, match=message):
        generate(model, built)


def test_stale_selection_in_a_mesh_control() -> None:
    model, _ = rect_model(curve_sizes={"left": 0.05})
    model.geometry[0] = g.Rectangle("r", 0.0, 0.0, W, 2 * H)
    with pytest.raises(MeshError, match="'left' is stale"):
        generate(model, build(model))
