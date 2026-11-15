"""Command-line entry point for ThermalFEA.

``thermalfea info model.tfea`` builds and meshes a model and prints its entity, node and
element counts. (``solve`` and ``export`` are added by later tasks.)
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from .core.errors import ThermalFEAError
from .core.log import configure_logging

EXIT_OK, EXIT_ERROR = 0, 1


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
        Process exit code: 0 on success, 1 on a ThermalFEA error.
    """
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_usage(sys.stdout)
        return EXIT_OK
    configure_logging(logging.INFO if args.verbose else logging.ERROR)
    try:
        return args.func(args)
    except ThermalFEAError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
