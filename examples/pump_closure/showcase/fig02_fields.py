from common import Run, np, plt, save, style_rz

run = Run("closure_transient")
st = Run("closure_steady")
assert np.allclose(run.nodes, st.nodes)  # same mesh -> can difference the fields
times_min = [5, 30, 60, 120, 240, 360]
idx = [int(np.argmin(abs(run.t / 60 - m))) for m in times_min]
levels = np.linspace(35, 180, 30)
fig, axs = plt.subplots(2, 4, figsize=(14.5, 9.4), gridspec_kw={"wspace": 0.06, "hspace": 0.22})
axs = axs.ravel()
panels = [(run.T[i], f"t = {run.t[i] / 60:.0f} min") for i in idx] + [
    (st.T[-1], "steady state (H held at 180 °C)")
]
for ax, (T, ttl) in zip(axs, panels, strict=False):
    cf = ax.tricontourf(run.tri, T, levels=levels, cmap="inferno", extend="both")
    ax.tricontour(run.tri, T, levels=np.arange(40, 181, 20), colors="w", linewidths=0.35, alpha=0.7)
    style_rz(ax, (100, 810), (-340, 310))
    ax.set_title(ttl, fontsize=10.5)
# difference panel: what is still to come after 6 h
ax = axs[7]
diff = st.T[-1] - run.T[-1]
cd = ax.tricontourf(run.tri, diff, levels=np.linspace(0, max(diff.max(), 1), 25), cmap="viridis")
style_rz(ax, (100, 810), (-340, 310))
ax.set_title("steady − 360 min: rise still to come", fontsize=10)
for a in axs[:4]:
    a.set_xlabel("")
for k in (1, 2, 3, 5, 6, 7):
    axs[k].set_ylabel("")
    axs[k].set_yticklabels([])
for a in axs:
    a.set_xticks([200, 400, 600, 800])
    a.tick_params(labelsize=8)
c1 = fig.colorbar(
    cf,
    ax=axs[:7],
    orientation="horizontal",
    fraction=0.025,
    pad=0.1,
    shrink=0.55,
    label="Temperature [°C]",
    ticks=np.arange(40, 181, 20),
)
fig.colorbar(
    cd,
    ax=axs[7],
    orientation="horizontal",
    fraction=0.04,
    pad=0.2,
    label="ΔT to steady [K]",
    ticks=[0, 1, 2, 3, 4],
)
fig.suptitle(
    "Heat-up of the closure: heat enters along the barrier and casing first; "
    "the flange and studs lag by hours",
    fontsize=13,
    fontweight="bold",
    y=0.95,
)
print("max remaining rise [K]", diff.max(), "at", run.nodes[np.argmax(diff)] * 1e3)
save(fig, "fig02_temperature_evolution.png")
