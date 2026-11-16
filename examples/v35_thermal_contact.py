"""V-35 — thermal contact.

V-11 (two-layer slab: layers 0.05 m each, k1 = 50, k2 = 5 W/(m K), T(0) = 400 K,
T(L) = 300 K) with a contact conductance h_c = 2000 W/(m^2 K) at the interface. The heat
flux follows from the series resistance including 1/h_c, and the temperature jumps by
q / h_c across the interface. 10 elements per layer; tolerance 1e-9.

The mesh is opened along the interface when the model is compiled, so the results have
two nodes at every interface position, one per layer; each is compared with the exact
temperature of its own layer.
"""

from __future__ import annotations

import common
import numpy as np
import v11_two_layer_slab as v11

from thermalfea import api
from thermalfea.model.bcs import Contact, FixedTemperature

H_C = 2000.0  # W/(m^2 K)
TOL = 1e-9


def run(etype: str) -> dict:
    L1, L2, K1, K2, T0, TL, N = v11.L1, v11.L2, v11.K1, v11.K2, v11.T0, v11.TL, v11.N
    model = api.new_model("planar", name="V-35 thermal contact")
    geo = api.Geometry(model)
    geo.rectangle(0.0, 0.0, L1, v11.HEIGHT)
    geo.rectangle(L1, 0.0, L2, v11.HEIGHT)
    built = api.build(model)
    common.select_sides(model, built, 0.0, 0.0, L1 + L2, v11.HEIGHT)
    api.select_surfaces(model, built, "layer1", where=lambda s: s.center[0] < L1)
    api.select_surfaces(model, built, "layer2", where=lambda s: s.center[0] > L1)
    api.select_curves(model, built, "interface", where=lambda c: abs(c.center[0] - L1) < 1e-9)
    api.assign_region(model, "layer1", material=common.add_material(model, "good", k=K1))
    api.assign_region(model, "layer2", material=common.add_material(model, "poor", k=K2))
    model.bcs += [FixedTemperature("hot", "left", T=T0), FixedTemperature("cold", "right", T=TL)]
    model.contacts.append(Contact("gap", "interface", conductance=H_C))
    common.set_element_type(model, etype)
    settings = model.mesh_settings
    settings.global_size = L1 / N
    settings.curve_divisions = {"bottom": N, "top": N, "left": 1, "right": 1, "interface": 1}
    settings.structured_surfaces = ["all"]
    case = common.solve(model, built)

    r1, r2, rc = L1 / K1, L2 / K2, 1.0 / H_C
    q = (T0 - TL) / (r1 + rc + r2)
    t_a = T0 - q * r1  # interface temperature on the side of layer 1
    t_b = t_a - q / H_C  # ... and on the side of layer 2

    mesh = case.results.mesh  # the opened mesh: two nodes per interface position
    T = case.results.temperature()
    x = mesh.nodes[:, 0]
    in_layer2 = np.zeros(mesh.n_nodes, dtype=bool)
    for block in mesh.blocks:
        centre = mesh.nodes[block.conn][:, :, 0].mean(axis=1)
        in_layer2[block.conn[centre > L1]] = True
    exact = np.where(in_layer2, t_b - q * (x - L1) / K2, T0 - q * x / K1)
    on_interface = np.isclose(x, L1)
    side_a, side_b = on_interface & ~in_layer2, on_interface & in_layer2
    jump = float(T[side_a].mean() - T[side_b].mean())
    return {
        "error": float(np.max(np.abs(T - exact) / exact)),
        "jump_error": abs(jump - q / H_C) / (q / H_C),
        "flux_error": abs(-case.heat("cold") / v11.HEIGHT - q) / q,
        "duplicated": int(mesh.n_nodes - case.mesh.n_nodes),
        "interface_nodes": int(side_a.sum()),
        "imbalance": abs(case.imbalance),
        "case": case,
    }


if __name__ == "__main__":
    common.main(run, __doc__.splitlines()[0])
