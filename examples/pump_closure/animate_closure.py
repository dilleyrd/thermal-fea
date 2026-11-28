"""Animate the temperature of the pump-closure heat-up as a GIF.

Usage (from the project folder)::

    .venv\\Scripts\\python.exe examples\\pump_closure\\animate_closure.py

Solves the heat-up of ``closure.json`` again with denser output than ``run_closure.py``:
every ``--early-interval`` seconds (default 60) up to ``--early-until`` (default 3600 s,
covering the 30-minute ramp of H and the peak of the joint heat), then every
``run.output_interval`` up to the end time. The animation is written to
``out/closure_heatup.gif`` in degC, mm and minutes, with one color scale for all frames.
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import sys
from pathlib import Path

import closure_model as cm
import numpy as np

from thermalfea import api
from thermalfea.core.units import UnitSettings


def main(argv: list[str] | None = None) -> int:
    """Solve the heat-up with dense early output and write the GIF."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=cm.HERE / "out", help="output folder")
    parser.add_argument("--early-interval", type=float, default=60.0, help="s between frames")
    parser.add_argument("--early-until", type=float, default=3600.0, help="s of dense frames")
    parser.add_argument("--fps", type=float, default=8.0, help="frames per second")
    parser.add_argument("--levels", type=int, default=20, help="contour levels")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stdout)
    args.out.mkdir(parents=True, exist_ok=True)

    p = cm.load_params()
    model, built = cm.build_model(p, kind="transient")
    end, late = float(p["run"]["end_time"]), float(p["run"]["output_interval"])
    early = np.arange(args.early_interval, args.early_until + 1e-9, args.early_interval)
    rest = np.arange(args.early_until + late, end + late / 2, late)
    model.solution = dataclasses.replace(
        model.solution, output_times=[float(t) for t in np.concatenate([early, rest])]
    )
    model.name = "pump closure, heat-up animation"
    model_path = args.out / "closure_animation.tfea"
    api.save(model, model_path)
    mesh = api.mesh(model, built)
    results = api.solve(model, mesh, built=built, path=api.results_path(model_path))

    units = dataclasses.replace(UnitSettings.preset("SI (mm)", temperature="degC"), time="min")
    results.display_units = units
    gif = api.export_animation(
        results, args.out / "closure_heatup.gif", fps=args.fps, dpi=90, levels=args.levels
    )
    sys.stdout.write(f"{results.n_steps} frames written to {gif}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
