"""Seat-conductance study and mesh check of the pump-closure demonstration (sheet 5).

Usage (from the project folder)::

    .venv\\Scripts\\python.exe examples\\pump_closure\\seat_study.py
    .venv\\Scripts\\python.exe examples\\pump_closure\\seat_study.py --mesh-check

The study solves the steady hot case (H at a constant T_end) once per factor in
``closure.json`` ``study.seat_factors``, scaling only the main-seat contact conductance,
and writes ``seat_study.csv`` and ``seat_study.png``: heat across the seated joint and
through the stud anchor, and the flange bore-to-rim difference, against the factor.

``--mesh-check`` solves the steady hot case with the element sizes of ``closure.json`` and
with both sizes halved, and compares the quantities sheet 5 names (flange bore-to-rim
difference, contact-side temperatures, mean stud temperature, cooling duty) against its
example criteria: changes under 1 K and 2 % in duty.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import closure_model as cm
import numpy as np
from matplotlib.figure import Figure
from run_closure import solve, write_csv

#: Example convergence criteria of sheet 5.
MAX_DT_CHANGE = 1.0  # K
MAX_DUTY_CHANGE = 0.02  # relative


def duty(row: dict[str, float]) -> float:
    """Heat removed by the coolant films M, Cw and J [W] (positive)."""
    return -(row["Q_film_M_W"] + row["Q_film_Cw_W"] + row["Q_film_J_W"])


def study(out: Path) -> None:
    """Steady hot case for every seat factor."""
    factors = cm.load_params()["study"]["seat_factors"]
    rows = []
    for factor in factors:
        _, history = solve("steady", out, seat_factor=factor, tag=f"_seat{factor:g}")
        row = {"seat_factor": factor, **history[-1]}
        row["Q_joint_W"] = row["Q_main_seat_W"] + row["Q_seal_land_W"]
        rows.append(row)
    write_csv(rows, out / "seat_study.csv")

    f = np.array(factors)
    fig = Figure(figsize=(8, 6.5), layout="constrained")
    ax1, ax2 = fig.subplots(2, 1, sharex=True)
    ax1.semilogx(f, [r["Q_joint_W"] for r in rows], "o-", label="seated joint (seal + seat)")
    ax1.semilogx(f, [r["Q_barrier_foot_W"] for r in rows], "o-", label="barrier foot")
    ax1.semilogx(f, [r["Q_stud_anchor_W"] for r in rows], "o-", label="stud anchor")
    ax1.set_ylabel("Heat into flange path [W]")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3, which="both")
    ax2.semilogx(f, [r["bore_to_rim_dT_K"] for r in rows], "o-", color="C3")
    ax2.set_ylabel("Flange bore - rim [K]")
    ax2.set_xlabel("Main-seat conductance factor (1 = 3000 W/(m^2 K))")
    ax2.grid(alpha=0.3, which="both")
    fig.suptitle("Steady hot case: effect of the main-seat conductance")
    fig.savefig(out / "seat_study.png", dpi=130)

    w = sys.stdout.write
    w("\nSeat study (steady hot case)\n")
    w(
        f"  {'factor':>6s} {'joint W':>9s} {'foot W':>9s} {'anchor W':>9s} {'stud %':>7s}"
        f" {'bore-rim K':>10s} {'stud degC':>9s}\n"
    )
    for r in rows:
        into_flange = r["Q_joint_W"] + r["Q_barrier_foot_W"] + r["Q_stud_anchor_W"]
        w(
            f"  {r['seat_factor']:6g} {r['Q_joint_W']:9.1f} {r['Q_barrier_foot_W']:9.1f}"
            f" {r['Q_stud_anchor_W']:9.1f} {100 * r['Q_stud_anchor_W'] / into_flange:7.1f}"
            f" {r['bore_to_rim_dT_K']:10.2f} {r['stud_mean_C']:9.2f}\n"
        )


def mesh_check(out: Path) -> bool:
    """Steady hot case with the element sizes as given and halved."""
    p = cm.load_params()
    rows = {}
    for factor in (1.0, 0.5):
        results, history = solve("steady", out, mesh_factor=factor, tag=f"_mesh{factor:g}")
        rows[factor] = (history[-1], results)

    def sides(results) -> tuple[float, float]:
        """Mean temperatures [degC] on the casing and flange sides of the main seat.

        The mesh in the results is opened along the contacts: every seat position has one
        node on the casing side and one on the flange side, told apart by their region.
        """
        g = p["geometry"]
        mesh, T = results.mesh, results.temperature()
        region = np.full(mesh.n_nodes, -1)
        for block in mesh.blocks:
            region[block.conn] = block.region[:, None]
        casing = np.isin(region, results.model.selections["casing"].tags)
        x, z = mesh.nodes[:, 0], mesh.nodes[:, 1]
        on = (
            (np.abs(z) < cm.TOL)
            & (x > g["seal_land_r_out"] * cm.MM + cm.TOL)
            & (x < g["casing_vertices"][-1][0] * cm.MM - cm.TOL)
        )
        return T[on & casing].mean() - cm.KELVIN, T[on & ~casing].mean() - cm.KELVIN

    w = sys.stdout.write
    w("\nMesh check (steady hot case; element sizes x1 and x0.5)\n")
    (c, rc), (f, rf) = rows[1.0], rows[0.5]
    checks = [
        ("bore - rim [K]", c["bore_to_rim_dT_K"], f["bore_to_rim_dT_K"]),
        ("mean stud [degC]", c["stud_mean_C"], f["stud_mean_C"]),
        ("seat, casing side [degC]", sides(rc)[0], sides(rf)[0]),
        ("seat, flange side [degC]", sides(rc)[1], sides(rf)[1]),
    ]
    ok = True
    for label, a, b in checks:
        good = abs(a - b) < MAX_DT_CHANGE
        ok &= good
        w(f"  {label:26s} {a:10.3f} {b:10.3f}  change {b - a:+.3f} K  {'ok' if good else 'NO'}\n")
    da, db = duty(c), duty(f)
    good = abs(db - da) / da < MAX_DUTY_CHANGE
    ok &= good
    w(
        f"  {'cooling duty [W]':26s} {da:10.1f} {db:10.1f}  change {100 * (db - da) / da:+.2f} %"
        f"  {'ok' if good else 'NO'}\n"
    )
    w(f"  nodes: {rc.mesh.n_nodes} and {rf.mesh.n_nodes}\n")
    return ok


def main(argv: list[str] | None = None) -> int:
    """Run the study, or the mesh check with ``--mesh-check``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mesh-check", action="store_true", help="compare sizes x1 and x0.5")
    parser.add_argument("--out", type=Path, default=cm.HERE / "out", help="output folder")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)
    args.out.mkdir(parents=True, exist_ok=True)
    if args.mesh_check:
        return 0 if mesh_check(args.out) else 1
    study(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
