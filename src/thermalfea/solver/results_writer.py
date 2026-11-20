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
    /steps           attr last_step: number of the time step the last stored step is (not
                     every step is stored; a continued run numbers its steps from it)
    /steps/energy    (n_steps, k); attr columns
    /reactions/<i>   (n_steps,) heat entering the body per boundary condition [W]; attr name
    /fluid/<i>       one group per stream; attrs name, mode. In-plane streams: ``s`` (path
                     coordinate of the fluid nodes [m]) and ``dofs``. Per step, (n_steps,):
                     mass_flow, h_mean, Re, dp, T_in, T_out, heat
    /steps/fields/T_fluid:<stream>  (n_steps, n_fluid_nodes); location ``extra:<stream>``

Every per-step dataset is extendable and chunked by step, so steps can be appended one at
a time and a file left by an interrupted run is still readable. A writer opened with
``append=True`` continues an existing file of a transient run (task M10.6) when the mesh,
the region data and the streams are unchanged (task M11.11); loads and settings may change.
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

from ..core.errors import ModelError
from ..core.mesh import Mesh
from ..model.serialize import to_json
from ..post.energy import EnergyBalance
from .problem import TEMPERATURE, CompiledProblem

log = logging.getLogger(__name__)

RESULTS_SCHEMA_VERSION = 1
ENERGY_COLUMNS = ("heat_in", "heat_out", "net", "stored_rate", "imbalance", "relative_imbalance")
_COMPRESSION = "gzip"
#: Name of the per-stream fluid-temperature field, ``T_fluid:<stream>`` (Data §9).
FLUID_FIELD = "T_fluid"
#: Step-independent datasets of a stream group.
STATIC_FLUID = ("s", "dofs")
#: Attribute of ``/steps``: the number of the time step of the last stored step.
LAST_STEP = "last_step"
#: Two meshes are the same when their nodes agree to this fraction of the mesh size.
_NODE_TOL = 1e-12


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


def region_data(problem: CompiledProblem) -> dict[str, dict[str, Any]]:
    """The per-region data stored in ``/meta`` attr ``regions`` (JSON-ready)."""
    return {
        str(region_id): {
            "name": r.name,
            "thickness": r.thickness,
            "material_angle": r.material_angle,
            "material": r.material.to_json(),
        }
        for region_id, r in problem.regions.items()
    }


def _normal(value: Any) -> Any:
    """The JSON round trip of a value, so stored and fresh forms compare equal."""
    return json.loads(json.dumps(value, sort_keys=True))


def _mesh_difference(f: h5py.File, mesh: Mesh, width: int, n_nodes: int) -> str | None:
    """What differs between the mesh in the file and ``mesh``, or None if nothing."""
    g = f["mesh"]
    nodes = g["nodes"][...]
    if (
        nodes.shape != mesh.nodes.shape
        or width != n_nodes
        or not np.allclose(nodes, mesh.nodes, rtol=0.0, atol=_NODE_TOL * _extent(mesh.nodes))
    ):
        return "the nodes"
    if bool(g.attrs.get("axisymmetric", False)) != bool(mesh.axisymmetric):
        return "planar against axisymmetric"
    blocks = g["blocks"]
    if len(blocks) != len(mesh.blocks):
        return "the number of element blocks"
    for i, b in enumerate(mesh.blocks):
        s = blocks[str(i)]
        if str(s.attrs["etype"]) != b.etype:
            return f"the element type of block {i}"
        for key in ("conn", "region", "elem_ids"):
            if not np.array_equal(s[key][...], getattr(b, key)):
                return f"the {'connectivity' if key == 'conn' else key} of block {i}"
    facets = g["facets"]
    if len(facets) != len(mesh.facets):
        return "the number of boundary facet blocks"
    for i, fb in enumerate(mesh.facets):
        s = facets[str(i)]
        if str(s.attrs["etype"]) != fb.etype:
            return f"the type of facet block {i}"
        for key in ("conn", "entity", "parent_elem"):
            if not np.array_equal(s[key][...], getattr(fb, key)):
                return f"the {key} of facet block {i}"
    return None


