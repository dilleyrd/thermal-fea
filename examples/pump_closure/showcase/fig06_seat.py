import pandas as pd
from common import OUT, plt, save

s = pd.read_csv(OUT / "seat_study.csv")
x = s.seat_factor.values
fig, axs = plt.subplots(1, 3, figsize=(16, 5.4), gridspec_kw={"wspace": 0.28})
ax = axs[0]
for col, lab, c in [
    ("Q_main_seat_W", "main seat", "#1b9e77"),
    ("Q_barrier_foot_W", "barrier foot", "#7570b3"),
    ("Q_vertical_fit_W", "vertical fit", "#e7298a"),
    ("Q_stud_anchor_W", "stud anchor", "#d95f02"),
    ("Q_seal_land_W", "seal land", "#66a61e"),
]:
    ax.plot(x, s[col], "o-", color=c, lw=2, label=lab)
    ax.annotate(
        f"{s[col].iloc[-1] / s[col].iloc[0] - 1:+.0%}",
        (x[-1], s[col].iloc[-1]),
        textcoords="offset points",
        xytext=(6, -3),
        fontsize=8.5,
        color=c,
    )
ax.axvline(1, color="k", ls=":", lw=1)
ax.text(1.06, 60, "baseline", fontsize=8.5)
ax.set_xscale("log")
ax.set_xlim(0.08, 18)
ax.set_xlabel("Main-seat conductance factor (× 3000 W/m²K)")
ax.set_ylabel("Steady heat across contact [W]")
ax.set_title("Heat is shifted between paths", loc="left", fontsize=11, fontweight="bold")
ax.legend(fontsize=8.5, frameon=False, loc="center left")
ax = axs[1]
ax.plot(x, s.flange_rim_C, "o-", color="#d62728", lw=2, label="flange rim")
ax.plot(x, s.stud_mean_C, "o-", color="#ff7f0e", lw=2, label="mean stud")
ax.plot(x, s.flange_bore_C, "o-", color="#1f77b4", lw=2, label="flange bore")
ax.set_xscale("log")
ax.set_xlim(0.08, 18)
ax.set_xlabel("Main-seat conductance factor")
ax.set_ylabel("Steady temperature [°C]")
ax.set_title("…but the flange hardly notices", loc="left", fontsize=11, fontweight="bold")
ax.legend(fontsize=8.5, frameon=False, loc="center right")
ax = axs[2]
ax.plot(x, s.Q_main_seat_W + s.Q_seal_land_W, "o-", color="#1b9e77", lw=2, label="seat + seal land")
ax.plot(
    x,
    s.Q_barrier_foot_W + s.Q_stud_anchor_W,
    "o-",
    color="#7570b3",
    lw=2,
    label="barrier foot + stud anchor",
)
ax.set_xscale("log")
ax.set_xlim(0.08, 18)
ax.set_xlabel("Main-seat conductance factor")
ax.set_ylabel("Heat [W]")
d = (s.Q_main_seat_W.iloc[-1] - s.Q_main_seat_W.iloc[-2]) / s.Q_main_seat_W.iloc[-2]
ax.set_title("Diminishing returns", loc="left", fontsize=11, fontweight="bold")
ax.legend(fontsize=8.5, frameon=False)
fig.suptitle(
    "Sensitivity of the steady hot case to the main-seat conductance (100× range, five solves)",
    fontsize=13,
    fontweight="bold",
    y=1.02,
)
save(fig, "fig06_seat_sensitivity.png")
print(
    s[
        [
            "seat_factor",
            "Q_main_seat_W",
            "Q_seal_land_W",
            "Q_barrier_foot_W",
            "Q_vertical_fit_W",
            "Q_stud_anchor_W",
            "flange_rim_C",
            "flange_bore_C",
            "stud_mean_C",
            "bore_to_rim_dT_K",
        ]
    ]
    .round(1)
    .to_string()
)
print("3x->10x main seat change", d)
print((s.Q_main_seat_W / s.Q_main_seat_W.iloc[2]).round(3).tolist())
