from common import (
    BODIES,
    BODY_COLOR,
    BODY_LABEL,
    FILM_COLOR,
    P,
    Run,
    np,
    plt,
    save,
    style_rz,
)
from matplotlib.colors import ListedColormap
from matplotlib.lines import Line2D

g = P["geometry"]
run = Run("closure_transient")
cas = g["casing_vertices"]
b = g["barrier"]
f = g["flange"]
s = g["studs"]
bot = -f["thickness"]
low = bot - g["extension_below_flange"]
seal = g["seal_land_r_out"]
under = b["top_z"] - b["web_thickness"]
w = s["count"] * s["shank_diameter"] ** 2 / (8 * s["bolt_circle_r"])
wn = s["count"] * g["nut"]["equivalent_od"] ** 2 / (8 * s["bolt_circle_r"])
s0, s1 = s["bolt_circle_r"] - w / 2, s["bolt_circle_r"] + w / 2
n0, n1 = s["bolt_circle_r"] - wn / 2, s["bolt_circle_r"] + wn / 2
lip = s["grip"]
segs = {
    "H": [
        ((b["bore_r"], under), (b["bore_r"], b["top_z"])),
        ((b["bore_r"], b["top_z"]), (b["skirt_r_out"], b["top_z"])),
        (tuple(cas[1]), tuple(cas[2])),
        (tuple(cas[2]), tuple(cas[3])),
    ],
    "M": [
        ((b["bore_r"], under), (b["skirt_r_in"], under)),
        ((b["skirt_r_in"], under), (b["skirt_r_in"], 0)),
        ((f["r_in"], 0), (b["skirt_r_in"], 0)),
        ((f["r_in"], bot), (f["r_in"], 0)),
        ((g["liner"]["r_in"], bot), (f["r_in"], bot)),
        ((g["liner"]["r_in"], low), (g["liner"]["r_in"], bot)),
    ],
    "J": [((g["shell"]["r_out"], low), (g["shell"]["r_out"], bot))],
    "A": [
        (tuple(cas[4]), tuple(cas[5])),
        (tuple(cas[5]), tuple(cas[6])),
        (tuple(cas[6]), tuple(cas[7])),
        (tuple(cas[8]), (s0, lip)),
        ((s1, lip), tuple(cas[7])),
        (tuple(cas[9]), tuple(cas[8])),
        ((cas[9][0], 0), (s0, 0)),
        ((s1, 0), (f["r_out"], 0)),
        ((f["r_out"], bot), (f["r_out"], 0)),
        ((g["shell"]["r_out"], bot), (n0, bot)),
        ((n1, bot), (f["r_out"], bot)),
    ],
}
contacts = {
    "main seat": [((seal, 0), tuple(cas[9]))],
    "seal land": [(tuple(cas[0]), (seal, 0))],
    "barrier foot": [((b["skirt_r_in"], 0), (b["skirt_r_out"], 0))],
    "vertical fit": [(tuple(cas[0]), tuple(cas[1]))],
    "stud anchor": [((s0, lip), (s1, lip))],
    "nut bearing": [((n0, bot), (n1, bot))],
}

fig, ax = plt.subplots(figsize=(11, 8.2))
codes = np.array([BODIES.index(x) for x in run.body_of_sub()])
cmap = ListedColormap([BODY_COLOR[x] for x in BODIES])
ax.tripcolor(run.tri, facecolors=codes, cmap=cmap, vmin=-0.5, vmax=8.5, edgecolors="none")
ax.triplot(run.corner, color="k", lw=0.12, alpha=0.35)
for name, ss in segs.items():
    for a, c in ss:
        ax.plot(
            [a[0], c[0]],
            [a[1], c[1]],
            color=FILM_COLOR[name],
            lw=3.2,
            solid_capstyle="butt",
            zorder=5,
        )
cc = P["geometry"]["passage"]
ax.add_patch(
    plt.Circle(
        (cc["r"], cc["z"]),
        cc["diameter"] / 2 * 1.0,
        fill=False,
        ec=FILM_COLOR["Cw"],
        lw=3,
        zorder=6,
    )
)
for _name, ss in contacts.items():
    for a, c in ss:
        ax.plot([a[0], c[0]], [a[1], c[1]], color="k", lw=1.6, ls=(0, (1.5, 1.5)), zorder=7)
style_rz(ax, (100, 830), (-345, 315))
ax.set_title(
    "Axisymmetric r–z model of the pump main closure: 9 bodies, 5 film sets, 6 thermal contacts",
    fontsize=12,
    fontweight="bold",
    loc="left",
)


# callouts
def tag(txt, xy, xyt, c="k"):
    ax.annotate(
        txt,
        xy=xy,
        xytext=xyt,
        fontsize=9,
        color=c,
        arrowprops=dict(arrowstyle="-", color=c, lw=0.8),
        zorder=9,
        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec=c, lw=0.6, alpha=0.9),
    )


tag("Hot primary water H\n3000 W/m²K, 40→180 °C", (200, 90), (110, 190), FILM_COLOR["H"])
tag("Cooled motor cavity M\n800 W/m²K, 55 °C", (340, -70), (130, -120), FILM_COLOR["M"])
tag("Barrier passage Cw\nØ16 mm, 1500 W/m²K, 35 °C", (460, 68), (330, 170), FILM_COLOR["Cw"])
tag("Jacket water J\n1500 W/m²K, 35 °C", (435, -250), (480, -320), FILM_COLOR["J"])
tag("Ambient A\n8 W/m²K, 30 °C", (800, 110), (740, 235), FILM_COLOR["A"])
tag("Main seat\n3000 W/m²K", (625, 0), (600, -90))
tag("Seal land\n500 W/m²K", (556, 0), (440, -45))
tag("Stud anchor\n5000 W/m²K", (740, 82), (650, 20))
tag("Nut bearing\n5000 W/m²K", (740, -150), (610, -255))
tag("Vertical fit\n3000 W/m²K", (550, 45), (440, 120))
handles = [plt.Rectangle((0, 0), 1, 1, fc=BODY_COLOR[x], ec="none") for x in BODIES]
l1 = ax.legend(
    handles,
    [BODY_LABEL[x] for x in BODIES],
    loc="upper left",
    bbox_to_anchor=(1.01, 1.0),
    title="Bodies (one region each)",
    frameon=False,
    fontsize=9,
)
ax.add_artist(l1)
ax.legend(
    [Line2D([0], [0], color=FILM_COLOR[k], lw=3) for k in FILM_COLOR]
    + [Line2D([0], [0], color="k", lw=1.6, ls=(0, (1.5, 1.5)))],
    ["H film", "M film", "Cw film", "J film", "A film", "Contact (resistance)"],
    loc="lower left",
    bbox_to_anchor=(1.01, 0.0),
    title="Boundary conditions",
    frameon=False,
    fontsize=9,
)
ax.text(
    1.01,
    0.5,
    f"{len(run.nodes):,} nodes\n{len(run.conn):,} six-node triangles\n"
    "mesh sizes 10 mm / 1.5 mm\n24 studs → ring D (6.49 mm)\nband G: orthotropic mix",
    transform=ax.transAxes,
    fontsize=9,
    va="top",
)
save(fig, "fig01_model_overview.png")
