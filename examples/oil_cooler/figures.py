"""Figures of the oil-cooler example (``examples/oil_cooler/README.md``).

All temperatures are plotted in degC (the model works in K); the axial coordinate is z, from
the oil inlet (z = 0) to the oil outlet (z = L). ``make_figures(result)`` takes the dict of
``oil_cooler.run()``.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import oil_cooler as oc  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Rectangle  # noqa: E402

K0 = 273.15
OIL_C, WATER_C, COPPER_C, SHELL_C = "#c8641e", "#1f6fb4", "#b87333", "#8a8f96"
plt.rcParams.update({
    "font.size": 10, "axes.grid": True, "grid.alpha": 0.3, "axes.spines.top": False,
    "axes.spines.right": False, "figure.dpi": 110, "savefig.dpi": 150,
})  # fmt: skip


def _save(fig, name: str) -> Path:
    oc.IMAGES.mkdir(exist_ok=True)
    path = oc.IMAGES / name
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def cutaway() -> Path:
    """The owner's illustration, scaled to 1400 px wide for the page."""
    from PIL import Image

    source = oc.HERE / "spec" / "Cutaway double-pipe lube oil cooler.png"
    image = Image.open(source)
    width = 1400
    image = image.resize((width, round(image.height * width / image.width)), Image.LANCZOS)
    path = oc.IMAGES / "cooler-cutaway.png"
    oc.IMAGES.mkdir(exist_ok=True)
    image.save(path, optimize=True)
    return path


def model_definition() -> Path:
    """Half-section of the modelled span: what is meshed, what is a stream, where heat goes."""
    fig, ax = plt.subplots(figsize=(10, 3.6))
    L = oc.LENGTH
    # radial sizes drawn to scale against each other, axial length compressed
    ri, ro, rs = oc.D_I / 2 * 1e3, oc.D_O / 2 * 1e3, oc.D_S / 2 * 1e3  # mm
    zl = 100.0  # drawing length
    ax.add_patch(Rectangle((0, 0), zl, ri, color="#f3c98b", lw=0))
    ax.add_patch(Rectangle((0, ri), zl, ro - ri, color=COPPER_C, lw=0))
    ax.add_patch(Rectangle((0, ro), zl, rs - ro, color="#a9d2f3", lw=0))
    ax.add_patch(Rectangle((0, rs), zl, 0.6, color=SHELL_C, lw=0))
    ax.plot([-4, zl + 4], [0, 0], "k-.", lw=0.8)
    ax.text(zl + 5, 0, "axis (r = 0)", va="center", fontsize=9)
    kw = dict(arrowstyle="-|>", mutation_scale=16, lw=2)
    ax.add_patch(FancyArrowPatch((30, ri / 2), (70, ri / 2), color=OIL_C, **kw))
    ax.add_patch(FancyArrowPatch((70, (ro + rs) / 2), (30, (ro + rs) / 2), color=WATER_C, **kw))
    ax.text(
        50,
        ri / 2 + 1.0,
        f"oil stream (in-plane), {oc.M_OIL * 1e3:.0f} g/s, {oc.T_OIL_IN - K0:.0f} °C in",
        ha="center",
        color="#7a3a08",
        fontsize=9,
    )
    ax.text(50, (ro + rs) / 2 + 0.9, f"water stream (in-plane, annulus), "
            f"{oc.M_WATER * 1e3:.0f} g/s, {oc.T_WATER_IN - K0:.0f} °C in", ha="center",
            color="#0d3f6b", fontsize=9)  # fmt: skip
    ax.text(
        50,
        (ri + ro) / 2,
        "copper tube wall: the only meshed solid",
        ha="center",
        va="center",
        color="white",
        fontsize=8.5,
        weight="bold",
    )
    ax.text(50, rs + 1.1, "shell (adiabatic, not meshed)", ha="center", color="#555", fontsize=9)
    for z, label in (
        (0, "z = 0\noil in · water out"),
        (zl, f"z = L = {L:g} m\noil out · water in"),
    ):
        ax.plot([z, z], [-0.4, rs + 0.6], "k:", lw=0.8)
        ax.text(z, -1.6, label, ha="center", va="top", fontsize=9)
    # radial dimensions
    for r, text in ((ri, f"D_i/2 = {ri:.3f} mm"), (ro, f"D_o/2 = {ro:.2f} mm"),
                    (rs, f"D_s/2 = {rs:.1f} mm")):  # fmt: skip
        ax.annotate(
            text,
            xy=(zl, r),
            xytext=(zl + 14, r + (0.4 if r == rs else 0)),
            fontsize=8.5,
            va="center",
            arrowprops=dict(arrowstyle="-", lw=0.6),
        )
    ax.set_xlim(-8, zl + 40)
    ax.set_ylim(-4.5, rs + 2.5)
    ax.set_aspect("auto")
    ax.axis("off")
    ax.set_title("Model definition: axisymmetric half-section (radius to scale, length "
                 "compressed)", fontsize=10.5)  # fmt: skip
    return _save(fig, "cooler-model.png")


