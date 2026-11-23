from common import Run, np, plt, save, style_rz
from fluxlib import element_flux
from matplotlib.colors import LogNorm
from scipy.interpolate import LinearNDInterpolator
from scipy.spatial import cKDTree

st = Run("closure_steady")
T = st.T[-1]
cen, qr, qz = element_flux(st, T)
q = np.hypot(qr, qz)
tree = cKDTree(cen)
xy_c = st.nodes[st.conn[:, :3]] * 1e3
edge = np.max(np.linalg.norm(xy_c - np.roll(xy_c, 1, axis=1), axis=2), axis=1)
interp_r = LinearNDInterpolator(cen, qr)
interp_z = LinearNDInterpolator(cen, qz)


def grid(xlim, ylim, n=420):
    gx = np.linspace(*xlim, n)
    gy = np.linspace(*ylim, int(n * (ylim[1] - ylim[0]) / (xlim[1] - xlim[0])))
    X, Y = np.meshgrid(gx, gy)
    d, k = tree.query(np.c_[X.ravel(), Y.ravel()])
    mask = (d > 1.0 * edge[k]).reshape(X.shape)
    U = np.ma.masked_array(interp_r(X, Y), mask=mask | np.isnan(interp_r(X, Y)))
    V = np.ma.masked_array(interp_z(X, Y), mask=mask | np.isnan(interp_z(X, Y)))
    return gx, gy, U, V


fig, axs = plt.subplots(
    1, 2, figsize=(15, 8.2), gridspec_kw={"width_ratios": [0.9, 1.1], "wspace": 0.08}
)
norm = LogNorm(vmin=300, vmax=9e4)
for ax, (xl, yl, dens, title) in zip(
    axs,
    [
        ((100, 810), (-340, 310), 1.1, "Whole section"),
        ((435, 810), (-170, 175), 2.0, "Zoom on the joint, flange and stud ring"),
    ],
    strict=False,
):
    pc = ax.tripcolor(
        st.corner, facecolors=np.clip(q, 300, 9e4), norm=norm, cmap="magma", edgecolors="none"
    )
    gx, gy, U, V = grid(xl, yl)
    sp = ax.streamplot(
        gx,
        gy,
        U,
        V,
        color="white",
        density=dens,
        linewidth=0.7,
        arrowstyle="-",
        broken_streamlines=False,
    )
    ax.tricontour(st.tri, T, levels=np.arange(40, 181, 20), colors="c", linewidths=0.6, alpha=0.8)
    style_rz(ax, xl, yl)
    ax.set_title(title, fontsize=11)
axs[1].set_ylabel("")
fig.colorbar(
    pc,
    ax=axs,
    orientation="horizontal",
    fraction=0.04,
    pad=0.09,
    shrink=0.5,
    label="Heat-flux magnitude [W/m²] (log)",
)
axs[1].text(
    0.02,
    0.02,
    "white: heat-flow streamlines (hot to cold)   cyan: isotherms every 20 K",
    transform=axs[1].transAxes,
    fontsize=8.5,
    color="w",
    bbox=dict(fc="k", alpha=0.5, ec="none"),
)
# annotations
axs[0].annotate(
    "flux concentrates around\nthe cooling passage",
    (460, 77),
    (140, 200),
    color="w",
    arrowprops=dict(arrowstyle="->", color="w"),
    fontsize=9,
)
fig.suptitle(
    "Steady hot case: heat flows from the 180 °C primary water through the casing "
    "into the flange along two parallel routes",
    fontsize=12.5,
    fontweight="bold",
    y=0.96,
)
save(fig, "fig04_steady_heat_flux.png")
