"""V-11 — two-layer slab.

Layers 0.05 m each, k1 = 50, k2 = 5 W/(m K), T(0) = 400 K, T(L) = 300 K. Series
resistance: interface T = 400 - 100 (L1/k1) / (L1/k1 + L2/k2). The nodal flux has one
value per region at the interface, and both equal q. 10 elements per layer; tolerance 1e-10.
"""

from __future__ import annotations

import common
import numpy as np

from thermalfea import api
from thermalfea.model.bcs import FixedTemperature

L1, L2, K1, K2, T0, TL, N = 0.05, 0.05, 50.0, 5.0, 400.0, 300.0, 10
HEIGHT = (L1 + L2) / 10
TOL = 1e-10


def run(etype: str) -> dict:
    model = api.new_model("planar", name="V-11 two-layer slab")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, L1, HEIGHT)
    geo.rectangle(L1, 0.0, L2, HEIGHT)
    built = api.build(model)
    common.select_sides(model, built, 0.0, 0.0, L1 + L2, HEIGHT)
    api.select_surfaces(model, built, "layer1", where=lambda s: s.center[0] < L1)
    api.select_surfaces(model, built, "layer2", where=lambda s: s.center[0] > L1)
    api.select_curves(model, built, "interface", where=lambda c: abs(c.center[0] - L1) < 1e-9)
    api.assign_region(model, "layer1", material=common.add_material(model, "good", k=K1))
    api.assign_region(model, "layer2", material=common.add_material(model, "poor", k=K2))
    model.bcs += [FixedTemperature("hot", "left", T=T0), FixedTemperature("cold", "right", T=TL)]
    common.set_element_type(model, etype)
    settings = model.mesh_settings
    settings.global_size = L1 / N
    settings.curve_divisions = {"bottom": N, "top": N, "left": 1, "right": 1, "interface": 1}
    settings.structured_surfaces = ["all"]
    case = common.solve(model, built)

    r1, r2 = L1 / K1, L2 / K2
    q = (T0 - TL) / (r1 + r2)
    t_interface = T0 - (T0 - TL) * r1 / (r1 + r2)
    x = case.nodes[:, 0]
    exact = np.where(x <= L1, T0 - q * x / K1, t_interface - q * (x - L1) / K2)

    # one flux value per region at the interface nodes, both equal to q
    flux = case.flux()
    on_interface = set(np.flatnonzero(np.isclose(x, L1)))
    flux_error = 0.0
    for nodes, values in flux.values():
        assert on_interface <= set(nodes)
        flux_error = max(flux_error, float(np.max(np.abs(values[:, 0] - q))) / q)
        flux_error = max(flux_error, float(np.max(np.abs(values[:, 1]))) / q)
    return {
        "error": case.max_relative_error(exact),
        "interface_error": abs(case.T[case.node_at(L1, 0.0)] - t_interface) / t_interface,
        "flux_error": flux_error,
        "regions": len(flux),
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
