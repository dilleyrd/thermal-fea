"""V-18 — semi-infinite solid with a step change of surface temperature.

Slab L = 0.5 m, initial 300 K; T(0) steps to 400 K at t = 0+.

    T(x, t) = 400 - 100 erf(x / (2 sqrt(alpha t)))

checked at x = 0.01 and 0.02 m at t = 30 s (the far end stays undisturbed). Graded mesh
(size 0.001 near x = 0), lumped capacitance, automatic time step; tolerance 1e-2.

The strip is drawn in three parts so that x = 0.01 and x = 0.02 are mesh nodes.
"""

from __future__ import annotations

from math import erf, sqrt

import common
import numpy as np

from thermalfea import api
from thermalfea.model.bcs import FixedTemperature
from thermalfea.model.settings import Refinement

L, T_INIT, T_STEP, END = 0.5, 300.0, 400.0, 30.0
HEIGHT = 0.005  # a thin strip keeps the graded mesh small; the problem is one-dimensional
POINTS = (0.01, 0.02)
ALPHA = common.K / (common.RHO * common.CP)
SIZE_NEAR, SIZE_FAR = 0.001, 0.02
TOL = 1e-2


def exact(x: float, t: float) -> float:
    return T_STEP - (T_STEP - T_INIT) * erf(x / (2.0 * sqrt(ALPHA * t)))


def run(etype: str) -> dict:
    model = api.new_model("planar", name="V-18 semi-infinite solid")
    geo = api.Geometry(model)
    cuts = [0.0, *POINTS, L]
    for a, b in zip(cuts, cuts[1:], strict=False):
        geo.rectangle(a, 0.0, b - a, HEIGHT)
    built = api.build(model)
    common.select_sides(model, built, 0.0, 0.0, L, HEIGHT)
    api.assign_region(model, "all", material=common.add_material(model))
    model.bcs.append(FixedTemperature("step", "left", T=T_STEP))
    common.set_element_type(model, etype)
    settings = model.mesh_settings
    settings.global_size = SIZE_FAR
    settings.refinements = [Refinement("left", SIZE_NEAR, SIZE_FAR, 0.03, 0.3)]
    common.transient(model, T_INIT, end_time=END, lumped_capacitance=True)
    case = common.solve(model, built)

    errors = [
        abs(case.T[case.node_at(x, 0.0)] - exact(x, END)) / exact(x, END) for x in POINTS
    ]
    far = float(np.abs(case.T[np.isclose(case.nodes[:, 0], L)] - T_INIT).max())
    return {
        "error": max(errors),
        "far_end_change": far,
        "steps": case.n_steps,
        "nodes": case.mesh.n_nodes,
        "imbalance": case.worst_imbalance,
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
