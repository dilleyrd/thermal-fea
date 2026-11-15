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
        if getattr(self, "_extra", None) is not None:
            self._extra.reset()

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

    def add_sparse(self, matrix: csr_matrix) -> None:
        """Add a whole sparse matrix of the size of the global system.

        Used by terms whose contribution is naturally built with sparse products (for
        example the stream coupling) rather than from element matrices.

        Parameters
        ----------
        matrix : scipy.sparse matrix, shape (n_dofs, n_dofs)
        """
        if matrix.shape != (self.n_dofs, self.n_dofs):
            raise SolverError(
                f"assembly: sparse matrix of shape {matrix.shape} does not match the "
                f"system size {self.n_dofs}"
            )
        coo = matrix.tocoo()
        self._rows.append(coo.row.astype(np.int64))
        self._cols.append(coo.col.astype(np.int64))
        self._vals.append(coo.data.astype(float))

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

    # ------------------------------------------------------- tangent-only contributions
    #
    # Theory §5 keeps two things apart: the matrix K and vector F with r = F - K T, and
    # contributions that enter only the Newton tangent (K_rad) or only the residual
    # (r_rad). Terms add the latter through the two methods below, so the drivers can
    # form r = F - K T + residual() and the tangent K + tangent() exactly as written.

    def _extra_channel(self) -> Assembler:
        extra = getattr(self, "_extra", None)
        if extra is None:
            extra = Assembler(self.n_dofs)
            self._extra = extra
        return extra

    def add_tangent(self, conn: ndarray, Ke: ndarray, cols: ndarray | None = None) -> None:
        """Add element matrices that belong to the Newton tangent but not to ``K``.

        Parameters are as for :meth:`add_matrix`.
        """
        self._extra_channel().add_matrix(conn, Ke, cols)

    def add_residual(self, conn: ndarray, fe: ndarray) -> None:
        """Add element vectors that enter the residual directly, not through ``F - K T``.

        Parameters are as for :meth:`add_vector`.
        """
        self._extra_channel().add_vector(conn, fe)

    def tangent(self) -> csr_matrix:
        """Return the assembled tangent-only matrix (zero when none was added)."""
        return self._extra_channel().matrix()

    def residual(self) -> ndarray:
        """Return the assembled direct residual contributions (zero when none was added)."""
        return self._extra_channel().vector()
