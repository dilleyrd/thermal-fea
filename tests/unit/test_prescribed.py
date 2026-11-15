"""M3.4 — prescribed temperatures (Theory §4)."""

from __future__ import annotations

import logging

import numpy as np
import pytest
from handmade import TYPES, make_problem

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Expression, Table
from thermalfea.model.bcs import FixedTemperature
from thermalfea.physics.prescribed import FixedTemperatureConstraint
from thermalfea.solver.compile import attach
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.terms import Constraint

W, H = 2.0, 1.0


@pytest.mark.parametrize("etype", TYPES)
def test_nodes_of_a_curve_selection(etype: str) -> None:
    problem = make_problem(etype, bcs=(FixedTemperature("base", "bottom", T=373.15),))
    (c,) = problem.constraints
    assert isinstance(c, FixedTemperatureConstraint) and isinstance(c, Constraint)
    assert not c.is_time_dependent and c.breakpoints() == []
    nodes = problem.mesh.nodes
    expected = np.flatnonzero(np.isclose(nodes[:, 1], 0.0))
    np.testing.assert_array_equal(c.nodes, expected)  # corners and mid-side nodes, once each
    idx, vals = problem.prescribed(0.0)
    np.testing.assert_array_equal(idx, problem.dofs.node_dofs("T", expected))
    np.testing.assert_array_equal(vals, 373.15)
    assert len(problem.terms) == 1  # a fixed temperature adds no term


def test_point_selection() -> None:
    problem = make_problem("Q8")
    problem.named_entities["corners"] = (0, [1, 3])  # lower-left and upper-right
    attach(problem, FixedTemperature("pin", "corners", T=300.0))
    idx, vals = problem.prescribed(0.0)
    np.testing.assert_allclose(problem.mesh.nodes[idx], [[0.0, 0.0], [W, H]])
    np.testing.assert_array_equal(vals, [300.0, 300.0])
    problem.named_entities["ghost"] = (0, [99])
    with pytest.raises(ModelError, match="pin2: point.*99.*no mesh node"):
        attach(problem, FixedTemperature("pin2", "ghost", T=300.0))


@pytest.mark.parametrize("etype", TYPES)
def test_temperature_as_a_function_of_time_and_position(etype: str) -> None:
    bc = FixedTemperature("wall", "right", T=Expression("300 + 50*y + 10*t + x"))
    problem = make_problem(etype, bcs=(bc,))
    (c,) = problem.constraints
    assert c.is_time_dependent and problem.is_time_dependent
    idx, vals = problem.prescribed(3.0)
    y = problem.mesh.nodes[idx, 1]
    np.testing.assert_allclose(vals, 300.0 + 50.0 * y + 30.0 + W, rtol=1e-14)
    ramp = Table([0, 40], [273, 373], "t")
    table = make_problem(etype, bcs=(FixedTemperature("w", "left", T=ramp),))
    assert table.constraints[0].breakpoints() == [0.0, 40.0]
    assert table.breakpoints() == [0.0, 40.0]
    np.testing.assert_allclose(table.prescribed(10.0)[1], 298.0)


def test_conflict_at_a_shared_node_later_bc_wins_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    problem = make_problem("Q4", bcs=(
        FixedTemperature("bottom-hot", "bottom", T=400.0),
        FixedTemperature("left-cold", "left", T=300.0),
    ))
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        idx, vals = problem.prescribed(0.0)
    nodes = problem.mesh.nodes[idx]
    corner = np.all(np.isclose(nodes, 0.0), axis=1)
    assert corner.sum() == 1
    assert vals[corner][0] == 300.0  # the later condition in the list wins
    on_bottom = np.isclose(nodes[:, 1], 0.0) & ~corner
    assert np.all(vals[on_bottom] == 400.0)
    assert np.unique(idx).size == idx.size
    messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(messages) == 1
    assert "'left-cold'" in messages[0] and "'bottom-hot'" in messages[0]
    assert "1 shared" in messages[0] and "wins" in messages[0]

    # equal values at the shared node are not a conflict
    same = make_problem("Q4", bcs=(
        FixedTemperature("a", "bottom", T=350.0), FixedTemperature("b", "left", T=350.0)))
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="thermalfea"):
        same.prescribed(0.0)
    assert not caplog.records


def test_errors_and_inactive() -> None:
    with pytest.raises(ModelError, match="cannot depend on T"):
        make_problem("Q4", bcs=(FixedTemperature("bad", "bottom", T=Expression("T + 1")),))
    with pytest.raises(ModelError, match="fix: selection 'all' has dimension 2"):
        make_problem("Q4", bcs=(FixedTemperature("fix", "all", T=300.0),))
    problem = make_problem("Q4", bcs=(FixedTemperature("off", "bottom", T=300.0, active=False),))
    assert problem.constraints == [] and problem.prescribed(0.0)[0].size == 0
    problem.named_entities["nowhere"] = (1, [42])
    with pytest.raises(ModelError, match="contains no mesh nodes"):
        attach(problem, FixedTemperature("fix", "nowhere", T=300.0))


def test_through_compile_on_a_gmsh_mesh() -> None:
    model = api.new_model()
    api.Geometry(model).rectangle(0.0, 0.0, 0.6, 1.0)
    model.mesh_settings.global_size = 0.1
    model.mesh_settings.order = 2
    built = api.build(model)
    api.select_curves(model, built, "bottom", where=lambda c: abs(c.center[1]) < 1e-9)
    api.select_points(model, built, "top-right", where=lambda p: p.center[0] + p.center[1] > 1.59)
    api.assign_region(model, "all", material="Carbon steel AISI 1010")
    model.bcs += [
        FixedTemperature("base", "bottom", T=373.15),
        FixedTemperature("probe", "top-right", T=Expression("300 + t")),
    ]
    mesh = api.mesh(model, built)
    problem = compile_problem(model, built, mesh)
    assert [c.name for c in problem.constraints] == ["base", "probe"]
    idx, vals = problem.prescribed(5.0)
    xy = mesh.nodes[idx]
    on_bottom = np.isclose(xy[:, 1], 0.0)
    assert on_bottom.sum() == np.count_nonzero(np.isclose(mesh.nodes[:, 1], 0.0)) == idx.size - 1
    np.testing.assert_array_equal(vals[on_bottom], 373.15)
    np.testing.assert_allclose(xy[~on_bottom], [[0.6, 1.0]], atol=1e-12)
    assert vals[~on_bottom][0] == 305.0
