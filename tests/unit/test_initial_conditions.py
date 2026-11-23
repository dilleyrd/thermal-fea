"""M4.5 — initial conditions: all four kinds; prescribed nodes take their value at t = 0."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from handmade import make_problem

from thermalfea import api
from thermalfea.core.errors import ModelError
from thermalfea.core.functions import Expression
from thermalfea.core.mesh import ElementBlock, Mesh
from thermalfea.model.bcs import Convection, FixedTemperature
from thermalfea.model.model import InitialCondition, Model
from thermalfea.model.settings import SolutionSettings
from thermalfea.solver.compile import compile as compile_problem
from thermalfea.solver.initial import (
    DEFAULT_INITIAL_TEMPERATURE,
    _per_region,
    initial_temperature,
    nodal_initial_temperature,
)
from thermalfea.solver.transient import initial_state, solve_transient


def two_regions(order: int = 1) -> tuple[Model, object, object]:
    model = api.new_model(name="two regions")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, 0.4, 0.5, id="left")
    geo.rectangle(0.4, 0.0, 0.6, 0.5, id="right")
    model.mesh_settings.global_size = 0.1
    model.mesh_settings.order = order
    built = api.build(model)
    api.select_surfaces(model, built, "L", where=lambda s: s.center[0] < 0.4)
    api.select_surfaces(model, built, "R", where=lambda s: s.center[0] > 0.4)
    api.select_curves(model, built, "west", where=lambda c: abs(c.center[0]) < 1e-9)
    api.select_curves(model, built, "east", where=lambda c: abs(c.center[0] - 1.0) < 1e-9)
    api.assign_region(model, "L", material="Copper (pure)")
    api.assign_region(model, "R", material="Silicon")
    model.solution = SolutionSettings(kind="transient", end_time=50.0, initial_dt=10.0,
                                      auto_timestep=False)
    return model, built, api.mesh(model, built)


def problem_with(ic: InitialCondition, bcs=()):
    model, built, mesh = two_regions()
    model.initial_condition = ic
    model.bcs += list(bcs)
    return compile_problem(model, built, mesh), mesh


def test_per_region_counts_a_region_once_per_node_across_its_blocks() -> None:
    """Region A has a Q4 and a T3 block that share nodes 1 and 2; B is a T3 next to them.

    Node 2 lies in all three blocks, so a per-block count would give (400+400+300)/3.
    """
    nodes = np.array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [2.0, 0.0], [2.0, 1.0]])
    blocks = [
        ElementBlock("Q4", np.array([[0, 1, 2, 3]]), np.array([1], np.int32), np.array([0])),
        ElementBlock("T3", np.array([[1, 4, 2]]), np.array([1], np.int32), np.array([1])),
        ElementBlock("T3", np.array([[4, 5, 2]]), np.array([2], np.int32), np.array([2])),
    ]
    mesh = Mesh(dim=2, nodes=nodes, blocks=blocks)
    tags = {"A": [1], "B": [2]}
    problem = SimpleNamespace(
        mesh=mesh, selection_tags=lambda name, dims: (name, tags[name])
    )
    T = _per_region(problem, {"A": 400.0, "B": 300.0})
    np.testing.assert_array_equal(T[2], 350.0)  # the interface node: (T_A + T_B) / 2
    np.testing.assert_array_equal(T[4], 350.0)
    np.testing.assert_array_equal(T[[0, 1, 3]], 400.0)
    np.testing.assert_array_equal(T[5], 300.0)


def test_uniform() -> None:
    problem, mesh = problem_with(InitialCondition("uniform", value=350.0))
    T = initial_temperature(problem)
    assert T.shape == (problem.dofs.n_dofs,)
    np.testing.assert_array_equal(T, 350.0)
    np.testing.assert_array_equal(
        nodal_initial_temperature(problem, InitialCondition("uniform", value=1.5)), 1.5
    )


def test_expression_of_position() -> None:
    ic = InitialCondition("expression", value=Expression("300 + 100*x + 50*y"))
    problem, mesh = problem_with(ic)
    x, y = mesh.nodes.T
    np.testing.assert_allclose(initial_temperature(problem), 300.0 + 100.0 * x + 50.0 * y)


def test_per_region() -> None:
    both = InitialCondition("per_region", per_region={"L": 400.0, "R": 300.0})
    problem, mesh = problem_with(both)
    T = initial_temperature(problem)
    x = mesh.nodes[:, 0]
    np.testing.assert_array_equal(T[x < 0.4 - 1e-9], 400.0)
    np.testing.assert_array_equal(T[x > 0.4 + 1e-9], 300.0)
    # a node on the interface belongs to both regions and takes their mean
    np.testing.assert_array_equal(T[np.isclose(x, 0.4)], 350.0)
    assert np.isclose(x, 0.4).sum() >= 2

    only_left = InitialCondition("per_region", per_region={"L": 400.0})
    with pytest.raises(ModelError, match="no temperature for region"):
        initial_temperature(problem_with(only_left)[0])
    with pytest.raises(ModelError, match="unknown selection"):
        initial_temperature(
            problem_with(InitialCondition("per_region", per_region={"L": 1.0, "nope": 2.0}))[0]
        )
    with pytest.raises(ModelError, match="dimension 1"):
        initial_temperature(
            problem_with(InitialCondition("per_region", per_region={"west": 1.0}))[0]
        )


def test_from_results(tmp_path: Path) -> None:
    """The last step of an earlier run becomes the start of the next one."""
    model, built, mesh = two_regions()
    model.initial_condition = InitialCondition("uniform", value=400.0)
    model.bcs.append(Convection("cool", "east", h=500.0, T_inf=300.0))
    first = api.solve(model, mesh, built=built, path=tmp_path / "first.h5")
    end_state = first.temperature()
    assert end_state.min() < 400.0

    model.initial_condition = InitialCondition("from_results", results_path=str(first.path))
    problem = compile_problem(model, built, mesh)
    np.testing.assert_array_equal(initial_temperature(problem), end_state)
    second = api.solve(model, mesh, built=built, path=tmp_path / "second.h5")
    np.testing.assert_array_equal(second.temperature(0), end_state)
    assert second.temperature().min() < end_state.min()  # the cooling continued

    # running 50 s + 50 s equals one run of 100 s (linear problem, backward Euler)
    model.initial_condition = InitialCondition("uniform", value=400.0)
    model.solution.end_time = 100.0
    whole = api.solve(model, mesh, built=built, path=tmp_path / "whole.h5")
    np.testing.assert_allclose(second.temperature(), whole.temperature(), rtol=1e-12)


def test_from_results_needs_the_same_mesh(tmp_path: Path) -> None:
    model, built, mesh = two_regions()
    model.bcs.append(Convection("cool", "east", h=500.0, T_inf=300.0))
    first = api.solve(model, mesh, built=built, path=tmp_path / "first.h5")
    model.mesh_settings.global_size = 0.05
    finer = api.mesh(model, built)
    model.initial_condition = InitialCondition("from_results", results_path=str(first.path))
    with pytest.raises(ModelError, match="different mesh"):
        initial_temperature(compile_problem(model, built, finer))
    model.initial_condition = InitialCondition("from_results", results_path=str(tmp_path / "x.h5"))
    with pytest.raises(ModelError, match="not found"):
        initial_temperature(compile_problem(model, built, mesh))
    model.initial_condition = InitialCondition("from_results")
    with pytest.raises(ModelError, match="needs a results file"):
        initial_temperature(compile_problem(model, built, mesh))


def test_incomplete_initial_conditions() -> None:
    for ic, message in (
        (InitialCondition("uniform"), "needs a value"),
        (InitialCondition("expression"), "needs a value"),
        (InitialCondition("per_region"), "needs a temperature per region"),
        (InitialCondition("uniform", value=Expression("T")), "cannot depend on T"),
        (InitialCondition("expression", value=Expression("log(x - 5)")), "non-finite"),
    ):
        with pytest.raises(ModelError, match=message):
            initial_temperature(problem_with(ic)[0])


def test_prescribed_nodes_take_their_boundary_value_at_t0() -> None:
    ic = InitialCondition("per_region", per_region={"L": 400.0, "R": 300.0})
    wall = FixedTemperature("wall", "west", T=Expression("500 + 10*t"))
    problem, mesh = problem_with(ic, [wall])
    x = mesh.nodes[:, 0]
    T, shock = initial_state(problem, None, 0.0)
    np.testing.assert_array_equal(T[np.isclose(x, 0.0)], 500.0)  # the BC value at t = 0
    np.testing.assert_array_equal(T[(x > 1e-9) & (x < 0.4 - 1e-9)], 400.0)  # the rest is the IC
    assert shock is True  # 400 K initial against 500 K prescribed: a jump at the start
    T7, _ = initial_state(problem, None, 7.0)
    np.testing.assert_array_equal(T7[np.isclose(x, 0.0)], 570.0)
    # no jump when the initial condition already agrees with the prescribed value
    agree = FixedTemperature("wall", "west", T=400.0)
    _, calm = initial_state(problem_with(ic, [agree])[0], None, 0.0)
    assert calm is False
    # and the transient run starts from that state
    result = solve_transient(problem)
    np.testing.assert_array_equal(result.temperatures[0], T)
    np.testing.assert_allclose(result.T[np.isclose(x, 0.0)], 500.0 + 10.0 * 50.0)


def test_problem_without_a_model_uses_the_default_or_an_explicit_state() -> None:
    problem = make_problem("Q4")
    np.testing.assert_array_equal(initial_temperature(problem), DEFAULT_INITIAL_TEMPERATURE)
    T, _ = initial_state(problem, 321.0, 0.0)
    np.testing.assert_array_equal(T, 321.0)


def test_new_model_default_is_uniform_20_degc() -> None:
    model, built, mesh = two_regions()
    np.testing.assert_array_equal(
        initial_temperature(compile_problem(model, built, mesh)), 293.15
    )
