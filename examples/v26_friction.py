"""V-26 — Churchill friction factor.

Laminar: f tends to 64 / Re at Re = 500 (tolerance 1e-3). Smooth turbulent flow at
Re = 1e5: within 3 % of (0.790 ln Re - 1.64)^-2.

This is a pure-function case: there is no model and no mesh.
"""

from __future__ import annotations

import math
import sys

from thermalfea.convection import correlations as c

RE_LAMINAR, RE_TURBULENT = 500.0, 1.0e5
TOL_LAMINAR, TOL_TURBULENT = 1e-3, 0.03


def run() -> dict[str, float]:
    """Relative differences of the Churchill friction factor from its two references."""
    laminar = float(c.friction_churchill(RE_LAMINAR))
    turbulent = float(c.friction_churchill(RE_TURBULENT))
    smooth = (0.790 * math.log(RE_TURBULENT) - 1.64) ** -2
    return {
        "f_laminar": laminar,
        "laminar_error": abs(laminar - 64.0 / RE_LAMINAR) / (64.0 / RE_LAMINAR),
        "f_turbulent": turbulent,
        "f_smooth_reference": smooth,
        "turbulent_error": abs(turbulent - smooth) / smooth,
    }


if __name__ == "__main__":
    sys.stdout.write(f"{__doc__.splitlines()[0]}\n")
    for key, value in run().items():
        sys.stdout.write(f"  {key:20s} = {value:.6g}\n")
