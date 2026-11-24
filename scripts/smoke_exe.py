"""Smoke test of the built Windows program (task M11.5).

Run with the project's Python after ``scripts/build_exe.ps1`` has made ``dist/ThermalFEA``::

    .venv\\Scripts\\python.exe scripts\\smoke_exe.py [--dist dist/ThermalFEA]

It drives the *built* executables as subprocesses:

* ``thermalfea-cli.exe info MODEL`` and ``thermalfea-cli.exe solve MODEL -o r.h5``; the results
  file is opened with this environment's ``thermalfea.post.results.Results`` and its
  temperatures must lie between the model's two boundary temperatures;
* ``ThermalFEA.exe --smoke-test MODEL --smoke-out status.json`` with the offscreen Qt
  platform: the window opens, meshes and solves the model and the program exits by itself.

Exit code 0 when every check passes, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODEL = ROOT / "src" / "thermalfea" / "gui" / "examples" / "v01_slab.tfea"
# V-01 slab: 300 K on one face, 400 K on the other (src/thermalfea/gui/examples/v01_slab.tfea)
T_RANGE_K = (300.0, 400.0)
TOL_K = 1e-6
CLI_TIMEOUT_S = 180
GUI_TIMEOUT_S = 180


def _run(command: list[str], timeout: float, env: dict[str, str] | None = None):
    return subprocess.run(
        command, capture_output=True, text=True, timeout=timeout, env=env, check=False
    )


def check_cli(dist: Path, work: Path) -> list[str]:
    """Run ``info`` and ``solve`` of the console program; return the failures."""
    exe = dist / "thermalfea-cli.exe"
    model = work / MODEL.name
    shutil.copy(MODEL, model)
    failures: list[str] = []
    info = _run([str(exe), "info", str(model)], CLI_TIMEOUT_S)
    if info.returncode != 0 or "Mesh:" not in info.stdout:
        failures.append(f"cli info: exit {info.returncode}\n{info.stdout}\n{info.stderr}")
    out = work / "r.h5"
    solve = _run([str(exe), "solve", str(model), "-o", str(out)], CLI_TIMEOUT_S)
    if solve.returncode != 0 or not out.is_file():
        failures.append(f"cli solve: exit {solve.returncode}\n{solve.stdout}\n{solve.stderr}")
        return failures
    from thermalfea.post.results import Results

    temperature = Results(out).temperature()
    low, high = float(temperature.min()), float(temperature.max())
    if low < T_RANGE_K[0] - TOL_K or high > T_RANGE_K[1] + TOL_K or high - low < 1.0:
        failures.append(f"cli solve: temperatures {low:.3f}..{high:.3f} K, "
                        f"expected within {T_RANGE_K}")
    print(f"cli: info ok; solve ok, T = {low:.3f}..{high:.3f} K")
    return failures


def check_gui(dist: Path, work: Path) -> list[str]:
    """Run the windowed program's ``--smoke-test``; return the failures."""
    exe = dist / "ThermalFEA.exe"
    model = work / "gui" / MODEL.name
    model.parent.mkdir()
    shutil.copy(MODEL, model)
    status_file = work / "status.json"
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    try:
        done = _run([str(exe), "--smoke-test", str(model), "--smoke-out", str(status_file)],
                    GUI_TIMEOUT_S, env)
    except subprocess.TimeoutExpired:
        return [f"gui: no exit within {GUI_TIMEOUT_S} s"]
    if not status_file.is_file():
        return [f"gui: no status file, exit {done.returncode}\n{done.stdout}\n{done.stderr}"]
    status = json.loads(status_file.read_text(encoding="utf-8"))
    failures = []
    if done.returncode != 0 or not status.get("ok"):
        failures.append(f"gui: exit {done.returncode}, status {status}")
    elif not T_RANGE_K[0] - TOL_K <= status["t_min"] < status["t_max"] <= T_RANGE_K[1] + TOL_K:
        failures.append(f"gui: temperatures {status['t_min']}..{status['t_max']} K")
    else:
        print(f"gui: ok, {status['nodes']} nodes, "
              f"T = {status['t_min']:.3f}..{status['t_max']:.3f} K")
    return failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dist", type=Path, default=ROOT / "dist" / "ThermalFEA")
    args = parser.parse_args(argv)
    dist = args.dist.resolve()
    for name in ("ThermalFEA.exe", "thermalfea-cli.exe"):
        if not (dist / name).is_file():
            print(f"missing {dist / name}; build first with scripts/build_exe.ps1")
            return 1
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="tfea-smoke-") as tmp:
        work = Path(tmp)
        failures += check_cli(dist, work)
        failures += check_gui(dist, work)
    for text in failures:
        print("FAIL", text)
    print("smoke test " + ("FAILED" if failures else "passed"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
