"""Lazy access to a results file (Data §9).

``Results(path)`` opens nothing until something is asked for, and each request opens the
file only for as long as it takes, so a results file can be replaced by a new solve while
a ``Results`` object for it exists.
"""

from __future__ import annotations

import json
from functools import cached_property
from pathlib import Path
from typing import Any

import h5py
import numpy as np
from numpy import ndarray

from ..core.errors import ModelError
from ..core.mesh import ElementBlock, FacetBlock, Mesh
from ..core.units import UnitSettings
from ..materials.material import Material
from ..model.model import Model
from ..model.serialize import from_json
from ..model.settings import SolutionSettings
from ..solver.dofs import DofMap
from ..solver.problem import TEMPERATURE, CompiledProblem, RegionData
from . import recovery

SUPPORTED_SCHEMA = 1


def read_mesh(group: h5py.Group) -> Mesh:
    """Rebuild a :class:`Mesh` from the group written by ``write_mesh``."""
    blocks = [
        ElementBlock(g.attrs["etype"], g["conn"][()], g["region"][()], g["elem_ids"][()])
        for _, g in sorted(group["blocks"].items(), key=lambda kv: int(kv[0]))
    ]
    facets = [
        FacetBlock(g.attrs["etype"], g["conn"][()], g["entity"][()], g["parent_elem"][()])
        for _, g in sorted(group["facets"].items(), key=lambda kv: int(kv[0]))
    ]
    node_sets = {
        ds.attrs["name"]: ds[()]
        for _, ds in sorted(group["node_sets"].items(), key=lambda kv: int(kv[0]))
    }
    return Mesh(
        dim=int(group.attrs["dim"]),
        nodes=group["nodes"][()],
        blocks=blocks,
        facets=facets,
        node_sets=node_sets,
        point_nodes={int(tag): int(node) for tag, node in group["point_nodes"][()]},
        axisymmetric=bool(group.attrs["axisymmetric"]),
    )


