"""Mesh and solution settings (Data §3, §10)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from ..core.errors import ModelError


def _choice(value: object, allowed: tuple, what: str) -> None:
    if value not in allowed:
        raise ModelError(f"{what} must be one of {', '.join(map(str, allowed))}; got {value!r}")


@dataclass
class Refinement:
    """Distance-based mesh refinement near a selection.

    Parameters
    ----------
    selection : str
        Name of a curve or point selection.
    size_min : float
        Element size [m] within ``dist_min`` of the selection.
    size_max : float
        Element size [m] beyond ``dist_max``.
    dist_min, dist_max : float
        Distances [m] between which the size grows linearly.
    """

    selection: str
    size_min: float
    size_max: float
    dist_min: float
    dist_max: float


@dataclass
class MeshSettings:
    """Meshing controls.

    Parameters
    ----------
    global_size : float
        Target element size [m].
    order : {1, 2}
        Element order.
    element_shape : {"tri", "quad"}
        Triangles or quad-dominant.
    algorithm : {"delaunay", "frontal", "frontal_quad"}
        Free-meshing algorithm.
    curve_sizes, point_sizes : dict of str to float
        Selection name -> element size [m].
    curve_divisions : dict of str to int
        Selection name -> number of elements along a transfinite curve.
    structured_surfaces : list of str
        Surface selections to mesh transfinite.
    refinements : list of Refinement
        Distance-based refinements.
    smoothing_passes : int
        Number of mesh smoothing passes.
    """

    global_size: float
    order: Literal[1, 2] = 1
    element_shape: Literal["tri", "quad"] = "tri"
    algorithm: Literal["delaunay", "frontal", "frontal_quad"] = "frontal"
    curve_sizes: dict[str, float] = field(default_factory=dict)
    point_sizes: dict[str, float] = field(default_factory=dict)
    curve_divisions: dict[str, int] = field(default_factory=dict)
    structured_surfaces: list[str] = field(default_factory=list)
    refinements: list[Refinement] = field(default_factory=list)
    smoothing_passes: int = 3

    def __post_init__(self) -> None:
        if not self.global_size > 0.0:
            raise ModelError("mesh global_size must be positive")
        _choice(self.order, (1, 2), "mesh order")
        _choice(self.element_shape, ("tri", "quad"), "element_shape")
        _choice(self.algorithm, ("delaunay", "frontal", "frontal_quad"), "mesh algorithm")


@dataclass
class SolutionSettings:
    """Solver controls (Data §10). Times in seconds, temperatures in kelvin.

    Parameters
    ----------
    kind : {"steady", "transient"}
    end_time : float
        End time [s] of a transient analysis.
    initial_dt : float, optional
        First time step [s]; ``None`` uses the Theory §6.1 suggestion.
    dt_min : float
        Smallest allowed time step [s].
    dt_max : float, optional
        Largest allowed time step [s].
    auto_timestep : bool
        Adapt the time step to the error estimate.
    time_tol : float
        Relative tolerance of the time-stepping error estimate.
    max_dT_per_step : float, optional
        Largest temperature change per step [K].
    theta : float
        Time-integration parameter (1 backward Euler, 0.5 Crank-Nicolson).
    lumped_capacitance : bool
        Use the lumped capacitance matrix.
    output : {"all", "every_n", "times"}
        Which steps are stored.
    output_every : int
        Store every n-th step when ``output == "every_n"``.
    output_times : list of float
        Times [s] stored when ``output == "times"``.
    rtol : float
        Relative residual tolerance of the nonlinear iteration.
    ttol : float
        Temperature-increment tolerance of the nonlinear iteration.
    max_iterations : int
        Largest number of nonlinear iterations per step.
    line_search : bool
        Use a line search in the nonlinear iteration.
    """

    kind: Literal["steady", "transient"] = "steady"
    end_time: float = 1.0
    initial_dt: float | None = None
    dt_min: float = 1e-9
    dt_max: float | None = None
    auto_timestep: bool = True
    time_tol: float = 0.02
    max_dT_per_step: float | None = None
    theta: float = 1.0
    lumped_capacitance: bool = False
    output: Literal["all", "every_n", "times"] = "all"
    output_every: int = 1
    output_times: list[float] = field(default_factory=list)
    rtol: float = 1e-6
    ttol: float = 1e-4
    max_iterations: int = 30
    line_search: bool = True

    def __post_init__(self) -> None:
        _choice(self.kind, ("steady", "transient"), "solution kind")
        _choice(self.output, ("all", "every_n", "times"), "output")
        if not 0.0 < self.theta <= 1.0:
            raise ModelError("theta must be in (0, 1]")
        if self.output_every < 1:
            raise ModelError("output_every must be at least 1")
        if self.max_iterations < 1:
            raise ModelError("max_iterations must be at least 1")