def profiles(result: dict) -> Path:
    """Steady counterflow profiles of the correlation run, with the e-NTU outlets marked."""
    p = result["correlation"]["profiles"]
    rows = result["correlation"]["rows"]
    ntu = result["correlation"]["ntu"]
    fig, ax = plt.subplots(figsize=(9, 5))
    ax.plot(p["z_oil"], p["T_oil"] - K0, color=OIL_C, lw=2.2, label="oil, bulk")
    ax.plot(p["z_oil_wall"], p["T_oil_wall"] - K0, color=OIL_C, lw=1.2, ls="--",
            label="copper, oil-side face")  # fmt: skip
    ax.plot(p["z_water_wall"], p["T_water_wall"] - K0, color=WATER_C, lw=1.2, ls="--",
            label="copper, water-side face")  # fmt: skip
    ax.plot(p["z_water"], p["T_water"] - K0, color=WATER_C, lw=2.2, label="water, bulk")
    L = oc.LENGTH
    ax.plot([L], [ntu.T_oil_out - K0], "o", mfc="none", mec="k", ms=8,
            label="effectiveness-NTU outlets")  # fmt: skip
    ax.plot([0.0], [ntu.T_water_out - K0], "o", mfc="none", mec="k", ms=8)
    oil, water = rows[oc.OIL_STREAM], rows[oc.WATER_STREAM]
    note = dict(fontsize=9, ha="left")
    box = dict(fc="white", ec="none", alpha=0.85, pad=1.5)
    ax.annotate(f"oil in {oil.T_in - K0:.1f} °C", (0, oil.T_in - K0), (0.06, oil.T_in - K0 + 2.5),
                color=OIL_C, bbox=box, **note)  # fmt: skip
    ax.annotate(f"oil out {oil.T_out - K0:.1f} °C", (L, oil.T_out - K0),
                (L - 0.52, oil.T_out - K0 + 4.5), color=OIL_C, bbox=box,
                arrowprops=dict(arrowstyle="-", color=OIL_C, lw=0.7), **note)  # fmt: skip
    ax.annotate(f"water out {water.T_out - K0:.1f} °C", (0, water.T_out - K0),
                (0.06, water.T_out - K0 - 6.5), color=WATER_C, bbox=box,
                arrowprops=dict(arrowstyle="-", color=WATER_C, lw=0.7), **note)  # fmt: skip
    ax.annotate(f"water in {water.T_in - K0:.1f} °C", (L, water.T_in - K0),
                (L - 0.52, water.T_in - K0 - 6.5), color=WATER_C, bbox=box,
                arrowprops=dict(arrowstyle="-", color=WATER_C, lw=0.7), **note)  # fmt: skip
    mid_oil = float(np.interp(1.0, p["z_oil"], p["T_oil"])) - K0
    mid_water = float(np.interp(1.0, p["z_water"][::-1], p["T_water"][::-1])) - K0
    for y, z0, z1, c, text in ((mid_oil + 6.0, 0.8, 1.2, OIL_C, "oil flow"),
                               (mid_water - 6.0, 1.2, 0.8, WATER_C, "water flow")):  # fmt: skip
        ax.add_patch(FancyArrowPatch((z0, y), (z1, y), arrowstyle="-|>", mutation_scale=14,
                                     color=c, lw=1.6))  # fmt: skip
        ax.text(1.0, y + (1.2 if c == OIL_C else -2.8), text, color=c, ha="center", fontsize=9)
    ax.text(1.0, 0.5 * (mid_oil + mid_water) + 6.0,
            "the copper sits close to the water: the laminar oil film\n"
            "is the controlling resistance; the two wall faces differ by < 0.1 K",
            ha="center", fontsize=8.5, color="#555", style="italic")  # fmt: skip
    ax.set_xlabel("axial position z [m]   (z = 0: oil inlet)")
    ax.set_ylabel("temperature [°C]")
    ax.set_xlim(0, L)
    ax.set_ylim(water.T_in - K0 - 9, oil.T_in - K0 + 8)
    ax.set_title(f"Counterflow temperature profiles, steady, Q = {water.heat:.1f} W")
    ax.legend(loc="upper right", fontsize=9, framealpha=0.95)
    return _save(fig, "cooler-profiles.png")


