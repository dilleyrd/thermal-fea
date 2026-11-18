import numpy as np

KMAT = {
    "casing": (14.9, 14.9),
    "barrier": (14.9, 14.9),
    "flange_inner": (14.9, 14.9),
    "flange_outer": (14.9, 14.9),
    "shell": (14.9, 14.9),
    "liner": (14.9, 14.9),
    "stud": (63.9, 63.9),
    "nut": (63.9, 63.9),
    "flange_band": (12.483783783783784, 22.845945945945946),
}  # (k_r, k_z) from the saved model


def element_flux(run, T):
    """Per-element heat flux [W/m^2] from the corner-node (linear) gradient.

    Returns centroid [mm], qr, qz.
    """
    c = run.conn[:, :3]
    xy = run.nodes[c]  # (ne,3,2) m
    Te = T[c]
    A = np.stack([np.ones((len(c), 3)), xy[..., 0], xy[..., 1]], axis=-1)
    coef = np.linalg.solve(A, Te[..., None])[..., 0]  # T = a + b x + c y
    gx, gy = coef[:, 1], coef[:, 2]
    kr = np.array([KMAT[run.body[r]][0] for r in run.region])
    kz = np.array([KMAT[run.body[r]][1] for r in run.region])
    return xy.mean(axis=1) * 1e3, -kr * gx, -kz * gy
