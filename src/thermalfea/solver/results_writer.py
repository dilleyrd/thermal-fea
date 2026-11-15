"""Writes a results file (HDF5, Data §9).

Layout::

    /meta            attrs: schema_version, model_hash, created, analysis, settings (JSON),
                     model (JSON), regions (JSON: region id -> material, thickness, angle)
    /mesh            attrs: dim, axisymmetric
    /mesh/nodes      (n_nodes, dim)
    /mesh/blocks/<i> conn, region, elem_ids; attr etype
    /mesh/facets/<i> conn, entity, parent_elem; attr etype
    /mesh/point_nodes  (n, 2): geometry point tag, node index
    /mesh/node_sets/<i>  node indices; attr name
    /steps/time      (n_steps,)
    /steps/fields/<name>  (n_steps, n_values); attrs location, units
    /steps/dt, /steps/iterations, /steps/converged
    /steps/energy    (n_steps, k); attr columns
    /reactions/<i>   (n_steps,) heat entering the body per boundary condition [W]; attr name

Every per-step dataset is extendable and chunked by step, so steps can be appended one at
a time and a file left by an interrupted run is still readable.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Any

import h5py
import numpy as np
from numpy import ndarray

from ..core.mesh import Mesh
from ..model.serialize import to_json
from ..post.energy import EnergyBalance
from .problem import TEMPERATURE, CompiledProblem

log = logging.getLogger(__name__)

RESULTS_SCHEMA_VERSION = 1
ENERGY_COLUMNS = ("heat_in", "heat_out", "net", "stored_rate", "imbalance", "relative_imbalance")
_COMPRESSION = "gzip"


def model_hash(model_json: dict[str, Any]) -> str:
    """SHA-256 of the canonical JSON form of a model."""
    text = json.dumps(model_json, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_mesh(group: h5py.Group, mesh: Mesh) -> None:
    """Store a mesh in an HDF5 group."""
    group.attrs["dim"] = mesh.dim
    group.attrs["axisymmetric"] = bool(mesh.axisymmetric)
    group.create_dataset("nodes", data=mesh.nodes, compression=_COMPRESSION)
    blocks = group.create_group("blocks")
    for i, b in enumerate(mesh.blocks):
        g = blocks.create_group(str(i))
        g.attrs["etype"] = b.etype
        g.create_dataset("conn", data=b.conn, compression=_COMPRESSION)
        g.create_dataset("region", data=b.region)
        g.create_dataset("elem_ids", data=b.elem_ids)
    facets = group.create_group("facets")
    for i, f in enumerate(mesh.facets):
        g = facets.create_group(str(i))
        g.attrs["etype"] = f.etype
        g.create_dataset("conn", data=f.conn, compression=_COMPRESSION)
        g.create_dataset("entity", data=f.entity)
        g.create_dataset("parent_elem", data=f.parent_elem)
    points = np.array(sorted(mesh.point_nodes.items()), dtype=np.int64).reshape(-1, 2)
    group.create_dataset("point_nodes", data=points)
    sets = group.create_group("node_sets")
    for i, (name, nodes) in enumerate(mesh.node_sets.items()):
        ds = sets.create_dataset(str(i), data=np.asarray(nodes, dtype=np.int64))
        ds.attrs["name"] = name


class ResultsWriter:
    """Streams the steps of one solve into a results file.

    Use as a context manager::

        with ResultsWriter(path, problem) as writer:
            writer.append_step(time, u, ...)

    Parameters
    ----------
    path : str or Path
        File to create (an existing file is replaced).
    problem : CompiledProblem
        Supplies the mesh, the DOF map, the region properties and, when it was compiled
        from a model, the model that is embedded in the file.
    """

    def __init__(self, path: str | Path, problem: CompiledProblem) -> None:
        self.path = Path(path)
        self.problem = problem
        self._file: h5py.File | None = None
        self._names: list[str] = []
        self.n_steps = 0

    # ----------------------------------------------------------------- context manager

    def __enter__(self) -> ResultsWriter:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def open(self) -> None:
        """Create the file and write the header (meta data and mesh)."""
        problem = self.problem
        self._file = f = h5py.File(self.path, "w")
        meta = f.create_group("meta")
        meta.attrs["schema_version"] = RESULTS_SCHEMA_VERSION
        meta.attrs["created"] = datetime.now(UTC).isoformat(timespec="seconds")
        meta.attrs["settings"] = json.dumps(asdict(problem.settings), sort_keys=True)
        model = problem.model
        if model is not None:
            data = to_json(model)
            meta.attrs["model"] = json.dumps(data, sort_keys=True)
            meta.attrs["model_hash"] = model_hash(data)
            meta.attrs["analysis"] = f"{model.analysis}, {model.solution.kind}"
        else:
            meta.attrs["model"] = ""
            meta.attrs["model_hash"] = ""
            geometry = "axisymmetric" if problem.mesh.axisymmetric else "planar"
            meta.attrs["analysis"] = f"{geometry}, {problem.settings.kind}"
        regions = {
            str(region_id): {
                "name": r.name,
                "thickness": r.thickness,
                "material_angle": r.material_angle,
                "material": r.material.to_json(),
            }
            for region_id, r in problem.regions.items()
        }
        meta.attrs["regions"] = json.dumps(regions, sort_keys=True)
        write_mesh(f.create_group("mesh"), problem.mesh)

        steps = f.create_group("steps")
        n_nodes = problem.dofs.n_nodes(TEMPERATURE)
        for name, dtype in (("time", "f8"), ("dt", "f8"), ("iterations", "i8"), ("converged", "?")):
            steps.create_dataset(name, shape=(0,), maxshape=(None,), dtype=dtype, chunks=(256,))
        energy = steps.create_dataset(
            "energy", shape=(0, len(ENERGY_COLUMNS)), maxshape=(None, len(ENERGY_COLUMNS)),
            dtype="f8", chunks=(256, len(ENERGY_COLUMNS)),
        )
        energy.attrs["columns"] = list(ENERGY_COLUMNS)
        fields = steps.create_group("fields")
        temperature = fields.create_dataset(
            TEMPERATURE, shape=(0, n_nodes), maxshape=(None, n_nodes), dtype="f8",
            chunks=(1, max(n_nodes, 1)), compression=_COMPRESSION,
        )
        temperature.attrs["location"] = "node"
        temperature.attrs["units"] = "K"
        f.create_group("reactions")

    def close(self) -> None:
        """Flush and close the file."""
        if self._file is not None:
            self._file.close()
            self._file = None

    # --------------------------------------------------------------------------- steps

    def _reaction_dataset(self, name: str) -> h5py.Dataset:
        group = self._file["reactions"]
        if name not in self._names:
            self._names.append(name)
            ds = group.create_dataset(
                str(len(self._names) - 1), shape=(self.n_steps,), maxshape=(None,), dtype="f8",
                chunks=(256,), fillvalue=np.nan,
            )
            ds.attrs["name"] = name
        return group[str(self._names.index(name))]

    def append_step(
        self,
        time: float,
        u: ndarray,
        dt: float = 0.0,
        iterations: int = 1,
        converged: bool = True,
        balance: EnergyBalance | None = None,
    ) -> None:
        """Append one step.

        Parameters
        ----------
        time : float
            Time of the step [s].
        u : ndarray, shape (n_dofs,)
            Solution [K].
        dt : float
            Time step that led to it [s] (0 for a steady solution).
        iterations : int
            Number of iterations taken.
        converged : bool
            False marks a step stored although it did not converge.
        balance : EnergyBalance, optional
            Energy balance of the step; its flows fill ``/reactions``.
        """
        f = self._file
        if f is None:
            raise RuntimeError("the results file is not open")
        i = self.n_steps
        steps = f["steps"]
        for name, value in (("time", time), ("dt", dt), ("iterations", iterations),
                            ("converged", converged)):
            steps[name].resize((i + 1,))
            steps[name][i] = value
        temperature = steps["fields"][TEMPERATURE]
        temperature.resize((i + 1, temperature.shape[1]))
        temperature[i] = np.asarray(u, dtype=float)[self.problem.dofs.field_dofs(TEMPERATURE)]
        energy = steps["energy"]
        energy.resize((i + 1, energy.shape[1]))
        if balance is None:
            energy[i] = np.nan
        else:
            energy[i] = [balance.heat_in, balance.heat_out, balance.net, balance.stored_rate,
                         balance.imbalance, balance.relative_imbalance]
            for name in balance.flows:
                self._reaction_dataset(name)
        for k, name in enumerate(self._names):
            ds = f["reactions"][str(k)]
            ds.resize((i + 1,))
            ds[i] = balance.flows.get(name, np.nan) if balance is not None else np.nan
        self.n_steps = i + 1

    def flush(self) -> None:
        """Write buffered data to disk, so the file is readable if the run stops here."""
        if self._file is not None:
            self._file.flush()