def local_transfer(result: dict) -> Path:
    """Local temperature difference and heat transfer per metre along the exchanger."""
    p = result["correlation"]["profiles"]
    rows = result["correlation"]["rows"]
    c_oil = result["correlation"]["ntu"].C_oil
    z = p["z_oil"]
    T_w = np.interp(z, p["z_water"][::-1], p["T_water"][::-1])
    dT = p["T_oil"] - T_w
    zc = 0.5 * (z[1:] + z[:-1])
    q_line = -c_oil * np.diff(p["T_oil"]) / np.diff(z)  # W/m released by the oil
    oil, water = rows[oc.OIL_STREAM], rows[oc.WATER_STREAM]
    d1, d2 = oil.T_in - water.T_out, oil.T_out - water.T_in
    lmtd = (d1 - d2) / np.log(d1 / d2)
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.plot(z, dT, color="k", lw=2, label="local ΔT = T_oil − T_water")
    ax.axhline(lmtd, color="k", ls=":", lw=1, label=f"LMTD = {lmtd:.1f} K")
    ax.set_xlabel("axial position z [m]")
    ax.set_ylabel("temperature difference [K]")
    ax.set_xlim(0, oc.LENGTH)
    ax2 = ax.twinx()
    ax2.plot(zc, q_line, color="#7b3fa0", lw=1.6, label="heat transfer per metre")
    ax2.set_ylabel("q′ [W/m]", color="#7b3fa0")
    ax2.tick_params(axis="y", colors="#7b3fa0")
    ax2.grid(False)
    ax2.spines["right"].set_visible(True)
    ax2.set_ylim(0, max(q_line) * 1.15)
    ax.set_ylim(0, max(dT) * 1.15)
    lines = ax.get_legend_handles_labels()
    lines2 = ax2.get_legend_handles_labels()
    ax.legend(lines[0] + lines2[0], lines[1] + lines2[1], loc="upper right", fontsize=9)
    ax.set_title("Driving temperature difference and local heat transfer")
    return _save(fig, "cooler-local.png")


def verification(result: dict) -> Path:
    """Solver against effectiveness-NTU at four axial meshes (constant film coefficients)."""
    rows = result["reference"]["rows"]
    n = [r["n_axial"] for r in rows]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(10, 3.8))
    a1.plot(n, [abs(r["dT_oil_out"]) for r in rows], "o-", color=OIL_C, label="oil outlet")
    a1.plot(n, [abs(r["dT_water_out"]) for r in rows], "s-", color=WATER_C,
            label="water outlet")  # fmt: skip
    a1.set_xscale("log")
    a1.set_xticks(n, [str(v) for v in n])
    a1.minorticks_off()
    a1.set_xlabel("axial elements = stream cells")
    a1.set_ylabel("|solver − e-NTU| [K]")
    a1.set_ylim(0, 0.01)
    a1.legend(fontsize=9)
    a1.set_title("Outlet temperatures")
    a2.plot(n, [abs(r["dQ_oil_pct"]) for r in rows], "o-", color=OIL_C, label="oil release")
    a2.plot(n, [abs(r["dQ_water_pct"]) for r in rows], "s--", color=WATER_C,
            label="water gain")  # fmt: skip
    a2.set_xscale("log")
    a2.set_xticks(n, [str(v) for v in n])
    a2.minorticks_off()
    a2.set_xlabel("axial elements = stream cells")
    a2.set_ylabel("|duty error| [%]")
    a2.set_ylim(0, 0.05)
    a2.legend(fontsize=9)
    a2.set_title("Heat duty")
    fig.suptitle("Verification: constant film coefficients, solver against "
                 "effectiveness-NTU", fontsize=11)  # fmt: skip
    fig.tight_layout()
    return _save(fig, "cooler-verification.png")


