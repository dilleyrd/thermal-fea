"""Boundary conditions, enclosures, contacts, streams and flow networks (Data §8).

All values are SI with temperatures in kelvin. Every field typed ``Function`` also accepts
a bare number, which becomes a :class:`~thermalfea.core.functions.Constant`.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from typing import Literal, get_type_hints

from ..core import registry
from ..core.errors import ModelError
from ..core.functions import Function, as_function
from .bc_forms import BC_FORMS


def _choice(value: object, allowed: tuple, what: str) -> None:
    if value not in allowed:
        raise ModelError(f"{what} must be one of {', '.join(map(str, allowed))}; got {value!r}")


def coerce_functions(obj: object) -> None:
    """Wrap bare numbers in the ``Function``-typed fields of a dataclass instance."""
    hints = get_type_hints(type(obj))
    for f in dataclasses.fields(obj):  # type: ignore[arg-type]
        hint = hints[f.name]
        value = getattr(obj, f.name)
        if hint is Function or (hint == (Function | None) and value is not None):
            setattr(obj, f.name, as_function(value))


# ---------------------------------------------------------------- boundary conditions


@dataclass
class BoundaryCondition:
    """Base class of all boundary conditions and loads.

    Parameters
    ----------
    name : str
        Name of the condition, unique in the model.
    selection : str
        Name of the selection it applies to.
    active : bool, keyword-only
        Inactive conditions are ignored by the solver.
    """

    name: str
    selection: str
    active: bool = field(default=True, kw_only=True)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ModelError("boundary condition name must be a non-empty string")
        coerce_functions(self)


@dataclass
class FixedTemperature(BoundaryCondition):
    """Prescribed temperature ``T`` [K] on curves or points."""

    T: Function


@dataclass
class HeatFlux(BoundaryCondition):
    """Heat flux ``q`` [W/m^2] on curves, positive into the body."""

    q: Function


@dataclass
class HeatFlow(BoundaryCondition):
    """Total heat flow ``P`` [W] spread uniformly over curves, positive into the body."""

    P: Function


@dataclass
class HeatGeneration(BoundaryCondition):
    """Volumetric heat generation ``Q`` [W/m^3] in surfaces."""

    Q: Function


@dataclass
class HeatPower(BoundaryCondition):
    """Total power ``P`` [W] generated uniformly in surfaces."""

    P: Function


@dataclass
class Convection(BoundaryCondition):
    """Convection with coefficient ``h`` [W/(m^2 K)] to a fluid at ``T_inf`` [K]."""

    h: Function
    T_inf: Function


@dataclass
class CorrelationConvection(BoundaryCondition):
    """Convection whose coefficient comes from a correlation (Theory §8).

    Parameters
    ----------
    correlation : str
        Correlation identifier from Theory §8.
    fluid : str
        Name of a library fluid.
    T_inf : Function
        Fluid temperature [K].
    velocity : Function, optional
        Free-stream velocity [m/s], for forced-convection correlations.
    char_length : float, optional
        Characteristic length [m]; when ``None``, the total length of the selection (half
        of it for the horizontal plates, where L_c = A_s/P).
    face_direction : {"up", "down"}, optional
        Orientation of a horizontal plate; chosen automatically when ``None``.
    wall_T_mode : {"local", "average"}
        Wall temperature used for the film properties.
    multiplier : float
        Factor applied to the computed coefficient.
    params : dict of str to float
        Extra inputs of some correlations. Documented keys: ``"theta_deg"`` (inclination
        from vertical [deg], ``inclined_natural``); ``"x0"``, ``"y0"`` (leading-edge point
        [m]) and ``"dir_x"``, ``"dir_y"`` (flow direction, need not be normalised) for
        ``plate_forced_local``; ``"C"`` and ``"n"`` for ``power_law``;
        ``"S"`` (plate spacing [m]) for ``vchannel_natural`` and ``vchannel_one_side_natural``;
        ``"W"``, ``"H"``, ``"x_r"`` [m] for ``slot_jet`` (``x_r`` defaults to half the selection
        length) and ``"D"``, ``"H"``, ``"r_r"`` [m] for ``round_jet`` (``r_r`` defaults to the
        largest radial coordinate of the selection in an axisymmetric model).
    """

    correlation: str
    fluid: str
    T_inf: Function
    velocity: Function | None = None
    char_length: float | None = None
    face_direction: Literal["up", "down"] | None = None
    wall_T_mode: Literal["local", "average"] = "local"
    multiplier: float = 1.0
    params: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        _choice(self.face_direction, ("up", "down", None), "face_direction")
        _choice(self.wall_T_mode, ("local", "average"), "wall_T_mode")


@dataclass
class RadiationAmbient(BoundaryCondition):
    """Radiation from curves to surroundings at ``T_inf`` [K] with the given emissivity."""

    emissivity: Function
    T_inf: Function


@dataclass
class Symmetry(BoundaryCondition):
    """Symmetry line: documentation only, contributes nothing."""


@dataclass
class Adiabatic(BoundaryCondition):
    """Insulated boundary: documentation only, contributes nothing."""


# ----------------------------------------------------------------- enclosure, contact


@dataclass
class EnclosureSurface:
    """One radiating surface of an enclosure: a curve selection and its emissivity."""

    selection: str
    emissivity: float


@dataclass
class Enclosure:
    """Surface-to-surface radiation enclosure.

    Parameters
    ----------
    name : str
    surfaces : list of EnclosureSurface
    open_to_ambient : bool
        The enclosure has openings that see surroundings at ``T_ambient``.
    T_ambient : Function, optional
        Temperature of the surroundings [K].
    """

    name: str
    surfaces: list[EnclosureSurface]
    open_to_ambient: bool = False
    T_ambient: Function | None = None

    def __post_init__(self) -> None:
        coerce_functions(self)


@dataclass
class Contact:
    """Thermal contact with ``conductance`` [W/(m^2 K)] on interface curves."""

    name: str
    selection: str
    conductance: Function

    def __post_init__(self) -> None:
        coerce_functions(self)


# -------------------------------------------------------------------------------- flow


STREAM_CROSS_SECTIONS = (
    "circular", "parallel_plates", "parallel_plates_one_side", "square",
    "rectangle_1_43", "rectangle_2", "rectangle_3", "rectangle_4", "rectangle_8",
    "triangle", "annulus_inner", "annulus_outer",
)
"""Values of ``Stream.cross_section`` (Theory §8.1)."""
STREAM_NU_OPTIONS = ("auto", "dittus_boelter", "sieder_tate")
"""Values of ``Stream.nu_option`` (Theory §8.1)."""
_ANNULUS_RANGE = {"annulus_inner": (0.05, 1.0), "annulus_outer": (0.0, 1.0)}


def diameter_ratio_problem(stream: Stream) -> str:
    """The complaint about ``diameter_ratio`` of a stream, or ``""`` when it is consistent.

    The annulus cross-sections need D_i/D_o within their range; the other cross-sections
    refuse it (Theory §8.1).
    """
    ratio = stream.diameter_ratio
    if stream.cross_section not in _ANNULUS_RANGE:
        if ratio is not None:
            return (
                "diameter_ratio is given, but it is for annulus cross-sections only "
                f"(cross_section is {stream.cross_section!r})"
            )
        return ""
    if ratio is None:
        return f"cross_section {stream.cross_section!r} needs diameter_ratio (D_i/D_o)"
    lo, hi = _ANNULUS_RANGE[stream.cross_section]
    if not lo <= ratio <= hi:
        return (
            f"diameter_ratio {ratio} is outside {lo} to {hi}, the range of "
            f"cross_section {stream.cross_section!r}"
        )
    return ""


@dataclass(kw_only=True)
class Stream:
    """A one-dimensional fluid stream wetting some walls of the model (keyword-only).

    Parameters
    ----------
    name : str
    fluid : str
        Name of a library fluid.
    mode : {"in_plane", "through_plane"}
    walls : list of str
        Curve selections wetted by the stream.
    flow_area : float
        Flow cross-section [m^2].
    wetted_perimeter : float
        Wetted perimeter [m], for the hydraulic diameter.
    cross_section : str
        One of the sections of Theory §8.1: ``"circular"``, ``"parallel_plates"``,
        ``"parallel_plates_one_side"``, ``"square"``, ``"rectangle_1_43"``, ``"rectangle_2"``,
        ``"rectangle_3"``, ``"rectangle_4"``, ``"rectangle_8"``, ``"triangle"``,
        ``"annulus_inner"``, ``"annulus_outer"``.
    roughness : float
        Wall roughness [m].
    mass_flow : Function, optional
        Mass flow rate [kg/s]; ``None`` when taken from a network branch.
    T_inlet : Function
        Inlet temperature [K].
    path : list of (x, y), optional
        Polyline from inlet to outlet [m] (in-plane streams only).
    n_cells : int, optional
        Number of fluid cells; default one per wall edge along the path.
    nu_option : {"auto", "dittus_boelter", "sieder_tate"}
    h_multiplier : float
        Factor applied to the computed heat-transfer coefficient.
    h_override : Function, optional
        Heat-transfer coefficient [W/(m^2 K)] used instead of the duct correlation; a
        function of time only.
    diameter_ratio : float, optional
        D_i/D_o of a concentric annulus; required by (and only for) the annulus
        cross-sections.
    """

    name: str
    fluid: str
    mode: Literal["in_plane", "through_plane"]
    walls: list[str]
    flow_area: float
    wetted_perimeter: float
    cross_section: Literal[
        "circular", "parallel_plates", "parallel_plates_one_side", "square",
        "rectangle_1_43", "rectangle_2", "rectangle_3", "rectangle_4", "rectangle_8",
        "triangle", "annulus_inner", "annulus_outer",
    ]
    T_inlet: Function
    roughness: float = 0.0
    mass_flow: Function | None = None
    path: list[tuple[float, float]] | None = None
    n_cells: int | None = None
    nu_option: Literal["auto", "dittus_boelter", "sieder_tate"] = "auto"
    h_multiplier: float = 1.0
    h_override: Function | None = None
    diameter_ratio: float | None = None

    def __post_init__(self) -> None:
        _choice(self.mode, ("in_plane", "through_plane"), "stream mode")
        _choice(self.cross_section, STREAM_CROSS_SECTIONS, "stream cross_section")
        _choice(self.nu_option, STREAM_NU_OPTIONS, "nu_option")
        message = diameter_ratio_problem(self)
        if message:
            raise ModelError(f"stream {self.name!r}: {message}")
        if self.path is not None:
            self.path = [(float(p[0]), float(p[1])) for p in self.path]
        coerce_functions(self)


@dataclass
class NetNode:
    """Node of a flow network: fixed ``pressure`` [Pa] and/or external ``inflow`` [kg/s]."""

    id: str
    pressure: float | None = None
    inflow: float | None = None


@dataclass
class NetBranch:
    """Branch of a flow network.

    Parameters
    ----------
    id : str
    node_from, node_to : str
        Node ids; positive flow goes from ``node_from`` to ``node_to``.
    kind : {"duct", "loss"}
    length : float
        Duct length [m].
    K_minor : float
        Minor-loss coefficient (dimensionless).
    stream : str, optional
        Stream supplying area, hydraulic diameter and roughness.
    """

    id: str
    node_from: str
    node_to: str
    kind: Literal["duct", "loss"] = "duct"
    length: float = 0.0
    K_minor: float = 0.0
    stream: str | None = None

    def __post_init__(self) -> None:
        _choice(self.kind, ("duct", "loss"), "branch kind")


@dataclass
class FlowNetwork:
    """A pipe network of nodes and branches."""

    nodes: list[NetNode] = field(default_factory=list)
    branches: list[NetBranch] = field(default_factory=list)


# ------------------------------------------------------------------------ registration

registry.register_family(registry.BC_FAMILY, BoundaryCondition)
for _tag, _cls in (
    ("fixed_temperature", FixedTemperature),
    ("heat_flux", HeatFlux),
    ("heat_flow", HeatFlow),
    ("heat_generation", HeatGeneration),
    ("heat_power", HeatPower),
    ("convection", Convection),
    ("correlation_convection", CorrelationConvection),
    ("radiation_ambient", RadiationAmbient),
    ("symmetry", Symmetry),
    ("adiabatic", Adiabatic),
):
    registry.register_bc(_tag, _cls, form=BC_FORMS[_tag])
