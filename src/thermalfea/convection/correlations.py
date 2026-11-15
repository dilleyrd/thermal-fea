"""Convection correlations (Theory §8 and §8.1).

Pure functions only: no model, mesh, solver or material access. Every formula is
transcribed from ``docs/theory.md``. Re, Pr, Ra, Nu and f are dimensionless. Other
arguments use SI units: lengths in m, temperatures differences in K, h in W/(m^2 K),
k in W/(m K), mu in Pa s, rho in kg/m^3, cp in J/(kg K), beta in 1/K.

Array inputs are supported: each function is evaluated elementwise with NumPy
broadcasting and returns a scalar ``float`` for scalar inputs, or an array of the
broadcast shape otherwise.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import ArrayLike

from thermalfea.core.errors import ModelError

G = 9.80665
"""Standard gravity [m/s^2] (Theory §8)."""

RE_LAMINAR, RE_TURBULENT = 2300.0, 4000.0
"""Laminar upper limit and turbulent lower limit of internal duct flow (Theory §8.1)."""

_NU_LAMINAR: dict[str, dict[str, float]] = {
    "circular": {"constant_T": 3.66, "constant_flux": 4.36},
    "parallel_plates": {"constant_T": 7.54, "constant_flux": 8.23},
    "parallel_plates_one_side": {"constant_T": 4.86, "constant_flux": 5.39},
    "square": {"constant_T": 2.98, "constant_flux": 3.61},
}
_DUCT_OPTIONS = ("auto", "dittus_boelter")


def _ret(x: ArrayLike) -> Any:
    """Return a Python/NumPy scalar for 0-d results and the array otherwise."""
    arr = np.asarray(x, dtype=float)
    return arr[()]


# --------------------------------------------------------------------------- dimensionless groups


def reynolds(rho: ArrayLike, V: ArrayLike, L: ArrayLike, mu: ArrayLike) -> Any:
    """Reynolds number ``Re = rho V L / mu`` (dimensionless).

    Parameters
    ----------
    rho : array_like
        Density [kg/m^3].
    V : array_like
        Velocity [m/s].
    L : array_like
        Length scale [m].
    mu : array_like
        Dynamic viscosity [Pa s].
    """
    return _ret(np.asarray(rho) * np.asarray(V) * np.asarray(L) / np.asarray(mu))


def prandtl(mu: ArrayLike, cp: ArrayLike, k: ArrayLike) -> Any:
    """Prandtl number ``Pr = mu cp / k_f`` (dimensionless).

    Parameters
    ----------
    mu : array_like
        Dynamic viscosity [Pa s].
    cp : array_like
        Specific heat at constant pressure [J/(kg K)].
    k : array_like
        Thermal conductivity [W/(m K)].
    """
    return _ret(np.asarray(mu) * np.asarray(cp) / np.asarray(k))


def rayleigh(
    beta: ArrayLike,
    dT: ArrayLike,
    L: ArrayLike,
    Pr: ArrayLike,
    rho: ArrayLike,
    mu: ArrayLike,
    g: float = G,
) -> Any:
    """Rayleigh number ``Ra = g beta |dT| L^3 Pr rho^2 / mu^2`` (dimensionless).

    Parameters
    ----------
    beta : array_like
        Volumetric thermal expansion coefficient [1/K].
    dT : array_like
        Wall minus ambient temperature difference [K]; the absolute value is used.
    L : array_like
        Characteristic length [m].
    Pr : array_like
        Prandtl number (dimensionless).
    rho : array_like
        Density [kg/m^3].
    mu : array_like
        Dynamic viscosity [Pa s].
    g : float, optional
        Gravitational acceleration [m/s^2], default ``G``.
    """
    beta_a, dT_a, L_a = np.asarray(beta), np.asarray(dT), np.asarray(L)
    Pr_a, rho_a, mu_a = np.asarray(Pr), np.asarray(rho), np.asarray(mu)
    return _ret(g * beta_a * np.abs(dT_a) * L_a**3 * Pr_a * rho_a**2 / mu_a**2)


def nusselt_to_h(Nu: ArrayLike, k: ArrayLike, L: ArrayLike) -> Any:
    """Convection coefficient ``h = Nu k_f / L_c`` [W/(m^2 K)].

    Parameters
    ----------
    Nu : array_like
        Nusselt number (dimensionless).
    k : array_like
        Fluid thermal conductivity [W/(m K)].
    L : array_like
        Characteristic length L_c [m].
    """
    return _ret(np.asarray(Nu) * np.asarray(k) / np.asarray(L))


# --------------------------------------------------------------------------- external forced


def nu_plate_forced_avg(Re: ArrayLike, Pr: ArrayLike) -> Any:
    """Average Nusselt number, flat plate in parallel flow (Theory §8).

    ``Re <= 5e5``: ``0.664 Re^(1/2) Pr^(1/3)``; otherwise
    ``(0.037 Re^0.8 - 871) Pr^(1/3)``.

    Parameters
    ----------
    Re : array_like
        Reynolds number based on the plate length (dimensionless).
    Pr : array_like
        Prandtl number (dimensionless).
    """
    Re_a, Pr_a = np.asarray(Re, dtype=float), np.asarray(Pr, dtype=float)
    laminar = 0.664 * Re_a**0.5 * Pr_a ** (1.0 / 3.0)
    turbulent = (0.037 * Re_a**0.8 - 871.0) * Pr_a ** (1.0 / 3.0)
    return _ret(np.where(Re_a <= 5e5, laminar, turbulent))


def nu_plate_forced_local(Re_x: ArrayLike, Pr: ArrayLike) -> Any:
    """Local Nusselt number at distance x from the leading edge (Theory §8).

    ``Re_x <= 5e5``: ``0.332 Re_x^(1/2) Pr^(1/3)``; otherwise
    ``0.0296 Re_x^0.8 Pr^(1/3)``.

    Parameters
    ----------
    Re_x : array_like
        Reynolds number based on the distance x (dimensionless).
    Pr : array_like
        Prandtl number (dimensionless).
    """
    Rx, Pr_a = np.asarray(Re_x, dtype=float), np.asarray(Pr, dtype=float)
    laminar = 0.332 * Rx**0.5 * Pr_a ** (1.0 / 3.0)
    turbulent = 0.0296 * Rx**0.8 * Pr_a ** (1.0 / 3.0)
    return _ret(np.where(Rx <= 5e5, laminar, turbulent))


def nu_cylinder_crossflow(Re: ArrayLike, Pr: ArrayLike) -> Any:
    """Average Nusselt number, cylinder in cross flow (Churchill–Bernstein, Theory §8).

    ``0.3 + 0.62 Re^(1/2) Pr^(1/3) [1+(0.4/Pr)^(2/3)]^(-1/4) [1+(Re/282000)^(5/8)]^(4/5)``.

    Parameters
    ----------
    Re : array_like
        Reynolds number based on the diameter (dimensionless).
    Pr : array_like
        Prandtl number (dimensionless).
    """
    Re_a, Pr_a = np.asarray(Re, dtype=float), np.asarray(Pr, dtype=float)
    return _ret(
        0.3
        + 0.62
        * Re_a**0.5
        * Pr_a ** (1.0 / 3.0)
        * (1.0 + (0.4 / Pr_a) ** (2.0 / 3.0)) ** (-0.25)
        * (1.0 + (Re_a / 282000.0) ** (5.0 / 8.0)) ** (4.0 / 5.0)
    )


# --------------------------------------------------------------------------- natural convection


def nu_vplate_natural(Ra: ArrayLike, Pr: ArrayLike) -> Any:
    """Vertical plate, natural convection (Churchill–Chu, Theory §8).

    ``Nu = {0.825 + 0.387 Ra^(1/6) / [1+(0.492/Pr)^(9/16)]^(8/27)}^2``, all Ra.

    Parameters
    ----------
    Ra : array_like
        Rayleigh number based on the height (dimensionless).
    Pr : array_like
        Prandtl number (dimensionless).
    """
    Ra_a, Pr_a = np.asarray(Ra, dtype=float), np.asarray(Pr, dtype=float)
    inner = 0.825 + 0.387 * Ra_a ** (1.0 / 6.0) / (1.0 + (0.492 / Pr_a) ** (9.0 / 16.0)) ** (
        8.0 / 27.0
    )
    return _ret(inner**2)


def nu_inclined_natural(Ra: ArrayLike, Pr: ArrayLike) -> Any:
    """Inclined plate, natural convection (Theory §8).

    Same formula as :func:`nu_vplate_natural`; the caller computes ``Ra`` with
    ``g cos(theta)`` in place of ``g``, where theta is the inclination from vertical
    (valid for theta <= 60 degrees).

    Parameters
    ----------
    Ra : array_like
        Rayleigh number computed with g cos(theta) (dimensionless).
    Pr : array_like
        Prandtl number (dimensionless).
    """
    return nu_vplate_natural(Ra, Pr)


def nu_hplate_up_natural(Ra: ArrayLike) -> Any:
    """Horizontal plate, hot face up or cold face down (Theory §8).

    ``Ra <= 1e7``: ``0.54 Ra^(1/4)``; otherwise ``0.15 Ra^(1/3)``.

    Parameters
    ----------
    Ra : array_like
        Rayleigh number based on area/perimeter (dimensionless).
    """
    Ra_a = np.asarray(Ra, dtype=float)
    return _ret(np.where(Ra_a <= 1e7, 0.54 * Ra_a**0.25, 0.15 * Ra_a ** (1.0 / 3.0)))


def nu_hplate_down_natural(Ra: ArrayLike) -> Any:
    """Horizontal plate, hot face down or cold face up (Theory §8).

    ``Nu = 0.27 Ra^(1/4)``.

    Parameters
    ----------
    Ra : array_like
        Rayleigh number based on area/perimeter (dimensionless).
    """
    Ra_a = np.asarray(Ra, dtype=float)
    return _ret(0.27 * Ra_a**0.25)


def nu_hcyl_natural(Ra: ArrayLike, Pr: ArrayLike) -> Any:
    """Horizontal cylinder, natural convection (Churchill–Chu, Theory §8).

    ``Nu = {0.60 + 0.387 Ra^(1/6) / [1+(0.559/Pr)^(9/16)]^(8/27)}^2``.

    Parameters
    ----------
    Ra : array_like
        Rayleigh number based on the diameter (dimensionless).
    Pr : array_like
        Prandtl number (dimensionless).
    """
    Ra_a, Pr_a = np.asarray(Ra, dtype=float), np.asarray(Pr, dtype=float)
    inner = 0.60 + 0.387 * Ra_a ** (1.0 / 6.0) / (1.0 + (0.559 / Pr_a) ** (9.0 / 16.0)) ** (
        8.0 / 27.0
    )
    return _ret(inner**2)


def h_power_law(C: ArrayLike, n: ArrayLike, dT: ArrayLike) -> Any:
    """User power-law convection coefficient ``h = C |dT|^n`` [W/(m^2 K)].

    Returns h directly, not Nu.

    Parameters
    ----------
    C : array_like
        Coefficient, units such that ``C |dT|^n`` is W/(m^2 K).
    n : array_like
        Exponent (dimensionless).
    dT : array_like
        Wall minus ambient temperature difference [K]; the absolute value is used.
    """
    return _ret(np.asarray(C) * np.abs(np.asarray(dT, dtype=float)) ** np.asarray(n))


# --------------------------------------------------------------------------- internal duct flow


def friction_smooth(Re: ArrayLike) -> Any:
    """Smooth-pipe friction factor ``f = (0.790 ln Re - 1.64)^-2`` (Theory §8.1).

    This is the ``f`` used inside the Gnielinski correlation.

    Parameters
    ----------
    Re : array_like
        Reynolds number (dimensionless).
    """
    Re_a = np.asarray(Re, dtype=float)
    return _ret((0.790 * np.log(Re_a) - 1.64) ** -2)


def nu_gnielinski(Re: ArrayLike, Pr: ArrayLike) -> Any:
    """Gnielinski turbulent internal-flow Nusselt number (Theory §8.1).

    ``Nu = (f/8)(Re - 1000) Pr / [1 + 12.7 (f/8)^(1/2) (Pr^(2/3) - 1)]`` with
    ``f = friction_smooth(Re)``. Valid for 0.5 <= Pr <= 2000 and Re <= 5e6.

    Parameters
    ----------
    Re : array_like
        Reynolds number (dimensionless).
    Pr : array_like
        Prandtl number (dimensionless).
    """
    Re_a, Pr_a = np.asarray(Re, dtype=float), np.asarray(Pr, dtype=float)
    f = friction_smooth(Re_a)
    num = (f / 8.0) * (Re_a - 1000.0) * Pr_a
    den = 1.0 + 12.7 * (f / 8.0) ** 0.5 * (Pr_a ** (2.0 / 3.0) - 1.0)
    return _ret(num / den)


def nu_dittus_boelter(Re: ArrayLike, Pr: ArrayLike, heating: bool = True) -> Any:
    """Dittus–Boelter Nusselt number ``Nu = 0.023 Re^0.8 Pr^n`` (Theory §8.1).

    ``n = 0.4`` when the wall is hotter than the fluid (``heating=True``), else
    ``n = 0.3``. Valid for Re >= 1e4.

    Parameters
    ----------
    Re : array_like
        Reynolds number (dimensionless).
    Pr : array_like
        Prandtl number (dimensionless).
    heating : bool, optional
        True when the fluid is heated (wall hotter than fluid), default True.
    """
    n = 0.4 if heating else 0.3
    Re_a, Pr_a = np.asarray(Re, dtype=float), np.asarray(Pr, dtype=float)
    return _ret(0.023 * Re_a**0.8 * Pr_a**n)


def nu_laminar(cross_section: str, wall: str = "constant_T") -> float:
    """Tabulated laminar fully developed Nusselt number (Theory §8.1).

    Parameters
    ----------
    cross_section : str
        One of ``"circular"``, ``"parallel_plates"`` (both heated),
        ``"parallel_plates_one_side"`` (one side insulated) or ``"square"``.
    wall : str, optional
        ``"constant_T"`` (default) for constant wall temperature or ``"constant_flux"``
        for constant wall heat flux.

    Raises
    ------
    ModelError
        If ``cross_section`` or ``wall`` is not a tabulated key.
    """
    if cross_section not in _NU_LAMINAR:
        raise ModelError(
            f"unknown duct cross-section {cross_section!r}; "
            f"expected one of {sorted(_NU_LAMINAR)}"
        )
    values = _NU_LAMINAR[cross_section]
    if wall not in values:
        raise ModelError(f"unknown wall condition {wall!r}; expected one of {sorted(values)}")
    return values[wall]


def nu_duct(
    Re: ArrayLike,
    Pr: ArrayLike,
    cross_section: str = "circular",
    wall: str = "constant_T",
    option: str = "auto",
    heating: bool = True,
) -> Any:
    """Internal duct flow Nusselt number, all regimes (Theory §8.1).

    * ``Re <= 2300``: :func:`nu_laminar`.
    * ``Re >= 4000``: the turbulent formula.
    * ``2300 < Re < 4000``: linear interpolation in Re between Nu_lam (at Re = 2300)
      and the turbulent formula evaluated at Re = 4000.

    The turbulent formula is Gnielinski for ``option="auto"`` and Dittus–Boelter for
    ``option="dittus_boelter"``. Using Dittus–Boelter as the turbulent formula, with the
    same laminar and transition rules, is this implementation's reading of the
    "optional user selection" in Theory §8.1.

    Parameters
    ----------
    Re : array_like
        Reynolds number based on D_h (dimensionless).
    Pr : array_like
        Prandtl number (dimensionless).
    cross_section : str, optional
        Key accepted by :func:`nu_laminar`, default ``"circular"``.
    wall : str, optional
        ``"constant_T"`` (default) or ``"constant_flux"``.
    option : str, optional
        ``"auto"`` (Gnielinski, default) or ``"dittus_boelter"``.
    heating : bool, optional
        Passed to :func:`nu_dittus_boelter`; True when the wall is hotter than the fluid.

    Raises
    ------
    ModelError
        If ``option``, ``cross_section`` or ``wall`` is unknown.
    """
    if option not in _DUCT_OPTIONS:
        raise ModelError(f"unknown duct Nusselt option {option!r}; expected one of {_DUCT_OPTIONS}")
    nu_lam = nu_laminar(cross_section, wall)

    def turbulent(R: ArrayLike) -> Any:
        if option == "auto":
            return nu_gnielinski(R, Pr)
        return nu_dittus_boelter(R, Pr, heating)

    Re_a = np.asarray(Re, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        nu_turb = np.asarray(turbulent(Re_a), dtype=float)
        nu_turb_end = np.asarray(turbulent(RE_TURBULENT), dtype=float)
    frac = (Re_a - RE_LAMINAR) / (RE_TURBULENT - RE_LAMINAR)
    transition = nu_lam + frac * (nu_turb_end - nu_lam)
    nu = np.where(Re_a <= RE_LAMINAR, nu_lam, np.where(Re_a >= RE_TURBULENT, nu_turb, transition))
    return _ret(nu)


def friction_churchill(Re: ArrayLike, relative_roughness: ArrayLike = 0.0) -> Any:
    """Darcy friction factor, all regimes, Churchill (1977) (Theory §8.1).

    ``f = 8 [ (8/Re)^12 + (A + B)^(-1.5) ]^(1/12)``, with
    ``A = [2.457 ln(1 / ((7/Re)^0.9 + 0.27 e/D_h))]^16`` and ``B = (37530/Re)^16``.

    Parameters
    ----------
    Re : array_like
        Reynolds number (dimensionless).
    relative_roughness : array_like, optional
        Relative roughness ``e / D_h`` (dimensionless), default 0 (smooth).
    """
    Re_a = np.asarray(Re, dtype=float)
    rr = np.asarray(relative_roughness, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        A = (2.457 * np.log(1.0 / ((7.0 / Re_a) ** 0.9 + 0.27 * rr))) ** 16
        B = (37530.0 / Re_a) ** 16
        f = 8.0 * ((8.0 / Re_a) ** 12 + (A + B) ** (-1.5)) ** (1.0 / 12.0)
    return _ret(f)


def pressure_drop(
    f: ArrayLike,
    L: ArrayLike,
    D_h: ArrayLike,
    K_minor: ArrayLike,
    rho: ArrayLike,
    V: ArrayLike,
) -> Any:
    """Duct pressure drop ``dp = (f L / D_h + K_minor) rho V^2 / 2`` [Pa] (Theory §8.1).

    The mean velocity is ``V = m_dot / (rho A)``; the caller computes it.

    Parameters
    ----------
    f : array_like
        Darcy friction factor (dimensionless).
    L : array_like
        Duct length [m].
    D_h : array_like
        Hydraulic diameter [m].
    K_minor : array_like
        Minor-loss coefficient (dimensionless).
    rho : array_like
        Density [kg/m^3].
    V : array_like
        Mean velocity [m/s].
    """
    f_a, L_a, D_a = np.asarray(f), np.asarray(L), np.asarray(D_h)
    K_a, rho_a, V_a = np.asarray(K_minor), np.asarray(rho), np.asarray(V)
    return _ret((f_a * L_a / D_a + K_a) * rho_a * V_a**2 / 2.0)


def hydraulic_diameter(area: ArrayLike, wetted_perimeter: ArrayLike) -> Any:
    """Hydraulic diameter ``D_h = 4 A / P_wet`` [m] (Theory §8.1).

    Parameters
    ----------
    area : array_like
        Flow area A [m^2].
    wetted_perimeter : array_like
        Wetted perimeter P_wet [m].
    """
    return _ret(4.0 * np.asarray(area) / np.asarray(wetted_perimeter))


# --------------------------------------------------------------------------- registry


def check_validity(info: CorrelationInfo, **values: ArrayLike) -> list[str]:
    """Return one message for each supplied quantity outside its validity range.

    A quantity is out of range if any element of its value is outside ``[min, max]``.
    Quantities that the correlation does not restrict, and bounds of ``None``, are ignored.

    Parameters
    ----------
    info : CorrelationInfo
        Registry entry to check against.
    **values : array_like
        Values by validity key (``"Re"``, ``"Pr"``, ``"Ra"``, ``"RePr"``, ``"theta_deg"``).
    """
    messages: list[str] = []
    for key, value in values.items():
        if key not in info.validity:
            continue
        lo, hi = info.validity[key]
        arr = np.asarray(value, dtype=float)
        bad_low = lo is not None and bool(np.any(arr < lo))
        bad_high = hi is not None and bool(np.any(arr > hi))
        if bad_low or bad_high:
            bounds = f"[{'-inf' if lo is None else lo}, {'inf' if hi is None else hi}]"
            messages.append(f"{info.id}: {key} outside validity range {bounds}")
    return messages


@dataclass(frozen=True)
class CorrelationInfo:
    """Registry entry describing one convection correlation.

    Attributes
    ----------
    id : str
        Correlation identifier (Theory §8 table).
    function : Callable
        The function computing Nu (or h for ``power_law``).
    inputs : tuple of str
        Names of the function's required arguments.
    kind : str
        ``"forced"``, ``"natural"``, ``"internal"`` or ``"user"``.
    validity : dict
        Quantity name to ``(min, max)``; ``None`` means unbounded.
    description : str
        The "Situation" text of the theory table.
    length : str
        Characteristic length text.
    source : str
        Source as named in the theory document.
    """

    id: str
    function: Callable[..., Any]
    inputs: tuple[str, ...]
    kind: str
    validity: dict[str, tuple[float | None, float | None]]
    description: str
    length: str
    source: str


_THEORY = "docs/theory.md §8"

CORRELATIONS: dict[str, CorrelationInfo] = {
    "plate_forced_avg": CorrelationInfo(
        id="plate_forced_avg",
        function=nu_plate_forced_avg,
        inputs=("Re", "Pr"),
        kind="forced",
        validity={"Pr": (0.6, None), "Re": (None, 1e8)},
        description="Flat plate, parallel flow, average",
        length="plate length",
        source=_THEORY,
    ),
    "plate_forced_local": CorrelationInfo(
        id="plate_forced_local",
        function=nu_plate_forced_local,
        inputs=("Re_x", "Pr"),
        kind="forced",
        validity={"Pr": (0.6, None)},
        description="Flat plate, local at distance x from leading edge",
        length="x",
        source=_THEORY,
    ),
    "cylinder_crossflow": CorrelationInfo(
        id="cylinder_crossflow",
        function=nu_cylinder_crossflow,
        inputs=("Re", "Pr"),
        kind="forced",
        validity={"RePr": (0.2, None)},
        description="Cylinder in cross flow (Churchill–Bernstein)",
        length="diameter",
        source="Churchill–Bernstein",
    ),
    "duct_internal": CorrelationInfo(
        id="duct_internal",
        function=nu_duct,
        inputs=("Re", "Pr"),
        kind="internal",
        validity={"Pr": (0.5, 2000), "Re": (None, 5e6)},
        description="Internal flow, circular or by hydraulic diameter",
        length="D_h",
        source="Gnielinski; Dittus–Boelter; laminar values tabulated in docs/theory.md §8.1",
    ),
    "vplate_natural": CorrelationInfo(
        id="vplate_natural",
        function=nu_vplate_natural,
        inputs=("Ra", "Pr"),
        kind="natural",
        validity={},
        description="Vertical plate (Churchill–Chu)",
        length="height",
        source="Churchill–Chu",
    ),
    "inclined_natural": CorrelationInfo(
        id="inclined_natural",
        function=nu_inclined_natural,
        inputs=("Ra", "Pr"),
        kind="natural",
        validity={"theta_deg": (None, 60)},
        description="Plate inclined θ from vertical",
        length="length",
        source="Churchill–Chu",
    ),
    "hplate_up_natural": CorrelationInfo(
        id="hplate_up_natural",
        function=nu_hplate_up_natural,
        inputs=("Ra",),
        kind="natural",
        validity={"Ra": (1e4, 1e11)},
        description="Horizontal, hot face up or cold face down",
        length="area/perimeter",
        source=_THEORY,
    ),
    "hplate_down_natural": CorrelationInfo(
        id="hplate_down_natural",
        function=nu_hplate_down_natural,
        inputs=("Ra",),
        kind="natural",
        validity={"Ra": (1e5, 1e10)},
        description="Horizontal, hot face down or cold face up",
        length="area/perimeter",
        source=_THEORY,
    ),
    "hcyl_natural": CorrelationInfo(
        id="hcyl_natural",
        function=nu_hcyl_natural,
        inputs=("Ra", "Pr"),
        kind="natural",
        validity={"Ra": (None, 1e12)},
        description="Horizontal cylinder (Churchill–Chu)",
        length="diameter",
        source="Churchill–Chu",
    ),
    "power_law": CorrelationInfo(
        id="power_law",
        function=h_power_law,
        inputs=("C", "n", "dT"),
        kind="user",
        validity={},
        description="User form, h = C |T_s − T∞|^n (gives h directly)",
        length="none",
        source=_THEORY,
    ),
}
"""Registry of the Theory §8 correlations, keyed by ID in table order."""
