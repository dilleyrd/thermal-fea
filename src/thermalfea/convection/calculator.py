"""Stand-alone heat-transfer coefficient for single values (Theory §8 and §8.1).

:func:`htc` is the calculator used by the GUI tool: one correlation, one fluid, one pair of
temperatures and the inputs that correlation needs. It calls the same functions as the
boundary-condition term in :mod:`thermalfea.convection.evaluator`. Validity messages and
the property-table warning are returned in :attr:`HtcResult.warnings` and not logged by
:func:`htc` itself; the property-table warning is also logged once per fluid by
:func:`~thermalfea.convection.fluid_props.fluid_props`.

Units: SI; temperatures in kelvin, lengths in m, velocities in m/s, h in W/(m^2 K).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from ..core.errors import ModelError
from ..materials import library
from ..materials.material import Fluid
from ..model.bcs import inclination_problem, power_law_problem
from . import correlations as c
from .evaluator import MIN_DISTANCE, _jet_length, film_coefficient
from .fluid_props import fluid_props

PLATE_TRANSITION_RE = 5e5
"""Re at which the flat-plate correlations change from laminar to turbulent (Theory §8).

Hard-coded in ``correlations.nu_plate_forced_avg`` and ``nu_plate_forced_local``.
"""

HPLATE_TRANSITION_RA = 1e7
"""Ra at which ``hplate_up_natural`` changes branch (Theory §8).