def _stream_difference(f: h5py.File, problem: CompiledProblem) -> str | None:
    """What differs between the streams in the file and those of ``problem``."""
    current: dict[str, dict[str, Any]] = {}
    for provider in problem.providers:
        static = getattr(provider, "static", None)
        current.update(static() if static is not None else {})
    stored = {str(g.attrs["name"]): g for g in f["fluid"].values()}
    if set(stored) != set(current):
        return "names"
    for name, data in current.items():
        group = stored[name]
        for key, value in data.items():
            if isinstance(value, str):
                if str(group.attrs.get(key)) != value:
                    return f"{key} of {name!r}"
            elif key not in group or not np.array_equal(group[key][...], np.asarray(value)):
                return f"{key} of {name!r}"
        if any(key in group and key not in data for key in STATIC_FLUID):
            return f"the data of {name!r}"
    return None


def check_restart_compatible(path: str | Path, problem: CompiledProblem) -> None:
    """Raise unless a results file can be continued with ``problem``.

    The file is only read. It can be continued when it holds a transient run and the
    problem has the same mesh (nodes, element types, connectivity, regions, boundary
    facets, planar or axisymmetric), the same region data (material, thickness and
    material angle; the name is ignored) and the same streams (names, mode, DOF mapping).
    Loads and solver settings may differ.

    Raises
    ------
    ModelError
        If the file is unreadable, holds a steady solution, or differs from the problem
        in one of the respects above.
    """
    name = Path(path).name
    try:
        with h5py.File(path, "r") as f:
            analysis = str(f["meta"].attrs["analysis"])
            width = f["steps"]["fields"][TEMPERATURE].shape[1]
            if not analysis.endswith("transient"):
                raise ModelError(f"cannot continue {name}: it holds a steady solution")
            diff = _mesh_difference(f, problem.mesh, width, problem.dofs.n_nodes(TEMPERATURE))
            if diff is not None:
                raise ModelError(
                    f"cannot continue {name}: it was computed on a different mesh ({diff}). "
                    "A run can only be continued on the mesh it was started on; solve again "
                    "from the start instead"
                )
            stored = json.loads(str(f["meta"].attrs["regions"]))
            fresh = _normal(region_data(problem))
            if set(stored) != set(fresh):
                raise ModelError(
                    f"cannot continue {name}: the regions of the model differ from those of "
                    "the results file. A run can only be continued with the same regions; "
                    "solve again from the start instead"
                )
            for key, old in stored.items():
                new = fresh[key]
                if any(old.get(k) != new[k] for k in ("thickness", "material_angle", "material")):
                    raise ModelError(
                        f"cannot continue {name}: the material, thickness or material angle "
                        f"of region {new['name']!r} differs from the results file. A run can "
                        "only be continued with the same regions; solve again from the start "
                        "instead"
                    )
            diff = _stream_difference(f, problem)
            if diff is not None:
                raise ModelError(
                    f"cannot continue {name}: the streams of the model are not those of the "
                    f"results file ({diff}). Solve again from the start instead"
                )
    except (OSError, KeyError) as exc:
        raise ModelError(f"cannot continue {name}: not a results file ({exc})") from exc


def _extent(nodes: ndarray) -> float:
    return float(np.ptp(nodes, axis=0).max()) if nodes.size else 1.0


