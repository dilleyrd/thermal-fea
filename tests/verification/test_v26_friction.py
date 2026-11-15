"""V-26 — Churchill friction factor (Theory §8.1).

Laminar: f -> 64/Re at Re = 500. Smooth turbulent: within 3% of (0.790 ln Re - 1.64)^-2 at
Re = 1e5. Zero roughness in both cases.
"""

from __future__ import annotations

import math

import pytest

from thermalfea.convection import correlations as c


def test_laminar_limit_is_64_over_re() -> None:
    Re = 500.0
    assert c.friction_churchill(Re, 0.0) == pytest.approx(64.0 / Re, rel=1e-3)


def test_smooth_turbulent_within_3_percent_of_smooth_formula() -> None:
    Re = 1e5
    want = (0.790 * math.log(Re) - 1.64) ** -2
    assert c.friction_churchill(Re, 0.0) == pytest.approx(want, rel=0.03)
