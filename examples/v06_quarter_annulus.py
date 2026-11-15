"""V-06 — the hollow cylinder of V-05 modelled planar, as a quarter annulus.

Symmetry (no condition) on the two cut edges. Same T(r) as V-05; the heat flow per unit
thickness is one quarter of 2 pi k (T_i - T_o) / ln(r_o / r_i). Mesh size 0.004;
tolerance 2e-3.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea import api
from thermalfea.model.bcs import FixedTemperature, Symmetry

RI, RO, TI, TO, SIZE = 0.05, 0.1, 400.0, 300.0, 0.004
TOL = 2e-3


def run(etype: str) -> dict:
    model = api.new_model("planar", name="V-06 quarter annulus")
    geo = api.Geometry(model)
    outer = geo.circle(0.0, 0.0, RO)
    inner = geo.circle(0.0, 0.0, RI)
    ring = geo.cut([outer], [inner])
    quadrant = geo.rectangle(0.0, 0.0, RO, RO)
    geo.intersect([ring], [quadrant])
    built = api.build(model)

    def arc(radius: float):
        length = np.pi * radius / 2.0
        return lambda c: abs(c.measure - length) < 1e-9

    api.select_curves(model, built, "inner", where=arc(RI))
    api.select_curves(model, built, "outer", where=arc(RO))
    api.select_curves(model, built, "cuts", where=lambda c: abs(c.measure - (RO - RI)) < 1e-9)
    api.assign_region(model, "all", material=common.add_material(model))
    model.bcs += [
        FixedTemperature("inner", "inner", T=TI),
        FixedTemperature("outer", "outer", T=TO),
        Symmetry("symmetry", "cuts"),
    ]
    common.set_element_type(model, etype)
    model.mesh_settings.global_size = SIZE
    case = common.solve(model, built)

    r = np.linalg.norm(case.nodes, axis=1)
    quarter = 0.25 * 2.0 * np.pi * common.K * (TI - TO) / np.log(RO / RI)
    return {
        "error": case.max_relative_error(TI - (TI - TO) * np.log(r / RI) / np.log(RO / RI)),
        "heat_error": abs(case.heat("inner") - quarter) / quarter,
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
