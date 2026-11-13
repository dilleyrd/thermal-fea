"""Assembly of element batches into a global sparse matrix and a dense vector."""

from __future__ import annotations

import numpy as np
from numpy import ndarray
from scipy.sparse import coo_matrix, csr_matrix

from ..core.errors import SolverError


class Assembler:
    """Collects batches of element matrices and vectors and sums them into global arrays.

    Batches are stored as given and combined once, in :meth:`matrix` and :meth:`vector`
    (COO triplets converted to CSR, duplicates summed), so there is no Python loop over
    elements.

    Parameters
    ----------
    n_dofs : int
        Size of the global system.
    """

    def __init__(self, n_dofs: int) -> None:
        self.n_dofs = int(n_dofs)
        self._rows: list[ndarray] = []
        self._cols: list[ndarray] = []
        self._vals: list[ndarray] = []
        self._vec_idx: list[ndarray] = []
        self._vec_val: list[ndarray] = []

    def reset(self) -> None:
        """Forget every batch added so far."""
        self._rows.clear()
        self._cols.clear()
        self._vals.clear()
        self._vec_idx.clear()
        self._vec_val.clear()

    def _check(self, idx: ndarray) -> ndarray:
        idx = np.asarray(idx, dtype=np.int64)
        if idx.size and (idx.min() < 0 or idx.max() >= self.n_dofs):
            raise SolverError("assembly: DOF index out of range")
        return idx

    def add_matrix(self, conn: ndarray, Ke: ndarray, cols: ndarray | None = None) -> None:
        """Add a batch of element matrices.

        Parameters
        ----------
        conn : ndarray of int, shape (e, n)
            Global DOF numbers of the rows (and of the columns unless ``cols`` is given).
        Ke : ndarray, shape (e, n, m)
            Element matrices.
        cols : ndarray of int, shape (e, m), optional
            Global DOF numbers of the columns, for coupling blocks.
        """
        rows = self._check(conn)
        columns = rows if cols is None else self._check(cols)
        Ke = np.asarray(Ke, dtype=float)
        if Ke.shape != (*rows.shape, columns.shape[-1]) or rows.shape[:-1] != columns.shape[:-1]:
            raise SolverError(
                f"assembly: matrix batch of shape {Ke.shape} does not match DOF arrays "
                f"{rows.shape} x {columns.shape}"
            )
        self._rows.append(np.broadcast_to(rows[..., :, None], Ke.shape).ravel())
        self._cols.append(np.broadcast_to(columns[..., None, :], Ke.shape).ravel())
        self._vals.append(Ke.ravel())

    def add_vector(self, conn: ndarray, fe: ndarray) -> None:
        """Add a batch of element vectors.

        Parameters
        ----------
        conn : ndarray of int, shape (e, n)
            Global DOF numbers.
        fe : ndarray, shape (e, n)
            Element vectors.
        """
        idx = self._check(conn)
        fe = np.asarray(fe, dtype=float)
        if fe.shape != idx.shape:
            raise SolverError(
                f"assembly: vector batch of shape {fe.shape} does not match DOFs {idx.shape}"
            )
        self._vec_idx.append(idx.ravel())
        self._vec_val.append(fe.ravel())

    def matrix(self) -> csr_matrix:
        """Return the assembled global matrix.

        Returns
        -------
        scipy.sparse.csr_matrix, shape (n_dofs, n_dofs)
            Entries of all batches, duplicates summed.
        """
        shape = (self.n_dofs, self.n_dofs)
        if not self._vals:
            return csr_matrix(shape)
        rows = np.concatenate(self._rows)
        cols = np.concatenate(self._cols)
        vals = np.concatenate(self._vals)
        out = coo_matrix((vals, (rows, cols)), shape=shape).tocsr()
        out.sum_duplicates()
        return out

    def vector(self) -> ndarray:
        """Return the assembled global vector.

        Returns
        -------
        ndarray, shape (n_dofs,)
        """
        if not self._vec_val:
            return np.zeros(self.n_dofs)
        idx = np.concatenate(self._vec_idx)
        val = np.concatenate(self._vec_val)
        return np.bincount(idx, weights=val, minlength=self.n_dofs).astype(float)
