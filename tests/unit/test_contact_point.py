"""M11.36 — a fixed temperature on a point at the end of a contact curve fixes both sides.

Owner's decision D12.6 (Q29.12), changing Q22.5: the contact split copies the node at the
end of the contact curve, and both copies are prescribed.
"""

from __future__ import annotations

import numpy as np
import pytest

from thermalfea import api
from thermalfea.model.bcs import Contact, FixedTemperature
from thermalfea.solver.compile import compile as compile_problem

TOL = 1e-9


def stacked_plates(with_contact: bool = True):
    """Two 1 x 0.5 plates, one on the other, with a contact on the shared curve."""
    model = api.new_model(name="stacked")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 1.0, 0.5, id="lower")
    geo.rectangle(0.0, 0.5, 1.0, 0.5, id="upper")
    model.mesh_settings.global_size = 0.25
    built = api.build(model)
    api.select_surfaces(model, built, "all", where=lambda s: True)
    api.select_curves(model, built, "joint", where=lambda c: abs(c.center[1] - 0.5) < TOL)
    api.select_curves(model, built, "top", where=lambda c: abs(c.center[1] - 1.0) < TOL)
    api.select_points(
        model, built, "corner",
        where=lambda p: abs(p.center[0]) < TOL and abs(p.center[1] - 0.5) < TOL,
    )
    api.assign_region(model, "all", material="Copper (pure)")
    if with_contact:
        model.contacts.append(Contact("gap", "joint", conductance=500.0))
    model.bcs.append(FixedTemperature("pin", "corner", T=350.0))
    model.bcs.append(FixedTemperature("cold", "top", T=300.0))
    return model, built, api.mesh(model, built)


def test_both_copies_of_the_end_node_are_prescribed() -> None:
    model, built, mesh = stacked_plates()
    problem = compile_problem(model, built, mesh)
    nodes = problem.mesh.nodes
    at_corner = np.flatnonzero(np.hypot(nodes[:, 0], nodes[:, 1] - 0.5) < TOL)
    assert at_corner.size == 2  # the contact split copied the end node
    idx, values = problem.prescribed(0.0)
    dofs = problem.dofs.node_dofs("T", at_corner)
    assert set(dofs) <= set(idx)
    np.testing.assert_allclose(values[np.isin(idx, dofs)], 350.0)


def test_both_sides_are_held_in_the_solution() -> None:
    model, built, mesh = stacked_plates()
    results = api.solve(model, mesh, built=built)
    nodes, T = results.mesh.nodes, results.temperature()
    at_corner = np.hypot(nodes[:, 0], nodes[:, 1] - 0.5) < TOL
    assert at_corner.sum() == 2
    np.testing.assert_allclose(T[at_corner], 350.0)


def test_a_point_away_from_a_contact_fixes_one_node() -> None:
    model, built, mesh = stacked_plates(with_contact=False)
    problem = compile_problem(model, built, mesh)
    pin = next(c for c in problem.constraints if c.name == "pin")
    assert pin.nodes.size == 1
    assert problem.mesh.nodes[pin.nodes[0], :2] == pytest.approx((0.0, 0.5))
