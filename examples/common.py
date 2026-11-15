"""Helpers shared by the verification examples.

Every ``examples/vNN_*.py`` script builds its model through the public API, solves it and
compares with the analytic answer of ``docs/verification.md``. Each has a
``run(etype) -> dict`` function (used by the tests) and prints a table when run as a
script::

    .venv\\Scripts\\python.exe examples\\v01_slab.py
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy import ndarray

from thermalfea import api
from thermalfea.core.mesh import Mesh
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.materials.material import Material
from thermalfea.model.model import Model
from thermalfea.post.results import Results

# Defaults of docs/verification.md: k = 50 W/(m K), rho = 7800 kg/m^3, c = 500 J/(kg K)
K, RHO, CP = 50.0, 7800.0, 500.0

#: Element type -> (element shape, order) of the mesh settings.
ELEMENT_TYPES = {"T3": ("tri", 1), "Q4": ("quad", 1), "T6": ("tri", 2), "Q8": ("quad", 2)}
LINEAR = ("T3", "Q4")


@dataclass
class Case:
    """A solved verification model."""

    model: Model
    built: BuiltGeometry
    mesh: Mesh
    results: Results

    @property
    def nodes(self) -> ndarray:
        """Node coordinates [m]."""
        return self.mesh.nodes

    @property
    def T(self) -> ndarray:
        """Nodal temperatures of the last step [K]."""
        return self.results.temperature()

    def heat(self, name: str) -> float:
        """Heat entering the body through a boundary condition at the last step [W]."""
        return float(self.results.heat_flow(name)[-1])

    @property
    def imbalance(self) -> float:
        """Relative energy imbalance of the last step (V-34)."""
        return float(self.results.energy_balance()["relative_imbalance"][-1])

    @property
    def iterations(self) -> int:
        """Iterations of the last step."""
        return int(self.results.iterations[-1])

    def node_at(self, x: float, y: float) -> int:
        """Index of the node located at ``(x, y)``; the mesh must have one there."""
        distance = np.linalg.norm(self.nodes - [x, y], axis=1)
        node = int(np.argmin(distance))
        if distance[node] > 1e-9 * max(1.0, self.built.diagonal):
            raise ValueError(f"no node at ({x}, {y}); the nearest is {distance[node]:.3g} m away")
        return node

    def flux(self) -> dict[int, tuple[ndarray, ndarray]]:
        """Nodal flux per region at the last step [W/m^2]."""
        return self.results.flux()

    def max_relative_error(self, exact: ndarray, nodes: ndarray | None = None) -> float:
        """Largest relative error of the nodal temperatures against ``exact``."""
        T = self.T if nodes is None else self.T[nodes]
        return float(np.max(np.abs(T - exact) / np.abs(exact)))

    # ------------------------------------------------------------------- transient

    def step_at(self, time: float) -> int:
        """Index of the stored step at ``time`` [s]; a step must have been stored there."""
        times = self.results.times
        step = int(np.argmin(np.abs(times - time)))
        if abs(times[step] - time) > 1e-9 * max(1.0, abs(time)):
            raise ValueError(f"no stored step at t = {time} s; the nearest is at {times[step]} s")
        return step

    def T_at(self, time: float) -> ndarray:
        """Nodal temperatures [K] at the stored step at ``time`` [s]."""
        return self.results.temperature(self.step_at(time))

    @property
    def worst_imbalance(self) -> float:
        """Largest relative energy imbalance over all steps (V-34)."""
        values = self.results.energy_balance()["relative_imbalance"]
        values = values[np.isfinite(values)]
        return float(np.abs(values).max()) if values.size else 0.0

    @property
    def n_steps(self) -> int:
        """Number of time steps taken (stored steps minus the initial state)."""
        return int(self.results.n_steps - 1)


def transient(model: Model, initial: float, **settings) -> None:
    """Make a model transient with a uniform initial temperature [K].

    ``settings`` are fields of ``SolutionSettings`` (``end_time``, ``theta``,
    ``initial_dt``, ``auto_timestep``, ``output_times``, ...).
    """
    from thermalfea.core.functions import Constant
    from thermalfea.model.model import InitialCondition
    from thermalfea.model.settings import SolutionSettings

    model.initial_condition = InitialCondition("uniform", value=Constant(initial))
    model.solution = SolutionSettings(kind="transient", **settings)


def set_element_type(model: Model, etype: str) -> None:
    """Choose the element shape and order of the mesh for an element type name."""
    shape, order = ELEMENT_TYPES[etype]
    model.mesh_settings.element_shape = shape
    model.mesh_settings.order = order


def add_material(
    model: Model, name: str = "solid", k=K, rho=RHO, cp=CP, k2=None
) -> str:
    """Add a material with the given properties to the model and return its name."""
    model.materials[name] = Material(name, k, rho, cp, k2=k2)
    return name


def select_sides(
    model: Model, built: BuiltGeometry, x0: float, y0: float, x1: float, y1: float
) -> None:
    """Name the curves on the sides of a box ``left``, ``right``, ``bottom`` and ``top``."""
    tol = 1e-9 * max(1.0, built.diagonal)

    def on(axis: int, value: float) -> Callable:
        lo, hi = axis, axis + 3
        return lambda c: abs(c.bbox[lo] - value) < 1e-6 and abs(c.bbox[hi] - value) < 1e-6 + tol

    api.select_curves(model, built, "left", where=on(0, x0))
    api.select_curves(model, built, "right", where=on(0, x1))
    api.select_curves(model, built, "bottom", where=on(1, y0))
    api.select_curves(model, built, "top", where=on(1, y1))


def structured(model: Model, nx: int, ny: int) -> None:
    """Mesh the single rectangle of the model with ``nx`` by ``ny`` cells (transfinite)."""
    settings = model.mesh_settings
    settings.curve_divisions = {"bottom": nx, "top": nx, "left": ny, "right": ny}
    settings.structured_surfaces = ["all"]


def solve(model: Model, built: BuiltGeometry) -> Case:
    """Mesh and solve a model whose geometry has been built."""
    mesh = api.mesh(model, built)
    return Case(model, built, mesh, api.solve(model, mesh, built=built))


def rectangle(
    name: str,
    etype: str,
    x0: float,
    y0: float,
    width: float,
    height: float,
    nx: int,
    ny: int,
    analysis: str = "planar",
    thickness: float = 1.0,
    **material,
) -> tuple[Model, BuiltGeometry]:
    """A one-rectangle model with named sides, one material and a structured mesh.

    Boundary conditions are added by the caller, then :func:`solve` runs it. The "1D"
    cases of the verification document use a strip of length L and height L/10 whose
    long sides are left free (adiabatic).
    """
    model = api.new_model(analysis, name=name)
    api.Geometry(model).rectangle(x0, y0, width, height)
    built = api.build(model)
    select_sides(model, built, x0, y0, x0 + width, y0 + height)
    api.assign_region(model, "all", material=add_material(model, **material), thickness=thickness)
    set_element_type(model, etype)
    model.mesh_settings.global_size = max(width / nx, height / ny)
    structured(model, nx, ny)
    return model, built


def l2_error(case: Case, exact: Callable[[ndarray, ndarray], ndarray]) -> float:
    """L2 norm of the temperature error, integrated with each element's quadrature rule."""
    from thermalfea.physics.kernel import geometry

    total = 0.0
    T = case.T
    for block in case.mesh.blocks:
        geom = geometry(block, case.mesh.nodes)
        computed = np.einsum("pn,en->ep", geom.N, T[block.conn])
        reference = exact(geom.xgp[..., 0], geom.xgp[..., 1])
        total += float(((computed - reference) ** 2 * geom.dV).sum())
    return float(np.sqrt(total))


def main(
    run: Callable[[str], dict], title: str, types: tuple[str, ...] = tuple(ELEMENT_TYPES)
) -> None:
    """Run a case for every element type and print its results as a table."""
    out = sys.stdout.write
    out(f"{title}\n")
    for etype in types:
        result = run(etype)
        cells = ", ".join(
            f"{key} = {value:.3e}" if isinstance(value, float) else f"{key} = {value}"
            for key, value in result.items()
            if isinstance(value, (int, float, str))
        )
        out(f"  {etype}: {cells}\n")


def here(file: str) -> str:
    """Name of an example script without its folder and extension."""
    return Path(file).stem