class Results:
    """The results of one solve.

    Step data (temperatures, fluxes, histories) is read from the file on each access. The
    handle caches the mesh, the model, the header and the names of the heat-flow and stream
    columns when they are first read. After the file is rewritten (a re-solve, or a restart
    that extends the run) open a new ``Results`` on the path;
    :func:`thermalfea.api.solve` always returns a new ``Results``, also when it restarts.

    Parameters
    ----------
    path : str or Path
        A results file written by :class:`~thermalfea.solver.results_writer.ResultsWriter`.

    Raises
    ------
    ModelError
        If the file does not exist or is not a results file this program can read.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._display_units: UnitSettings | None = None
        if not self.path.is_file():
            raise ModelError(f"results file not found: {self.path}")
        try:
            with h5py.File(self.path, "r") as f:
                version = int(f["meta"].attrs["schema_version"])
        except (OSError, KeyError) as exc:
            raise ModelError(f"{self.path} is not a ThermalFEA results file: {exc}") from None
        if version > SUPPORTED_SCHEMA:
            raise ModelError(
                f"{self.path} has results schema version {version}; this program reads up "
                f"to version {SUPPORTED_SCHEMA}"
            )

    def _read(self, name: str, index: Any = ()) -> Any:
        with h5py.File(self.path, "r") as f:
            return f[name][index]

    def _attr(self, group: str, name: str) -> Any:
        with h5py.File(self.path, "r") as f:
            return f[group].attrs[name]

    # ------------------------------------------------------------------------ header

    @cached_property
    def mesh(self) -> Mesh:
        """The mesh the results were computed on."""
        with h5py.File(self.path, "r") as f:
            return read_mesh(f["mesh"])

    @property
    def display_units(self) -> UnitSettings:
        """The units plots and read-outs of these results use.

        Unless set, the display units of the model stored in the file (SI when the file
        has none). The GUI sets them to the units chosen in the open document; the file
        is never changed.
        """
        if self._display_units is not None:
            return self._display_units
        model = self.model
        return model.display_units if model is not None else UnitSettings()

    @display_units.setter
    def display_units(self, settings: UnitSettings | None) -> None:
        self._display_units = settings

    @cached_property
    def model(self) -> Model | None:
        """The model embedded in the file, or ``None`` if it was solved without one."""
        text = self._attr("meta", "model")
        return from_json(json.loads(text)) if text else None

    @cached_property
    def meta(self) -> dict[str, Any]:
        """Header information: schema version, model hash, creation time, analysis."""
        with h5py.File(self.path, "r") as f:
            attrs = f["meta"].attrs
            return {
                "schema_version": int(attrs["schema_version"]),
                "model_hash": str(attrs["model_hash"]),
                "created": str(attrs["created"]),
                "analysis": str(attrs["analysis"]),
                "settings": json.loads(attrs["settings"]),
            }

    @cached_property
    def problem(self) -> CompiledProblem:
        """A problem holding the mesh and region properties, for recovery (no loads)."""
        mesh = self.mesh
        dofs = DofMap()
        dofs.add_field(TEMPERATURE, mesh.n_nodes)
        regions = {
            int(region_id): RegionData(
                Material.from_json(r["material"]), r["thickness"], r["material_angle"], r["name"]
            )
            for region_id, r in json.loads(self._attr("meta", "regions")).items()
        }
        settings = SolutionSettings(**self.meta["settings"])
        return CompiledProblem(mesh=mesh, dofs=dofs, regions=regions, settings=settings)

    # ------------------------------------------------------------------------- steps

    @property
    def times(self) -> ndarray:
        """Time of every stored step [s]."""
        return self._read("steps/time")

    @property
    def n_steps(self) -> int:
        """Number of stored steps."""
        with h5py.File(self.path, "r") as f:
            return int(f["steps/time"].shape[0])

    @property
    def dt(self) -> ndarray:
        """Time step that led to every stored step [s]."""
        return self._read("steps/dt")

    @property
    def iterations(self) -> ndarray:
        """Iterations taken by every stored step."""
        return self._read("steps/iterations")

    @property
    def converged(self) -> ndarray:
        """Whether every stored step converged."""
        return self._read("steps/converged")

    def _step(self, step: int) -> int:
        n = self.n_steps
        if not -n <= step < n:
            raise ModelError(f"step {step} is out of range; the file has {n} step(s)")
        return step % n

    @property
    def fields(self) -> list[str]:
        """Names of the stored fields."""
        with h5py.File(self.path, "r") as f:
            return list(f["steps/fields"])

    def field(self, name: str, step: int = -1) -> ndarray:
        """Values of a stored field at one step."""
        if name not in self.fields:
            raise ModelError(f"the results have no field {name!r}")
        return self._read(f"steps/fields/{name}", self._step(step))

    def temperature(self, step: int = -1) -> ndarray:
        """Nodal temperatures [K] at one step (negative steps count from the end)."""
        return self.field(TEMPERATURE, step)

    def nodal_history(self, node: int) -> ndarray:
        """Temperature [K] of one node at every stored step."""
        if not 0 <= node < self.mesh.n_nodes:
            raise ModelError(f"node {node} is out of range")
        return self._read(f"steps/fields/{TEMPERATURE}", (slice(None), node))

    # ---------------------------------------------------------------- derived fields

    def flux(self, step: int = -1) -> dict[int, tuple[ndarray, ndarray]]:
        """Nodal heat flux [W/m^2] per region at one step, computed from the temperature.

        Returns
        -------
        dict of int to (node_idx, q)
            See :func:`thermalfea.post.recovery.nodal_flux`.
        """
        return recovery.nodal_flux(self.mesh, self.problem, self.temperature(step))

    def gradient(self, step: int = -1) -> dict[int, tuple[ndarray, ndarray]]:
        """Nodal temperature gradient [K/m] per region at one step."""
        return recovery.gradient(self.mesh, self.problem, self.temperature(step))

    def element_flux(self, step: int = -1) -> ndarray:
        """Heat flux [W/m^2] at the centroid of every element at one step."""
        return recovery.element_flux(self.mesh, self.problem, self.temperature(step))

    # ------------------------------------------------------------------- heat flows

    @cached_property
    def _reaction_names(self) -> dict[str, str]:
        with h5py.File(self.path, "r") as f:
            return {str(ds.attrs["name"]): key for key, ds in f["reactions"].items()}

    @property
    def heat_flow_names(self) -> list[str]:
        """Names of the boundary conditions and loads with a stored heat flow."""
        return list(self._reaction_names)

    def heat_flow(self, bc_name: str) -> ndarray:
        """Heat entering the body through one boundary condition at every step [W].

        Positive when heat enters the body, negative when it leaves.
        """
        key = self._reaction_names.get(bc_name)
        if key is None:
            raise ModelError(
                f"no heat flow stored for {bc_name!r} (available: "
                f"{', '.join(self.heat_flow_names) or 'none'})"
            )
        return self._read(f"reactions/{key}")

    def energy_balance(self) -> dict[str, ndarray]:
        """Energy balance of every step: column name -> values [W] (last one relative)."""
        with h5py.File(self.path, "r") as f:
            ds = f["steps/energy"]
            columns = [str(c) for c in ds.attrs["columns"]]
            data = ds[()]
        return {name: data[:, i] for i, name in enumerate(columns)}

    # ---------------------------------------------------------------------- streams

    @cached_property
    def _stream_keys(self) -> dict[str, str]:
        with h5py.File(self.path, "r") as f:
            if "fluid" not in f:  # a file written before streams were stored
                return {}
            return {str(g.attrs["name"]): key for key, g in f["fluid"].items()}

    @property
    def streams(self) -> list[str]:
        """Names of the streams with stored results."""
        return list(self._stream_keys)

    def stream(self, name: str) -> dict[str, Any]:
        """Everything stored for one stream.

        Returns
        -------
        dict
            ``mode``; for an in-plane stream ``s`` (path coordinate of the fluid nodes
            [m]) and ``dofs``; and one array of shape (n_steps,) per quantity:
            ``mass_flow`` [kg/s], ``h_mean`` [W/(m^2 K)], ``Re``, ``dp`` [Pa], ``T_in``,
            ``T_out`` [K] and ``heat`` (heat picked up from the walls [W]). A quantity
            that does not apply is NaN.
        """
        key = self._stream_keys.get(name)
        if key is None:
            raise ModelError(
                f"no results stored for stream {name!r} (available: "
                f"{', '.join(self.streams) or 'none'})"
            )
        with h5py.File(self.path, "r") as f:
            group = f["fluid"][key]
            out: dict[str, Any] = {"mode": str(group.attrs.get("mode", ""))}
            out.update({k: ds[()] for k, ds in group.items()})
        return out

    def fluid_temperature(self, stream: str, step: int = -1) -> ndarray:
        """Temperature of the fluid nodes of an in-plane stream at one step [K], inlet first."""
        self.stream(stream)  # an unknown stream is reported as such
        name = f"T_fluid:{stream}"
        if name not in self.fields:
            raise ModelError(f"stream {stream!r} has no fluid nodes (it is through-plane)")
        return self.field(name, step)

    def __repr__(self) -> str:
        return f"Results({str(self.path)!r}, steps={self.n_steps})"

    @staticmethod
    def node_values(values: dict[int, tuple[ndarray, ndarray]], n_nodes: int) -> ndarray:
        """Merge a per-region nodal result into one array, averaging at interface nodes."""
        first = next(iter(values.values()))[1]
        total = np.zeros((n_nodes, first.shape[1]))
        count = np.zeros(n_nodes)
        for nodes, q in values.values():
            total[nodes] += q
            count[nodes] += 1.0
        return total / np.maximum(count, 1.0)[:, None]
