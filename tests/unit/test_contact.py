"""M10.1 — opening contact interfaces (node duplication) and the contact term (Theory §11)."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from thermalfea.core.contact_split import split_interfaces
from thermalfea.core.errors import MeshError, ModelError
from thermalfea.core.functions import Expression
from thermalfea.core.mesh import FacetBlock, Mesh
from thermalfea.core.meshgen import BOTTOM, LEFT, RIGHT, TOP, rect_mesh
from thermalfea.core.registry import element
from thermalfea.materials.material import Material
from thermalfea.model.bcs import Contact, FixedTemperature
from thermalfea.physics.conduction import ConductionTerm
from thermalfea.physics.contact import PARTNERS, ContactTerm
from thermalfea.post.energy import energy_balance
from thermalfea.solver.assembler import Assembler
from thermalfea.solver.compile import attach
from thermalfea.solver.dofs import DofMap
from thermalfea.solver.problem import CompiledProblem, RegionData
from thermalfea.solver.steady import steady_solution
from thermalfea.solver.terms import State

TYPES = ["T3", "Q4", "T6", "Q8"]
WIDTH, HEIGHT = 2.0, 1.0


def regioned(
    etype: str,
    cells: tuple[int, int],
    region_of: Callable[[float, float], int],
    entity_of: Callable[[int, int, np.ndarray], int] = lambda lo, hi, mid: 100 + 10 * lo + hi,
) -> Mesh:
    """A rectangle mesh with several regions and facets on the interfaces between them.

    ``region_of(x, y)`` gives the region of an element from its centroid;
    ``entity_of(lower, higher, midpoint)`` the tag of an interface facet. As the mesher
    does, an interface facet is oriented by, and belongs to, the element of the lower
    region id.
    """
    mesh = rect_mesh(0.0, 0.0, WIDTH, HEIGHT, *cells, etype)
    sides: dict[tuple, list[tuple[int, int, np.ndarray]]] = {}
    region: dict[int, int] = {}
    for block in mesh.blocks:
        centre = mesh.nodes[block.conn].mean(axis=1)
        block.region[:] = [region_of(x, y) for x, y in centre]
        local = element(block.etype).facets
        for conn, elem, reg in zip(block.conn, block.elem_ids, block.region, strict=True):
            region[int(elem)] = int(reg)
            for side in conn[local]:
                sides.setdefault(tuple(sorted(side)), []).append((int(elem), int(reg), side))
    conn, entity, parent = [], [], []
    for owners in sides.values():
        if len(owners) == 2 and owners[0][1] != owners[1][1]:
            low, high = sorted(owners, key=lambda o: o[1])
            conn.append(low[2])
            entity.append(entity_of(low[1], high[1], mesh.nodes[low[2]].mean(axis=0)))
            parent.append(low[0])
    facet_type = element(mesh.blocks[0].etype).facet_type
    mesh.facets.append(
        FacetBlock(facet_type, np.array(conn), np.array(entity, dtype=np.int32), np.array(parent))
    )
    mesh.validate()
    return mesh


def two_layers(etype: str, cells: tuple[int, int] = (4, 2)) -> Mesh:
    return regioned(etype, cells, lambda x, y: 1 if x < WIDTH / 2 else 2)


def on_line(mesh: Mesh, x: float) -> np.ndarray:
    return np.flatnonzero(np.isclose(mesh.nodes[:, 0], x))


# ------------------------------------------------------------------- opening the mesh


@pytest.mark.parametrize("etype", TYPES)
def test_whole_interface_is_opened(etype: str) -> None:
    mesh = two_layers(etype)
    interface = on_line(mesh, WIDTH / 2)
    split = split_interfaces(mesh, [112])
    new = split.mesh
    new.validate()
    # every interface node was duplicated once (both ends lie on the outer boundary)
    assert split.n_new == interface.size and new.n_nodes == mesh.n_nodes + interface.size
    np.testing.assert_array_equal(new.nodes[: mesh.n_nodes], mesh.nodes)  # indices kept
    np.testing.assert_array_equal(split.origin[: mesh.n_nodes], np.arange(mesh.n_nodes))
    np.testing.assert_array_equal(np.sort(split.origin[mesh.n_nodes :]), interface)
    added = split.origin[mesh.n_nodes :]
    np.testing.assert_array_equal(new.nodes[mesh.n_nodes :], mesh.nodes[added])
    # the higher region got the new nodes; the lower keeps the originals
    for block in new.blocks:
        low = block.conn[block.region == 1]
        high = block.conn[block.region == 2]
        assert low.max() < mesh.n_nodes
        assert not np.isin(high, interface).any()
        assert np.isin(np.arange(mesh.n_nodes, new.n_nodes), high).all()
    # the two layers no longer share a node
    low_nodes = np.unique(np.concatenate([b.conn[b.region == 1].ravel() for b in new.blocks]))
    high_nodes = np.unique(np.concatenate([b.conn[b.region == 2].ravel() for b in new.blocks]))
    assert np.intersect1d(low_nodes, high_nodes).size == 0
    # partners: same position, other side, in the order of the facet nodes
    partner = split.partner[112]
    np.testing.assert_array_equal(np.flatnonzero(partner >= 0), interface)
    np.testing.assert_array_equal(split.origin[partner[interface]], interface)
    assert np.all(partner[interface] >= mesh.n_nodes)
    # the interface facets keep the nodes of the lower side
    (facets,) = new.facets_on([112])
    assert facets.conn.max() < mesh.n_nodes
    # the input mesh is untouched
    assert mesh.n_nodes == split.origin.size - split.n_new
    assert all(b.conn.max() < mesh.n_nodes for b in mesh.blocks)


@pytest.mark.parametrize("etype", TYPES)
def test_boundary_facets_follow_their_element(etype: str) -> None:
    mesh = two_layers(etype)
    new = split_interfaces(mesh, [112]).mesh
    centroids = new.element_centroids()
    for fb in new.facets_on([BOTTOM, TOP]):
        right_half = centroids[fb.parent_elem][:, 0] > WIDTH / 2
        touching = np.isclose(new.nodes[fb.conn][:, :, 0], WIDTH / 2)
        # a boundary edge of the right layer that ends at the interface uses the new node
        assert np.all(fb.conn[right_half][touching[right_half]] >= mesh.n_nodes)
        assert np.all(fb.conn[~right_half] < mesh.n_nodes)


@pytest.mark.parametrize("etype", TYPES)
def test_an_end_point_inside_the_body_is_not_duplicated(etype: str) -> None:
    """Only the lower half of the interface is a contact: its upper end is an interior point."""
    mesh = regioned(
        etype, (4, 4), lambda x, y: 1 if x < WIDTH / 2 else 2,
        lambda lo, hi, mid: 7 if mid[1] < HEIGHT / 2 else 8,
    )
    interface = on_line(mesh, WIDTH / 2)
    y = mesh.nodes[interface, 1]
    split = split_interfaces(mesh, [7])
    split.mesh.validate()
    duplicated = np.sort(split.origin[mesh.n_nodes :])
    np.testing.assert_array_equal(duplicated, interface[y < HEIGHT / 2 - 1e-12])
    # the end point at mid height keeps one node, and is its own partner
    tip = interface[np.isclose(y, HEIGHT / 2)]
    assert tip.size == 1 and split.partner[7][tip[0]] == tip[0]
    # opening both halves separates the layers completely
    both = split_interfaces(mesh, [7, 8])
    assert both.n_new == interface.size
    assert both.partner[7][tip[0]] >= mesh.n_nodes and both.partner[8][tip[0]] >= mesh.n_nodes


def test_a_contact_wholly_inside_opens_only_its_inner_nodes() -> None:
    """A contact that touches the boundary nowhere: both end points stay closed."""
    mesh = regioned(
        "Q4", (4, 4), lambda x, y: 1 if x < WIDTH / 2 else 2,
        lambda lo, hi, mid: 7 if 0.25 < mid[1] < 0.75 else 8,
    )
    interface = on_line(mesh, WIDTH / 2)
    split = split_interfaces(mesh, [7])
    y = mesh.nodes[split.origin[mesh.n_nodes :], 1]
    np.testing.assert_allclose(y, [0.5])
    assert interface.size == 5


def test_four_regions_meeting_at_a_point() -> None:
    quadrant = lambda x, y: 1 + (x > WIDTH / 2) + 2 * (y > HEIGHT / 2)  # noqa: E731
    mesh = regioned("Q4", (4, 4), quadrant)
    tags = np.unique(mesh.facets[-1].entity).tolist()
    centre = int(np.flatnonzero(np.all(np.isclose(mesh.nodes, [WIDTH / 2, HEIGHT / 2]), axis=1))[0])
    split = split_interfaces(mesh, tags)
    new = split.mesh
    new.validate()
    copies = np.flatnonzero(split.origin == centre)
    assert copies.size == 4  # one per region
    owners = {}
    for block in new.blocks:
        for node in copies:
            regions = np.unique(block.region[(block.conn == node).any(axis=1)])
            assert regions.size == 1
            owners[int(node)] = int(regions[0])
    assert sorted(owners.values()) == [1, 2, 3, 4] and owners[centre] == 1  # lowest keeps it
    # opening only the contact between regions 1 and 2 leaves the centre whole: the
    # elements around it are still joined through regions 3 and 4
    one = split_interfaces(mesh, [112])
    assert centre not in one.origin[mesh.n_nodes :]


def test_no_contact_and_bad_contact() -> None:
    mesh = two_layers("T3")
    same = split_interfaces(mesh, [])
    assert same.n_new == 0 and same.mesh.n_nodes == mesh.n_nodes and same.partner == {}
    assert same.mesh is not mesh
    # a boundary curve is not an interface
    with pytest.raises(MeshError, match="between two"):
        split_interfaces(mesh, [BOTTOM])
    # a tag with no facets does nothing
    assert split_interfaces(mesh, [999]).n_new == 0


def test_orphaned_contact_facet_raises_mesh_error() -> None:
    """A contact facet on nodes that no element uses is an inconsistent mesh."""
    mesh = two_layers("T3")
    mesh.nodes = np.vstack([mesh.nodes, [[5.0, 5.0], [6.0, 5.0]]])  # used by no element
    a = mesh.nodes.shape[0] - 2
    facet_type = element(mesh.blocks[0].etype).facet_type
    mesh.facets.append(FacetBlock(
        facet_type, np.array([[a, a + 1]]), np.array([777], dtype=np.int32), np.array([0]),
    ))
    with pytest.raises(MeshError, match="belongs to no element"):
        split_interfaces(mesh, [777])


def test_node_sets_and_points_are_kept() -> None:
    mesh = two_layers("Q4")
    mesh.node_sets["probe"] = np.array([0, 1, 2])
    new = split_interfaces(mesh, [112]).mesh
    np.testing.assert_array_equal(new.node_sets["probe"], [0, 1, 2])
    assert new.point_nodes == mesh.point_nodes and new.axisymmetric == mesh.axisymmetric


# ---------------------------------------------------------------------- contact term


def contact_problem(etype: str, h_c=500.0, axisymmetric: bool = False, thickness: float = 1.0):
    mesh = two_layers(etype, cells=(8, 2))
    mesh.axisymmetric = axisymmetric
    split = split_interfaces(mesh, [112])
    dofs = DofMap()
    dofs.add_field("T", split.mesh.n_nodes)
    regions = {
        1: RegionData(Material("a", 50.0, 7800.0, 500.0), thickness, 0.0, "a"),
        2: RegionData(Material("b", 5.0, 7800.0, 500.0), thickness, 0.0, "b"),
    }
    problem = CompiledProblem(
        mesh=split.mesh, dofs=dofs, regions=regions,
        named_entities={"interface": (1, [112]), "left": (1, [LEFT]), "right": (1, [RIGHT])},
    )
    problem.cache[PARTNERS] = split.partner
    conduction = ConductionTerm()
    conduction.setup(problem)
    problem.terms.append(conduction)
    term = ContactTerm(Contact("gap", "interface", conductance=h_c))
    term.setup(problem)
    problem.terms.append(term)
    return problem, term


def state(problem: CompiledProblem, u: np.ndarray, t: float = 0.0) -> State:
    return State(u=u, u_prev=u, t=t, dt=None, dofs=problem.dofs)


@pytest.mark.parametrize("etype", TYPES)
def test_contact_matrix(etype: str) -> None:
    h_c = 500.0
    problem, term = contact_problem(etype, h_c, thickness=0.3)
    n = problem.dofs.n_dofs
    asm = Assembler(n)
    term.conductance(state(problem, np.zeros(n)), asm)
    K = asm.matrix().toarray()
    np.testing.assert_allclose(K, K.T, atol=1e-12)
    # no heat for a uniform temperature, nor when both sides are equal
    np.testing.assert_allclose(K @ np.full(n, 321.0), 0.0, atol=1e-9)
    # a jump of 1 K: the heat leaving side A is h_c times the interface area
    partner = problem.cache[PARTNERS][112]
    side_a = np.flatnonzero(partner >= 0)
    u = np.zeros(n)
    u[side_a] = 1.0
    area = HEIGHT * 0.3
    assert (K @ u)[side_a].sum() == pytest.approx(h_c * area, rel=1e-12)
    assert (K @ u)[partner[side_a]].sum() == pytest.approx(-h_c * area, rel=1e-12)
    assert term.heat_across(state(problem, u)) == pytest.approx(h_c * area, rel=1e-12)
    # rows of DOFs away from the interface are empty
    others = np.setdiff1d(np.arange(n), np.concatenate([side_a, partner[side_a]]))
    assert not K[others].any() and not K[:, others].any()


@pytest.mark.parametrize("etype", TYPES)
def test_series_resistance_with_contact(etype: str) -> None:
    """The V-35 arrangement on a hand-built mesh: jump = q / h_c."""
    h_c, T0, TL = 500.0, 400.0, 300.0
    problem, term = contact_problem(etype, h_c)
    attach(problem, FixedTemperature("hot", "left", T=T0))
    attach(problem, FixedTemperature("cold", "right", T=TL))
    result = steady_solution(problem)
    assert result.iterations == 1  # linear
    q = (T0 - TL) / (1.0 / 50.0 + 1.0 / h_c + 1.0 / 5.0)
    partner = problem.cache[PARTNERS][112]
    side_a = np.flatnonzero(partner >= 0)
    np.testing.assert_allclose(result.T[side_a], T0 - q / 50.0, rtol=1e-12)
    np.testing.assert_allclose(result.T[side_a] - result.T[partner[side_a]], q / h_c, rtol=1e-10)
    assert term.heat_across(state(problem, result.T)) == pytest.approx(q * HEIGHT, rel=1e-10)
    assert term.results(state(problem, result.T))["contact_heat:gap"][0] == pytest.approx(
        q * HEIGHT, rel=1e-10
    )
    balance = energy_balance(problem, result.T, system=result.system)
    assert balance.flows["hot"] == pytest.approx(q * HEIGHT, rel=1e-10)
    assert "gap" not in balance.flows  # heat inside the body is not a boundary flow
    assert abs(balance.relative_imbalance) < 1e-8


def test_axisymmetric_contact_uses_the_radius() -> None:
    problem, term = contact_problem("Q4", 500.0, axisymmetric=True)
    n = problem.dofs.n_dofs
    partner = problem.cache[PARTNERS][112]
    side_a = np.flatnonzero(partner >= 0)
    u = np.zeros(n)
    u[side_a] = 1.0
    area = 2.0 * np.pi * (WIDTH / 2) * HEIGHT  # a cylinder of radius 1 and height 1
    assert term.heat_across(state(problem, u)) == pytest.approx(500.0 * area, rel=1e-12)


def test_conductance_function_rules() -> None:
    problem, term = contact_problem("Q4", Expression("100 + 10*t"))
    assert term.is_time_dependent and term.is_linear and term.symmetric
    partner = problem.cache[PARTNERS][112]
    u = np.zeros(problem.dofs.n_dofs)
    u[np.flatnonzero(partner >= 0)] = 1.0
    assert term.heat_across(state(problem, u, t=5.0)) == pytest.approx(150.0 * HEIGHT)
    with pytest.raises(ModelError, match="cannot depend on temperature"):
        ContactTerm(Contact("gap", "interface", conductance=Expression("100 + T")))


def test_contact_needs_an_opened_mesh() -> None:
    problem, _ = contact_problem("Q4")
    problem.cache.pop(PARTNERS)
    term = ContactTerm(Contact("gap", "interface", conductance=10.0))
    with pytest.raises(ModelError, match="not opened"):
        term.setup(problem)
    problem.named_entities["nothing"] = (1, [999])
    problem.cache[PARTNERS] = {999: np.full(problem.mesh.n_nodes, -1)}
    with pytest.raises(ModelError, match="no element edges"):
        ContactTerm(Contact("gap", "nothing", conductance=10.0)).setup(problem)
