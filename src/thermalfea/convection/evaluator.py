"""Heat-transfer coefficient from a correlation, at every integration point (Theory §8).

``h = Nu k_f / L_c`` with the fluid properties taken at the film temperature
``T_film = (T_s + T_inf) / 2``. The wall temperature ``T_s`` is the current nonlinear
iterate, which is the "lagged" wall temperature of Theory §8: the Newton driver uses a
tangent without ``dh/dT``. The computed ``h`` feeds the ordinary convection assembly of
:class:`~thermalfea.physics.surface_loads.ConvectionTerm`.

Characteristic length: ``char_length`` of the boundary condition when given. Otherwise the
total length of the selection (the sum of the in-plane lengths of its edges, without the
geometry factor) for the plate correlations and the vertical channels, and half of it for the
horizontal plates ``hplate_up_natural`` and ``hplate_down_natural``: [I] defines
L = A_s/P, which is half the strip width in a planar model and half the ring width in an
axisymmetric one (Theory §8, Q17.2). The cylinder, sphere and non-circular cylinder
correlations need ``char_length`` (the diameter or D). ``sphere_forced`` takes all properties
at ``T_inf`` except ``mu_s`` at ``T_s`` (at each point when the wall temperature is local).

Units: SI, temperatures in kelvin, lengths in m, h in W/(m^2 K).
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
from numpy import ndarray

from ..core import registry
from ..core.errors import ModelError
from ..materials import library
from ..materials.material import Fluid
from ..model.bcs import CorrelationConvection
from ..physics.batches import FacetBatch
from ..physics.evaluate import at_points
from ..physics.surface_loads import ConvectionTerm, FacetTerm
from ..solver.terms import State
from . import correlations as c
from .fluid_props import fluid_props, reset_clamp_warning

log = logging.getLogger(__name__)

MIN_DISTANCE = 1e-6
"""Smallest distance from the leading edge used by ``plate_forced_local`` [m] (Theory §8)."""

_HPLATES = ("hplate_up_natural", "hplate_down_natural")
_INCLINED = "inclined_natural"
_LOCAL = "plate_forced_local"
_USER = "power_law"
_DUCT = "duct_internal"
_SPHERE_FORCED = "sphere_forced"
_GIVEN_LENGTH = frozenset(
    {
        "cylinder_crossflow",
        "hcyl_natural",
        "square_corner_crossflow",
        "square_face_crossflow",
        "hexagon_face_crossflow",
        "hexagon_corner_crossflow",
        "plate_front_crossflow",
        "plate_back_crossflow",
        "sphere_forced",
        "sphere_natural",
    }
)
"""Correlations whose L_c (a diameter or D) must be given (Theory §8, Diameters)."""

_CHANNELS = ("vchannel_natural", "vchannel_one_side_natural")
_PARAM_KEYS = ("theta_deg", "x0", "y0", "dir_x", "dir_y", "C", "n", "S")
_REQUIRED_PARAMS: dict[str, tuple[str, ...]] = {
    _INCLINED: ("theta_deg",),
    _LOCAL: ("x0", "y0", "dir_x", "dir_y"),
    _USER: ("C", "n"),
    **{channel: ("S",) for channel in _CHANNELS},
}


def _scalar(value: Any) -> Any:
    """0-d arrays become NumPy scalars; other arrays are returned unchanged."""
    return np.asarray(value)[()]


def film_coefficient(
    info: c.CorrelationInfo,
    fluid: Fluid | None,
    T_s: Any,
    T_inf: Any,
    length: Any,
    velocity: Any = None,
    theta_deg: Any = 0.0,
    face_direction: str | None = None,
    params: dict[str, float] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """Heat-transfer coefficient of a correlation (before any multiplier).

    Parameters
    ----------
    info : CorrelationInfo
        Registry entry of the correlation.
    fluid : Fluid or None
        Fluid whose properties are taken at the film temperature; not needed for
        ``power_law``.
    T_s : array_like
        Wall temperature [K].
    T_inf : array_like
        Fluid temperature [K].
    length : array_like
        Characteristic length [m]; for ``plate_forced_local`` the distance ``x`` from the
        leading edge.
    velocity : array_like, optional
        Free-stream velocity [m/s], required for forced correlations.
    theta_deg : array_like, optional
        Inclination from vertical [deg], used by ``inclined_natural``.
    face_direction : {"up", "down"}, optional
        For the horizontal-plate pair, choose the correlation per point from the sign of
        ``T_s - T_inf`` and the declared direction; ``None`` uses ``info`` as given.
    params : dict, optional
        ``C`` and ``n`` for ``power_law``.

    Returns
    -------
    h : float or ndarray
        Coefficient [W/(m^2 K)], with the broadcast shape of the inputs.
    numbers : dict
        ``"T_film"``, ``"dT"`` (``T_s - T_inf``), and for fluid correlations ``"Nu"``,
        ``"Re"`` (forced) or ``"Ra"`` (natural), ``"Pr"``, ``"k"`` and ``"clamped"``
        (properties held at a table end);
        ``"use_up"`` (bool) when the horizontal-plate direction was chosen automatically.

    Raises
    ------
    ModelError
        For ``duct_internal``, a missing fluid, velocity or parameter.
    """
    T_s_a = np.asarray(T_s, dtype=float)
    T_inf_a = np.asarray(T_inf, dtype=float)
    T_film = 0.5 * (T_s_a + T_inf_a)
    if info.kind == "internal":
        raise ModelError(
            f"correlation {info.id!r} is not available as a boundary condition: internal duct "
            "flow is modelled with a stream"
        )
    if info.kind == "user":
        given = params or {}
        missing = [key for key in info.inputs[:2] if key not in given]
        if missing:
            raise ModelError(f"correlation {info.id!r} needs the parameters {missing}")
        h = info.function(given["C"], given["n"], T_s_a - T_inf_a)
        return _scalar(h), {"T_film": _scalar(T_film)}
    if fluid is None:
        raise ModelError(f"correlation {info.id!r} needs a fluid")

    if info.id == _SPHERE_FORCED:
        # Theory §8: all properties at T_inf, except mu_s at T_s.
        T_film = T_inf_a + 0.0 * T_s_a
    p = fluid_props(fluid, T_film)
    values: dict[str, Any] = {"Pr": p.Pr}
    if info.id == _SPHERE_FORCED:
        p_s = fluid_props(fluid, T_s_a)
        values["mu_ratio"] = p.mu / p_s.mu
        p.clamped = p.clamped | p_s.clamped
    numbers: dict[str, Any] = {
        "T_film": T_film,
        "Pr": p.Pr,
        "k": p.k,
        "clamped": p.clamped,
        "dT": T_s_a - T_inf_a,
    }
    if "mu_ratio" in values:
        numbers["mu_ratio"] = values["mu_ratio"]
    if info.kind == "forced":
        if velocity is None:
            raise ModelError(f"correlation {info.id!r} needs a velocity")
        Re = c.reynolds(p.rho, velocity, length, p.mu)
        values["Re"] = values["Re_x"] = numbers["Re"] = Re
    else:
        g = c.G * np.cos(np.radians(theta_deg)) if info.id == _INCLINED else c.G
        if info.id in _CHANNELS:
            # Theory §8: Ra_S uses the spacing S; L is the channel height; h = Nu_S k_f / S.
            spacing = (params or {}).get("S")
            if spacing is None or not spacing > 0.0:
                raise ModelError(
                    f"correlation {info.id!r} needs the plate spacing S (> 0); got {spacing!r}"
                )
            values["S_over_L"] = spacing / np.asarray(length, dtype=float)
            length = spacing
        Ra = c.rayleigh(p.beta, T_s_a - T_inf_a, length, p.Pr, p.rho, p.mu, g)
        values["Ra"] = numbers["Ra"] = Ra

    if info.id in _HPLATES and face_direction is not None:
        up = c.CORRELATIONS["hplate_up_natural"]
        down = c.CORRELATIONS["hplate_down_natural"]
        use_up = (T_s_a > T_inf_a) == (face_direction == "up")
        Nu = np.where(use_up, up.function(values["Ra"]), down.function(values["Ra"]))
        numbers["use_up"] = use_up
    else:
        Nu = info.function(*[values[name] for name in info.inputs])
    numbers["Nu"] = Nu
    return _scalar(c.nusselt_to_h(Nu, p.k, length)), numbers


class CorrelationConvectionTerm(ConvectionTerm):
    """Convection ``q_n = h (T - T_inf)`` with ``h`` from a correlation (Theory §8).

    The coefficient is evaluated at each integration point from the current iterate; the
    assembly of the matrix, the load and the boundary heat is that of ``ConvectionTerm``.
    The term is always nonlinear.
    """

    is_linear = False

    def __init__(self, bc: CorrelationConvection) -> None:
        FacetTerm.__init__(self, bc.name, bc.selection)
        if bc.correlation not in c.CORRELATIONS:
            raise ModelError(
                f"{bc.name}: unknown correlation {bc.correlation!r}; valid: "
                f"{', '.join(c.CORRELATIONS)}"
            )
        self.info = c.CORRELATIONS[bc.correlation]
        if self.info.kind == "internal":
            raise ModelError(
                f"{bc.name}: {bc.correlation!r} is not available as a boundary condition; "
                "internal duct flow is modelled with a stream"
            )
        if not bc.multiplier > 0.0:
            raise ModelError(f"{bc.name}: multiplier must be positive; got {bc.multiplier}")
        unknown = sorted(set(bc.params) - set(_PARAM_KEYS))
        if unknown:
            raise ModelError(
                f"{bc.name}: unknown params {unknown}; valid: {', '.join(_PARAM_KEYS)}"
            )
        missing = [k for k in _REQUIRED_PARAMS.get(self.info.id, ()) if k not in bc.params]
        if missing:
            raise ModelError(f"{bc.name}: {bc.correlation!r} needs the params {missing}")
        if "S" in bc.params and not float(bc.params["S"]) > 0.0:
            raise ModelError(
                f"{bc.name}: the plate spacing S must be positive; got {bc.params['S']}"
            )
        if self.info.kind == "forced" and bc.velocity is None:
            raise ModelError(f"{bc.name}: {bc.correlation!r} needs a velocity")
        self.fluid: Fluid | None = None
        if self.info.kind != "user":
            self.fluid = library.fluid(bc.fluid)
        self.char_length = bc.char_length
        if bc.char_length is not None and not bc.char_length > 0.0:
            raise ModelError(f"{bc.name}: char_length must be positive; got {bc.char_length}")
        if bc.char_length is None and self.info.id in _GIVEN_LENGTH:
            what = "the diameter" if "diameter" in self.info.length else "D"
            raise ModelError(f"{bc.name}: {bc.correlation!r} needs char_length ({what})")
        self.params = {k: float(v) for k, v in bc.params.items()}
        self._direction = np.zeros(2)
        if self.info.id == _LOCAL:
            d = np.array([self.params["dir_x"], self.params["dir_y"]])
            if not np.linalg.norm(d) > 0.0:
                raise ModelError(f"{bc.name}: the flow direction (dir_x, dir_y) is zero")
            self._direction = d / np.linalg.norm(d)
        self.T_inf = bc.T_inf
        self.velocity = bc.velocity
        self.face_direction = bc.face_direction
        self.wall_T_mode = bc.wall_T_mode
        self.multiplier = float(bc.multiplier)
        self.is_time_dependent = bc.T_inf.depends_on_time or (
            bc.velocity is not None and bc.velocity.depends_on_time
        )
        self._length = 0.0
        self._emitted: set[str] = set()

    # ------------------------------------------------------------------------ setup

    def setup(self, problem: Any) -> None:
        """Resolve the selection, the characteristic length and reset the warnings."""
        super().setup(problem)
        if self.char_length is not None:
            self._length = float(self.char_length)
        else:
            self._length = float(sum(b.geom.dS.sum() for b in self._batches))
            if self.info.id in _HPLATES:
                self._length *= 0.5  # L = A_s/P of a horizontal face (Theory §8, Q17.2)
        self.reset_warnings()
        if self.fluid is not None:
            reset_clamp_warning(self.fluid)

    def reset_warnings(self) -> None:
        """Allow every validity warning to be logged again."""
        self._emitted.clear()

    # ------------------------------------------------------------------- evaluation

    def _warn(self, message: str) -> None:
        if message not in self._emitted:
            self._emitted.add(message)
            log.warning("%s: %s", self.name, message)

    def _wall_temperature(self, s: State, batch: FacetBatch) -> ndarray:
        local = self.temperature(s, batch)
        if self.wall_T_mode == "local":
            return local
        num = den = 0.0
        for b in self._batches:
            weight = b.g * b.geom.dS
            num += float((self.temperature(s, b) * weight).sum())
            den += float(weight.sum())
        return np.full(local.shape, num / den)

    def _check_validity(self, numbers: dict[str, Any]) -> None:
        if "clamped" in numbers and np.any(numbers["clamped"]):
            self._warn("fluid temperature outside the property table; end values are used")
        if "Pr" not in numbers:
            return
        values: dict[str, Any] = {"Pr": numbers["Pr"]}
        if "Re" in numbers:
            values["Re"] = numbers["Re"]
            values["RePr"] = numbers["Re"] * numbers["Pr"]
        if "Ra" in numbers:
            values["Ra"] = numbers["Ra"]
        if "mu_ratio" in numbers:
            values["mu_ratio"] = numbers["mu_ratio"]
        if self.info.id == _INCLINED:
            values["theta_deg"] = self.params["theta_deg"]
        cases: list[tuple[c.CorrelationInfo, ndarray | None]] = [(self.info, None)]
        if "use_up" in numbers:
            up_mask = np.broadcast_to(numbers["use_up"], numbers["Ra"].shape)
            cases = [
                (c.CORRELATIONS["hplate_up_natural"], up_mask),
                (c.CORRELATIONS["hplate_down_natural"], ~up_mask),
            ]
        for info, mask in cases:
            if mask is None:
                subset = values
            elif mask.any():
                subset = {k: np.broadcast_to(v, mask.shape)[mask] for k, v in values.items()}
            else:
                continue
            for message in c.check_validity(info, **subset):
                self._warn(message)
        if self.info.id == _INCLINED:
            for message in c.inclined_face_messages(self.face_direction, numbers["dT"]):
                self._warn(message)

    def coefficient(self, s: State, batch: FacetBatch) -> ndarray:
        """Heat-transfer coefficient at the integration points [W/(m^2 K)], shape (f, gp)."""
        xgp = batch.geom.xgp
        local = self.temperature(s, batch)
        T_s = self._wall_temperature(s, batch)
        T_inf = self.ambient(s, batch)
        velocity = None
        if self.velocity is not None:
            velocity = at_points(self.velocity, s.t, xgp, local)
        length: Any = self._length
        if self.info.id == _LOCAL:
            start = np.array([self.params["x0"], self.params["y0"]])
            offset = xgp[..., 0] - start[0], xgp[..., 1] - start[1]
            along = offset[0] * self._direction[0] + offset[1] * self._direction[1]
            length = np.maximum(along, MIN_DISTANCE)
        h, numbers = film_coefficient(
            self.info,
            self.fluid,
            T_s,
            T_inf,
            length,
            velocity=velocity,
            theta_deg=self.params.get("theta_deg", 0.0),
            face_direction=self.face_direction,
            params=self.params,
        )
        self._check_validity(numbers)
        return np.broadcast_to(h * self.multiplier, local.shape)

    def breakpoints(self) -> list[float]:
        """Breakpoints of the fluid temperature and of the velocity."""
        points = set(self.T_inf.breakpoints())
        if self.velocity is not None:
            points |= set(self.velocity.breakpoints())
        return sorted(points)

    # ---------------------------------------------------------------------- output

    def mean_coefficient(self, s: State) -> float:
        """Area-weighted mean heat-transfer coefficient over the selection [W/(m^2 K)]."""
        num = den = 0.0
        for b in self._batches:
            weight = b.g * b.geom.dS
            num += float((self.coefficient(s, b) * weight).sum())
            den += float(weight.sum())
        return num / den

    def results(self, s: State) -> dict[str, ndarray]:
        """Mean coefficient of the boundary condition, keyed ``h_mean:<name>``."""
        return {f"h_mean:{self.name}": np.array([self.mean_coefficient(s)])}


registry.set_bc_term_factory(CorrelationConvection, CorrelationConvectionTerm)
