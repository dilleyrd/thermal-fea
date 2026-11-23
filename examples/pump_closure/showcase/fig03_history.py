import pandas as pd
from common import FILM_COLOR, OUT, np, plt, save

h = pd.read_csv(OUT / "closure_transient_history.csv")
t = h.time_s.values / 3600


def cross(x, y):
    i = np.where(np.diff(np.sign(y)) != 0)[0]
    return [float(x[j] - y[j] * (x[j + 1] - x[j]) / (y[j + 1] - y[j])) for j in i]


c_dT = cross(t[1:], h.bore_to_rim_dT_K.values[1:])
c_vf = cross(t[1:], h.Q_vertical_fit_W.values[1:])
c_nut = cross(t[1:], h.Q_nut_bearing_W.values[1:])
pk = h.bore_to_rim_dT_K.idxmax()
stud_pk = h.Q_stud_anchor_W.idxmax()
seat_pk = h.Q_main_seat_W.idxmax()
fig, axs = plt.subplots(3, 1, figsize=(10.5, 12), sharex=True, gridspec_kw={"hspace": 0.12})
ax = axs[0]
ax.plot(
    t[1:], h.Q_film_H_W[1:] / 1e3, color=FILM_COLOR["H"], lw=2.2, label="H  (hot water, heat in)"
)
for k in ("M", "Cw", "J", "A"):
    ax.plot(
        t[1:], -h[f"Q_film_{k}_W"][1:] / 1e3, color=FILM_COLOR[k], lw=1.8, label=f"{k}  (heat out)"
    )
ax.axvline(0.5, color="k", ls=":", lw=1)
ax.text(0.58, 33, "H ramp ends\n(30 min)", fontsize=8.5, va="top")
ax.set_ylabel("Heat through films [kW]")
ax.legend(ncol=3, fontsize=8.5, loc="upper right", frameon=False)
ax.set_title(
    "1  The whole ring: the hot face peaks at 62 kW as the ramp ends, then settles toward 35 kW",
    loc="left",
    fontsize=10.5,
    fontweight="bold",
)
ax = axs[1]
ax.plot(t, h.flange_bore_C, color="#1f77b4", lw=2.2, label="flange bore (r = 340 mm)")
ax.plot(t, h.flange_rim_C, color="#d62728", lw=2.2, label="flange rim (r = 800 mm)")
ax.plot(t, h.stud_mean_C, color="#ff7f0e", lw=1.8, ls="--", label="mean stud temperature")
ax.set_ylabel("Temperature [°C]")
ax2 = ax.twinx()
ax2.spines["right"].set_visible(True)
ax2.grid(False)
ax2.fill_between(
    t, h.bore_to_rim_dT_K, 0, where=h.bore_to_rim_dT_K >= 0, color="#1f77b4", alpha=0.18
)
ax2.fill_between(
    t, h.bore_to_rim_dT_K, 0, where=h.bore_to_rim_dT_K <= 0, color="#d62728", alpha=0.18
)
ax2.set_ylabel("bore − rim [K]  (shaded)")
ax2.axhline(0, color="k", lw=0.6)
ax2.set_ylim(-45, 45)
ax.set_ylim(30, 125)
ax2.annotate(
    f"+{h.bore_to_rim_dT_K.max():.1f} K at {h.time_s[pk] / 60:.0f} min",
    (h.time_s[pk] / 3600, h.bore_to_rim_dT_K.max()),
    (1.9, 36),
    arrowprops=dict(arrowstyle="->"),
    fontsize=9,
)
ax2.annotate(
    f"sign reversal at {c_dT[0]:.1f} h",
    (c_dT[0], 0),
    (3.4, 20),
    arrowprops=dict(arrowstyle="->"),
    fontsize=9,
)
ax2.annotate(
    f"{h.bore_to_rim_dT_K.iloc[-1]:.1f} K at 6 h",
    (6, h.bore_to_rim_dT_K.iloc[-1]),
    (4.2, -33),
    arrowprops=dict(arrowstyle="->"),
    fontsize=9,
)
ax.legend(loc="upper left", fontsize=8.5, frameon=False, bbox_to_anchor=(0.0, 0.93))
ax.set_title(
    "2  The flange's radial temperature gradient reverses: "
    "the bore leads for ~1.5 h, then the rim overtakes",
    loc="left",
    fontsize=10.5,
    fontweight="bold",
)
ax = axs[2]
joint = h.Q_main_seat_W + h.Q_seal_land_W
for col, lab, c, ls in [
    ("Q_main_seat_W", "main seat", "#1b9e77", "-"),
    ("Q_seal_land_W", "seal land", "#66a61e", "-"),
    ("Q_barrier_foot_W", "barrier foot → flange", "#7570b3", "-"),
    ("Q_vertical_fit_W", "vertical fit: casing → barrier", "#e7298a", "-"),
    ("Q_stud_anchor_W", "stud anchor: casing → stud", "#d95f02", "-"),
    ("Q_nut_bearing_W", "nut bearing: nut → flange", "#a6761d", "--"),
]:
    ax.plot(t[1:], h[col][1:], color=c, lw=2, ls=ls, label=lab)
ax.axhline(0, color="k", lw=0.8)
ax.annotate(
    f"vertical fit reverses\nat {c_vf[0]:.2f} h ({c_vf[0] * 60:.0f} min)",
    (c_vf[0], 0),
    (1.55, -700),
    arrowprops=dict(arrowstyle="->"),
    fontsize=9,
)
ax.annotate(
    f"stud path peaks:\n{h.Q_stud_anchor_W.max():.0f} W at {h.time_s[stud_pk] / 3600:.1f} h",
    (h.time_s[stud_pk] / 3600, h.Q_stud_anchor_W.max()),
    (3.5, 1500),
    arrowprops=dict(arrowstyle="->"),
    fontsize=9,
)
ax.annotate(
    f"seat peaks {h.Q_main_seat_W.max():.0f} W\nat {h.time_s[seat_pk] / 3600:.1f} h",
    (h.time_s[seat_pk] / 3600, h.Q_main_seat_W.max()),
    (2.3, 3700),
    arrowprops=dict(arrowstyle="->"),
    fontsize=9,
)
ax.set_ylabel("Heat across contact [W]")
ax.set_xlabel("Time [h]")
ax.legend(ncol=2, fontsize=8.5, loc="lower right", frameon=False)
ax.set_xlim(0, 6)
ax.set_ylim(-1200, 4100)
ax.set_title(
    "3  Parallel heat paths from the casing into the flange evolve very differently",
    loc="left",
    fontsize=10.5,
    fontweight="bold",
)
fig.suptitle(
    "Six-hour heat-up of the closure: history of the whole assembly",
    fontsize=13.5,
    fontweight="bold",
    y=0.93,
)
save(fig, "fig03_heatup_history.png")
