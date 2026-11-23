"""Shared loaders/helpers for the pump-closure showcase figures (reads out/*.h5 and *.csv only)."""

from __future__ import annotations

import json
from pathlib import Path

import h5py
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.tri import Triangulation

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out"
FIG = HERE / "figures"
FIG.mkdir(exist_ok=True)
P = json.loads((HERE.parent / "closure.json").read_text())
K0 = 273.15
BODIES = [
    "casing",
    "barrier",
    "stud",
    "nut",
    "flange_inner",
    "flange_band",
    "flange_outer",
    "shell",
    "liner",
]
BODY_LABEL = {
    "casing": "Casing",
    "barrier": "Thermal barrier",
    "stud": "Stud ring D",
    "nut": "Nut ring N",
    "flange_inner": "Flange (inner)",
    "flange_band": "Band G (stud mix)",
    "flange_outer": "Flange (outer)",
    "shell": "Stator shell S",
    "liner": "Liner L",
}
BODY_COLOR = {
    "casing": "#8da0cb",
    "barrier": "#66c2a5",
    "stud": "#fc8d62",
    "nut": "#e78ac3",
    "flange_inner": "#d9d9d9",
    "flange_band": "#ffd92f",
    "flange_outer": "#bdbdbd",
    "shell": "#a6d854",
    "liner": "#b3b3b3",
}
FILM_COLOR = {"H": "#d62728", "M": "#ff7f0e", "Cw": "#1f77b4", "J": "#17becf", "A": "#7f7f7f"}

plt.rcParams.update(
    {
        "font.size": 10,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.25,
        "figure.dpi": 100,
        "savefig.dpi": 170,
    }
)


class Run:
    """One results file: nodes [m], quadratic triangles, regions, temperature [degC] per step."""

    def __init__(self, name):
        with h5py.File(OUT / f"{name}.tfea.h5", "r") as f:
            self.nodes = f["mesh/nodes"][:]
            self.conn = f["mesh/blocks/0/conn"][:]
            self.region = f["mesh/blocks/0/region"][:]
            self.T = f["steps/fields/T"][:] - K0
            self.t = f["steps/time"][:]
            self.react = {
                k: f[f"reactions/{i}"][:] for i, k in enumerate(["H", "M", "Cw", "J", "A"])
            }
        c = self.conn
        sub = np.vstack([c[:, [0, 3, 5]], c[:, [3, 1, 4]], c[:, [5, 4, 2]], c[:, [3, 4, 5]]])
        self.tri = Triangulation(self.nodes[:, 0] * 1e3, self.nodes[:, 1] * 1e3, sub)  # mm
        self.body = self._classify()  # body name per element (region ids are not in BODIES order)
        self.sub_region = np.tile(self.region, 4)
        self.corner = Triangulation(self.nodes[:, 0] * 1e3, self.nodes[:, 1] * 1e3, c[:, :3])

    def _classify(self):
        """Name each region from where its elements sit (mm), using the closure.json dimensions."""
        g = P["geometry"]
        f = g["flange"]
        s = g["studs"]
        cen = self.nodes[self.conn[:, :3]].mean(axis=1) * 1e3
        out = {}
        for rid in np.unique(self.region):
            r, z = cen[self.region == rid].mean(axis=0)
            if (
                z > 0
                and abs(r - s["bolt_circle_r"]) < 10
                and z < s["grip"]
                and cen[self.region == rid][:, 0].std() < 8
            ):
                nm = "stud"
            elif (
                z > 0
                and r < 560
                and z < 95
                and r < 550 + 5
                and cen[self.region == rid][:, 0].max() < 553
            ):
                nm = "barrier"
            elif z > 0 and (cen[self.region == rid][:, 1].max() > 120):
                nm = "casing"
            elif (
                -g["extension_below_flange"] - f["thickness"] - 1 < z < -f["thickness"] and r > 700
            ):
                nm = "nut"
            elif z < -f["thickness"]:
                nm = "liner" if r < g["shell"]["r_in"] else "shell"
            elif r < f["band_r_in"]:
                nm = "flange_inner"
            elif r < f["band_r_out"]:
                nm = "flange_band"
            else:
                nm = "flange_outer"
            out[rid] = nm
        assert sorted(out.values()) == sorted(BODIES), out
        return out

    def body_of_sub(self):
        return np.array([self.body[r] for r in self.sub_region])


def save(fig, name):
    p = FIG / name
    fig.savefig(p, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def style_rz(ax, xlim=None, ylim=None):
    ax.set_aspect("equal")
    ax.set_xlabel("r [mm]")
    ax.set_ylabel("z [mm]")
    ax.grid(False)
    if xlim:
        ax.set_xlim(*xlim)
    if ylim:
        ax.set_ylim(*ylim)
