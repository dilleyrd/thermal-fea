"""Command-line entry point for ThermalFEA.

* ``thermalfea info model.tfea`` builds and meshes a model and prints its entity, node and
  element counts.
* ``thermalfea solve model.tfea [-o results.h5]`` solves it, printing one progress line
  per step. The results go to ``model.tfea.h5`` beside the model unless ``-o`` is given.

Exit codes: 0 success, 1 a ThermalFEA error (bad model, geometry or mesh failure, ...),
2 the solution did not converge.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from .core.errors import ConvergenceError, ThermalFEAError
from .core.log import configure_logging

EXIT_OK, EXIT_ERROR, EXIT_NOT_CONVERGED = 0, 1, 2


def _solve(args: argparse.Namespace) -> int:
    from . import api
    from .post.summary import text_summary

    out = sys.stdout.write
    model = api.load(args.model)
    built = api.build(model)
    mesh = api.mesh(model, built)
    path = args.output or api.results_path(args.model)
    out(f"Model:    {model.name} ({model.analysis}, {model.solution.kind})\n")
    out(f"Mesh:     {mesh.n_nodes} nodes, {mesh.n_elements} elements\n")

    def progress(info: api.StepInfo) -> bool:
        if model.solution.kind == "steady":
            out(f"steady solution: {info.iterations} iteration(s), "
                f"residual {info.residual:.3e} W\n")
        else:
            done = 100.0 * info.time / info.end_time if info.end_time else 100.0
            out(f"step {info.step:5d}  t = {info.time:.6g} s  dt = {info.dt:.3g} s  "
                f"iterations {info.iterations}  residual {info.residual:.2e} W  "
                f"({done:.0f} %)\n")
        sys.stdout.flush()
        return True

    results = api.solve(
        model, mesh, progress=progress, built=built, path=path, restart=args.restart
    )
    out(text_summary(results) + "\n")
    out(f"Results:  {results.path}\n")
    return EXIT_OK


def _info(args: argparse.Namespace) -> int:
    from . import api
    from .meshing.quality import report

    model = api.load(args.model)
    built = api.build(model)
    lines = [
        f"Model:     {model.name}",
        f"Analysis:  {model.analysis}, {model.solution.kind}",
        f"Geometry:  {len(built.surfaces)} surfaces, {len(built.curves)} curves, "
        f"{len(built.points)} points",
        f"Materials: {len(model.materials)}    Regions: {len(model.regions)}    "
        f"Loads/BCs: {len(model.bcs)}",
    ]
    if built.surfaces:
        mesh = api.mesh(model, built)
        quality = report(mesh)
        by_type = ", ".join(f"{n} {name}" for name, n in sorted(quality.counts.items()))
        lines += [
            f"Mesh:      {mesh.n_nodes} nodes, {mesh.n_elements} elements ({by_type})",
            f"Quality:   minimum angle {quality.min_angle.min():.1f} deg, "
            f"largest aspect ratio {quality.aspect_ratio.max():.2f}",
        ]
    else:
        lines.append("Mesh:      no surfaces to mesh")
    sys.stdout.write("\n".join(lines) + "\n")
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thermalfea", description="2D thermal finite-element analysis."
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="show log messages")
    sub = parser.add_subparsers(dest="command")
    info = sub.add_parser("info", help="print entity, node and element counts of a model")
    info.add_argument("model", help="path of a .tfea model file")
    info.set_defaults(func=_info)
    solve = sub.add_parser("solve", help="solve a model and write its results")
    solve.add_argument("model", help="path of a .tfea model file")
    solve.add_argument(
        "-o", "--output", metavar="RESULTS", default=None,
        help="results file to write (default: <model>.h5 beside the model)",
    )
    solve.add_argument(
        "--restart", action="store_true",
        help="continue the transient run in the results file to the end time of the model",
    )
    solve.set_defaults(func=_solve)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the ``thermalfea`` command line.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments without the program name. Defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        Process exit code: 0 on success, 1 on a ThermalFEA error, 2 when the solution
        did not converge.
    """
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_usage(sys.stdout)
        return EXIT_OK
    configure_logging(logging.INFO if args.verbose else logging.ERROR)
    try:
        return args.func(args)
    except ConvergenceError as exc:
        sys.stderr.write(f"error: the solution did not converge: {exc}\n")
        return EXIT_NOT_CONVERGED
    except ThermalFEAError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