class ResultsWriter:
    """Streams the steps of one solve into a results file.

    Use as a context manager::

        with ResultsWriter(path, problem) as writer:
            writer.append_step(time, u, ...)

    Parameters
    ----------
    path : str or Path
        File to create (an existing file is replaced), or to continue with ``append``.
    problem : CompiledProblem
        Supplies the mesh, the DOF map, the region properties and, when it was compiled
        from a model, the model that is embedded in the file.
    append : bool
        Continue the existing file of a transient run: its steps are kept and new ones
        are added after them. The mesh, the region data (materials, thicknesses, material
        angles) and the streams must be those of the file (``check_restart_compatible``).
        The embedded model and settings are replaced by those of ``problem``.
    """

    def __init__(self, path: str | Path, problem: CompiledProblem, append: bool = False) -> None:
        self.path = Path(path)
        self.problem = problem
        self.append = append
        self._file: h5py.File | None = None
        self._names: list[str] = []
        self._streams: list[str] = []
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
        """Create the file and write the header (meta data and mesh), or reopen it."""
        if self.append:
            self._reopen()
            return
        problem = self.problem
        self._file = f = h5py.File(self.path, "w")
        meta = f.create_group("meta")
        meta.attrs["schema_version"] = RESULTS_SCHEMA_VERSION
        meta.attrs["created"] = datetime.now(UTC).isoformat(timespec="seconds")
        self._write_model(meta)
        meta.attrs["regions"] = json.dumps(region_data(problem), sort_keys=True)
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
        f.create_group("fluid")
        for provider in problem.providers:
            static = getattr(provider, "static", None)
            for stream, data in (static() if static is not None else {}).items():
                group = self._fluid_group(stream)
                for key, value in data.items():
                    if isinstance(value, str):
                        group.attrs[key] = value
                    else:
                        group.create_dataset(key, data=np.asarray(value))

    def _write_model(self, meta: h5py.Group) -> None:
        """Store the settings and the model of the problem in ``/meta``."""
        problem = self.problem
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

    def _reopen(self) -> None:
        """Open an existing file to add steps after those it holds."""
        problem = self.problem
        if not self.path.is_file():
            raise ModelError(f"results file not found: {self.path}")
        check_restart_compatible(self.path, problem)
        self._file = f = h5py.File(self.path, "r+")
        self.n_steps = int(f["steps"]["time"].shape[0])
        reactions = f["reactions"]
        self._names = [str(reactions[str(k)].attrs["name"]) for k in range(len(reactions))]
        fluid = f["fluid"]
        self._streams = [str(fluid[str(k)].attrs["name"]) for k in range(len(fluid))]
        self._write_model(f["meta"])

    def _fluid_group(self, stream: str) -> h5py.Group:
        """The group of one stream under ``/fluid`` (numbered; the name is an attribute)."""
        if stream not in self._streams:
            self._streams.append(stream)
            group = self._file["fluid"].create_group(str(len(self._streams) - 1))
            group.attrs["name"] = stream
        return self._file["fluid"][str(self._streams.index(stream))]

    def _append_extras(self, i: int, extras: dict[str, ndarray]) -> None:
        """Store the per-step flow results, keyed ``"<quantity>:<stream>"``."""
        fields = self._file["steps"]["fields"]
        for key, value in extras.items():
            quantity, _, stream = key.partition(":")
            values = np.atleast_1d(np.asarray(value, dtype=float))
            if quantity == FLUID_FIELD:
                if key not in fields:
                    ds = fields.create_dataset(
                        key, shape=(i, values.size), maxshape=(None, values.size), dtype="f8",
                        chunks=(1, max(values.size, 1)), compression=_COMPRESSION,
                        fillvalue=np.nan,
                    )
                    ds.attrs["location"] = f"extra:{stream}"
                    ds.attrs["units"] = "K"
                ds = fields[key]
                ds.resize((i + 1, ds.shape[1]))
                ds[i] = values
            else:
                group = self._fluid_group(stream)
                if quantity not in group:
                    group.create_dataset(
                        quantity, shape=(i,), maxshape=(None,), dtype="f8", chunks=(256,),
                        fillvalue=np.nan,
                    )
                group[quantity].resize((i + 1,))
                group[quantity][i] = values[0]
        # keep every per-step flow dataset as long as the step list
        for name, ds in fields.items():
            if name != TEMPERATURE and ds.shape[0] < i + 1:
                ds.resize((i + 1, ds.shape[1]))
        for group in self._file["fluid"].values():
            for name, ds in group.items():
                if ds.maxshape == (None,) and name not in STATIC_FLUID and ds.shape[0] < i + 1:
                    ds.resize((i + 1,))

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
        extras: dict[str, ndarray] | None = None,
        step: int | None = None,
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
        extras : dict of str to ndarray, optional
            Flow results of the step, keyed ``"<quantity>:<stream>"`` (the output of
            ``FlowProvider.results``): ``T_fluid`` becomes a field, every other quantity
            a per-step scalar under ``/fluid``.
        step : int, optional
            Number of the time step (not every step is stored); by default the number
            of steps stored before it.
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
        steps.attrs[LAST_STEP] = int(i if step is None else step)
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
        self._append_extras(i, extras or {})
        self.n_steps = i + 1

    def flush(self) -> None:
        """Write buffered data to disk, so the file is readable if the run stops here."""
        if self._file is not None:
            self._file.flush()
