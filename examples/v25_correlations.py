"""V-25 — correlation spot checks.

Each convection correlation of Theory §8 is evaluated at Pr = 0.7 for Reynolds or Rayleigh
numbers on both sides of every branch point, and compared with the formula written out
again here in plain arithmetic. Tolerance 1e-12 (relative).

This is a pure-function case: there is no model and no mesh.
"""

from __future__ import annotations

import math
import sys

from thermalfea.convection import correlations as c

PR = 0.7
TOL = 1e-12


def expected() -> dict[str, list[tuple[float, float]]]:
    """For each correlation: (Re or Ra, Nu from the formula of Theory §8) pairs."""
    third = PR ** (1.0 / 3.0)
    out: dict[str, list[tuple[float, float]]] = {
        "plate_forced_avg": [
            (re, 0.664 * re**0.5 * third if re <= 5e5 else (0.037 * re**0.8 - 871.0) * third)
            for re in (1e4, 5e5, 5e5 + 1.0, 1e6, 1e7)
        ],
        "plate_forced_local": [
            (re, 0.332 * re**0.5 * third if re <= 5e5 else 0.0296 * re**0.8 * third)
            for re in (1e3, 5e5, 5e5 + 1.0, 1e7)
        ],
        "cylinder_crossflow": [
            (
                re,
                0.3
                + 0.62 * re**0.5 * third
                * (1.0 + (0.4 / PR) ** (2.0 / 3.0)) ** -0.25
                * (1.0 + (re / 282000.0) ** (5.0 / 8.0)) ** (4.0 / 5.0),
            )
            for re in (10.0, 1e3, 1e5, 1e6)
        ],
        "vplate_natural": [
            (
                ra,
                (0.825 + 0.387 * ra ** (1.0 / 6.0)
                 / (1.0 + (0.492 / PR) ** (9.0 / 16.0)) ** (8.0 / 27.0)) ** 2,
            )
            for ra in (1e3, 1e6, 1e9, 1e12)
        ],
        "hplate_up_natural": [
            (ra, 0.54 * ra**0.25 if ra <= 1e7 else 0.15 * ra ** (1.0 / 3.0))
            for ra in (1e5, 1e7, 1e7 + 1.0, 1e9)
        ],
        "hplate_down_natural": [(ra, 0.52 * ra ** (1.0 / 5.0)) for ra in (1e4, 1e7, 1e9)],
        "hcyl_natural": [
            (
                ra,
                (0.60 + 0.387 * ra ** (1.0 / 6.0)
                 / (1.0 + (0.559 / PR) ** (9.0 / 16.0)) ** (8.0 / 27.0)) ** 2,
            )
            for ra in (1e2, 1e6, 1e10)
        ],
    }
    out["inclined_natural"] = out["vplate_natural"]  # same formula; Ra carries g cos(theta)
    return out


def gnielinski(re: float) -> float:
    f = (0.790 * math.log(re) - 1.64) ** -2
    return (f / 8.0) * (re - 1000.0) * PR / (1.0 + 12.7 * (f / 8.0) ** 0.5 * (PR ** (2 / 3) - 1.0))


def run() -> dict[str, float]:
    """Largest relative error of every correlation against its written-out formula."""
    errors: dict[str, float] = {}
    for name, pairs in expected().items():
        info = c.CORRELATIONS[name]
        worst = 0.0
        for number, exact in pairs:
            args = (number, PR) if len(info.inputs) > 1 else (number,)
            worst = max(worst, abs(float(info.function(*args)) - exact) / exact)
        errors[name] = worst
    duct = [(1000.0, 3.66), (2300.0, 3.66), (4000.0, gnielinski(4000.0)), (1e5, gnielinski(1e5)),
            (3150.0, 3.66 + 0.5 * (gnielinski(4000.0) - 3.66))]
    errors["duct_internal"] = max(
        abs(float(c.nu_duct(re, PR)) - exact) / exact for re, exact in duct
    )
    errors["power_law"] = abs(float(c.h_power_law(1.5, 0.25, -16.0)) - 1.5 * 16.0**0.25) / 3.0
    return errors


if __name__ == "__main__":
    sys.stdout.write(f"{__doc__.splitlines()[0]}\n")
    for correlation, error in run().items():
        sys.stdout.write(f"  {correlation:22s} largest relative error = {error:.2e}\n")
