"""L-bracket with a hole and an inset of a second material (milestone M2 gate).

Builds the geometry from a script, names selections, assigns two materials, saves the
model, loads it again, rebuilds and meshes it, and checks that every selection resolves to
the same entities after the round trip.

Run with::

    .venv\\Scripts\\python.exe examples\\l_bracket.py [output-folder]
"""

from __future__ import annotations

import logging
import math
import sys
import tempfile
from pathlib import Path

from thermalfea import api
from thermalfea.core.mesh import Mesh
from thermalfea.geometry.builder import BuiltGeometry
from thermalfea.meshing.quality import report
from thermalfea.model.model import Model
from thermalfea.model.selections import resolve
from thermalfea.physics.kernel import geometry

log = logging.getLogger("thermalfea.examples.l_bracket")

LEG, THICK = 0.20, 0.05  # leg length and leg thickness [m]
HOLE = (0.15, 0.025, 0.010)  # centre x, centre y, radius [m]
INSET = (0.015, 0.110, 0.020, 0.030)  # x, y, width, height [m]
SIZE = 0.005  # element size [m]


def exact_areas() -> dict[str, float]:
    """Analytic areas [m^2] of the two regions."""
    inset = INSET[2] * INSET[3]
    bracket = 2 * LEG * THICK - THICK**2 - math.pi * HOLE[2] ** 2
    return {"body": bracket - inset, "inset": inset}


def make_model() -> tuple[Model, BuiltGeometry]:
    """Create the model: geometry, selections, regions and mesh settings."""
    model = api.new_model("planar", name="L-bracket")
    geo = api.Geometry(model)
    outline = geo.polygon(
        [(0, 0), (LEG, 0), (LEG, THICK), (THICK, THICK), (THICK, LEG), (0, LEG)], id="outline"
    )
    hole = geo.circle(*HOLE, id="hole")
    geo.cut([outline], [hole], id="bracket")
    geo.rectangle(*INSET, id="inset")  # drawn on top: becomes its own region
    built = api.build(model)

    tol = 1e-9
    inset_area = INSET[2] * INSET[3]
    api.select_surfaces(model, built, "inset", where=lambda s: abs(s.measure - inset_area) < tol)
    api.select_surfaces(model, built, "body", where=lambda s: abs(s.measure - inset_area) > tol)
    api.select_curves(model, built, "base", where=lambda c: abs(c.center[1]) < tol)
    api.select_curves(model, built, "top", where=lambda c: abs(c.center[1] - LEG) < tol)
    api.select_curves(
        model, built, "hole", where=lambda c: abs(c.measure - 2 * math.pi * HOLE[2]) < tol
    )
    api.select_curves(
        model,
        built,
        "inset-boundary",
        where=lambda c: len(built.curve_surfaces[_tag_of(built, c)]) > 1,
    )
    api.select_points(model, built, "corner", where=lambda p: max(map(abs, p.center)) < tol)

    api.assign_region(model, "body", material="Aluminum, Alloy 2024-T6", thickness=0.01)
    api.assign_region(model, "inset", material="Copper (pure)", thickness=0.01)

    model.mesh_settings.global_size = SIZE
    model.mesh_settings.order = 2
    model.mesh_settings.curve_sizes = {"hole": SIZE / 3}
    return model, built


def _tag_of(built: BuiltGeometry, fingerprint: object) -> int:
    """Tag of the curve that has this fingerprint object."""
    return next(tag for tag, fp in built.curves.items() if fp is fingerprint)


def region_areas(model: Model, mesh: Mesh) -> dict[str, float]:
    """Meshed area [m^2] of each region selection."""
    out: dict[str, float] = {}
    for region in model.regions:
        blocks = [b for tag in model.selections[region.selection].tags
                  for b in mesh.region_elements(tag)]
        out[region.selection] = float(sum(geometry(b, mesh.nodes).dV.sum() for b in blocks))
    return out


def main(folder: Path | None = None) -> dict[str, object]:
    """Run the example and return what it found.

    Parameters
    ----------
    folder : Path, optional
        Where to write ``l_bracket.tfea``; a temporary folder by default.
    """
    folder = Path(folder) if folder else Path(tempfile.mkdtemp(prefix="thermalfea-"))
    path = folder / "l_bracket.tfea"

    model, built = make_model()
    mesh = api.mesh(model, built)
    before = {name: (list(s.tags), list(s.fingerprints)) for name, s in model.selections.items()}
    api.save(model, path)

    loaded = api.load(path)
    rebuilt = api.build(loaded)  # refreshes the tags of every selection
    remeshed = api.mesh(loaded, rebuilt)
    after = {name: (list(s.tags), list(s.fingerprints)) for name, s in loaded.selections.items()}
    resolved = {name: resolve(s, rebuilt) for name, s in loaded.selections.items()}

    quality = report(remeshed)
    result = {
        "path": path,
        "model_round_trip": loaded == model,
        "selections_identical": before == after,
        "resolved": resolved,
        "tags": {name: tags for name, (tags, _) in after.items()},
        "n_surfaces": len(rebuilt.surfaces),
        "areas": region_areas(loaded, remeshed),
        "exact_areas": exact_areas(),
        "n_nodes": (mesh.n_nodes, remeshed.n_nodes),
        "n_elements": (mesh.n_elements, remeshed.n_elements),
        "element_types": sorted(quality.counts),
        "min_angle": float(quality.min_angle.min()),
        "mesh": remeshed,
        "model": loaded,
        "built": rebuilt,
    }
    log.info("saved %s", path)
    log.info("selections identical after save/load/rebuild: %s", result["selections_identical"])
    log.info("mesh: %d nodes, %d elements, minimum angle %.1f deg",
             remeshed.n_nodes, remeshed.n_elements, result["min_angle"])
    for name, value in result["areas"].items():
        log.info("area of %-5s: %.8f m^2 (exact %.8f)", name, value, result["exact_areas"][name])
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
