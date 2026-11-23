import pandas as pd
from common import OUT, P, Run, np, plt, save

st = Run("closure_steady")
T = st.T[-1]
hs = pd.read_csv(OUT / "closure_steady_history.csv").iloc[-1]
# node -> set of bodies using it
nb = {}
for e, r in zip(st.conn, st.region, strict=False):
    for n in e:
        nb.setdefault(int(n), set()).add(st.body[r])
key = np.round(st.nodes * 1e7).astype(np.int64)
groups = {}
for i, k in enumerate(map(tuple, key)):
    groups.setdefault(k, []).append(i)
pairs = {k: v for k, v in groups.items() if len(v) == 2}


def jump_line(upper, lower, xr, z=0.0):
    rows = []
    for (kx, ky), (a, b) in pairs.items():
        x, y = kx / 1e7 * 1e3, ky / 1e7 * 1e3
        if abs(y - z) > 1e-3 or not (xr[0] - 1e-3 <= x <= xr[1] + 1e-3):
            continue
        for u, low in ((a, b), (b, a)):
            if nb[u] == {upper} and nb[low] == {lower}:
                rows.append((x, T[u], T[low]))
    rows.sort()
    return np.array(rows)


seg = {
    "barrier foot": jump_line("barrier", "flange_inner", (490, 550)),
    "seal land": jump_line("casing", "flange_inner", (550, 565)),
    "main seat": jump_line("casing", "flange_inner", (565, 685)),
}
h_c = P["contacts"]
Q = {}
for k, name in (
    ("barrier foot", "barrier_foot"),
    ("seal land", "seal_land"),
    ("main seat", "main_seat"),
):
    a = seg[k]
    Q[k] = np.trapezoid(
        h_c[name] * (a[:, 1] - a[:, 2]) * 2 * np.pi * a[:, 0] * 1e-3, a[:, 0] * 1e-3
    )
fig, axs = plt.subplots(
    2, 1, figsize=(11, 8.2), sharex=True, gridspec_kw={"height_ratios": [2, 1.1], "hspace": 0.08}
)
col = {"barrier foot": "#7570b3", "seal land": "#66a61e", "main seat": "#1b9e77"}
ax = axs[0]
allr = np.vstack([seg[k] for k in seg])
ax.plot(allr[:, 0], allr[:, 1], color="#d62728", lw=2.2, label="upper side (barrier / casing)")
ax.plot(allr[:, 0], allr[:, 2], color="#1f77b4", lw=2.2, label="lower side (flange)")
ax.fill_between(
    allr[:, 0],
    allr[:, 1],
    allr[:, 2],
    color="0.8",
    alpha=0.7,
    label="temperature jump across the contact",
)
ax.set_ylabel("Temperature at z = 0 [°C]")
ax.legend(loc="lower right", fontsize=9, frameon=False)
ax.set_title(
    "Thermal contact resistance makes a real temperature jump across the seated joint "
    "(steady hot case)",
    loc="left",
    fontsize=11.5,
    fontweight="bold",
)
ax = axs[1]
for k, a in seg.items():
    ax.plot(
        a[:, 0],
        a[:, 1] - a[:, 2],
        color=col[k],
        lw=2.4,
        label=f"{k}  (h = {h_c[k.replace(' ', '_')]:g} W/m²K)",
    )
ax.set_ylabel("Jump ΔT [K]")
ax.set_xlabel("Radius r [mm]")
ax.legend(fontsize=9, frameon=False, loc="upper right")
for x, lab in ((520, "barrier foot"), (557, "seal\nland"), (625, "main seat")):
    axs[0].text(
        x,
        axs[0].get_ylim()[0] + 0.5,
        lab,
        ha="center",
        fontsize=9,
        color=col[lab.replace("\n", " ")],
        va="bottom",
    )
save(fig, "fig05_contact_jumps.png")