Hard-coded in ``correlations.nu_hplate_up_natural``.
"""

_UP = "hplate_up_natural"
_DOWN = "hplate_down_natural"
_HPLATES = (_UP, _DOWN)
_FORCED_PLATES = ("plate_forced_avg", "plate_forced_local")
_LOCAL = "plate_forced_local"
_INCLINED = "inclined_natural"
_CHANNELS = ("vchannel_natural", "vchannel_one_side_natural")
_JETS = ("slot_jet", "round_jet")
_DUCT = "duct_internal"
_USER = "power_law"
_TEMPERATURE_CLAMP = "fluid temperature outside the property table; end values are used"
_INPUT_KEYS = frozenset(
    {
        "length",
        "velocity",
        "theta_deg",
        "S",
        "W",
        "H",
        "x_r",
        "D",
        "r_r",
        "face_direction",
        "x",
        "C",
        "n",
        "multiplier",
        "mass_flow",
        "area",
        "wetted_perimeter",
        "cross_section",
        "diameter_ratio",
        "wall",
        "option",
    }
)


@dataclass
class HtcResult:
    """Result of :func:`htc`.

    Attributes
    ----------
    correlation : str
        Correlation ID as requested.
    h : float
        Heat-transfer coefficient [W/(m^2 K)], multiplier applied.
    Nu : float or None
        Nusselt number; None for ``power_law``.
    Re : float or None
        Reynolds number (forced and internal correlations).
    Ra : float or None
        Rayleigh number (natural correlations).
    Pr : float or None
        Prandtl number of the fluid at ``T_film``.
    regime : str
        Short description of the branch used.
    T_film : float
        Temperature the properties were evaluated at [K]; ``T_inf`` for ``sphere_forced``.
    length : float or None
        Characteristic length used [m]; D_h for ``duct_internal``.
    warnings : list of str
        Validity-range and property-table messages.
    """

    correlation: str
    h: float
    Nu: float | None
    Re: float | None
    Ra: float | None
    Pr: float | None
    regime: str
    T_film: float
    length: float | None
    warnings: list[str]


def _positive(name: str, value: Any) -> float:
    number = float(value)
    if not number > 0.0:
        raise ModelError(f"{name} must be positive; got {number}")
    return number


def _need(correlation: str, inputs: dict[str, Any], *keys: str) -> None:
    missing = [key for key in keys if inputs.get(key) is None]
    if missing:
        raise ModelError(f"correlation {correlation!r} needs the input(s) {missing}")


def _fluid_object(correlation: str, fluid: str | Fluid | None) -> Fluid:
    if fluid is None:
        raise ModelError(f"correlation {correlation!r} needs a fluid")
    if isinstance(fluid, Fluid):
        return fluid
    if isinstance(fluid, str):
        return library.fluid(fluid)  # raises ModelError for an unknown name
    raise ModelError(f"fluid must be a library name or a Fluid object; got {fluid!r}")


def htc(
    correlation: str,
    fluid: str | Fluid | None,
    T_surface: float,
    T_inf: float,
    **inputs: Any,
) -> HtcResult:
    """Heat-transfer coefficient of one correlation at single values.

    Parameters
    ----------
    correlation : str
        An ID in ``correlations.CORRELATIONS``.
    fluid : str or Fluid or None
        Library fluid name or a Fluid object; not needed for ``power_law``.
    T_surface : float
        Wall temperature [K], above 0.
    T_inf : float
        Fluid temperature [K], above 0. For ``duct_internal`` the properties are taken at
        this bulk temperature.
    **inputs
        ``length`` [m] (characteristic length; the diameter for cylinders; A_s/P for the
        horizontal plates, which a boundary condition takes as half the selection length),
        ``velocity`` [m/s] (forced), ``theta_deg`` [deg] (``inclined_natural``), ``S`` [m]
        (plate spacing of the vertical channels; ``length`` is then the channel height),
        ``W``, ``H``, ``x_r`` [m] (``slot_jet``) and ``D``, ``H``, ``r_r`` [m] (``round_jet``;
        the jets take their length from these, so ``length`` is refused),
        ``face_direction``
        (``"up"``/``"down"``, horizontal plates), ``x`` [m] (``plate_forced_local``),
        ``C`` and ``n`` (``power_law``), ``multiplier`` (default 1.0, > 0), and for
        ``duct_internal``: ``mass_flow`` [kg/s], ``area`` [m^2], ``wetted_perimeter`` [m],
        ``cross_section`` (default ``"circular"``), ``diameter_ratio`` (D_i/D_o, annulus sections
        only), ``wall`` (default ``"constant_T"``), ``option`` (``"auto"`` (default),
        ``"dittus_boelter"`` or ``"sieder_tate"``; mu_s at ``T_surface``).

    Returns
    -------
    HtcResult

    Raises
    ------
    ModelError
        For an unknown correlation or input, a missing required input, a non-positive
        temperature or multiplier, or an unknown fluid.
    """
    if correlation not in c.CORRELATIONS:
        raise ModelError(
            f"unknown correlation {correlation!r}; valid: {', '.join(c.CORRELATIONS)}"
        )
    unknown = sorted(set(inputs) - _INPUT_KEYS)
    if unknown:
        raise ModelError(f"unknown input(s) {unknown}; valid: {', '.join(sorted(_INPUT_KEYS))}")
    info = c.CORRELATIONS[correlation]
    T_s = _positive("T_surface", T_surface)
    T_i = _positive("T_inf", T_inf)
    multiplier = _positive("multiplier", inputs.get("multiplier", 1.0))
    if info.kind == "user":
        return _user_law(info.id, inputs, T_s, T_i, multiplier)
    fluid_obj = _fluid_object(correlation, fluid)
    if info.kind == "internal":
        return _duct(info, fluid_obj, T_s, T_i, inputs, multiplier)
    return _fluid_correlation(info, fluid_obj, T_s, T_i, inputs, multiplier)


def _user_law(
    correlation: str, inputs: dict[str, Any], T_s: float, T_i: float, multiplier: float
) -> HtcResult:
    _need(correlation, inputs, "C", "n")
    message = power_law_problem(inputs["C"], inputs["n"])
    if message:
        raise ModelError(message)
    h, numbers = film_coefficient(
        c.CORRELATIONS[correlation],
        None,
        T_s,
        T_i,
        None,
        params={"C": float(inputs["C"]), "n": float(inputs["n"])},
    )
    return HtcResult(
        correlation=correlation,
        h=float(h) * multiplier,
        Nu=None,
        Re=None,
        Ra=None,
        Pr=None,
        regime="single correlation",
        T_film=float(numbers["T_film"]),
        length=None,
        warnings=[],
    )


def _fluid_correlation(
    info: c.CorrelationInfo,
    fluid: Fluid,
    T_s: float,
    T_i: float,
    inputs: dict[str, Any],
    multiplier: float,
) -> HtcResult:
    if info.id == _LOCAL:
        _need(info.id, inputs, "x")
        x = float(inputs["x"])
        if x < 0.0:
            raise ModelError(f"x must not be negative; got {x}")
        length = max(x, MIN_DISTANCE)
    elif info.id in _JETS:
        if inputs.get("length") is not None:
            raise ModelError(
                f"correlation {info.id!r} takes its length from its inputs (2W or D); "
                "length is not allowed"
            )
        length = None
    else:
        _need(info.id, inputs, "length")
        length = _positive("length", inputs["length"])
    velocity = None
    if info.kind == "forced":
        _need(info.id, inputs, "velocity")
        velocity = float(inputs["velocity"])
        if velocity < 0.0:
            raise ModelError(f"velocity must not be negative; got {velocity}")
    theta_deg = 0.0
    if info.id == _INCLINED:
        _need(info.id, inputs, "theta_deg")
        message = inclination_problem(inputs["theta_deg"])
        if message:
            raise ModelError(message)
        theta_deg = float(inputs["theta_deg"])
    params: dict[str, float] | None = None
    if info.id in _CHANNELS:
        _need(info.id, inputs, "S")
        params = {"S": _positive("S", inputs["S"])}
    if info.id in _JETS:
        names = ("W", "H", "x_r") if info.id == "slot_jet" else ("D", "H", "r_r")
        _need(info.id, inputs, *names)
        params = {n: _positive(n, inputs[n]) for n in names}
        length = _jet_length(info.id, params)
    face = inputs.get("face_direction")
    if face is not None and face not in ("up", "down"):
        raise ModelError(f"face_direction must be 'up', 'down' or None; got {face!r}")

    h, numbers = film_coefficient(
        info,
        fluid,
        T_s,
        T_i,
        length,
        velocity=velocity,
        theta_deg=theta_deg,
        face_direction=face,
        params=params,
    )
    Pr = float(numbers["Pr"])
    auto = info.id in _HPLATES and face is not None
    used = info.id
    if auto:
        used = _UP if bool(numbers["use_up"]) else _DOWN

    values: dict[str, float] = {"Pr": Pr}
    Re: float | None = None
    Ra: float | None = None
    if "Re" in numbers:
        Re = float(numbers["Re"])
        values["Re"] = Re
        values["RePr"] = Re * Pr
    if "Ra" in numbers:
        Ra = float(numbers["Ra"])
        values["Ra"] = Ra
    if "mu_ratio" in numbers:
        values["mu_ratio"] = float(numbers["mu_ratio"])
    for key in ("H_over_W", "H_over_D", "A_r"):
        if key in numbers:
            values[key] = float(numbers[key])
    if info.id == _INCLINED:
        values["theta_deg"] = theta_deg
    warnings = c.check_validity(c.CORRELATIONS[used], **values)
    if info.id == _INCLINED:
        warnings += c.inclined_face_messages(face, numbers["dT"])
    if bool(numbers["clamped"]):
        warnings.append(_TEMPERATURE_CLAMP)

    if used in _FORCED_PLATES:
        base = "laminar" if float(numbers["Re"]) <= PLATE_TRANSITION_RE else "turbulent"
    elif used == _UP:
        base = "laminar" if float(numbers["Ra"]) <= HPLATE_TRANSITION_RA else "turbulent"
    else:
        base = "single correlation"
    regime = f"{used}, {base}" if auto else base

    return HtcResult(
        correlation=info.id,
        h=float(h) * multiplier,
        Nu=float(numbers["Nu"]),
        Re=Re,
        Ra=Ra,
        Pr=Pr,
        regime=regime,
        T_film=float(numbers["T_film"]),
        length=length,
        warnings=warnings,
    )


def _duct(
    info: c.CorrelationInfo,
    fluid: Fluid,
    T_s: float,
    T_i: float,
    inputs: dict[str, Any],
    multiplier: float,
) -> HtcResult:
    _need(info.id, inputs, "mass_flow", "area", "wetted_perimeter")
    m_dot = _positive("mass_flow", inputs["mass_flow"])
    area = _positive("area", inputs["area"])
    perimeter = _positive("wetted_perimeter", inputs["wetted_perimeter"])
    cross_section = inputs.get("cross_section", "circular")
    wall = inputs.get("wall", "constant_T")
    option = inputs.get("option", "auto")

    # Theory §8.1: properties at the bulk fluid temperature, which is T_inf here.
    props = fluid_props(fluid, T_i)
    D_h = float(c.hydraulic_diameter(area, perimeter))
    Re = float(m_dot * D_h / (area * props.mu))
    Pr = float(props.Pr)
    diameter_ratio = inputs.get("diameter_ratio")
    if diameter_ratio is not None:
        diameter_ratio = float(diameter_ratio)
    mu_ratio = 1.0
    wall_props = None
    if option == "sieder_tate":
        # Theory §8.1: mu_s at the wall (surface) temperature, the other properties at bulk
        wall_props = fluid_props(fluid, T_s)
        mu_ratio = float(props.mu / wall_props.mu)
    Nu = float(
        c.nu_duct(
            Re, Pr, cross_section, wall, option, T_s > T_i, diameter_ratio, mu_ratio
        )
    )
    h = float(c.nusselt_to_h(Nu, float(props.k), D_h)) * multiplier

    extra = {
        "dittus_boelter": c.DITTUS_BOELTER_BOUNDS,
        "sieder_tate": c.SIEDER_TATE_BOUNDS,
    }.get(option, ())
    # Sieder-Tate replaces Gnielinski, so the Gnielinski ranges do not apply to it
    checked = replace(info, validity={}) if option == "sieder_tate" else info
    warnings = c.check_validity(checked, extra_bounds=extra, Re=Re, Pr=Pr)
    if bool(props.clamped) or (wall_props is not None and bool(wall_props.clamped)):
        warnings.append(_TEMPERATURE_CLAMP)
    if Re <= c.RE_LAMINAR:
        regime = "laminar"
    elif Re < c.RE_TURBULENT:
        regime = "transition"
    else:
        regime = "turbulent"

    return HtcResult(
        correlation=info.id,
        h=h,
        Nu=Nu,
        Re=Re,
        Ra=None,
        Pr=Pr,
        regime=regime,
        T_film=T_i,
        length=D_h,
        warnings=warnings,
    )
