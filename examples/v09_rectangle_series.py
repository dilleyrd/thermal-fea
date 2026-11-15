"""V-09 — square with three cold sides and one hot side (Fourier series).

Rectangle a x b = 1 x 1, three sides at 300 K, top side at 400 K.

    theta(x, y) = (2 / pi) sum_{n=1..199} [((-1)^(n+1) + 1) / n] sin(n pi x / a)
                  sinh(n pi y / a) / sinh(n pi b / a),      T = 300 + 100 theta

Checked at (0.5, 0.5) (theta = 0.25) and (0.5, 0.75). Mesh size 0.02; tolerance 1e-3.

The square is drawn as six rectangles so that both check points are mesh nodes.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea import api
from thermalfea.model.bcs import FixedTemperature

A, B, T_COLD, T_HOT, SIZE = 1.0, 1.0, 300.0, 400.0, 0.02
POINTS = [(0.5, 0.5), (0.5, 0.75)]
TOL = 1e-3


def theta(x: float, y: float) -> float:
    n = np.arange(1, 200)
    # sinh ratio written with exponentials so that large n does not overflow
    ratio = np.exp(n * np.pi * (y - B) / A) * (
        -np.expm1(-2 * n * np.pi * y / A) / -np.expm1(-2 * n * np.pi * B / A)
    )
    terms = ((-1.0) ** (n + 1) + 1.0) / n * np.sin(n * np.pi * x / A) * ratio
    return float(2.0 / np.pi * terms.sum())


def run(etype: str) -> dict:
    model = api.new_model("planar", name="V-09 rectangle series")
    geo = api.Geometry(model)
    xs, ys = [0.0, 0.5, A], [0.0, 0.5, 0.75, B]
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            geo.rectangle(xs[i], ys[j], xs[i + 1] - xs[i], ys[j + 1] - ys[j])
    built = api.build(model)
    common.select_sides(model, built, 0.0, 0.0, A, B)
    api.select_curves(
        model, built, "cold", tags=[
            *model.selections["left"].tags,
            *model.selections["right"].tags,
            *model.selections["bottom"].tags,
        ]
    )
    api.assign_region(model, "all", material=common.add_material(model))
    # the hot side is listed last: at the two top corners it wins over the cold sides
    model.bcs += [
        FixedTemperature("cold", "cold", T=T_COLD),
        FixedTemperature("hot", "top", T=T_HOT),
    ]
    common.set_element_type(model, etype)
    model.mesh_settings.global_size = SIZE
    case = common.solve(model, built)

    errors = []
    for x, y in POINTS:
        exact = T_COLD + (T_HOT - T_COLD) * theta(x, y)
        errors.append(abs(case.T[case.node_at(x, y)] - exact) / exact)
    return {
        "error": max(errors),
        "centre_theta": (case.T[case.node_at(0.5, 0.5)] - T_COLD) / (T_HOT - T_COLD),
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