def startup(result: dict) -> Path:
    """Start-up: temperatures and duties after the 20 K oil-inlet rise."""
    s, after = result["startup"], result["after"]["rows"]
    t = s["times"]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 7.2), sharex=True)
    a1.plot(t, s["T_oil_in"] - K0, color=OIL_C, lw=1.2, ls="-.", label="oil inlet")
    a1.plot(t, s["T_oil_out"] - K0, color=OIL_C, lw=2, label="oil outlet")
    a1.plot(t, s["T_mid"] - K0, color=COPPER_C, lw=2, ls="--", label="copper, mid-length")
    a1.plot(t, s["T_water_out"] - K0, color=WATER_C, lw=2, label="water outlet")
    for name, colour in ((oc.OIL_STREAM, OIL_C), (oc.WATER_STREAM, WATER_C)):
        a1.axhline(after[name].T_out - K0, color=colour, lw=0.8, ls=":")
    a1.text(t[-1], after[oc.OIL_STREAM].T_out - K0 + 1.2, "dotted: steady after the step",
            ha="right", fontsize=8.5, color="#444")  # fmt: skip
    a1.set_ylabel("temperature [°C]")
    a1.legend(loc="upper center", bbox_to_anchor=(0.5, 0.86), fontsize=9, ncol=4,
              framealpha=0.95)  # fmt: skip
    a1.set_title("Start-up: oil inlet 76.9 → 96.9 °C over 1 s; water inlet and flows held")
    a1.text(0.99, 0.30, "quasi-steady streams: the outlets respond without transit delay\n"
            "(real transit time over 2 m: oil ≈ 70 s, water ≈ 125 s)", transform=a1.transAxes,
            ha="right", fontsize=8.5, color="#444", style="italic")  # fmt: skip
    a2.plot(t, s["q_oil"], color=OIL_C, lw=2, label="heat released by the oil")
    a2.plot(t, s["q_water"], color=WATER_C, lw=2, label="heat gained by the water")
    a2.fill_between(t, s["q_water"], s["q_oil"], color=COPPER_C, alpha=0.25,
                    label="stored in the copper")  # fmt: skip
    rel = 100 * (s["stored"] - s["delta_u"]) / s["delta_u"]
    a2.text(0.98, 0.08, f"∫(Q_oil − Q_water) dt = {s['stored']:.0f} J\n"
            f"copper ΔU = {s['delta_u']:.0f} J  ({rel:+.2f} %)", transform=a2.transAxes,
            ha="right", va="bottom", fontsize=9,
            bbox=dict(fc="white", ec="#ccc"))  # fmt: skip
    a2.set_xlabel("time [s]")
    a2.set_ylabel("heat flow [W]")
    a2.legend(loc="center right", bbox_to_anchor=(1.0, 0.55), fontsize=9)
    a2.set_xlim(0, t[-1])
    fig.tight_layout()
    return _save(fig, "cooler-startup.png")


def wall_response(result: dict) -> Path:
    """Copper temperature (water-side face) along z at several times of the start-up."""
    results = result["startup"]["results"]
    times = result["startup"]["times"]
    fig, ax = plt.subplots(figsize=(9, 4.4))
    cmap = plt.get_cmap("plasma")
    picks = [0.0, 1.0, 3.0, 6.0, 12.0, 25.0, 50.0, times[-1]]
    for i, when in enumerate(picks):
        step = int(np.argmin(abs(times - when)))
        z, T = oc.flow.wall_temperature(results, oc.WATER_STREAM, step)
        ax.plot(oc.LENGTH - np.asarray(z), np.asarray(T) - K0, color=cmap(i / len(picks)),
                lw=1.8, label=f"t = {times[step]:.0f} s")  # fmt: skip
    ax.set_xlabel("axial position z [m]   (z = 0: oil inlet)")
    ax.set_ylabel("copper temperature [°C]")
    ax.set_xlim(0, oc.LENGTH)
    ax.legend(fontsize=9, ncol=2)
    ax.set_title("Copper wall response to the oil-inlet step (water-side face)")
    return _save(fig, "cooler-wall-response.png")


def make_figures(result: dict) -> list[Path]:
    """Write every figure of the page; returns their paths."""
    return [
        cutaway(), model_definition(), profiles(result), local_transfer(result),
        verification(result), startup(result), wall_response(result),
    ]  # fmt: skip
