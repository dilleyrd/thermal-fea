import h5py
import pandas as pd
from common import OUT, Run, np, plt, save

tr = Run("closure_transient")
h = pd.read_csv(OUT / "closure_transient_history.csv")
f = h5py.File(OUT / "closure_transient.tfea.h5", "r")
dt = f["steps/dt"][:]
its = f["steps/iterations"][:]


def metrics(name):
    r = Run(name)
    n = r.nodes
    T = r.T[-1]
    w = 24 * 40**2 / (8 * 740) / 1000

    def mean(rr=None, rx=None, z=None):
        k = np.ones(len(n), bool)
        if rx is not None:
            k &= abs(n[:, 0] - rx) < 1e-6
        if z is not None:
            k &= (n[:, 1] > z[0] - 1e-6) & (n[:, 1] < z[1] + 1e-6)
        if rr is not None:
            k &= (n[:, 0] > rr[0] - 1e-6) & (n[:, 0] < rr[1] + 1e-6)
        return T[k].mean()

    return dict(
        nodes=len(n),
        bore=mean(rx=0.34, z=(-0.15, 0)),
        rim=mean(rx=0.8, z=(-0.15, 0)),
        stud=mean(rr=(0.74 - w / 2 * 1e0, 0.74 + w / 2), z=(0, 0.082)),
        QH=r.react["H"][-1],
    )


coarse, fine = metrics("closure_steady_mesh1"), metrics("closure_steady_mesh0.5")
print(coarse, fine)
dK = {k: fine[k] - coarse[k] for k in ("bore", "rim", "stud")}
dQ = (fine["QH"] - coarse["QH"]) / coarse["QH"]
print(dK, dQ)
fig, axs = plt.subplots(1, 3, figsize=(16, 4.8), gridspec_kw={"wspace": 0.3})
ax = axs[0]
ax.semilogy(h.time_s[1:] / 3600, np.abs(h.relative_imbalance[1:]), "o-", color="#2c7fb8", ms=3)
ax.axhline(1e-6, color="r", ls="--", lw=1)
ax.text(0.2, 1.6e-6, "1e-6 reference line", color="r", fontsize=8.5)
ax.set_ylim(1e-15, 1e-4)
ax.set_xlabel("Time [h]")
ax.set_ylabel("|relative energy imbalance|")
ax.set_title(
    "Energy balance closes to ~1e-13\n"
    f"(worst {np.abs(h.relative_imbalance[1:]).max():.1e}, 72 stored steps)",
    loc="left",
    fontsize=10.5,
    fontweight="bold",
)
ax = axs[1]
labels = ["flange bore", "flange rim", "mean stud"]
vals = [abs(dK["bore"]), abs(dK["rim"]), abs(dK["stud"])]
b = ax.barh(labels, vals, color="#fc8d62")
ax.axvline(1.0, color="r", ls="--", lw=1)
ax.text(0.97, 2.35, "criterion 1 K", color="r", ha="right", fontsize=8.5)
for rect, v in zip(b, vals, strict=False):
    ax.text(v + 0.02, rect.get_y() + rect.get_height() / 2, f"{v:.3f} K", va="center", fontsize=9)
ax.set_xlim(0, 1.2)
ax.set_xlabel("|change| on halving the element sizes [K]")
ax.invert_yaxis()
ax.set_title(
    f"Mesh independence: {coarse['nodes']:,} → {fine['nodes']:,} nodes\n"
    f"hot-film duty changes {abs(dQ) * 100:.3f} % (criterion 2 %)",
    loc="left",
    fontsize=10.5,
    fontweight="bold",
)
ax = axs[2]
ts = f["steps/time"][:] / 3600
ax.step(ts[1:], dt[1:], where="post", color="#4daf4a")
ax.set_yscale("log")
ax.set_xlabel("Time [h]")
ax.set_ylabel("Internal step before each output [s]")
ax.set_title(
    f"Adaptive time stepping: step grows from {dt[1:].min():.0f} s to {dt[1:].max():.0f} s\n"
    "(1 Newton iteration at every stored step)",
    loc="left",
    fontsize=10.5,
    fontweight="bold",
)
save(fig, "fig07_verification.png")
print("dt range", dt[1:].min(), dt[1:].max(), "iters", its.max(), its.sum())
