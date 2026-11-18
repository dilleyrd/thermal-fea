"""Build, mesh and solve the pump-closure demonstration; write results, CSV and plots.

Usage (from the project folder)::

    .venv\\Scripts\\python.exe examples\\pump_closure\\run_closure.py            # heat-up
    .venv\\Scripts\\python.exe examples\\pump_closure\\run_closure.py --steady   # hot case

Writes into ``examples/pump_closure/out`` (or ``--out``):

* ``closure_<kind>.tfea`` - the model; open it in the GUI (File > Open...), mesh and look;
* ``closure_<kind>.tfea.h5`` - the results, attached when the model is opened and meshed;
* ``closure_<kind>_history.csv`` - per stored step: flange bore and rim temperatures, their
  difference, mean stud temperature, heat across every contact and through every film,
  energy imbalance;
* ``closure_<kind>_T.png`` - temperature at the last step (degC, mm);
* ``closure_transient_paths.png`` - heat-up only: heat through the seat and the stud path,
  and the bore-to-rim difference, against time.
"""

from __future__ import annotations

import argparse
import csv
import logging
import sys
import time
from pathlib import Path

import closure_model as cm
from matplotlib.figure import Figure

from thermalfea import api
from thermalfea.core.units import UnitSettings
from thermalfea.post.results import Results
from thermalfea.solver.run import StepInfo

log = logging.getLogger("closure")


def write_csv(rows: list[dict[str, float]], path: Path) -> None:
    """Write one row per stored step."""
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def plot_paths(rows: list[dict[str, float]], path: Path) -> None:
    """Heat through the two parallel paths and the flange bore-to-rim difference vs time."""
    t = [r["time_s"] / 60.0 for r in rows]
    fig = Figure(figsize=(9, 6.5), layout="constrained")
    ax1, ax2 = fig.subplots(2, 1, sharex=True)
    joint = [r["Q_main_seat_W"] + r["Q_seal_land_W"] for r in rows]
    ax1.plot(t, joint, label="casing to flange across seal land + main seat")
    ax1.plot(t, [r["Q_barrier_foot_W"] for r in rows], label="barrier foot into flange")
    ax1.plot(t, [r["Q_stud_anchor_W"] for r in rows], label="casing lip into studs (anchor)")
    ax1.plot(t, [r["Q_nut_bearing_W"] for r in rows], "--", label="nuts into flange underside")
    ax1.set_ylabel("Heat [W]")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.3)
    ax2.plot(t, [r["bore_to_rim_dT_K"] for r in rows], color="C3")
    ax2.set_ylabel("Flange bore - rim [K]")
    ax2.set_xlabel("Time [min]")
    ax2.grid(alpha=0.3)
    fig.suptitle("Pump closure heat-up: the two parallel heat paths")
    fig.savefig(path, dpi=130)


def solve(kind: str, out: Path, seat_factor: float = 1.0, mesh_factor: float = 1.0,
          tag: str = "") -> tuple[Results, list[dict[str, float]]]:  # fmt: skip
    """Build, save, mesh and solve one case; return its results and per-step metrics."""
    p = cm.load_params()
    model, built = cm.build_model(p, kind=kind, seat_factor=seat_factor, mesh_factor=mesh_factor)
    stem = f"closure_{kind}{tag}"
    model_path = out / f"{stem}.tfea"
    api.save(model, model_path)
    mesh = api.mesh(model, built)
    log.info("%s: mesh of %d nodes", stem, mesh.n_nodes)

    def progress(info: StepInfo) -> bool:
        if kind == "transient" and info.step % 20 == 0:
            log.info("  step %d  t = %.0f s  dt = %.3g s", info.step, info.time, info.dt)
        return True

    start = time.perf_counter()
    results = api.solve(model, mesh, progress, built=built, path=api.results_path(model_path))
    log.info("%s: solved in %.1f s, %d stored steps", stem, time.perf_counter() - start,
             results.n_steps)  # fmt: skip
    heats = cm.ContactHeats(model, built, mesh)
    rows = [cm.metrics(p, results, step, heats) for step in range(results.n_steps)]
    return results, rows


def main(argv: list[str] | None = None) -> int:
    """Run the heat-up (default) or the steady hot case."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--steady", action="store_true", help="steady hot case (H at T_end)")
    parser.add_argument("--out", type=Path, default=cm.HERE / "out", help="output folder")
    parser.add_argument("--mesh-factor", type=float, default=1.0, help="scale element sizes")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    for noisy in ("thermalfea",):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    kind = "steady" if args.steady else "transient"
    args.out.mkdir(parents=True, exist_ok=True)

    results, rows = solve(kind, args.out, mesh_factor=args.mesh_factor)
    write_csv(rows, args.out / f"closure_{kind}_history.csv")
    results.display_units = UnitSettings.preset("SI (mm)", temperature="degC")
    api.plot_contour(results, -1, "T", path=args.out / f"closure_{kind}_T.png", levels=16)
    if kind == "transient":
        plot_paths(rows, args.out / "closure_transient_paths.png")

    last = rows[-1]
    out = sys.stdout.write
    out(f"\nPump closure, {kind}, t = {last['time_s']:.0f} s\n")
    out(
        f"  flange bore {last['flange_bore_C']:.2f} degC, rim {last['flange_rim_C']:.2f} degC,"
        f" bore - rim {last['bore_to_rim_dT_K']:.2f} K; mean stud {last['stud_mean_C']:.2f} degC\n"
    )
    out("  heat across contacts [W] (first body -> second body):\n")
    for name, (a, b) in cm.CONTACT_SIDES.items():
        out(f"    {name:13s} {a:>8s} -> {b:<12s} {last[f'Q_{name}_W']:12.1f}\n")
    out("  heat entering through films [W]:\n")
    for name in cm.FILMS:
        out(f"    {name:3s} {last[f'Q_film_{name}_W']:12.1f}\n")
    worst = max(abs(r["relative_imbalance"]) for r in rows[1:]) if len(rows) > 1 else 0.0
    out(f"  energy imbalance: last {last['relative_imbalance']:.2e}, worst {worst:.2e}\n")
    out(f"  files in {args.out}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
