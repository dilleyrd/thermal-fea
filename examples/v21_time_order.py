"""V-21 — order of the time stepping.

V-16 solved with dt, dt/2 and dt/4 (dt = tau / 200) up to t = tau. The observed order is
about 1 for theta = 1 and about 2 for theta = 1/2, within 0.15.

The order is taken from the differences between successive solutions,
log2(|T(dt) - T(dt/2)| / |T(dt/2) - T(dt/4)|), which does not depend on the small,
step-independent departure of the two-dimensional body from the lumped formula.
"""

from __future__ import annotations

import common
import numpy as np
import v16_lumped_body as v16

EXPECTED = {1.0: 1.0, 0.5: 2.0}
TOL = 0.15


def run(etype: str, theta: float = 0.5) -> dict:
    dt = v16.TAU / 200.0
    results = [v16.run(etype, theta, dt / 2**i, v16.TAU) for i in range(3)]
    means = [r["T_mean_end"] for r in results]
    order = float(np.log2(abs(means[0] - means[1]) / abs(means[1] - means[2])))
    return {
        "order": order,
        "order_error": abs(order - EXPECTED[theta]),
        "imbalance": max(r["imbalance"] for r in results),
        "case": results[-1]["case"],
    }


if __name__ == "__main__":
    for value in (1.0, 0.5):
        title = f"{__doc__.splitlines()[0]} theta={value}"
        common.main(lambda etype, th=value: run(etype, th), title)
